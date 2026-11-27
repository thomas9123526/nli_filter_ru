"""tools/build_benchmark_corpus.py (benchmark -> .jsonl.zst corpus): every source field kept (clarity tags etc.), sets
without a side, a source "group" -> "control_group", --sides / --flat, clarity counts; and nli_label.py run gives the
same labels with or without the extra fields. Runs on a temp src dir, never on the real dataset."""
import importlib.util
import json
from pathlib import Path

import zstandard

import nli_label
from test_label import FakeScorer, small_policy

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("build_benchmark_corpus", ROOT / "tools" / "build_benchmark_corpus.py")
bbc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bbc)


def write_jsonl(path: Path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def read_zst(path: Path):
    text = zstandard.ZstdDecompressor().stream_reader(path.open("rb")).read().decode("utf-8")
    return [json.loads(x) for x in text.splitlines()]


def make_src(tmp_path: Path) -> Path:
    src = tmp_path / "benchmark"
    src.mkdir()
    write_jsonl(src / "benchmark_ru_llm_russian_food_v1.jsonl", [
        {"text": "Borscht is a beet soup.", "decision": "keep", "label": "none", "note": "real",
         "clarity": "clear", "clarity_reason": "plain food text"},
        {"text": "A Moscow chef opened a cafe.", "decision": "keep", "label": "none"},  # no clarity
    ])
    write_jsonl(src / "benchmark_ru_llm_russian_food_v2.jsonl", [
        {"text": "Borscht is a beet soup.\n\nIt is red.", "decision": "keep", "clarity": "hard",
         "clarity_reason": "x"},
        {"text": "A Moscow chef opened a cafe.\n\nIt is new.", "decision": "keep", "clarity": "clear"},
    ])
    write_jsonl(src / "benchmark_ru_llm_ukrainian_food_v1.jsonl", [
        {"text": "Varenyky are dumplings.", "decision": "keep", "clarity": "clear"},
    ])
    write_jsonl(src / "benchmark_ru_llm_negative_controls_v1.jsonl", [
        {"group": "clean", "country": "Belarus", "text": "The forest has bison.", "decision": "keep",
         "gate_expected": False, "clarity": "clear", "clarity_reason": "nature", "note": "real",
         "id": "should-not-win", "case": "nor-this", "future_field": [1, 2]},
    ])
    write_jsonl(src / "benchmark_ru_llm_long_docs.jsonl", [{"text": "skipped: no _v<N>"}])
    return src


def test_parse_name():
    assert bbc.parse_name("benchmark_ru_llm_russian_famous_people_v2.jsonl") == \
        ("russian", "famous_people", "russian_famous_people", 2)
    assert bbc.parse_name("benchmark_ru_llm_ukrainian_values_v1.jsonl") == \
        ("ukrainian", "values", "ukrainian_values", 1)
    assert bbc.parse_name("benchmark_ru_llm_contested_history_v1.jsonl") == \
        ("shared", "contested_history", "contested_history", 1)
    assert bbc.parse_name("benchmark_ru_llm_some_new_set_v3.jsonl") == ("shared", "some_new_set", "some_new_set", 3)
    assert bbc.parse_name("benchmark_ru_llm_long_docs.jsonl") is None


def test_all_sides_keep_every_source_field(tmp_path, capsys):
    src, out = make_src(tmp_path), tmp_path / "corpus"
    assert bbc.main(["--src", str(src), "--out", str(out)]) == 0
    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*.zst"))
    assert files == ["russian/food/russian_food__v1.jsonl.zst", "russian/food/russian_food__v2.jsonl.zst",
                     "shared/negative_controls/negative_controls__v1.jsonl.zst",
                     "ukrainian/food/ukrainian_food__v1.jsonl.zst"]

    ru1 = read_zst(out / "russian/food/russian_food__v1.jsonl.zst")
    assert ru1[0] == {"id": "russian_food_v1#1", "item": "russian_food#1", "text": "Borscht is a beet soup.",
                      "expected_action": "keep", "case": "russian_food", "group": "russian", "variant": "v1",
                      "decision": "keep", "label": "none", "note": "real", "clarity": "clear",
                      "clarity_reason": "plain food text", "source": "dataset/benchmark/benchmark_ru_llm_russian_food_v1.jsonl"}
    assert "clarity" not in ru1[1] and ru1[1]["id"] == "russian_food_v1#2"  # a line without tags is fine
    # a set with one version has no item
    assert "item" not in read_zst(out / "ukrainian/food/ukrainian_food__v1.jsonl.zst")[0]

    neg = read_zst(out / "shared/negative_controls/negative_controls__v1.jsonl.zst")[0]
    assert neg["id"] == "negative_controls_v1#1" and neg["case"] == "negative_controls"  # builder's fields win
    assert neg["group"] == "shared" and neg["control_group"] == "clean"
    assert neg["country"] == "Belarus" and neg["gate_expected"] is False and neg["future_field"] == [1, 2]
    assert neg["clarity"] == "clear" and neg["clarity_reason"] == "nature" and neg["text"] == "The forest has bison."

    man = json.loads((tmp_path / "corpus.manifest.json").read_text(encoding="utf-8"))
    assert man["lines"] == 6 and man["lines_per_side"] == {"russian": 4, "shared": 1, "ukrainian": 1}
    assert man["clarity"] == {"clear": 4, "hard": 1} and man["no_clarity"] == 1
    per_file = {f["path"]: f for f in man["files"]}
    assert per_file["russian/food/russian_food__v1.jsonl.zst"]["clarity"] == {"clear": 1, "(none)": 1}
    assert per_file["shared/negative_controls/negative_controls__v1.jsonl.zst"]["side"] == "shared"
    printed = capsys.readouterr().out
    assert "per clarity: clear 4, hard 1, without clarity 1" in printed
    assert "per side: russian 4, shared 1, ukrainian 1" in printed


def test_sides_and_flat(tmp_path):
    src, out = make_src(tmp_path), tmp_path / "corpus_ru"
    assert bbc.main(["--src", str(src), "--out", str(out), "--sides", "russian", "--flat"]) == 0
    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*.zst"))
    assert files == ["food/russian_food__v1.jsonl.zst", "food/russian_food__v2.jsonl.zst"]
    assert read_zst(out / "food/russian_food__v2.jsonl.zst")[0]["id"] == "russian_food_v2#1"
    man = json.loads((tmp_path / "corpus_ru.manifest.json").read_text(encoding="utf-8"))
    assert man["sides"] == ["russian"] and man["flat"] is True and man["lines_per_side"] == {"russian": 4}

    out2 = tmp_path / "two"
    assert bbc.main(["--src", str(src), "--out", str(out2), "--sides", "ukrainian, shared"]) == 0
    assert sorted(p.relative_to(out2).as_posix() for p in out2.rglob("*.zst")) == [
        "shared/negative_controls/negative_controls__v1.jsonl.zst", "ukrainian/food/ukrainian_food__v1.jsonl.zst"]


def test_label_run_same_with_or_without_extra_fields(tmp_path, monkeypatch):
    pol_path = tmp_path / "policy.json"
    pol_path.write_text(json.dumps(small_policy().data), encoding="utf-8")
    texts = ["The Russian ballet in Moscow opened with a new film about the invasion and the war.",
             "Nothing here.", "Russian hockey team wins again in Moscow tonight, a long report follows."]
    plain = [{"id": f"x{i}", "text": t} for i, t in enumerate(texts)]
    tagged = [{**d, "expected_action": "keep", "case": "c", "group": "russian", "variant": "v1",
               "clarity": "ambiguous", "clarity_reason": "why", "control_group": "clean", "gate_expected": False,
               "country": "Belarus"} for d in plain]
    monkeypatch.setattr(nli_label, "build_scorer", lambda args: (FakeScorer(), None, None))
    labels = {}
    for name, rows in (("plain", plain), ("tagged", tagged)):
        d = tmp_path / name
        d.mkdir()
        write_jsonl(d / "in.jsonl", rows)
        out = tmp_path / f"out_{name}"
        assert nli_label.main(["run", "--compress", "none", str(d / "in.jsonl"), "--output-dir", str(out),
                               "--policy", str(pol_path)]) == 0
        labels[name] = (out / "in.labels.jsonl").read_text(encoding="utf-8")
    assert labels["plain"] and labels["plain"] == labels["tagged"]

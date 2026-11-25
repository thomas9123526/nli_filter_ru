"""nli_label.py --output-mode simple, nli_simple.py (schema, rows, evidence) and nli_label.py export. No models."""
import json

import pytest

import nli_label
import nli_simple
from nli_simple import Schema
from test_label import FakeScorer, small_policy

TEXTS = [
    "A long paragraph about Russian ballet and every film the theatre made, quite long enough here.\n\n"
    "Then a paragraph about Russian algorithm research in physics, also long enough to stand alone.",  # remove + keep
    "A long paragraph about Russian algorithm research in physics, also long enough here, Moscow too.",  # keep
    "A long paragraph about Russian hockey and the league this season, quite long enough to count.",  # review
    "No keyword at all in this line.",  # untouched
]

BASE = {"file": "decisions.jsonl.zst", "include": ["remove", "review", "keep", "pass", "untouched", "error"],
        "omit_empty": True, "evidence": "none",
        "fields": [{"name": "id", "from": "id"}, {"name": "ln", "from": "line"}, {"name": "src", "from": "file"},
                   {"name": "decision", "from": "decision"}, {"name": "reason", "from": "reason_text"},
                   {"name": "keyword_hint", "from": "keyword_counts"}],
        "reason_text": {"cult*": "arts", "untouched": "no_keyword", "keep_label": "never-used"}}


def setup(tmp_path, monkeypatch, schema=None):
    pol = tmp_path / "policy.json"
    data = small_policy().data
    data["keywords_file"] = None
    pol.write_text(json.dumps(data), encoding="utf-8")
    inp = tmp_path / "in.jsonl"
    inp.write_text("".join(json.dumps({"id": f"d{i}", "text": t, "url": f"https://x/{i}"}) + "\n"
                           for i, t in enumerate(TEXTS, 1)), encoding="utf-8")
    sc = tmp_path / "schema.json"
    sc.write_text(json.dumps(schema or BASE), encoding="utf-8")
    fake = FakeScorer()
    monkeypatch.setattr(nli_label, "build_scorer", lambda args: (fake, None, None))
    return pol, inp, sc, fake


def rows(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def run(pol, inp, out, *extra):
    return nli_label.main(["run", "--compress", "none", str(inp), "--output-dir", str(out), "--policy", str(pol),
                           *extra])


def test_simple_rows_line_unit(tmp_path, monkeypatch):
    pol, inp, sc, _ = setup(tmp_path, monkeypatch)
    out = tmp_path / "out"
    assert run(pol, inp, out, "--output-mode", "simple", "--schema", str(sc), "--decision-unit", "line") == 0
    assert sorted(p.name for p in out.iterdir() if p.name.startswith("in.")) == \
        ["in.decisions.jsonl", "in.summary.json"]  # no labels, rewrites or clean
    r = rows(out / "in.decisions.jsonl")
    assert r[0] == {"id": "d1", "ln": 1, "src": "in", "decision": "remove", "reason": "arts",
                    "keyword_hint": {"russian": 2}}
    assert r[1]["decision"] == "keep" and r[1]["reason"] == "science" and r[1]["keyword_hint"] == {"russian": 1, "moscow": 1}
    assert r[2]["decision"] == "review" and r[2]["reason"] == "sport"
    assert r[3] == {"id": "d4", "ln": 4, "src": "in", "decision": "untouched", "reason": "no_keyword"}  # omit_empty
    summ = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summ["settings"]["output_mode"] == "simple" and summ["schema"]["fields"]
    assert summ["stats"]["lines"] == 4 and summ["stats"]["docs"]["untouched"] == 1  # totals count every line


def test_simple_rows_paragraph_unit_and_custom_fields(tmp_path, monkeypatch):
    schema = dict(BASE, omit_empty=False, include=["remove", "review"],
                  fields=[{"name": "line_no", "from": "line"}, {"name": "what", "from": "decision"},
                          {"name": "lvl", "from": "level"}, {"name": "why", "from": "reason"},
                          {"name": "paras", "from": "paragraphs"}, {"name": "url", "from": "input.url"},
                          {"name": "exc", "from": "exception"}])
    pol, inp, sc, _ = setup(tmp_path, monkeypatch, schema)
    out = tmp_path / "out"
    assert run(pol, inp, out, "--output-mode", "simple", "--schema", str(sc)) == 0
    r = rows(out / "in.decisions.jsonl")
    assert [x["line_no"] for x in r] == [1, 3]  # include: only remove / review lines
    assert list(r[0]) == ["line_no", "what", "lvl", "why", "paras", "url", "exc"]  # order and names as listed
    assert (r[0]["what"], r[0]["lvl"], r[0]["why"], r[0]["url"], r[0]["exc"]) == \
        ("edited", "remove", "remove_label", "https://x/1", None)  # omit_empty false: None kept
    assert [p[2] for p in r[0]["paras"]] == ["remove", "keep"]


def test_simple_untouched_off_and_evidence(tmp_path, monkeypatch):
    for evidence, lines in (("decided", [1, 3]), ("all", [1, 2, 3])):
        pol, inp, sc, _ = setup(tmp_path, monkeypatch, dict(BASE, include=["remove", "review", "keep", "pass"],
                                                            evidence=evidence))
        out = tmp_path / f"out_{evidence}"
        assert run(pol, inp, out, "--output-mode", "simple", "--schema", str(sc), "--decision-unit", "line") == 0
        assert [x["ln"] for x in rows(out / "in.decisions.jsonl")] == [1, 2, 3]  # untouched left out
        ev = rows(out / "in.evidence.jsonl")
        assert [x["line"] for x in ev] == lines
        assert ev[0]["paragraphs"][0]["scores"] and ev[0]["decision"] == "remove"


def test_simple_refuses_write_clean_and_bad_schema(tmp_path, monkeypatch, capsys):
    pol, inp, sc, _ = setup(tmp_path, monkeypatch)
    assert run(pol, inp, tmp_path / "o1", "--output-mode", "simple", "--write-clean") == 2
    assert "--write-clean is not available" in capsys.readouterr().err
    sc.write_text(json.dumps(dict(BASE, fields=[{"name": "a", "from": "nope"}])), encoding="utf-8")
    assert run(pol, inp, tmp_path / "o2", "--output-mode", "simple", "--schema", str(sc)) == 2
    assert "unknown source 'nope'" in capsys.readouterr().err


@pytest.mark.parametrize("bad, msg", [
    ({"fields": [{"name": "a", "from": "id"}, {"name": "a", "from": "line"}]}, "used twice"),
    ({"include": ["remove", "maybe"]}, "include"),
    ({"evidence": "some"}, "evidence"),
    ({"omit_empty": "yes"}, "omit_empty"),
    ({"file": "my file.jsonl"}, "file"),
    ({"file": "labels.jsonl.zst"}, "used by other outputs"),
    ({"reason_text": {"x": ""}}, "reason_text"),
    ({"fields": []}, "fields"),
])
def test_schema_checks(bad, msg):
    with pytest.raises(ValueError, match=msg):
        Schema(dict(BASE, **bad))


def test_shipped_schema_loads_and_vocabulary():
    s = Schema.load()
    assert s.kind == "decisions" and s.evidence == "none" and "untouched" in s.include
    assert s.word("hostility_russians") == "insult" and s.word("violence_call") == "violence"
    assert s.word("opinion_about_ukraine") == "opinion" and s.word("gate_negative") == "not_related"
    assert s.word("war") == "war"  # not in the vocabulary: the key itself


def test_deciding_key():
    info = {"involves": {"level": 0, "decision": "gate"}, "culture": {"level": 1, "decision": "remove"},
            "science": {"level": 1, "decision": "keep"}, "narr": {"level": 2, "decision": "remove"}}
    row = {"action": "edited", "paragraphs": [
        {"action": "keep", "reason": "keep_label", "labels": ["science"]},
        {"action": "remove", "reason": "narrative", "labels": ["science", "narr"]}]}
    assert nli_simple.deciding_key(row, info) == "narr"
    row["paragraphs"][1] = {"action": "review", "reason": "exception", "exception": "our_country", "labels": []}
    assert nli_simple.deciding_key(row, info) == "our_country"
    assert nli_simple.deciding_key({"action": "untouched"}, info) == "untouched"
    assert nli_simple.deciding_key({"action": "error", "error": "bad_json"}, info) == "bad_json"


def test_export_equals_simple_run(tmp_path, monkeypatch):
    pol, inp, sc, fake = setup(tmp_path, monkeypatch, dict(BASE, evidence="decided"))
    simple = tmp_path / "simple"
    assert run(pol, inp, simple, "--output-mode", "simple", "--schema", str(sc), "--decision-unit", "line") == 0
    detail = tmp_path / "detail"
    assert run(pol, inp, detail) == 0  # paragraph unit, detail
    calls = fake.fast_pairs
    exp = tmp_path / "exp"
    assert nli_label.main(["export", "--compress", "none", str(detail), "--output-dir", str(exp), "--schema", str(sc),
                           "--decision-unit", "line"]) == 0
    assert fake.fast_pairs == calls  # no model calls
    assert rows(exp / "in.decisions.jsonl") == rows(simple / "in.decisions.jsonl")
    assert rows(exp / "in.evidence.jsonl") == rows(simple / "in.evidence.jsonl")
    # a simple run cannot be exported or redecided again
    assert nli_label.main(["export", str(simple), "--output-dir", str(tmp_path / "x")]) == 2
    assert nli_label.main(["redecide", str(simple), "--output-dir", str(tmp_path / "y")]) == 2


def test_simple_resume_skips_finished_files(tmp_path, monkeypatch):
    pol, inp, sc, fake = setup(tmp_path, monkeypatch)
    out = tmp_path / "out"
    assert run(pol, inp, out, "--output-mode", "simple", "--schema", str(sc)) == 0
    calls = fake.fast_pairs
    assert run(pol, inp, out, "--output-mode", "simple", "--schema", str(sc)) == 0
    assert fake.fast_pairs == calls

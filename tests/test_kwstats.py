"""nli_kwstats.py: keyword / marker statistics over a corpus (counts, units, shards, 10,000 terms)."""
import csv
import json
import random
import time
from pathlib import Path

import pytest

import nli_kwstats

LABELS = {"involves": {"level": 0, "decision": "gate", "threshold": 0.5, "hypothesis": "GATE"},
          "culture": {"level": 1, "decision": "remove", "threshold": 0.8, "hypothesis": "CULTURE"},
          "science": {"level": 1, "decision": "keep", "threshold": 0.8, "hypothesis": "SCIENCE"},
          "narr": {"level": 2, "decision": "remove", "threshold": 0.8, "hypothesis": "NARR"}}

F1 = [
    {"id": "a1", "topic": "politics",
     "text": "Moscow is big. The Kremlin is in Moscow.\n\nAnother paragraph about Russia and the weather today."},
    {"id": "a2", "topic": "tech", "text": "Languages: English, Russian, German, French"},
    {"id": "a3", "topic": "tech", "text": "Nothing to see here."},
]
F2 = [
    {"id": "b1", "topic": "politics", "text": "The orcs came. The Moscow Times reported it."},
    {"id": "b2"},
    {"id": "b3", "topic": "history", "text": "Russia. Russia again!\nAnd Russia."},
]


def _write(p: Path, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


@pytest.fixture()
def setup(tmp_path):
    kw = tmp_path / "kw.txt"
    kw.write_text("# test list\nRussia\nRussian\nMoscow\nKremlin\nMoscow Times\nNeverword\nrussia\n", encoding="utf-8")
    pol = {"country": "Russia", "keywords_file": [str(kw)], "markers": ["orcs"],
           "paragraphs": {"min_chars": 20, "max_chars": 400}, "labels": LABELS,
           "run_if": {"1": ["involves", "@marker"], "2": ["involves", "@marker"]}}
    pp = tmp_path / "policy.json"
    pp.write_text(json.dumps(pol), encoding="utf-8")
    corpus = tmp_path / "corpus"
    _write(corpus / "a" / "f1.jsonl", F1)
    _write(corpus / "b" / "f2.jsonl", F2)
    return pp, corpus


def run(pp, corpus, out, *extra):
    rc = nli_kwstats.main([str(corpus), "--policy", str(pp), "--output-dir", str(out), *extra])
    assert rc == 0
    return json.loads((out / "kwstats.json").read_text(encoding="utf-8"))


def term(st, name, kind="keyword"):
    return next(t for t in st["terms"] if t["term"] == name and t["kind"] == kind)


def test_counts(setup, tmp_path):
    pp, corpus = setup
    st = run(pp, corpus, tmp_path / "out", "--topic-field", "topic")
    tot = st["totals"]
    assert tot["lines"] == 6 and tot["lines_text"] == 5 and tot["no_text"] == 1 and tot["files"] == 2
    assert tot["lines_with_hit"] == 3 + 1  # a1, a2 (incidental only), b1, b3
    assert tot["lines_gated"] == 3          # a2's only hit is a language-menu hit
    m = term(st, "Moscow")
    assert (m["hits"], m["lines"], m["paragraphs"], m["sentences"], m["files"]) == (2, 1, 1, 2, 1)
    r = term(st, "Russia")
    # a1 (paragraph 2) and b3 (3 hits in 3 sentences; the line break splits it into 2 paragraphs, policy rules)
    assert (r["hits"], r["lines"], r["paragraphs"], r["sentences"], r["files"]) == (4, 2, 3, 4, 2)
    assert r["units"]["folder"] == {"a": [1, 1], "b": [3, 1]}
    assert r["units"]["topic"] == {"politics": [1, 1], "history": [3, 1]}
    ru = term(st, "Russian")
    assert (ru["hits"], ru["incidental"], ru["gate_lines"], ru["incidental_share"]) == (1, 1, 0, 1.0)
    assert term(st, "Moscow Times")["hits"] == 1  # the longest match wins: no Moscow hit in b1
    o = term(st, "orcs", "marker")
    assert (o["hits"], o["list"]) == (1, "markers")
    assert term(st, "Russia")["list"] == "kw.txt"
    never = {st["terms"][i]["term"] for i in st["never_hit"]}
    assert never == {"Neverword"}
    assert [d["term"] for d in st["duplicates"]] == ["russia"]
    assert {(o["inner"], o["outer"]) for o in st["overlaps"]} == {("Moscow", "Moscow Times")}
    # co-occurrence per paragraph: Moscow + Kremlin in a1's first paragraph
    assert [st["terms"][j]["term"] for j, _ in term(st, "Kremlin")["co"]] == ["Moscow"]
    assert st["hist"]["hits_per_line"] == {"0": 1, "1": 1, "2": 1, "3": 1, "4": 1}
    # candidate paragraphs = what a run labels: a1 2, b1 1, b3 2
    assert tot["paragraphs_candidate"] == 5
    f = st["forecast"]
    assert f["pairs_per_paragraph"]["high"] == 1 + 2 + 1 and f["pairs_high"] == 5 * 4
    units = st["units"]["folder"]
    assert units["a"]["lines"] == 3 and units["a"]["lines_gated"] == 1 and units["b"]["lines"] == 2
    assert st["units"]["topic"]["tech"]["lines_with_hit"] == 1
    out = tmp_path / "out"
    rows = list(csv.reader(open(out / "terms.csv", encoding="utf-8-sig")))
    assert rows[0][:3] == ["rank", "term", "kind"] and len(rows) == 1 + len(st["terms"])
    md = (out / "report.md").read_text(encoding="utf-8")
    for h in ("## Coverage", "## Dead terms", "## Mostly incidental terms", "## Duplicates and overlaps",
              "## GPU-time forecast", "## Suggestions"):
        assert h in md
    assert "Neverword" in md


def test_same_as_labeller_gate(setup, tmp_path):
    """The gated lines are the lines an nli_label run marks gate: true (same matchers and rules)."""
    import nli_label
    from nli_models import JsonlSource
    pp, corpus = setup
    st = run(pp, corpus, tmp_path / "out")
    policy = nli_label.Policy.load(str(pp))
    matcher, rules, markers = nli_label.build_matchers(policy)

    class NoScorer:
        def score(self, premises, hyps):
            return [(0.0, None, 0.0) for _ in premises]
    lab = nli_label.Labeller(policy, matcher, rules, NoScorer(), marker_matcher=markers)
    gated = 0
    for f in sorted(corpus.rglob("*.jsonl")):
        for o in lab.process(list(JsonlSource(str(f)).records())):
            gated += bool(o.row.get("gate"))
    assert st["totals"]["lines_gated"] == gated


def test_shards_merge_like_one_scan(setup, tmp_path):
    pp, corpus = setup
    _write(corpus / "c" / "f3.jsonl", [{"id": "c1", "text": "Kremlin and Moscow, then Russia."}])
    one = run(pp, corpus, tmp_path / "one", "--topic-field", "topic")
    out = tmp_path / "sh"
    assert nli_kwstats.main([str(corpus), "--policy", str(pp), "--output-dir", str(out), "--shard", "0/2",
                             "--topic-field", "topic"]) == 0
    assert not (out / "kwstats.json").exists()  # waits for the other part
    merged = run(pp, corpus, out, "--shard", "1/2", "--topic-field", "topic")
    for k in ("totals", "hist", "units", "terms", "never_hit", "pairs", "concentration", "duplicates", "overlaps"):
        assert merged[k] == one[k], k
    assert sorted(f["name"] for f in merged["files"]) == ["f1", "f2", "f3"]
    # --merge again from the parts alone
    assert nli_kwstats.main(["--policy", str(pp), "--output-dir", str(out), "--merge"]) == 0
    again = json.loads((out / "kwstats.json").read_text(encoding="utf-8"))
    assert again["terms"] == one["terms"]


def test_group_by_file_and_limit(setup, tmp_path):
    pp, corpus = setup
    st = run(pp, corpus, tmp_path / "out", "--group-by", "file", "--limit", "1")
    assert st["totals"]["lines"] == 2
    assert sorted(st["units"]["file"]) == ["f1", "f2"]


def test_10000_terms_speed_and_size(tmp_path):
    rnd = random.Random(7)
    letters = "abcdefghijklmnopqrstuvwxyz"
    words = sorted({"".join(rnd.choice(letters) for _ in range(rnd.randint(5, 10))) for _ in range(10_500)})[:10_000]
    kw = tmp_path / "kw.txt"
    kw.write_text("\n".join(words) + "\n", encoding="utf-8")
    pol = {"country": "Russia", "keywords_file": [str(kw)], "markers": ["orcs"],
           "paragraphs": {"min_chars": 200, "max_chars": 2000}, "labels": LABELS}
    pp = tmp_path / "policy.json"
    pp.write_text(json.dumps(pol), encoding="utf-8")
    filler = [w.capitalize() for w in ("the", "and", "report", "city", "weather", "market", "people", "today")]
    rows = []
    for i in range(1500):  # ~1 KB lines, many terms each: the worst case for pairs and per-unit lists
        toks = [rnd.choice(words) if rnd.random() < 0.15 else rnd.choice(filler) for _ in range(150)]
        rows.append({"id": str(i), "text": " ".join(toks) + "."})
    for k in range(5):
        _write(tmp_path / "corpus" / f"part{k}" / "x.jsonl", rows[k * 300:(k + 1) * 300])
    t0 = time.perf_counter()
    st = run(pp, tmp_path / "corpus", tmp_path / "out")
    secs = time.perf_counter() - t0
    assert len(st["terms"]) == 10_001
    assert st["totals"]["lines_text"] == 1500
    assert secs < 60, secs
    assert len(st["pairs"]) <= nli_kwstats.PAIR_CAP_FINAL
    assert all(len(t["co"]) <= nli_kwstats.CO_PER_TERM for t in st["terms"])
    size = (tmp_path / "out" / "kwstats.json").stat().st_size
    assert size < 15_000_000, size
    part = (tmp_path / "out" / "kwstats.part.json").stat().st_size
    assert part < 25_000_000, part

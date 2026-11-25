"""nli_label.py: --decision-unit line (strictest paragraph decides the whole line) and the non-English setting
(policy non_english_file: keywords / markers in Arabic ... checked as usual or removed). No models."""
import json

import pytest

import nli_label
from nli_label import NonEnglish, Policy
from test_label import FakeScorer, make_labeller, rec, small_policy

TWO = ("A long paragraph about Russian ballet and every film the theatre made, quite long enough here.\n\n"
       "Then a paragraph about Russian algorithm research in physics, also long enough to stand alone.")
SCIENCE_ONLY = ("A long paragraph about Russian algorithm research in physics, also long enough here.\n\n"
                "Another paragraph about Moscow physics labs and their algorithm teams, also long.")
SPORT_AND_SCIENCE = ("A long paragraph about Russian hockey and the league this season, quite long enough.\n\n"
                     "Then a paragraph about Russian algorithm research in physics, also long enough here.")


# ---------------------------------------------------------------------------------------------------
# decision unit
# ---------------------------------------------------------------------------------------------------

def test_line_unit_strictest_paragraph_wins():
    lab = make_labeller(unit="line")
    o = lab.process([rec(1, TWO)])[0]
    assert [p["action"] for p in o.row["paragraphs"]] == ["remove", "keep"]  # paragraphs still checked one by one
    assert o.row["decision"] == "remove" and o.row["reason"] == "remove_label" and o.row["decided_by"] == 0
    assert o.row["action"] == "removed" and o.clean is None  # the whole line goes
    assert o.row["tokens_removed"] == o.row["tokens"]


def test_paragraph_unit_unchanged():
    o = make_labeller().process([rec(1, TWO)])[0]
    assert o.row["action"] == "edited" and "decision" not in o.row
    assert "ballet" not in o.clean["text"] and "algorithm" in o.clean["text"]


def test_line_unit_keep_review_pass_untouched():
    lab = make_labeller(unit="line")
    kept, review, untouched = lab.process([rec(1, SCIENCE_ONLY), rec(2, SPORT_AND_SCIENCE),
                                           rec(3, "Nothing here but Kiev and some words.")])
    assert (kept.row["decision"], kept.row["action"]) == ("keep", "kept")
    assert kept.clean["text"] == SCIENCE_ONLY  # kept whole
    assert (review.row["decision"], review.row["action"], review.row["decided_by"]) == ("review", "review", 0)
    assert review.clean["text"] == SPORT_AND_SCIENCE
    assert untouched.row["action"] == "untouched" and "decision" not in untouched.row
    assert untouched.clean["text"] == "Nothing here but Kyiv and some words."  # place names still rewritten
    # pass: a keyword that is only incidental (gate negative)
    pol = small_policy()
    pol.labels["involves"].threshold = 0.99  # the fake gate score 0.95 is now below it
    p = make_labeller(pol, unit="line").process([rec(4, "The weather in Russia was not discussed in this text.")])[0]
    assert p.row["decision"] == "pass" and p.row["reason"] == "gate_negative" and p.row["action"] == "pass"


def test_line_unit_review_as_remove_drops_the_line():
    o = make_labeller(unit="line", review_as="remove").process([rec(1, SPORT_AND_SCIENCE)])[0]
    assert o.row["decision"] == "review" and o.row["action"] == "removed" and o.clean is None


def test_line_unit_tie_takes_the_first_paragraph():
    text = ("Russian ballet one: a film about the theatre that is long enough to be a paragraph.\n\n"
            "Russian ballet two: another film about the theatre, long enough to be a paragraph.")
    o = make_labeller(unit="line").process([rec(1, text)])[0]
    assert o.row["decided_by"] == 0


def test_bad_unit():
    with pytest.raises(ValueError, match="decision unit"):
        make_labeller(unit="document")


def _run_files(tmp_path, data):
    pol = tmp_path / "policy.json"
    pol.write_text(json.dumps(data), encoding="utf-8")
    inp = tmp_path / "in.jsonl"
    inp.write_text("".join(json.dumps({"id": f"d{i}", "text": t}) + "\n"
                           for i, t in enumerate([TWO, SCIENCE_ONLY, "No keyword at all here."])), encoding="utf-8")
    return pol, inp


def _rows(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def test_run_line_unit_and_redecide_switches_unit(tmp_path, monkeypatch):
    data = small_policy().data
    pol, inp = _run_files(tmp_path, data)
    fake = FakeScorer()
    monkeypatch.setattr(nli_label, "build_scorer", lambda args: (fake, None, None))
    out = tmp_path / "out"
    assert nli_label.main(["run", "--compress", "none", str(inp), "--output-dir", str(out), "--policy", str(pol),
                           "--write-clean", "--decision-unit", "line"]) == 0
    assert [r["action"] for r in _rows(out / "in.labels.jsonl")] == ["removed", "kept", "untouched"]
    assert [json.loads(x)["id"] for x in (out / "in.clean.jsonl").read_text(encoding="utf-8").splitlines()] == ["d1", "d2"]
    summ = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summ["settings"]["decision_unit"] == "line" and summ["policy_data"]["labels"]
    calls = fake.fast_pairs
    # redecide keeps the run's unit by default ...
    out2 = tmp_path / "out2"
    assert nli_label.main(["redecide", "--compress", "none", str(out), "--policy", str(pol),
                           "--output-dir", str(out2)]) == 0
    assert [r["action"] for r in _rows(out2 / "in.labels.jsonl")] == ["removed", "kept", "untouched"]
    # ... and switches it on the stored scores
    out3 = tmp_path / "out3"
    assert nli_label.main(["redecide", "--compress", "none", str(out), "--policy", str(pol),
                           "--output-dir", str(out3), "--decision-unit", "paragraph"]) == 0
    assert [r["action"] for r in _rows(out3 / "in.labels.jsonl")] == ["edited", "kept", "untouched"]
    assert fake.fast_pairs == calls  # no model calls


# ---------------------------------------------------------------------------------------------------
# non-English keywords / markers
# ---------------------------------------------------------------------------------------------------

NE = {"about": "x",
      "scripts": {"arabic": {"enabled": True, "ranges": ["0600-06FF", "0750-077F"]},
                  "japanese": {"enabled": False, "ranges": ["3040-309F", "30A0-30FF"]}},
      "keywords": "remove", "markers": "check", "score_when_removed": False}
AR_TEXT = ("A long paragraph that says روسيا in Arabic and talks about Moscow physics and algorithm research.\n\n"
           "A second paragraph about Russian physics and algorithm research, long enough on its own.")


def ne_labeller(tmp_path, ne=None, unit="paragraph", markers=None, **pol_over):
    from nli_filter import IncidentalRules, KeywordMatcher
    from nli_names import NameRewriter
    f = tmp_path / "non_english.json"
    f.write_text(json.dumps(ne or NE), encoding="utf-8")
    policy = small_policy(non_english_file=str(f), **({"markers": markers} if markers else {}), **pol_over)
    matcher = KeywordMatcher(["Russia", "Russian", "Moscow", "روسيا", "ロシア"])
    return nli_label.Labeller(policy, matcher, IncidentalRules("Russian"), FakeScorer(), NameRewriter({}, []),
                              marker_matcher=KeywordMatcher(policy.markers), unit=unit)


def test_non_english_config_checks():
    NonEnglish(NE)
    for bad, msg in [({"scripts": {}}, "at least one script"),
                     ({"scripts": {"Arabic": {"enabled": True, "ranges": ["0600-06FF"]}}}, "name"),
                     ({"scripts": {"arabic": {"enabled": True, "ranges": ["06G0"]}}}, "hex"),
                     ({"scripts": {"arabic": {"enabled": True, "ranges": ["06FF-0600"]}}}, "valid range"),
                     ({"scripts": {"arabic": {"enabled": "yes", "ranges": ["0600"]}}}, "enabled"),
                     (dict(NE, keywords="delete"), "keywords must be"),
                     (dict(NE, score_when_removed="no"), "score_when_removed")]:
        with pytest.raises(ValueError, match=msg):
            NonEnglish(bad)
    ne = NonEnglish(NE)
    assert ne.script_of("روسيا") == "arabic" and ne.script_of("Россия") is None and ne.script_of("Kyiv") is None
    assert ne.script_of("ロシア") is None  # japanese is switched off


def test_policy_non_english_file_missing():
    with pytest.raises(ValueError, match="non_english_file"):
        small_policy(non_english_file="policy/does_not_exist.json")


def test_non_english_keyword_removed_without_scoring(tmp_path):
    lab = ne_labeller(tmp_path)
    o = lab.process([rec(1, AR_TEXT)])[0]
    p0, p1 = o.row["paragraphs"]
    assert (p0["action"], p0["reason"], p0["levels"], p0["scores"]) == ("remove", "non_english_keyword", [], {})
    assert p0["non_english"] == [{"term": "روسيا", "kind": "keyword", "script": "arabic"}]
    assert p1["action"] == "keep" and "non_english" not in p1
    assert o.row["action"] == "edited" and "روسيا" not in o.clean["text"]
    assert lab.scorer.seen.count("GATE") == 1  # only p1 was scored


def test_non_english_score_when_removed_keeps_scores(tmp_path):
    lab = ne_labeller(tmp_path, dict(NE, score_when_removed=True))
    p0 = lab.process([rec(1, AR_TEXT)])[0].row["paragraphs"][0]
    assert p0["action"] == "remove" and p0["reason"] == "non_english_keyword"
    assert p0["scores"] and p0["action_before"] == "keep" and p0["levels"]


def test_non_english_check_is_the_normal_check(tmp_path):
    lab = ne_labeller(tmp_path, dict(NE, keywords="check"))
    p0 = lab.process([rec(1, AR_TEXT)])[0].row["paragraphs"][0]
    assert p0["action"] == "keep" and p0["non_english"][0]["script"] == "arabic"  # recorded, not removed


def test_non_english_script_switched_off_or_added(tmp_path):
    off = dict(NE, scripts={"arabic": {"enabled": False, "ranges": ["0600-06FF"]}})
    p0 = ne_labeller(tmp_path, off).process([rec(1, AR_TEXT)])[0].row["paragraphs"][0]
    assert p0["action"] == "keep" and "non_english" not in p0
    jp = dict(NE, scripts={"japanese": {"enabled": True, "ranges": ["3040-309F", "30A0-30FF"]}})
    text = "A long paragraph that says ロシア in Japanese and talks about physics and algorithm research here."
    p = ne_labeller(tmp_path, jp).process([rec(1, text)])[0].row["paragraphs"][0]
    assert p["action"] == "remove" and p["non_english"][0]["script"] == "japanese"


def test_non_english_marker_remove(tmp_path):
    lab = ne_labeller(tmp_path, dict(NE, keywords="check", markers="remove"), markers=["عملية خاصة"])
    text = "A long paragraph with the marker عملية خاصة and nothing else of note in it, long enough here."
    p = lab.process([rec(1, text)])[0].row["paragraphs"][0]
    assert p["action"] == "remove" and p["reason"] == "non_english_marker"


def test_non_english_exception_cannot_lower(tmp_path):
    lab = ne_labeller(tmp_path, exceptions=[{"key": "physics_ok", "decision": "keep", "priority": 5,
                                             "match": {"phrases": ["physics"]}}])
    p0 = lab.process([rec(1, AR_TEXT)])[0].row["paragraphs"][0]
    assert p0["action"] == "remove" and "exception" not in p0
    lab2 = ne_labeller(tmp_path, dict(NE, score_when_removed=True),
                       exceptions=[{"key": "physics_ok", "decision": "keep", "priority": 5,
                                    "match": {"phrases": ["physics"]}}])
    p = lab2.process([rec(1, AR_TEXT)])[0].row["paragraphs"][0]
    assert p["action"] == "remove" and "exception" not in p


def test_non_english_line_unit(tmp_path):
    o = ne_labeller(tmp_path, unit="line").process([rec(1, AR_TEXT)])[0]
    assert o.row["decision"] == "remove" and o.row["reason"] == "non_english_keyword" and o.row["action"] == "removed"


def test_non_english_counts_and_redecide_applies_changed_config(tmp_path, monkeypatch):
    f = tmp_path / "non_english.json"
    f.write_text(json.dumps(dict(NE, keywords="check")), encoding="utf-8")
    data = small_policy().data
    data["non_english_file"] = str(f)
    data["keywords_file"] = None
    pol = tmp_path / "policy.json"
    pol.write_text(json.dumps(data), encoding="utf-8")
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps({"id": "a", "text": AR_TEXT}) + "\n", encoding="utf-8")
    monkeypatch.setattr(nli_label, "build_scorer", lambda args: (FakeScorer(), None, None))
    # the keywords come from the policy's country default; add the Arabic one through a keyword file
    kw = tmp_path / "kw.txt"
    kw.write_text("Russia\nRussian\nروسيا\n", encoding="utf-8")
    data["keywords_file"] = str(kw)
    pol.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "out"
    assert nli_label.main(["run", "--compress", "none", str(inp), "--output-dir", str(out), "--policy", str(pol)]) == 0
    summ = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summ["stats"]["non_english"] == {"keyword:arabic": 1}
    assert summ["policy"]["non_english"]["keywords"] == "check"
    assert _rows(out / "in.labels.jsonl")[0]["action"] == "kept"
    f.write_text(json.dumps(dict(NE, keywords="remove")), encoding="utf-8")
    out2 = tmp_path / "out2"
    assert nli_label.main(["redecide", "--compress", "none", str(out), "--policy", str(pol),
                           "--output-dir", str(out2)]) == 0
    assert _rows(out2 / "in.labels.jsonl")[0]["paragraphs"][0]["reason"] == "non_english_keyword"

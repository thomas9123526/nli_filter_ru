"""Level-A (strict) keywords: a line with one is filtered without models; the explanation says so."""
from nli_viewer.explain import explain
from nli_viewer.results import REASONS

TEXT = "In 1930 Stalin and Russian officials met."


def test_strict_keyword_explained():
    d = {"line": 1, "decision": "filter", "reason": "strict_keyword", "strict": ["Stalin"],
         "hits": [{"kw": "Stalin", "span": [8, 14], "level": "A"}, {"kw": "Russian", "span": [19, 26]}]}
    ex = explain(TEXT, d, {})
    hits = [m for m in ex["marks"] if m["kind"] == "hit"]
    assert [(m["kw"], m["state"], m["level"]) for m in hits] == [("Stalin", "strict", "A"), ("Russian", "open", "B")]
    assert "level-A" in ex["verdict"]["summary"]
    assert any("level-A (strict) keyword: 'Stalin'" in s and "without any model" in s for s in ex["verdict"]["steps"])
    assert ex["check1"] is None and ex["check2"] is None


def test_a_hit_cleared_by_a_rule_is_shown_as_rule():
    d = {"line": 1, "decision": "keep", "reason": "rules_incidental",
         "hits": [{"kw": "Kremlin", "span": [0, 7], "level": "A", "rule": "company_name"}]}
    m = [m for m in explain("Kremlin Kitchens Ltd", d, {})["marks"] if m["kind"] == "hit"][0]
    assert m["state"] == "rule" and m["level"] == "A"


def test_reason_is_known():
    assert "strict_keyword" in REASONS


def test_audit_is_explained():
    d = {"line": 1, "decision": "filter", "reason": "strict_keyword", "strict": ["Stalin"],
         "hits": [{"kw": "Stalin", "span": [8, 14], "level": "A"}],
         "audit": {"decision": "keep", "reason": "check1_negative", "check1": {"score": 0.12, "hyp": "country"},
                   "hits": [{"kw": "Stalin", "span": [8, 14]}]}}
    ex = explain(TEXT, d, {})
    assert ex["audit"] == {"decision": "keep", "reason": "check1_negative", "check1": 0.12, "check1_hyp": "country",
                           "check2": None, "rules": []}
    assert any(s.startswith("audit (level A run as if B): the rules / models would keep it") for s in ex["verdict"]["steps"])
    assert explain(TEXT, dict(d, audit=None), {})["audit"] is None

"""The record page's check-2 table lists every check-2 hypothesis's scores (decisions written since 2026-11-17)."""
from nli_viewer.explain import explain


def _decision(pairs=True):
    c2 = {"window": [0, 41], "hyp": "location", "fast": 0.029, "judge": None, "score": 0.029, "incidental": False}
    if pairs:
        c2["pairs"] = [{"hyp": "company_name", "fast": 0.004, "judge": None, "score": 0.004},
                       {"hyp": "language_setting", "fast": 0.001, "judge": None, "score": 0.001},
                       {"hyp": "location", "fast": 0.029, "judge": None, "score": 0.029}]
    return {"line": 1, "decision": "filter", "reason": "about_country",
            "check1": {"score": 0.99, "positive": True, "hyp": "topic", "window": [0, 41],
                       "pairs": [{"window": [0, 41], "hyp": "topic", "fast": 0.99, "judge": None, "score": 0.99}]},
            "hits": [{"kw": "Russian", "span": [28, 35], "check2": c2}]}


TEXT = "Turkey soldiers invade into Russian Land."


def test_every_check2_hypothesis_is_shown():
    run = {"hypotheses": {"check2": {"company_name": "a", "language_setting": "b", "location": "c"}}}
    row = explain(TEXT, _decision(), run)["check2"]["rows"][0]
    assert [p["hyp"] for p in row["pairs"]] == ["company_name", "language_setting", "location"]
    assert [p["best"] for p in row["pairs"]] == [False, False, True]
    assert row["hyp"] == "location" and row["score"] == 0.029


def test_older_decisions_show_the_best_only():
    row = explain(TEXT, _decision(pairs=False), {})["check2"]["rows"][0]
    assert row["pairs"] == [] and row["hyp"] == "location"

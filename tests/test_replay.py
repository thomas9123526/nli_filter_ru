"""nli_replay.py: decisions recomputed from stored scores (thresholds, hypotheses left out)."""
import json

import nli_compare
import nli_replay


def _d(line, expect, c1_pairs, hits, reason="about_country", decision="filter", **extra):
    best = max(c1_pairs, key=lambda p: p["score"])
    return {"line": line, "id": f"r{line}", "expect": expect, "decision": decision, "reason": reason,
            "check1": {"score": best["score"], "positive": best["score"] >= 0.8, "hyp": best["hyp"],
                       "window": [0, 10], "pairs": c1_pairs}, "hits": hits, **extra}


def _p(hyp, score):
    return {"window": [0, 10], "hyp": hyp, "fast": score, "judge": None, "score": score}


def _hit(c2pairs=None):
    h = {"kw": "Russia", "span": [0, 6]}
    if c2pairs:
        b = max(c2pairs, key=lambda p: p["score"])
        h["check2"] = {"window": [0, 10], "hyp": b["hyp"], "score": b["score"], "incidental": b["score"] >= 0.8,
                       "pairs": c2pairs}
    return h


def test_replay_one_drops_and_thresholds():
    d = _d(1, "filter", [_p("country", 0.6), _p("region", 0.9)], [_hit([_p("brand", 0.1)])])
    assert nli_replay.replay_one(d, 0.8, 0.8, set(), set())["decision"] == "filter"
    r = nli_replay.replay_one(d, 0.8, 0.8, {"region"}, set())
    assert (r["decision"], r["reason"], r["check1"]["hyp"]) == ("keep", "check1_negative", "country")
    assert r["replay"] == {"from": {"decision": "filter", "reason": "about_country"}, "estimated": False}
    assert d["decision"] == "filter"  # the input is not changed
    assert nli_replay.replay_one(d, 0.5, 0.8, {"region"}, set())["decision"] == "filter"
    # check 2: a hit becomes incidental at a lower threshold; keyword templates drop with their key
    d2 = _d(2, "keep", [_p("place:Siberia", 0.95)], [_hit([_p("brand", 0.1), _p("sense:Siberia/2", 0.7)])])
    assert nli_replay.replay_one(d2, 0.8, 0.6, set(), set())["reason"] == "check2_incidental"
    assert nli_replay.replay_one(d2, 0.8, 0.6, set(), {"sense"})["reason"] == "about_country"
    assert nli_replay.replay_one(d2, 0.8, 0.8, {"place"}, set())["reason"] == "check1_negative"


def test_replay_estimates_and_model_free_lines():
    neg = _d(3, None, [_p("country", 0.7)], [_hit()], reason="check1_negative", decision="keep")
    r = nli_replay.replay_one(neg, 0.6, 0.8, set(), set())
    assert r["decision"] == "filter" and r["replay"]["estimated"]  # check 2 never ran for it
    skipped = _d(4, None, [_p("country", 0.7)], [_hit()], reason="check1_negative", decision="keep")
    skipped["check1"]["skipped"] = 1
    assert nli_replay.replay_one(skipped, 0.8, 0.8, set(), set())["replay"]["estimated"]
    plain = {"line": 5, "decision": "keep", "reason": "no_keyword"}
    assert nli_replay.replay_one(plain, 0.1, 0.1, {"country"}, set()) == plain
    strict = {"line": 6, "decision": "filter", "reason": "strict_keyword", "hits": [{"kw": "Stalin", "level": "A"}]}
    assert nli_replay.replay_one(strict, 0.99, 0.1, set(), set()) == strict


def test_replay_folder_and_compare(tmp_path, capsys):
    src = tmp_path / "run"
    (src / "web").mkdir(parents=True)
    rows = [_d(1, "filter", [_p("country", 0.6), _p("region", 0.9)], [_hit([_p("brand", 0.1)])]),
            _d(2, "keep", [_p("country", 0.2), _p("region", 0.85)], [_hit([_p("brand", 0.2)])]),
            {"line": 3, "decision": "keep", "reason": "no_keyword", "expect": "keep"}]
    (src / "web" / "a.decisions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (src / "web" / "a.summary.json").write_text(json.dumps({"input": "corpus/web/a.jsonl", "complete": True}))
    (src / "summary.json").write_text(json.dumps({
        "settings": {"check1_threshold": 0.8, "check2_threshold": 0.8},
        "hypotheses": {"check1": {"country": "x", "region": "y"}, "check2": {"brand": "z"}},
        "timing": {"fast_pairs": 9}}))
    dst = tmp_path / "replayed"
    assert nli_replay.main([str(src), "--drop-check1", "region", "nope", "--output-dir", str(dst)]) == 0
    out = capsys.readouterr().out
    assert "2 changed" in out and "not a check1 hypothesis key of the run: nope" in out
    summ = json.loads((dst / "summary.json").read_text(encoding="utf-8"))
    assert summ["hypotheses"]["check1"] == {"country": "x"} and summ["replay"]["drop_check1"] == ["nope", "region"]
    assert summ["stats"]["eval"]["metrics"]["accuracy"] == 2 / 3
    per = json.loads((dst / "web" / "a.summary.json").read_text(encoding="utf-8"))
    assert per["input"] == "corpus/web/a.jsonl" and per["outputs"] == {"decisions": "a.decisions.jsonl"}
    r = nli_compare.compare(src, dst)
    assert r["changes"] == {"filter -> keep": 2} and r["verdicts"] == {"worse": 1, "better": 1}
    assert nli_replay.main([str(src), "--output-dir", str(src)]) == 2
    assert nli_replay.main([str(tmp_path / "nothing"), "--output-dir", str(dst)]) == 2

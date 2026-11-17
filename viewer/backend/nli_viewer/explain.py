"""
explain.py - turn one nli_filter.py decision record into something a person can read.

    from nli_viewer.explain import explain
    info = explain(text, decision, run_summary)

Returns
    marks       keyword hits (with rule / check-2 state), check-1 windows, check-2 windows
    segments    the text cut at every mark boundary: [{start, end, text, marks:[ids]}], or {gap: n} for
                parts left out of very long texts (only the surroundings of the marks are kept)
    check1      one row per (window x hypothesis): hypothesis sentence, fast / judge / final score, passed
    check2      one row per hit that went to check 2: best hypothesis and scores, incidental or not
    verdict     decision, reason, a one-sentence summary and the steps that led to it
    models      fast / judge model, uncertain band, thresholds
Pure functions, no I/O: usable from the API, the CLI or a notebook.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

__all__ = ["explain", "build_segments", "REASON_TEXT"]

REASON_TEXT = {
    "blank": "Kept: the line is empty.",
    "bad_json": "Kept: the line is not valid JSON (left untouched).",
    "no_text": "Kept: the text field is missing or empty.",
    "no_keyword": "Kept: no keyword of the country appears in the text.",
    "rules_incidental": "Kept: every keyword hit was resolved by a cheap rule (language menu / label / locale code / company name).",
    "check1_negative": "Kept: the NLI model says the text is not about the country (check 1 below threshold).",
    "check2_incidental": "Kept: the text looked like it is about the country, but every remaining keyword hit is only incidental (check 2).",
    "about_country": "Filtered: the text is about the country (check 1 passed) and not every hit is incidental.",
}


def build_segments(text: str, marks: List[Dict[str, Any]], max_chars: int = 30000,
                   context: int = 300) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Cut text at every mark start/end. Each segment lists the ids of the marks covering it.
    If the text is longer than max_chars, only the marks' surroundings (+- context chars) are kept and the
    left-out parts become {"gap": n_chars, "start", "end"} items. Returns (segments, excerpted).
    """
    n = len(text)
    spans = [(max(0, min(n, m["start"])), max(0, min(n, m["end"]))) for m in marks]
    if n <= max_chars:
        keep = [(0, n)]
    else:
        wanted = sorted((max(0, s - context), min(n, e + context)) for s, e in spans) or [(0, min(n, 2000))]
        keep = []
        for s, e in wanted:
            if keep and s <= keep[-1][1]:
                keep[-1] = (keep[-1][0], max(keep[-1][1], e))
            else:
                keep.append((s, e))
    bounds = {0, n}
    for s, e in keep:
        bounds.update((s, e))
    for s, e in spans:
        bounds.update((s, e))
    cuts = sorted(bounds)
    segments: List[Dict[str, Any]] = []
    k = 0
    for a, b in zip(cuts, cuts[1:]):
        if a == b:
            continue
        while k < len(keep) and keep[k][1] <= a:
            k += 1
        inside = k < len(keep) and keep[k][0] <= a and b <= keep[k][1]
        if not inside:
            if segments and "gap" in segments[-1]:
                segments[-1]["gap"] += b - a
                segments[-1]["end"] = b
            else:
                segments.append({"gap": b - a, "start": a, "end": b})
            continue
        ids = [m["id"] for m, (s, e) in zip(marks, spans) if s < b and a < e]
        segments.append({"start": a, "end": b, "text": text[a:b], "marks": ids})
    return segments, n > max_chars


def _hyp_text(run: Dict[str, Any], check: str, key: str) -> Optional[str]:
    return ((run.get("hypotheses") or {}).get(check) or {}).get(key)


def _fmt(x: Optional[float]) -> str:
    return "-" if x is None else f"{x:.3f}"


def explain(text: Optional[str], decision: Dict[str, Any], run: Optional[Dict[str, Any]] = None,
            max_chars: int = 30000, context: int = 300) -> Dict[str, Any]:
    run = run or {}
    settings = run.get("settings") or {}
    t1 = settings.get("check1_threshold", 0.8)
    t2 = settings.get("check2_threshold", 0.8)
    band = settings.get("uncertain_band")
    models = run.get("models") or {}
    fast = (models.get("fast") or {}).get("model")
    judge = (models.get("judge") or {}).get("model")

    marks: List[Dict[str, Any]] = []
    hits = decision.get("hits") or []
    for i, h in enumerate(hits):
        s, e = h.get("span", [0, 0])
        c2 = h.get("check2")
        state = "rule" if h.get("rule") else ("incidental" if c2 and c2.get("incidental") else
                                              ("about" if c2 else "open"))
        marks.append({"id": len(marks), "kind": "hit", "hit": i, "start": s, "end": e, "kw": h.get("kw"),
                      "state": state, "rule": h.get("rule"), "check2": c2})
    c1 = decision.get("check1") or {}
    win_ids: Dict[Tuple[int, int], int] = {}
    for p in c1.get("pairs", []):
        w = tuple(p.get("window", [0, 0]))
        if w not in win_ids:
            win_ids[w] = len(marks)
            marks.append({"id": len(marks), "kind": "check1_window", "start": w[0], "end": w[1],
                          "best": list(w) == c1.get("window")})
    for i, h in enumerate(hits):
        c2 = h.get("check2")
        if c2 and c2.get("window"):
            marks.append({"id": len(marks), "kind": "check2_window", "hit": i, "start": c2["window"][0],
                          "end": c2["window"][1]})

    if text is not None:
        segments, excerpted = build_segments(text, marks, max_chars, context)
    else:
        segments, excerpted = [], False

    def window_text(w):
        if text is None:
            return None
        s = text[w[0]:w[1]]
        return s if len(s) <= 1500 else s[:1500] + " ..."

    check1_rows = []
    for p in c1.get("pairs", []):
        check1_rows.append({
            "window": p.get("window"), "window_mark": win_ids.get(tuple(p.get("window", [0, 0]))),
            "hyp": p.get("hyp"), "hypothesis": _hyp_text(run, "check1", p.get("hyp")),
            "fast": p.get("fast"), "judge": p.get("judge"), "score": p.get("score"),
            "judged": p.get("judge") is not None, "passed": (p.get("score") or 0) >= t1,
            "window_text": window_text(p.get("window", [0, 0])),
        })
    check2_rows = []
    for m in marks:
        if m["kind"] == "hit" and m["check2"]:
            c2 = m["check2"]
            check2_rows.append({
                "hit": m["hit"], "hit_mark": m["id"], "kw": m["kw"], "span": [m["start"], m["end"]],
                "window": c2.get("window"), "hyp": c2.get("hyp"), "hypothesis": _hyp_text(run, "check2", c2.get("hyp")),
                "fast": c2.get("fast"), "judge": c2.get("judge"), "score": c2.get("score"),
                "judged": c2.get("judge") is not None, "incidental": bool(c2.get("incidental")),
                "window_text": window_text(c2.get("window", [0, 0])),
                # every check-2 hypothesis's scores (decisions written since 2026-11-17; older ones: best only)
                "pairs": [{"hyp": p.get("hyp"), "hypothesis": _hyp_text(run, "check2", p.get("hyp")),
                           "fast": p.get("fast"), "judge": p.get("judge"), "score": p.get("score"),
                           "judged": p.get("judge") is not None, "best": p.get("hyp") == c2.get("hyp")}
                          for p in c2.get("pairs") or []],
            })

    # ---- verdict ----------------------------------------------------------------------------------
    reason = decision.get("reason")
    steps: List[str] = []
    n_hits = len(hits)
    if n_hits:
        steps.append(f"{n_hits} keyword hit{'s' if n_hits != 1 else ''}: "
                     + ", ".join(f"'{h.get('kw')}'" for h in hits[:8]) + (" ..." if n_hits > 8 else ""))
    ruled = [h for h in hits if h.get("rule")]
    if ruled:
        steps.append("resolved by rules: " + ", ".join(f"'{h.get('kw')}' ({h['rule']})" for h in ruled[:8]))
    if c1:
        best = max(check1_rows, key=lambda r: r["score"] or 0) if check1_rows else None
        if best:
            by = f", decided by the judge {judge}" if best["judged"] else (f", fast model {fast}" if fast else "")
            steps.append(f"check 1: best score {_fmt(best['score'])} {'>=' if best['passed'] else '<'} threshold "
                         f"{t1} for '{best['hyp']}' on characters {best['window'][0]}-{best['window'][1]}{by}")
        if c1.get("skipped"):
            n = c1["skipped"]
            steps.append(f"check 1 stopped early: {n} more window{'s' if n != 1 else ''} not scored "
                         f"(the line was already over the threshold)")
    if check2_rows:
        inc = [r for r in check2_rows if r["incidental"]]
        not_inc = [r for r in check2_rows if not r["incidental"]]
        if inc:
            steps.append("check 2 incidental: " + ", ".join(f"'{r['kw']}' ({r['hyp']} {_fmt(r['score'])})" for r in inc[:6]))
        if not_inc:
            steps.append("check 2 NOT incidental: " + ", ".join(f"'{r['kw']}' (best {_fmt(r['score'])} < {t2})"
                                                                 for r in not_inc[:6]))
    if decision.get("check2_skipped"):
        n = decision["check2_skipped"]
        steps.append(f"check 2 stopped early: {n} more hit{'s' if n != 1 else ''} not scored "
                     f"(one hit was already not incidental, so the line is filtered)")
    summary = REASON_TEXT.get(reason, f"{decision.get('decision')}: {reason}")
    expect = decision.get("expect")
    expect_info = None
    if isinstance(expect, str) and expect.lower() in ("filter", "keep"):
        expect_info = {"value": expect, "correct": expect.lower() == decision.get("decision")}
    return {
        "text_available": text is not None, "text_length": None if text is None else len(text),
        "excerpted": excerpted, "marks": marks, "segments": segments,
        "check1": {"threshold": t1, "positive": c1.get("positive"), "score": c1.get("score"), "rows": check1_rows}
        if c1 else None,
        "check2": {"threshold": t2, "rows": check2_rows,
                   "all_incidental": bool(check2_rows) and all(r["incidental"] for r in check2_rows)}
        if check2_rows else None,
        "verdict": {"decision": decision.get("decision"), "reason": reason, "summary": summary, "steps": steps},
        "expect": expect_info,
        "models": {"fast": fast, "judge": judge, "band": band, "check1_threshold": t1, "check2_threshold": t2,
                   "fast_info": models.get("fast"), "judge_info": models.get("judge")},
    }

"""
nli_replay.py - recompute an nli_filter.py run's decisions from its STORED scores (no model is loaded):
other thresholds, and / or some hypotheses left out. Writes a normal output folder (decisions + summaries),
so the viewer can show it and nli_compare.py can compare it with the original run.

    python nli_replay.py out_ru_kw --drop-check1 history --output-dir out_ru_kw_nohistory
    python nli_replay.py out_ru_kw --check1-threshold 0.7 --check2-threshold 0.9 --output-dir out_ru_kw_t07
    python nli_compare.py out_ru_kw out_ru_kw_nohistory

What it can and cannot know:
  - Every hypothesis of a scored check-1 window / check-2 sentence is stored, so dropping hypotheses and moving
    thresholds is exact for those.
  - Early stop (the default) leaves some windows / hit sentences unscored. When the replayed decision depends
    on them, the line is marked "estimated" (replay.estimated = true) and decided like the viewer's Tune page:
    a line that becomes check-1 positive without check-2 scores is filtered. For exact replays, run nli_filter.py
    once with --no-early-stop.
  - Keyword-built hypotheses (keys "<key>:<keyword>") are dropped with their template key: --drop-check1 place
    drops place:Siberia, place:Moscow, ...
  - Lines decided without models (no keyword, rules, level-A keywords) keep their decision.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from nli_compare import _decision_files, _read_lines  # noqa: E402

REASONS = ["blank", "bad_json", "no_text", "no_keyword", "rules_incidental", "check1_negative",
           "check2_incidental", "about_country", "strict_keyword", "keyword_only"]


def _dropped(key: str, drop: Iterable[str]) -> bool:
    base = key.split(":", 1)[0]
    return key in drop or base in drop


def replay_one(d: Dict[str, Any], t1: float, t2: float, drop1: set, drop2: set) -> Dict[str, Any]:
    """One decision recomputed (a new dict; the input is not changed)."""
    d = json.loads(json.dumps(d))
    c1 = d.get("check1")
    if not c1:  # decided without check 1: no keyword / rules / level A / no text
        return d
    before = (d.get("decision"), d.get("reason"))
    estimated = False
    pairs = [p for p in c1.get("pairs") or [] if not _dropped(p.get("hyp", ""), drop1)]
    best = max(pairs, key=lambda p: p.get("score") or 0.0) if pairs else None
    score = (best or {}).get("score") or 0.0
    positive = score >= t1
    if not positive and c1.get("skipped"):
        estimated = True  # a window that was not scored might pass
    c1.update(pairs=pairs, score=round(score, 4), positive=positive, hyp=(best or {}).get("hyp"),
              window=(best or {}).get("window"))
    open_hits = [h for h in d.get("hits") or [] if not h.get("rule") and h.get("level") != "A"]
    if not positive:
        decision, reason = "keep", "check1_negative"
    else:
        any_c2 = False
        all_inc = True
        for h in open_hits:
            c2 = h.get("check2")
            if not c2:
                all_inc = False  # never scored (early stop, or check 1 was negative in the run)
                continue
            ps = [p for p in c2.get("pairs") or [{"hyp": c2.get("hyp"), "score": c2.get("score"),
                                                   "fast": c2.get("fast"), "judge": c2.get("judge")}]
                  if not _dropped(p.get("hyp", ""), drop2)]
            b = max(ps, key=lambda p: p.get("score") or 0.0) if ps else None
            if b is None:
                h.pop("check2", None)
                all_inc = False
                continue
            any_c2 = True
            inc = (b.get("score") or 0.0) >= t2
            c2.update(pairs=ps, hyp=b.get("hyp"), score=b.get("score"), fast=b.get("fast"), judge=b.get("judge"),
                      incidental=inc)
            if not inc:
                all_inc = False
        unscored = [h for h in open_hits if not h.get("check2")]
        if unscored and before[1] in ("check1_negative",):
            estimated = True  # positive now; check 2 never ran for this line
        if unscored and d.get("check2_skipped"):
            estimated = True
        if any_c2 and all_inc and not unscored:
            decision, reason = "keep", "check2_incidental"
        else:
            decision, reason = "filter", "about_country"
    d["decision"], d["reason"] = decision, reason
    d["replay"] = {"from": {"decision": before[0], "reason": before[1]}, "estimated": estimated}
    return d


def _stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    dec, rea, rules = collections.Counter(), collections.Counter(), collections.Counter()
    conf = collections.Counter()
    hits = c2h = est = changed = 0
    for d in rows:
        dec[d.get("decision")] += 1
        rea[d.get("reason")] += 1
        for h in d.get("hits") or []:
            hits += 1
            if h.get("rule"):
                rules[h["rule"]] += 1
            if h.get("check2"):
                c2h += 1
        r = d.get("replay") or {}
        est += bool(r.get("estimated"))
        changed += bool(r) and r["from"]["decision"] != d.get("decision")
        e = str(d.get("expect") or "").strip().lower()
        if e in ("filter", "keep"):
            conf[{("filter", "filter"): "tp", ("keep", "filter"): "fp", ("keep", "keep"): "tn",
                  ("filter", "keep"): "fn"}[(e, d.get("decision"))]] += 1
    out: Dict[str, Any] = {"lines": len(rows), "decisions": dict(dec),
                           "reasons": {k: rea[k] for k in REASONS if rea.get(k)}, "rules": dict(rules),
                           "hits": hits, "check2_hits": c2h, "replay": {"changed": changed, "estimated": est}}
    n = sum(conf.values())
    if n:
        tp, fp, tn, fn = conf["tp"], conf["fp"], conf["tn"], conf["fn"]
        out["eval"] = {"confusion": dict(conf), "metrics": {
            "n": n, "tp": tp, "fp": fp, "tn": tn, "fn": fn, "accuracy": (tp + tn) / n,
            "precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None}}
    return out


def replay(src: Path, dst: Path, t1: Optional[float], t2: Optional[float], drop1: Iterable[str],
           drop2: Iterable[str]) -> Dict[str, Any]:
    summary = json.loads((src / "summary.json").read_text(encoding="utf-8")) if (src / "summary.json").is_file() else {}
    st = dict(summary.get("settings") or {})
    t1 = st.get("check1_threshold", 0.8) if t1 is None else t1
    t2 = st.get("check2_threshold", 0.8) if t2 is None else t2
    drop1, drop2 = set(drop1), set(drop2)
    dst.mkdir(parents=True, exist_ok=True)
    every: List[Dict[str, Any]] = []
    files = []
    for key, path in _decision_files(src).items():
        rows = [replay_one(d, t1, t2, drop1, drop2) for d in _read_lines(path)]
        every += rows
        out = dst / f"{key}.decisions.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in rows), encoding="utf-8")
        old = src / f"{key}.summary.json"
        per = json.loads(old.read_text(encoding="utf-8")) if old.is_file() else {}
        per.update(complete=True, seconds=0.0, stats=_stats(rows), outputs={"decisions": out.name})
        (dst / f"{key}.summary.json").write_text(json.dumps(per, ensure_ascii=False, indent=1), encoding="utf-8")
        files.append({"input": per.get("input"), "status": "done", "lines": len(rows),
                      "filtered": sum(1 for d in rows if d.get("decision") == "filter"), "seconds": 0.0})
    hyp = json.loads(json.dumps(summary.get("hypotheses") or {}))
    for chk, drop in (("check1", drop1), ("check2", drop2)):
        hyp[chk] = {k: v for k, v in (hyp.get(chk) or {}).items() if k not in drop}
        types = hyp.get(f"{chk}_types") or {}
        for typ in list(types):
            types[typ] = {k: v for k, v in types[typ].items() if k not in drop}
            if not types[typ]:
                del types[typ]
    st.update(check1_threshold=t1, check2_threshold=t2)
    run = dict(summary, hypotheses=hyp, settings=st, files=files, stats=_stats(every), output_dir=str(dst),
               replay={"of": str(src), "drop_check1": sorted(drop1), "drop_check2": sorted(drop2),
                       "check1_threshold": t1, "check2_threshold": t2},
               timing={"run_seconds": 0.0, "fast_pairs": 0, "judge_pairs": 0, "replayed": True},
               command="nli_replay.py " + " ".join(sys.argv[1:]), finished=time.strftime("%Y-%m-%d %H:%M:%S"))
    (dst / "summary.json").write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8")
    return run


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Recompute a run's decisions from its stored scores (no models): "
                                             "other thresholds and / or hypotheses left out.")
    ap.add_argument("run", help="output folder of an nli_filter.py run")
    ap.add_argument("--output-dir", required=True, help="where to write the replayed run (a new folder)")
    ap.add_argument("--check1-threshold", type=float)
    ap.add_argument("--check2-threshold", type=float)
    ap.add_argument("--drop-check1", nargs="+", default=[], metavar="KEY", help="check-1 hypothesis keys to leave out")
    ap.add_argument("--drop-check2", nargs="+", default=[], metavar="KEY", help="check-2 hypothesis keys to leave out")
    args = ap.parse_args(argv)
    src, dst = Path(args.run), Path(args.output_dir)
    if not (src / "summary.json").is_file() and not _decision_files(src):
        print(f"error: {src} is not an nli_filter.py output folder", file=sys.stderr)
        return 2
    if dst.resolve() == src.resolve():
        print("error: --output-dir must be a new folder, not the run itself", file=sys.stderr)
        return 2
    for t in (args.check1_threshold, args.check2_threshold):
        if t is not None and not 0 <= t <= 1:
            print("error: thresholds must be between 0 and 1", file=sys.stderr)
            return 2
    summ = json.loads((src / "summary.json").read_text(encoding="utf-8")) if (src / "summary.json").is_file() else {}
    hyps = summ.get("hypotheses") or {}
    run = replay(src, dst, args.check1_threshold, args.check2_threshold, args.drop_check1, args.drop_check2)
    s = run["stats"]
    m = (s.get("eval") or {}).get("metrics")
    print(f"replayed {s['lines']} lines into {dst}: {s['replay']['changed']} changed, "
          f"{s['replay']['estimated']} estimated (scores not stored because of early stop)")
    if m:
        print(f"accuracy {m['accuracy']:.3f} ({m['tp'] + m['tn']}/{m['n']})")
    for chk, drop in (("check1", args.drop_check1), ("check2", args.drop_check2)):
        known = set(hyps.get(chk) or {}) | {k for t in (hyps.get(f"{chk}_types") or {}).values() for k in t}
        unknown = [k for k in drop if hyps and k not in known]
        if unknown:
            print(f"note: not a {chk} hypothesis key of the run: {', '.join(unknown)}")
    print(f"compare: python nli_compare.py {src} {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

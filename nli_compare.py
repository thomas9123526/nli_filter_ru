"""
nli_compare.py - compare two nli_filter.py output folders line by line (no model is loaded).

    python nli_compare.py out_ru_plain out_ru_kw
    python nli_compare.py out_ru_plain out_ru_kw --json compare.json --show 50

Shows, for runs of the SAME input (e.g. the same test file with other keywords / hypotheses / thresholds):
  - each run's accuracy / precision / recall (when lines have expect labels), model pairs, time
  - which lines changed their decision, and whether the change made them right or wrong
  - reasons A vs B, and what differs in the settings, hypotheses and keywords of the two runs
Lines are matched by their result file (path inside the output folder) and line number.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

_SUFFIXES = (".decisions.jsonl.zst", ".decisions.jsonl.gz", ".decisions.jsonl")


def _decision_files(out: Path) -> Dict[str, Path]:
    """result key (path inside the folder without the suffix) -> decisions file"""
    found: Dict[str, Path] = {}
    for p in sorted(out.rglob("*.decisions.jsonl*")):
        name = p.as_posix()
        for suf in _SUFFIXES:
            if name.endswith(suf):
                found[p.relative_to(out).as_posix()[: -len(suf)]] = p
                break
    return found


def _read_lines(p: Path) -> Iterator[Dict[str, Any]]:
    data = p.read_bytes()
    if p.name.endswith(".zst"):
        import zstandard
        data = zstandard.ZstdDecompressor().stream_reader(__import__("io").BytesIO(data)).read()
    elif p.name.endswith(".gz"):
        import gzip
        data = gzip.decompress(data)
    for raw in data.splitlines():
        if raw.strip():
            try:
                yield json.loads(raw)
            except ValueError:
                continue


def _summary(out: Path) -> Dict[str, Any]:
    p = out / "summary.json"
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {}


def _expect(d: Dict[str, Any]) -> Optional[str]:
    e = str(d.get("expect") or "").strip().lower()
    return e if e in ("filter", "keep") else None


def _metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    c = collections.Counter()
    for d in rows:
        e = _expect(d)
        if e:
            c[{("filter", "filter"): "tp", ("keep", "filter"): "fp", ("keep", "keep"): "tn",
               ("filter", "keep"): "fn"}[(e, d.get("decision"))]] += 1
    n = sum(c.values())
    tp, fp, tn, fn = c["tp"], c["fp"], c["tn"], c["fn"]
    return {"n": n, "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "accuracy": (tp + tn) / n if n else None,
            "precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None}


def _kws(d: Dict[str, Any]) -> List[str]:
    return sorted({h.get("keyword") or h.get("kw", "") for h in d.get("hits") or []})


def _score(d: Dict[str, Any]) -> Optional[float]:
    return (d.get("check1") or {}).get("score")


def _texts(summary: Dict[str, Any], keys: Dict[str, List[int]], base: Path) -> Dict[Tuple[str, int], str]:
    """Best effort: the text of these lines from the run's input files (when they can still be read here)."""
    out: Dict[Tuple[str, int], str] = {}
    field = (summary.get("settings") or {}).get("text_field", "text")
    for f in summary.get("files") or []:
        inp = f.get("input")
        if not inp:
            continue
        stem = Path(str(inp).replace("\\", "/")).name.split(".")[0]
        key = next((k for k in keys if Path(k).name.split(".")[0] == stem), None)
        if key is None:
            continue
        p = Path(inp)
        if not p.is_absolute():
            p = (base / p) if (base / p).exists() else (Path.cwd() / p)
        if not p.exists():
            continue
        want = set(keys[key])
        try:
            for n, d in enumerate(_read_lines(p), 1):
                if n in want and isinstance(d.get(field), str):
                    out[(key, n)] = d[field]
        except OSError:
            continue
    return out


def _dict_diff(a: Dict[str, Any], b: Dict[str, Any], skip=()) -> List[Tuple[str, Any, Any]]:
    keys = sorted(set(a) | set(b))
    return [(k, a.get(k), b.get(k)) for k in keys if k not in skip and a.get(k) != b.get(k)]


def compare(a_dir: Path, b_dir: Path) -> Dict[str, Any]:
    fa, fb = _decision_files(a_dir), _decision_files(b_dir)
    common = sorted(set(fa) & set(fb))
    rows_a: List[Dict[str, Any]] = []
    rows_b: List[Dict[str, Any]] = []
    changed: List[Dict[str, Any]] = []
    same = 0
    for key in common:
        da = {(d.get("source"), d.get("line")): d for d in _read_lines(fa[key])}
        db = {(d.get("source"), d.get("line")): d for d in _read_lines(fb[key])}
        for k in sorted(set(da) & set(db), key=lambda x: (str(x[0]), x[1] or 0)):
            x, y = da[k], db[k]
            rows_a.append(x)
            rows_b.append(y)
            if x.get("decision") == y.get("decision"):
                same += 1
                continue
            e = _expect(x) or _expect(y)
            verdict = "unlabelled" if not e else ("better" if y.get("decision") == e else "worse")
            changed.append({"file": key, "line": k[1], "source": k[0], "id": x.get("id"), "expect": e,
                            "verdict": verdict,
                            "a": {"decision": x.get("decision"), "reason": x.get("reason"), "check1": _score(x)},
                            "b": {"decision": y.get("decision"), "reason": y.get("reason"), "check1": _score(y)},
                            "keywords": sorted(set(_kws(x)) | set(_kws(y)))})
    sa, sb = _summary(a_dir), _summary(b_dir)
    texts = _texts(sb or sa, {k: [c["line"] for c in changed if c["file"] == k] for k in common}, HERE) if changed else {}
    for c in changed:
        if (c["file"], c["line"]) in texts:
            c["text"] = texts[(c["file"], c["line"])]
    reasons = collections.Counter()
    for x, y in zip(rows_a, rows_b):
        reasons[(x.get("reason"), y.get("reason"))] += 1
    ha, hb = sa.get("hypotheses") or {}, sb.get("hypotheses") or {}
    diffs = {
        "settings": _dict_diff(sa.get("settings") or {}, sb.get("settings") or {}, skip=("shard",)),
        "check1": _dict_diff(ha.get("check1") or {}, hb.get("check1") or {}),
        "check2": _dict_diff(ha.get("check2") or {}, hb.get("check2") or {}),
        "check1_types": _dict_diff(ha.get("check1_types") or {}, hb.get("check1_types") or {}),
        "check2_types": _dict_diff(ha.get("check2_types") or {}, hb.get("check2_types") or {}),
        "keywords_only_a": sorted(set((sa.get("country") or {}).get("keywords") or []) - set((sb.get("country") or {}).get("keywords") or [])),
        "keywords_only_b": sorted(set((sb.get("country") or {}).get("keywords") or []) - set((sa.get("country") or {}).get("keywords") or [])),
        "lexicon": _dict_diff((sa.get("country") or {}).get("lexicon_meta") or {}, (sb.get("country") or {}).get("lexicon_meta") or {}),
    }
    return {
        "a": {"dir": str(a_dir), "hypotheses_file": ha.get("file"), "metrics": _metrics(rows_a), "timing": sa.get("timing"),
              "command": sa.get("command")},
        "b": {"dir": str(b_dir), "hypotheses_file": hb.get("file"), "metrics": _metrics(rows_b), "timing": sb.get("timing"),
              "command": sb.get("command")},
        "files": {"common": len(common), "only_a": sorted(set(fa) - set(fb)), "only_b": sorted(set(fb) - set(fa))},
        "lines": len(rows_a), "same": same, "changed": changed,
        "changes": dict(collections.Counter(f"{c['a']['decision']} -> {c['b']['decision']}" for c in changed)),
        "verdicts": dict(collections.Counter(c["verdict"] for c in changed)),
        "reasons": [{"a": ra, "b": rb, "lines": n} for (ra, rb), n in sorted(reasons.items(), key=lambda kv: -kv[1])],
        "diffs": diffs,
    }


def _f(x: Optional[float], d: int = 3) -> str:
    return "-" if x is None else f"{x:.{d}f}"


def render(r: Dict[str, Any], show: int = 30) -> str:
    L = ["", "=" * 78, " nli_compare: A vs B", "=" * 78]
    for side in ("a", "b"):
        s, m, t = r[side], r[side]["metrics"], r[side]["timing"] or {}
        acc = f"accuracy {_f(m['accuracy'])} ({m['tp'] + m['tn']}/{m['n']}), precision {_f(m['precision'])}, recall {_f(m['recall'])}" \
            if m["n"] else "no expect labels"
        L.append(f" {side.upper()}: {s['dir']}  hypotheses {s['hypotheses_file'] or '-'}")
        L.append(f"    {acc}")
        if t:
            L.append(f"    pairs fast {t.get('fast_pairs', '-')} / judge {t.get('judge_pairs', '-')}, run {t.get('run_seconds', '-')} s, "
                     f"{t.get('lines_per_second', '-')} lines/s")
    f = r["files"]
    L.append(f" result files compared {f['common']}" + (f", only in A {len(f['only_a'])}" if f["only_a"] else "")
             + (f", only in B {len(f['only_b'])}" if f["only_b"] else ""))
    L.append(f" lines {r['lines']}: same decision {r['same']}, changed {len(r['changed'])}"
             + (f"  ({', '.join(f'{k} {v}' for k, v in r['changes'].items())})" if r["changes"] else ""))
    if r["verdicts"]:
        L.append("   " + ", ".join(f"{k} {v}" for k, v in r["verdicts"].items())
                 + "   (better = B is now right, worse = B is now wrong)")
    if r["changed"]:
        L += ["", f" changed lines (first {min(show, len(r['changed']))}):"]
        order = {"worse": 0, "better": 1, "unlabelled": 2}
        for c in sorted(r["changed"], key=lambda c: (order[c["verdict"]], c["file"], c["line"]))[:show]:
            a, b = c["a"], c["b"]
            L.append(f"  [{c['verdict']}] {c['file']}:{c['line']} id {c['id']}" + (f" expect {c['expect']}" if c["expect"] else ""))
            L.append(f"      A {a['decision']} ({a['reason']}, c1 {_f(a['check1'])})  ->  B {b['decision']} ({b['reason']}, c1 {_f(b['check1'])})"
                     f"  keywords {', '.join(c['keywords']) or '-'}")
            if c.get("text"):
                t = " ".join(c["text"].split())
                L.append(f"      \"{t[:150]}{'...' if len(t) > 150 else ''}\"")
    moved = [x for x in r["reasons"] if x["a"] != x["b"]]
    if moved:
        L += ["", " reasons that changed (A -> B: lines):"]
        L += [f"   {x['a']} -> {x['b']}: {x['lines']}" for x in moved[:20]]
    d = r["diffs"]
    lines = []
    for k, va, vb in d["settings"]:
        lines.append(f"   setting {k}: {va} -> {vb}")
    for chk in ("check1", "check2"):
        for k, va, vb in d[chk]:
            lines.append(f"   {chk} '{k}': {'(none)' if va is None else repr(va)} -> {'(none)' if vb is None else repr(vb)}")
    for chk in ("check1_types", "check2_types"):
        for k, va, vb in d[chk]:
            lines.append(f"   {chk} '{k}': {va} -> {vb}")
    if d["keywords_only_a"]:
        lines.append(f"   keywords only in A: {', '.join(d['keywords_only_a'][:30])}")
    if d["keywords_only_b"]:
        lines.append(f"   keywords only in B: {', '.join(d['keywords_only_b'][:30])}")
    for k, va, vb in d["lexicon"][:30]:
        lines.append(f"   lexicon '{k}': {va} -> {vb}")
    if lines:
        L += ["", " what differs between the runs:"] + lines
    L.append("=" * 78)
    return "\n".join(L) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Compare two nli_filter.py output folders line by line (no models).")
    ap.add_argument("a", help="output folder of run A (e.g. the old settings)")
    ap.add_argument("b", help="output folder of run B (e.g. the new settings)")
    ap.add_argument("--show", type=int, default=30, help="changed lines to print (default 30)")
    ap.add_argument("--json", help="also write the full comparison to this JSON file")
    args = ap.parse_args(argv)
    a, b = Path(args.a), Path(args.b)
    for p in (a, b):
        if not p.is_dir():
            print(f"error: not a folder: {p}", file=sys.stderr)
            return 2
    r = compare(a, b)
    if not r["files"]["common"]:
        print("error: the two folders have no result file in common (were they made from the same input?)", file=sys.stderr)
        return 2
    try:
        sys.stdout.write(render(r, args.show))
    except UnicodeEncodeError:  # a Windows console that cannot show some characters
        sys.stdout.write(render(r, args.show).encode("ascii", "replace").decode("ascii"))
    if args.json:
        Path(args.json).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"full comparison: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

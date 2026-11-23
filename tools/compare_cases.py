"""
compare_cases.py - a nli_label.py run on a cases corpus vs the cases' expected actions.

    python tools/compare_cases.py out_label_ru_v1 --corpus test_corpus_cases_ru [--details]

The corpus is the one tools/build_cases_corpus.py wrote (each line has expected_action, acceptable, case, note).
A text is OK when its action is the expected one or one of its "acceptable" actions. The action of a text is its
strictest paragraph action (remove > review > keep > pass), or the document action when no paragraph was labelled
(untouched). "pass" and "untouched" count as the same (as on the viewer's Try page).
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

ORDER = ("remove", "review", "keep", "pass")


def read_lines(path: Path):
    import zstandard
    raw = path.read_bytes()
    if path.suffix == ".zst":
        raw = zstandard.ZstdDecompressor().stream_reader(raw).read() if False else \
            zstandard.ZstdDecompressor().decompressobj().decompress(raw)
    return [json.loads(x) for x in raw.decode("utf-8").split("\n") if x.strip()]


def text_action(row):
    ps = row.get("paragraphs") or []
    if not ps:
        return row.get("action", "untouched")
    return next(a for a in ORDER if any(p["action"] == a for p in ps))


def main() -> int:
    ap = argparse.ArgumentParser(description="a run on a cases corpus vs the expected actions")
    ap.add_argument("run")
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--details", action="store_true", help="every text, not only the wrong ones")
    args = ap.parse_args()
    run, corpus = Path(args.run), Path(args.corpus)
    by_group = collections.defaultdict(collections.Counter)
    wrong, rows_out = [], []
    for f in sorted(corpus.rglob("*.jsonl*")):
        name = f.name.split(".jsonl")[0]
        lp = run / f"{name}.labels.jsonl"
        if not lp.is_file():
            print(f"missing in the run: {lp.name}")
            continue
        got = {r["line"]: r for r in (json.loads(x) for x in lp.read_text(encoding="utf-8").splitlines() if x)}
        for i, d in enumerate(read_lines(f), 1):
            row = got.get(i) or {}
            act = text_action(row)
            ok_set = {d["expected_action"], *(d.get("acceptable") or [])}
            if ok_set & {"pass", "untouched"}:
                ok_set |= {"pass", "untouched"}  # both leave the text as it is (as on the viewer's Try page)
            ok = act in ok_set
            g = d.get("group") or "?"
            by_group[g]["n"] += 1
            by_group[g]["ok"] += ok
            ps = row.get("paragraphs") or []
            info = {"case": d.get("case"), "text": d["text"], "expected": d["expected_action"],
                    "acceptable": d.get("acceptable") or [], "got": act,
                    "labels": sorted({k for p in ps for k in p.get("labels") or []}),
                    "exception": next((p.get("exception") for p in ps if p.get("exception")), None),
                    "gate": next((p["scores"].get(k) for p in ps for k in p["scores"] if k.startswith("involves")),
                                 None),
                    "ok": ok}
            rows_out.append(info)
            if not ok:
                wrong.append(info)
    n = sum(c["n"] for c in by_group.values())
    ok = sum(c["ok"] for c in by_group.values())
    print(f"{'group':<40} {'texts':>5} {'ok':>4}")
    for g, c in by_group.items():
        print(f"{g:<40} {c['n']:>5} {c['ok']:>4}")
    print(f"{'all':<40} {n:>5} {ok:>4}  ({100.0 * ok / max(1, n):.0f} %)")
    show = rows_out if args.details else wrong
    if show:
        print("\n" + ("every text" if args.details else "not as expected") + ":")
    for w in show:
        mark = "  " if w["ok"] else "x "
        print(f"{mark}[{w['case']}] expected {w['expected']}{'/' + '/'.join(w['acceptable']) if w['acceptable'] else ''}"
              f", got {w['got']}  labels {', '.join(w['labels']) or '-'}"
              f"{'  exception ' + w['exception'] if w['exception'] else ''}"
              f"{'  gate %.2f' % w['gate'] if w['gate'] is not None else ''}")
        print(f"     {w['text'][:150]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

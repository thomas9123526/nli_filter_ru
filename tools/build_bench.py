"""
build_bench.py - assemble the synthetic regression benchmark (hand-written paragraphs with known labels) into a
label file that nli_label.py eval and tools/label_tool.html read.

    python tools/build_bench.py bench_a.json bench_b.json bench_c.json --out labels/bench_synthetic_v1.jsonl

Input: JSON lists of {"id", "target", "kind": "yes"|"near", "text", "labels": {all policy labels}, "note"}.
Checks: unique ids, every policy label answered, target true for "yes" and false for "near" items.
Each item gets status "done", by "synthetic", picked_for ["bench:<target>:<kind>"] and the action the policy
derives from its labels (expected_action, for reading; eval derives it again from the labels).
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import nli_label  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--policy", default=None)
    args = ap.parse_args()
    policy = nli_label.Policy.load(args.policy)
    matcher, rules, markers = nli_label.build_matchers(policy)
    keys = list(policy.labels)
    items, errors, seen = [], [], set()
    for f in args.inputs:
        for d in json.load(open(f, encoding="utf-8")):
            i = d.get("id")
            if i in seen:
                errors.append(f"{i}: duplicate id")
            seen.add(i)
            labs = d.get("labels") or {}
            miss = [k for k in keys if not isinstance(labs.get(k), bool)]
            if miss:
                errors.append(f"{i}: labels missing / not true-false: {', '.join(miss)}")
                continue
            t, kind = d.get("target"), d.get("kind")
            if t in policy.labels and kind in ("yes", "near") and labs[t] != (kind == "yes"):
                errors.append(f"{i}: target {t} is {labs[t]} but kind is {kind}")
            text = d["text"].strip()
            hs = matcher.find(text)
            if hs:
                rules.apply(text, hs)
            hits = [[h.start, h.end] for h in hs if not h.rule]
            if markers is not None:
                hits += [[m.start, m.end] for m in markers.find(text)]
            marker = bool(markers is not None and markers.find(text))
            items.append({
                "key": f"bench#{i}", "source": {"file": "synthetic", "line": None, "span": None, "id": i},
                "text": text, "before": "", "after": "", "hits": sorted(hits), "marker": marker,
                "picked_for": [f"bench:{t}:{kind}"], "model": None,
                "labels": {k: labs[k] for k in keys}, "action": None,
                "expected_action": nli_label.action_from_labels(policy, labs, marker),
                "status": "done", "by": "synthetic", "note": d.get("note", "")})
    if errors:
        print("problems:\n  " + "\n  ".join(errors[:40]), file=sys.stderr)
        return 1
    meta = nli_label.label_meta(policy, kind="synthetic regression benchmark", version=Path(args.out).stem)
    nli_label.write_labels_file(args.out, meta, items)
    by_t = collections.Counter(f"{it['picked_for'][0].split(':')[1]}:{it['picked_for'][0].split(':')[2]}"
                               for it in items)
    acts = collections.Counter(it["expected_action"] for it in items)
    yes = {k: sum(1 for it in items if it["labels"][k]) for k in keys}
    print(f"{len(items)} items -> {args.out}")
    print("expected actions: " + ", ".join(f"{a} {n}" for a, n in acts.most_common()))
    print("yes per label:    " + ", ".join(f"{k} {n}" for k, n in yes.items()))
    print("targets:          " + ", ".join(f"{k} {n}" for k, n in sorted(by_t.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())

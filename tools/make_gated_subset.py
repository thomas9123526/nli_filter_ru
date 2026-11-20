"""
make_gated_subset.py - pick documents that hit the policy's keywords / marker terms from big corpus files
(.parquet / .jsonl / .jsonl.zst), at random, into one small JSONL file: the input for a labelling seed run.

    python tools/make_gated_subset.py corpus_olmo/dclm --n 400 --seed 1 --out corpus_olmo/seed_docs.jsonl

Only id, text, url and source are kept (whatever of them exists). The gate is the same as in nli_label.py
(keywords + rules + markers), so every picked document has at least one paragraph to label.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from nli_label import Policy, build_matchers  # noqa: E402
from nli_models import JsonlSource, expand_inputs  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Random documents that pass the keyword gate -> one JSONL file.")
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--policy", default=None)
    ap.add_argument("--text-field", default="text")
    ap.add_argument("--keep-fields", default="id,url,source", help="fields copied besides the text")
    args = ap.parse_args()
    pol = Policy.load(args.policy)
    matcher, rules, markers = build_matchers(pol)
    rng = random.Random(args.seed)
    keep = [f for f in args.keep_fields.split(",") if f]
    reservoir, seen = [], 0
    total = 0
    for path in expand_inputs(args.inputs):
        for rec in JsonlSource(path).records():
            total += 1
            text = rec.get(args.text_field)
            if not isinstance(text, str):
                continue
            hs = matcher.find(text)
            if hs:
                rules.apply(text, hs)
            if not any(not h.rule for h in hs) and not (markers and markers.find(text)):
                continue
            seen += 1
            row = {k: rec.get(k) for k in keep if rec.get(k) is not None}
            row[args.text_field] = text
            row.setdefault("source", Path(path).parent.name)
            if len(reservoir) < args.n:  # reservoir sampling: a uniform sample of all gated documents
                reservoir.append(row)
            else:
                j = rng.randrange(seen)
                if j < args.n:
                    reservoir[j] = row
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        for row in reservoir:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{total:,} documents read, {seen:,} pass the gate ({100.0 * seen / max(1, total):.2f}%), "
          f"{len(reservoir)} picked at random -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

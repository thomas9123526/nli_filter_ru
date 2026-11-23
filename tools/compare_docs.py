"""
compare_docs.py - a nli_label.py run on the multi-paragraph test documents vs their expected actions, paragraph by
paragraph and per document.

    python tools/compare_docs.py dataset/out_label_docs_ru --corpus dataset/test_corpus_docs_ru [--details]

The corpus is the one tools/build_russia_llm_docs.py wrote (each line has expected_paragraphs and
expected_doc_action). A paragraph is OK when its action is the expected one or an "acceptable" one; "none" (never
labelled: no keyword) and "pass" (labelled, the gate called the mention incidental) both leave the text as it is and
count as the same.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

SAME = [{"none", "pass", "untouched"}]


def norm(actions):
    out = set(actions)
    for group in SAME:
        if out & group:
            out |= group
    return out


def main() -> int:
    from nli_label import Policy, output_file, split_paragraphs
    from nli_models import open_text
    ap = argparse.ArgumentParser(description="a run on the test documents vs the expected actions")
    ap.add_argument("run")
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--details", action="store_true", help="every paragraph, not only the wrong ones")
    args = ap.parse_args()
    run, corpus = Path(args.run), Path(args.corpus)
    summ = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    pol = Policy.load(str(HERE / (summ.get("policy") or {}).get("path", "policy/russia_llm_policy_v2.json")))
    by_kind = collections.defaultdict(collections.Counter)
    n_para = ok_para = n_doc = ok_doc = 0
    lines_out = []
    for f in sorted(corpus.rglob("*.jsonl*")):
        name = f.name.split(".jsonl")[0]
        lp = output_file(run, name)
        if lp is None:
            print(f"missing in the run: {name}")
            continue
        with open_text(lp) as fh:
            rows = {r["line"]: r for r in (json.loads(x) for x in fh.read().splitlines() if x.strip())}
        with open_text(f) as fh:
            docs = [json.loads(x) for x in fh.read().split("\n") if x.strip()]
        for i, d in enumerate(docs, 1):
            row = rows.get(i) or {}
            got_paras = {tuple(p["span"]): p for p in row.get("paragraphs") or []}
            spans = split_paragraphs(d["text"], pol.min_chars, pol.max_chars)
            exp = d["expected_paragraphs"]
            if len(spans) != len(exp):
                print(f"{d['id']}: the text splits into {len(spans)} paragraphs, {len(exp)} expected (rebuild the corpus)")
                continue
            doc_ok = True
            for k, ((s, e), x) in enumerate(zip(spans, exp), 1):
                p = got_paras.get((s, e))
                got = p["action"] if p else "none"
                ok = got in norm([x["expected_action"], *(x.get("acceptable") or [])])
                n_para += 1
                ok_para += ok
                doc_ok &= ok
                kind = x["expected_action"]
                by_kind[kind]["n"] += 1
                by_kind[kind]["ok"] += ok
                if args.details or not ok:
                    extra = ""
                    if p:
                        extra = f"  labels {', '.join(p['labels']) or '-'}" + (f"  exception {p['exception']}" if p.get("exception") else "")
                    acc = "/".join(x.get("acceptable") or [])
                    lines_out.append(f"{'  ' if ok else 'x '}{d['id']} ¶{k}: expected {kind}{'/' + acc if acc else ''}, "
                                     f"got {got}{extra}\n      {d['text'][s:e][:110]}…  ({x.get('note', '')})")
            got_doc = row.get("action", "?")
            n_doc += 1
            doc_match = got_doc == d["expected_doc_action"]
            ok_doc += doc_match
            if args.details or not doc_match:
                lines_out.append(f"{'  ' if doc_match else 'x '}{d['id']}: document expected {d['expected_doc_action']}, "
                                 f"got {got_doc}" + ("" if doc_ok else "  (follows from the paragraphs above)"))
    print(f"{'expected':<10} {'paragraphs':>10} {'ok':>4}")
    for k in ("remove", "review", "keep", "none"):
        if by_kind[k]["n"]:
            print(f"{k:<10} {by_kind[k]['n']:>10} {by_kind[k]['ok']:>4}")
    print(f"{'all':<10} {n_para:>10} {ok_para:>4}  ({100.0 * ok_para / max(1, n_para):.0f} %)")
    print(f"documents: {ok_doc} / {n_doc} with the expected document action")
    if lines_out:
        print("\n" + ("every paragraph:" if args.details else "not as expected:"))
        print("\n".join(lines_out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

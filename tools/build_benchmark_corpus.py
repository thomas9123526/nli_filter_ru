"""
build_benchmark_corpus.py - the collected benchmark (dataset/benchmark/benchmark_ru_llm_<name>_v<N>.jsonl) as a
test corpus for nli_label.py and the viewer: .jsonl.zst files in one folder per side and topic.

    python tools/build_benchmark_corpus.py      ->  dataset/corpus_benchmark/<side>/<topic>/<case>__v<N>.jsonl.zst
                                                    + dataset/corpus_benchmark.manifest.json

    dataset/corpus_benchmark/
        russian/companies/russian_companies__v1.jsonl.zst     v1: one sentence per line
        russian/companies/russian_companies__v2.jsonl.zst     v2: the same items as several paragraphs
        ...
        ukrainian/traditions/ukrainian_traditions__v2.jsonl.zst
        shared/contested_history/contested_history__v1.jsonl.zst

Source names: benchmark_ru_llm_russian_<topic>_v<N>.jsonl and benchmark_ru_llm_ukrainian_<topic>_v<N>.jsonl have the
side russian / ukrainian (case <side>_<topic>); any other benchmark_ru_llm_<name>_v<N>.jsonl is a set without a side:
side "shared", topic and case = <name> (e.g. contested_history, negative_controls). New sets need no code change.
Files without _v<N> (e.g. the long / mixed document sets) are skipped.

Each line keeps every source field (text, decision, label, note, clarity, clarity_reason, topic, country,
gate_expected, ... and any later one) and adds:
    id               <case>_v<N>#<k>   (k = 1-based line number in the source file)
    item             <case>#<k>        the same item in v1 and v2 (when all versions of the case have the same count)
    expected_action  = decision (remove / review / keep / flag), read by the viewer's "expected vs result"
    case, group      <case>, <side>    (the viewer's case / group columns)
    variant, source  v<N>, the source file
The added fields win on a name clash, except that a source field "group" is kept as "control_group" (the added
"group" stays the side). nli_label.py reads only id / text; the other fields are passed through for the viewer.

Options:
    --sides russian[,ukrainian,shared]   build only these sides (default: all)
    --flat                               no <side>/ folder level: <topic>/<case>__v<N>.jsonl.zst
    e.g. python tools/build_benchmark_corpus.py --sides russian --flat --out dataset/corpus_benchmark_russian

At the end the number of lines per side and per clarity value (and lines without "clarity") is printed; the
manifest (<out>.manifest.json next to the folder) records the same counts. The source files are not changed.
Rerunning replaces the corpus folder.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

import zstandard

HERE = Path(__file__).resolve().parent.parent
NAME = re.compile(r"benchmark_ru_llm_([a-z0-9_]+?)_v(\d+)\.jsonl$")
SIDED = re.compile(r"(russian|ukrainian)_([a-z0-9_]+)$")
ADDED = ("id", "item", "text", "expected_action", "case", "group", "variant", "source")
NO_CLARITY = "(none)"


def parse_name(name: str):
    """benchmark_ru_llm_<name>_v<N>.jsonl -> (side, topic, case, N), or None."""
    m = NAME.match(name)
    if not m:
        return None
    rest, v = m.group(1), int(m.group(2))
    s = SIDED.match(rest)
    if s:
        side, topic = s.group(1), s.group(2)
        return side, topic, f"{side}_{topic}", v
    return "shared", rest, rest, v


def read(path: Path) -> list:
    rows = []
    for k, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except ValueError as exc:
            raise SystemExit(f"{path.name} line {k}: not JSON ({exc})")
        if not isinstance(d, dict) or not isinstance(d.get("text"), str) or not d["text"].strip():
            raise SystemExit(f"{path.name} line {k}: needs a non-empty \"text\"")
        rows.append(d)
    return rows


def record(d: dict, *, case: str, side: str, v: int, k: int, paired: bool, source: str) -> dict:
    """One corpus line: the builder's fields, then every other source field (source "group" -> "control_group")."""
    rec = {"id": f"{case}_v{v}#{k}", **({"item": f"{case}#{k}"} if paired else {}), "text": d["text"],
           "expected_action": d.get("decision"), "case": case, "group": side, "variant": f"v{v}"}
    for key, val in d.items():
        if key == "group":
            rec["control_group"] = val
        elif key not in ADDED and key not in rec:
            rec[key] = val
    rec["source"] = source
    return rec


def counts(values) -> dict:
    c = Counter(values)
    return {a: c[a] for a in sorted(c, key=lambda x: (x is None, str(x)))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="dataset/benchmark -> dataset/corpus_benchmark (.jsonl.zst)")
    ap.add_argument("--src", default=str(HERE / "dataset" / "benchmark"))
    ap.add_argument("--out", default=str(HERE / "dataset" / "corpus_benchmark"))
    ap.add_argument("--sides", default="",
                    help="comma list of sides to build (russian, ukrainian, shared); default: all")
    ap.add_argument("--flat", action="store_true", help="no <side>/ folder level: <topic>/<case>__v<N>.jsonl.zst")
    args = ap.parse_args(argv)
    src, out = Path(args.src), Path(args.out)
    sides = {s.strip() for s in args.sides.split(",") if s.strip()}
    plan = []
    for p in sorted(src.glob("*.jsonl")):
        parsed = parse_name(p.name)
        if not parsed:
            print(f"skip {p.name} (not benchmark_ru_llm_<name>_v<N>.jsonl)", file=sys.stderr)
            continue
        if sides and parsed[0] not in sides:
            continue
        plan.append((p, *parsed))
    if not plan:
        raise SystemExit(f"no benchmark files in {src}" + (f" for sides {','.join(sorted(sides))}" if sides else ""))
    data = {(case, v): read(p) for p, side, topic, case, v in plan}
    if out.exists():
        shutil.rmtree(out)
    cctx = zstandard.ZstdCompressor(level=10)
    manifest = {"source": str(src.relative_to(HERE)) if src.is_relative_to(HERE) else str(src),
                **({"sides": sorted(sides)} if sides else {}), "flat": args.flat, "files": []}
    per_side, clarity = Counter(), []
    for p, side, topic, case, v in plan:
        rows = data[(case, v)]
        others = [len(r) for (c, vv), r in data.items() if c == case and vv != v]
        paired = bool(others) and all(n == len(rows) for n in others)
        lines = [json.dumps(record(d, case=case, side=side, v=v, k=k, paired=paired,
                                   source=f"dataset/benchmark/{p.name}"), ensure_ascii=False)
                 for k, d in enumerate(rows, 1)]
        target = (out if args.flat else out / side) / topic / f"{case}__v{v}.jsonl.zst"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(cctx.compress(("\n".join(lines) + "\n").encode("utf-8")))
        tags = [d.get("clarity") for d in rows]
        clarity += tags
        per_side[side] += len(lines)
        manifest["files"].append({"path": target.relative_to(out).as_posix(), "from": p.name, "side": side,
                                  "lines": len(lines), "decisions": counts(d.get("decision") for d in rows),
                                  "clarity": counts(t if t is not None else NO_CLARITY for t in tags)})
        shown = target.relative_to(HERE) if target.is_relative_to(HERE) else target
        print(f"{shown.as_posix()}: {len(lines)} lines")
    manifest["lines"] = sum(f["lines"] for f in manifest["files"])
    manifest["lines_per_side"] = dict(sorted(per_side.items()))
    manifest["clarity"] = counts(t for t in clarity if t is not None)
    manifest["no_clarity"] = sum(1 for t in clarity if t is None)
    (out.parent / f"{out.name}.manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                                                          encoding="utf-8")
    shown = out.relative_to(HERE) if out.is_relative_to(HERE) else out
    print(f"{len(manifest['files'])} files, {manifest['lines']} lines -> {shown.as_posix()}")
    print("per side: " + ", ".join(f"{s} {n}" for s, n in manifest["lines_per_side"].items()))
    print("per clarity: " + ", ".join([f"{t} {n}" for t, n in manifest["clarity"].items()]
                                      + [f"without clarity {manifest['no_clarity']}"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

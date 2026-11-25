"""
build_benchmark_corpus.py - the collected benchmark (dataset/benchmark/benchmark_ru_llm_<side>_<topic>_v<N>.jsonl) as a
test corpus for nli_label.py and the viewer: .jsonl.zst files in one folder per side and topic.

    python tools/build_benchmark_corpus.py      ->  dataset/corpus_benchmark/<side>/<topic>/<side>_<topic>__v<N>.jsonl.zst
                                                    + dataset/corpus_benchmark.manifest.json

    dataset/corpus_benchmark/
        russian/companies/russian_companies__v1.jsonl.zst     v1: one sentence per line
        russian/companies/russian_companies__v2.jsonl.zst     v2: the same items as several paragraphs
        ...
        ukrainian/traditions/ukrainian_traditions__v2.jsonl.zst

Each line keeps the source fields (text, decision, label, note) and adds:
    id               <side>_<topic>_v<N>#<k>   (k = 1-based line number in the source file)
    item             <side>_<topic>#<k>        the same item in v1 and v2 (when both files have k lines)
    expected_action  = decision (remove / review / keep / flag), read by the viewer's "expected vs result"
    case, group      <side>_<topic>, <side>    (the viewer's case / group columns)
    variant, source  v<N>, the source file
The source files are not changed. Rerunning replaces the corpus folder.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import zstandard

HERE = Path(__file__).resolve().parent.parent
NAME = re.compile(r"benchmark_ru_llm_(russian|ukrainian)_([a-z_]+?)_v(\d+)\.jsonl$")


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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="dataset/benchmark -> dataset/corpus_benchmark (.jsonl.zst)")
    ap.add_argument("--src", default=str(HERE / "dataset" / "benchmark"))
    ap.add_argument("--out", default=str(HERE / "dataset" / "corpus_benchmark"))
    args = ap.parse_args(argv)
    src, out = Path(args.src), Path(args.out)
    files = sorted(p for p in src.glob("*.jsonl"))
    plan = []
    for p in files:
        m = NAME.match(p.name)
        if not m:
            print(f"skip {p.name} (not benchmark_ru_llm_<side>_<topic>_v<N>.jsonl)", file=sys.stderr)
            continue
        plan.append((p, m.group(1), m.group(2), int(m.group(3))))
    if not plan:
        raise SystemExit(f"no benchmark files in {src}")
    data = {(side, topic, v): read(p) for p, side, topic, v in plan}
    if out.exists():
        shutil.rmtree(out)
    cctx = zstandard.ZstdCompressor(level=10)
    manifest = {"source": str(src.relative_to(HERE)) if src.is_relative_to(HERE) else str(src), "files": []}
    for p, side, topic, v in plan:
        rows = data[(side, topic, v)]
        others = [len(r) for (s, t, vv), r in data.items() if s == side and t == topic and vv != v]
        paired = bool(others) and all(n == len(rows) for n in others)
        case = f"{side}_{topic}"
        lines = []
        for k, d in enumerate(rows, 1):
            rec = {"id": f"{case}_v{v}#{k}", **({"item": f"{case}#{k}"} if paired else {}), "text": d["text"],
                   "expected_action": d.get("decision"), "case": case, "group": side, "variant": f"v{v}",
                   **{x: d[x] for x in ("decision", "label", "note") if x in d}, "source": f"dataset/benchmark/{p.name}"}
            lines.append(json.dumps(rec, ensure_ascii=False))
        target = out / side / topic / f"{case}__v{v}.jsonl.zst"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(cctx.compress(("\n".join(lines) + "\n").encode("utf-8")))
        manifest["files"].append({"path": target.relative_to(out).as_posix(), "from": p.name, "lines": len(lines),
                                  "decisions": {a: sum(1 for d in rows if d.get("decision") == a)
                                                for a in sorted({d.get("decision") for d in rows})}})
        print(f"{target.relative_to(HERE).as_posix()}: {len(lines)} lines")
    manifest["lines"] = sum(f["lines"] for f in manifest["files"])
    (out.parent / f"{out.name}.manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                                                          encoding="utf-8")
    print(f"{len(manifest['files'])} files, {manifest['lines']} lines -> {out.relative_to(HERE).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

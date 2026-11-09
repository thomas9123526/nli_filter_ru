#!/usr/bin/env python3
"""
make_test_corpus.py - build a small nested corpus of .zst files for testing nli_filter.py.

Layout (defaults):

    test_corpus/
        common-crawl-news/          5 top folders
            part-00/                3 sub folders each
                shard-00000.jsonl.zst     1-2 files per sub folder
                shard-00001.jsonl.zst
            part-01/ ...
        common-crawl-games/ ...
    test_corpus.manifest.json       every file with its line count and the line ids (outside the folder,
                                    so nli_filter.py does not read it as input)

Each .zst file is zstd-compressed JSONL: lines sampled from the source file (default test_russia.jsonl),
copied unchanged, so "id", "expect" and "category" stay usable for nli_filter.py's evaluation.

Examples
--------
    python make_test_corpus.py
    python make_test_corpus.py --folders 5 --subfolders 3 --files 1-2 --lines 20-40 --seed 7
    python make_test_corpus.py --source my.jsonl --out D:\\data\\test_corpus --force
    python nli_filter.py test_corpus --device cpu --judge-model none
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from pathlib import Path
from typing import List, Tuple

HERE = Path(__file__).resolve().parent

FOLDER_NAMES = ["common-crawl-news", "common-crawl-games", "wikipedia", "books", "forums",
                "common-crawl-music", "common-crawl-movies", "patents", "papers", "code-comments"]


def parse_range(text: str, what: str) -> Tuple[int, int]:
    """'3' -> (3, 3); '1-2' -> (1, 2)."""
    lo, _, hi = text.partition("-")
    try:
        lo_i, hi_i = int(lo), int(hi or lo)
    except ValueError:
        raise SystemExit(f"error: {what} must be N or MIN-MAX, got {text!r}")
    if lo_i < 1 or hi_i < lo_i:
        raise SystemExit(f"error: {what} needs 1 <= MIN <= MAX, got {text!r}")
    return lo_i, hi_i


def read_lines(path: Path) -> List[bytes]:
    lines = []
    with open(path, "rb") as fh:
        for n, line in enumerate(fh, 1):
            line = line.rstrip(b"\r\n")
            if not line.strip():
                continue
            try:
                json.loads(line)
            except ValueError:
                raise SystemExit(f"error: {path} line {n} is not valid JSON")
            lines.append(line)
    if not lines:
        raise SystemExit(f"error: {path} has no JSON lines")
    return lines


def main() -> int:
    p = argparse.ArgumentParser(description="Build a nested test corpus of .jsonl.zst files.",
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__.split("Examples\n--------\n", 1)[1])
    p.add_argument("--source", default=str(HERE / "test_russia.jsonl"), help="JSONL to sample lines from "
                                                                              "(default test_russia.jsonl)")
    p.add_argument("--out", default=str(HERE / "test_corpus"), help="output folder (default ./test_corpus)")
    p.add_argument("--folders", type=int, default=5, help="top-level folders (default 5, max 10 named)")
    p.add_argument("--subfolders", type=int, default=3, help="sub folders in each folder (default 3)")
    p.add_argument("--files", default="1-2", help="zst files per sub folder, N or MIN-MAX (default 1-2)")
    p.add_argument("--lines", default="20-40", help="lines per file, N or MIN-MAX (default 20-40)")
    p.add_argument("--level", type=int, default=3, help="zstd compression level (default 3)")
    p.add_argument("--seed", type=int, default=42, help="random seed; same seed = same corpus (default 42)")
    p.add_argument("--force", action="store_true", help="delete the output folder first if it exists")
    args = p.parse_args()

    try:
        import zstandard
    except ImportError:
        print("error: needs the 'zstandard' package: python -m pip install zstandard", file=sys.stderr)
        return 2

    files_lo, files_hi = parse_range(args.files, "--files")
    lines_lo, lines_hi = parse_range(args.lines, "--lines")
    if not 1 <= args.folders <= len(FOLDER_NAMES):
        print(f"error: --folders must be 1..{len(FOLDER_NAMES)}", file=sys.stderr)
        return 2
    if args.subfolders < 1:
        print("error: --subfolders must be >= 1", file=sys.stderr)
        return 2

    source = Path(args.source)
    if not source.is_file():
        print(f"error: source not found: {source}", file=sys.stderr)
        return 2
    out = Path(args.out)
    manifest_path = out.parent / f"{out.name}.manifest.json"
    if out.exists():
        if not args.force:
            print(f"error: {out} already exists; use --force to replace it", file=sys.stderr)
            return 2
        shutil.rmtree(out)

    lines = read_lines(source)
    rng = random.Random(args.seed)
    cctx = zstandard.ZstdCompressor(level=args.level)
    manifest = {"source": str(source), "seed": args.seed, "files": []}
    total_lines = 0

    for folder in FOLDER_NAMES[:args.folders]:
        for s in range(args.subfolders):
            leaf = out / folder / f"part-{s:02d}"
            leaf.mkdir(parents=True, exist_ok=True)
            for f in range(rng.randint(files_lo, files_hi)):
                n = rng.randint(lines_lo, lines_hi)
                # without repeats when the source is big enough, otherwise with repeats
                picked = rng.sample(lines, n) if n <= len(lines) else [rng.choice(lines) for _ in range(n)]
                path = leaf / f"shard-{f:05d}.jsonl.zst"
                with open(path, "wb") as raw, cctx.stream_writer(raw) as zw:
                    zw.write(b"\n".join(picked) + b"\n")
                ids = [json.loads(x).get("id") for x in picked]
                manifest["files"].append({"path": str(path.relative_to(out)).replace("\\", "/"),
                                          "lines": n, "ids": ids})
                total_lines += n

    # read every file back to make sure it decompresses to the same number of valid JSON lines
    dctx = zstandard.ZstdDecompressor()
    for entry in manifest["files"]:
        with open(out / entry["path"], "rb") as fh:
            data = dctx.stream_reader(fh).read()
        got = [json.loads(x) for x in data.splitlines() if x.strip()]
        if len(got) != entry["lines"]:
            print(f"error: {entry['path']}: wrote {entry['lines']} lines, read back {len(got)}", file=sys.stderr)
            return 1

    manifest["total_files"] = len(manifest["files"])
    manifest["total_lines"] = total_lines
    # next to the folder, not inside it: nli_filter.py would read a .json file inside as input
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)

    print(f"{out}: {args.folders} folders x {args.subfolders} sub folders, {len(manifest['files'])} .zst files, "
          f"{total_lines} lines (from {len(lines)} source lines, seed {args.seed}); all files verified")
    print(f"manifest: {manifest_path}")
    for folder in FOLDER_NAMES[:args.folders]:
        entries = [e for e in manifest["files"] if e["path"].startswith(folder + "/")]
        print(f"  {folder:<20} {len(entries)} files, {sum(e['lines'] for e in entries)} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())

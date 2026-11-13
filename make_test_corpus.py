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

Long texts (--long-lines): each .zst file also gets N generated texts of about --long-chars characters
(default 12,000) about / mentioning Russia, in the 8 categories of test_russia_long.jsonl (long_about_last,
long_incidental_only, ...) with "expect" labels, mixed in at random places. Keep N small (default 1-2 when the
option is given without a number): every long text costs nli_filter.py several model calls.

Examples
--------
    python make_test_corpus.py
    python make_test_corpus.py --folders 5 --subfolders 3 --files 1-2 --lines 20-40 --seed 7
    python make_test_corpus.py --source my.jsonl --out D:\\data\\test_corpus --force
    python make_test_corpus.py --long-lines                      # + 1-2 long texts (~12,000 chars) per file
    python make_test_corpus.py --long-lines 1 --lines 0 --folders 200 --out test_corpus_long --force
                                                                 # 200 folders, every file = 1 long text only
    python make_test_corpus.py --long-lines 2 --long-chars 20000 --long-categories long_about_last,long_about_middle
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

from long_texts import CATEGORIES as LONG_CATEGORIES, MIN_CHARS, check_pools, make_long_record, pick_categories

HERE = Path(__file__).resolve().parent

FOLDER_NAMES = ["common-crawl-news", "common-crawl-games", "wikipedia", "books", "forums",
                "common-crawl-music", "common-crawl-movies", "patents", "papers", "code-comments"]


def parse_range(text: str, what: str, minimum: int = 1) -> Tuple[int, int]:
    """'3' -> (3, 3); '1-2' -> (1, 2)."""
    lo, _, hi = text.partition("-")
    try:
        lo_i, hi_i = int(lo), int(hi or lo)
    except ValueError:
        raise SystemExit(f"error: {what} must be N or MIN-MAX, got {text!r}")
    if lo_i < minimum or hi_i < lo_i:
        raise SystemExit(f"error: {what} needs {minimum} <= MIN <= MAX, got {text!r}")
    return lo_i, hi_i


def folder_name(i: int) -> str:
    """The 10 named folders first, then folder-010, folder-011, ..."""
    return FOLDER_NAMES[i] if i < len(FOLDER_NAMES) else f"folder-{i:03d}"


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
    p.add_argument("--folders", type=int, default=5, help="top-level folders (default 5; the first 10 have names "
                                                          "like 'books', then folder-010, folder-011, ...)")
    p.add_argument("--subfolders", type=int, default=3, help="sub folders in each folder (default 3)")
    p.add_argument("--files", default="1-2", help="zst files per sub folder, N or MIN-MAX (default 1-2)")
    p.add_argument("--lines", default="20-40", help="lines sampled from --source per file, N or MIN-MAX "
                                                    "(default 20-40; 0 = only the long texts)")
    g = p.add_argument_group("long texts (like test_russia_long.jsonl, generated)")
    g.add_argument("--long-lines", nargs="?", const="1-2", default="0", metavar="N|MIN-MAX",
                   help="long texts per .zst file; the option alone = 1-2; default 0 (none)")
    g.add_argument("--long-chars", type=int, default=12000,
                   help=f"length of each long text in characters (default 12000, min {MIN_CHARS})")
    g.add_argument("--long-categories", default=",".join(LONG_CATEGORIES),
                   help="comma-separated categories to draw from (default all 8: " + ", ".join(LONG_CATEGORIES) + ")")
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
    long_lo, long_hi = parse_range(args.long_lines, "--long-lines", minimum=0)
    lines_lo, lines_hi = parse_range(args.lines, "--lines", minimum=0)
    if lines_lo + long_lo < 1:
        print("error: every file needs at least one line: --lines MIN or --long-lines MIN must be >= 1",
              file=sys.stderr)
        return 2
    if args.folders < 1:
        print("error: --folders must be >= 1", file=sys.stderr)
        return 2
    if long_hi and args.long_chars < MIN_CHARS:
        print(f"error: --long-chars must be >= {MIN_CHARS} (the Russia sentences must be > 1,000 characters apart)",
              file=sys.stderr)
        return 2
    try:
        long_cats = pick_categories([c.strip() for c in args.long_categories.split(",") if c.strip()])
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if long_hi and not long_cats:
        print("error: --long-categories is empty", file=sys.stderr)
        return 2
    check_pools()
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
    if long_hi:
        manifest["long"] = {"lines_per_file": args.long_lines, "chars": args.long_chars, "categories": long_cats}
    total_lines = total_long = 0
    long_counter = 0

    for i in range(args.folders):
        folder = folder_name(i)
        for s in range(args.subfolders):
            leaf = out / folder / f"part-{s:02d}"
            leaf.mkdir(parents=True, exist_ok=True)
            for f in range(rng.randint(files_lo, files_hi)):
                n = rng.randint(lines_lo, lines_hi)
                # without repeats when the source is big enough, otherwise with repeats
                picked = rng.sample(lines, n) if n <= len(lines) else [rng.choice(lines) for _ in range(n)]
                n_long = rng.randint(long_lo, long_hi) if long_hi else 0
                if n + n_long == 0:  # e.g. --lines 0-5 --long-lines 0-2 drew 0 and 0: one long text
                    n_long = 1
                for _ in range(n_long):
                    long_counter += 1
                    cat = long_cats[(long_counter - 1) % len(long_cats)]  # every category in turn
                    rec = make_long_record(rng, cat, f"{cat}-g{long_counter:06d}", chars=args.long_chars)
                    line = json.dumps(rec, ensure_ascii=False).encode("utf-8")
                    picked.insert(rng.randint(0, len(picked)), line)  # at a random place in the file
                path = leaf / f"shard-{f:05d}.jsonl.zst"
                with open(path, "wb") as raw, cctx.stream_writer(raw) as zw:
                    zw.write(b"\n".join(picked) + b"\n")
                ids = [json.loads(x).get("id") for x in picked]
                entry = {"path": str(path.relative_to(out)).replace("\\", "/"), "lines": len(picked), "ids": ids}
                if n_long:
                    entry["long_lines"] = n_long
                manifest["files"].append(entry)
                total_lines += len(picked)
                total_long += n_long

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
    if long_hi:
        manifest["total_long_lines"] = total_long
    # next to the folder, not inside it: nli_filter.py would read a .json file inside as input
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)

    long_note = f", {total_long} of them long texts (~{args.long_chars:,} chars)" if long_hi else ""
    print(f"{out}: {args.folders} folders x {args.subfolders} sub folders, {len(manifest['files'])} .zst files, "
          f"{total_lines} lines{long_note} (from {len(lines)} source lines, seed {args.seed}); all files verified")
    print(f"manifest: {manifest_path}")
    shown = range(args.folders) if args.folders <= 12 else list(range(10)) + [args.folders - 1]
    for i in shown:
        folder = folder_name(i)
        if args.folders > 12 and i == args.folders - 1:
            print(f"  ... ({args.folders - 11} more folders)")
        entries = [e for e in manifest["files"] if e["path"].startswith(folder + "/")]
        n_long = sum(e.get("long_lines", 0) for e in entries)
        print(f"  {folder:<20} {len(entries)} files, {sum(e['lines'] for e in entries)} lines"
              + (f" ({n_long} long)" if long_hi else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

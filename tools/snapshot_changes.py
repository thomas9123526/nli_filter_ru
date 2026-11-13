#!/usr/bin/env python3
"""
snapshot_changes.py - remember the files of a folder, later list what changed and copy only those files
(keeping the folder tree) into a target folder. Works without git.

    python tools/snapshot_changes.py snapshot                 # remember the current state (default name: date-time)
    python tools/snapshot_changes.py changes                  # what changed since the latest snapshot
    python tools/snapshot_changes.py copy D:\\transfer\\nli     # copy new + changed files there (tree kept)
    python tools/snapshot_changes.py copy D:\\transfer\\nli --dry-run
    python tools/snapshot_changes.py list                     # the snapshots there are

The folder is the project root (the folder above tools/) unless --root is given. Snapshots are stored in
<root>/.snapshots/<name>.json (that folder is never part of a snapshot).

A file counts as changed when its content differs: size and modification time are compared first, and when
they differ the SHA-256 is compared too, so a file that was only touched (same content) is not copied.
Files larger than --hash-limit MB (default 200, e.g. model weights) get no checksum: for them a different size
or modification time counts as a change.

`copy` also writes into the target folder:
    _changes/CHANGES.txt      new / changed / deleted files, from which snapshot, when
    _changes/deleted.txt      files deleted since the snapshot (delete them on the other side by hand)
    _changes/delete_files.ps1 / delete_files.sh   scripts that delete exactly those files there
Add --update to take a new snapshot after copying, so the next `copy` starts from now.

Skipped by default (--no-default-excludes to include them): .git .snapshots .venv venv node_modules
__pycache__ .pytest_cache .mypy_cache .next .viewer_cache .download *.pyc *.pyo *.tmp *.part
Thumbs.db .DS_Store. Add more with --exclude NAME_OR_PATTERN (repeatable), e.g. --exclude models
--exclude "out_*" --exclude "viewer/frontend/out". A pattern without "/" matches any file or folder name;
one with "/" matches the path from the root.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

DEFAULT_EXCLUDES = [".git", ".snapshots", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
                    ".mypy_cache", ".next", ".viewer_cache", ".download", "*.pyc", "*.pyo", "*.tmp", "*.part",
                    "Thumbs.db", ".DS_Store"]
SNAP_DIR = ".snapshots"


# ------------------------------------------------------------------ scanning


def _excluded(rel: str, name: str, patterns: List[str]) -> bool:
    for p in patterns:
        p = p.replace("\\", "/").strip("/")
        if "/" in p:
            if fnmatch.fnmatch(rel, p) or rel.startswith(p + "/"):
                return True
        elif fnmatch.fnmatch(name, p):
            return True
    return False


def walk(root: Path, patterns: List[str]) -> Iterator[Tuple[str, Path]]:
    """(relative '/'-path, full path) of every file below root that is not excluded, sorted."""
    for dirpath, dirnames, filenames in os.walk(root):
        base = Path(dirpath)
        rel_dir = base.relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        keep = []
        for d in sorted(dirnames):
            rel = f"{rel_dir}/{d}" if rel_dir else d
            if not _excluded(rel, d, patterns) and not (base / d).is_symlink():
                keep.append(d)
        dirnames[:] = keep
        for f in sorted(filenames):
            rel = f"{rel_dir}/{f}" if rel_dir else f
            if not _excluded(rel, f, patterns):
                yield rel, base / f


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def scan(root: Path, patterns: List[str], hash_limit: int, old: Optional[Dict[str, dict]] = None,
         quiet: bool = False) -> Dict[str, dict]:
    """{rel: {size, mtime, sha256 or None}}. With old: reuse its checksum when size + mtime are unchanged."""
    out: Dict[str, dict] = {}
    t0 = last = time.time()
    for n, (rel, full) in enumerate(walk(root, patterns), 1):
        try:
            st = full.stat()
        except OSError:
            continue
        entry = {"size": st.st_size, "mtime": round(st.st_mtime, 3), "sha256": None}
        prev = (old or {}).get(rel)
        if prev and prev["size"] == entry["size"] and prev["mtime"] == entry["mtime"]:
            entry["sha256"] = prev.get("sha256")
        elif st.st_size <= hash_limit:
            try:
                entry["sha256"] = sha256(full)
            except OSError as exc:
                print(f"warning: cannot read {rel}: {exc}", file=sys.stderr)
                continue
        out[rel] = entry
        if not quiet and time.time() - last > 5:
            last = time.time()
            print(f"  ... {n} files scanned ({time.time() - t0:.0f}s)", file=sys.stderr)
    return out


# ------------------------------------------------------------------ snapshots


def snap_dir(root: Path) -> Path:
    return root / SNAP_DIR


def load_snapshot(root: Path, name: Optional[str]) -> Tuple[str, dict]:
    d = snap_dir(root)
    if name:
        p = Path(name) if name.endswith(".json") and Path(name).exists() else d / f"{name}.json"
    else:
        snaps = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime) if d.is_dir() else []
        if not snaps:
            raise SystemExit(f"error: no snapshot in {d}; run 'snapshot' first")
        p = snaps[-1]
    if not p.is_file():
        raise SystemExit(f"error: snapshot not found: {p}")
    with open(p, encoding="utf-8") as fh:
        return p.stem, json.load(fh)


def compare(old: Dict[str, dict], new: Dict[str, dict]) -> Tuple[List[str], List[str], List[str]]:
    """(new files, changed files, deleted files)."""
    added = sorted(set(new) - set(old))
    deleted = sorted(set(old) - set(new))
    changed = []
    for rel in sorted(set(new) & set(old)):
        a, b = old[rel], new[rel]
        if a["sha256"] and b["sha256"]:
            if a["sha256"] != b["sha256"]:
                changed.append(rel)
        elif a["size"] != b["size"] or a["mtime"] != b["mtime"]:
            changed.append(rel)
    return added, changed, deleted


def _patterns(args, snap: Optional[dict] = None) -> List[str]:
    if snap is not None and not args.exclude and not args.no_default_excludes:
        return snap.get("excludes", DEFAULT_EXCLUDES)  # same rules as when the snapshot was taken
    base = [] if args.no_default_excludes else list(DEFAULT_EXCLUDES)
    return base + [SNAP_DIR] + list(args.exclude)


def _mb(n: int) -> str:
    return f"{n / 1e6:.1f} MB"


# ------------------------------------------------------------------ commands


def cmd_snapshot(args, root: Path) -> int:
    patterns = _patterns(args)
    name = args.name or time.strftime("%Y%m%d-%H%M%S")
    print(f"scanning {root} ...", file=sys.stderr)
    files = scan(root, patterns, args.hash_limit * 1_000_000)
    d = snap_dir(root)
    d.mkdir(exist_ok=True)
    p = d / f"{name}.json"
    data = {"root": str(root), "created": time.strftime("%Y-%m-%d %H:%M:%S"), "excludes": patterns,
            "hash_limit_mb": args.hash_limit, "files": files}
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=0)
    os.replace(tmp, p)
    total = sum(f["size"] for f in files.values())
    print(f"snapshot '{name}': {len(files)} files, {_mb(total)} -> {p}")
    return 0


def _diff(args, root: Path):
    name, snap = load_snapshot(root, args.snapshot)
    patterns = _patterns(args, snap)
    now = scan(root, patterns, snap.get("hash_limit_mb", args.hash_limit) * 1_000_000, old=snap["files"],
               quiet=True)
    return name, snap, patterns, now, compare(snap["files"], now)


def _print(name: str, snap: dict, added, changed, deleted, now) -> None:
    print(f"since snapshot '{name}' ({snap['created']}): {len(added)} new, {len(changed)} changed, "
          f"{len(deleted)} deleted")
    for tag, rels in (("new     ", added), ("changed ", changed)):
        for rel in rels:
            print(f"  {tag} {rel}  ({_mb(now[rel]['size'])})")
    for rel in deleted:
        print(f"  deleted  {rel}")


def cmd_changes(args, root: Path) -> int:
    name, snap, _, now, (added, changed, deleted) = _diff(args, root)
    _print(name, snap, added, changed, deleted, now)
    return 0


def cmd_copy(args, root: Path) -> int:
    name, snap, patterns, now, (added, changed, deleted) = _diff(args, root)
    target = Path(args.target).resolve()
    if target == root or root in target.parents:
        raise SystemExit("error: the target folder must be outside the project folder")
    _print(name, snap, added, changed, deleted, now)
    todo = added + changed
    size = sum(now[r]["size"] for r in todo)
    if args.dry_run:
        print(f"\ndry run: would copy {len(todo)} files ({_mb(size)}) to {target}")
        return 0
    for rel in todo:
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, dst)
    info = target / "_changes"
    info.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"Changes in {root}", f"since snapshot '{name}' ({snap['created']}), copied {stamp}", "",
             f"new: {len(added)}"] + [f"  {r}" for r in added] + ["", f"changed: {len(changed)}"] + \
            [f"  {r}" for r in changed] + ["", f"deleted: {len(deleted)} (not copied; see delete_files.*)"] + \
            [f"  {r}" for r in deleted]
    (info / "CHANGES.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (info / "deleted.txt").write_text("".join(r + "\n" for r in deleted), encoding="utf-8")
    ps = ["# Run inside the copy of the project to delete the files that were deleted at the source.",
          "# Check the list first. Usage: powershell -ExecutionPolicy Bypass -File delete_files.ps1 <project folder>",
          "param([string]$Root = '.')"]
    ps += [f"Remove-Item -LiteralPath (Join-Path $Root '{r.replace(chr(39), chr(39) * 2)}') -ErrorAction SilentlyContinue"
           for r in deleted]
    # with BOM: Windows PowerShell 5.1 reads a script without BOM in the ANSI code page (breaks non-ASCII paths)
    (info / "delete_files.ps1").write_text("\n".join(ps) + "\n", encoding="utf-8-sig")
    sh = ["#!/usr/bin/env bash", "# Run inside the copy of the project to delete the files that were deleted at the source.",
          "# Check the list first. Usage: bash delete_files.sh <project folder>", 'ROOT="${1:-.}"']
    sh += [f"rm -f -- \"$ROOT/{r}\"" for r in deleted]
    with open(info / "delete_files.sh", "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(sh) + "\n")
    print(f"\ncopied {len(todo)} files ({_mb(size)}) to {target}; list in {info / 'CHANGES.txt'}")
    if args.update:
        args.name = None
        args.exclude = []  # keep the snapshot's own rules
        data = {"root": str(root), "created": time.strftime("%Y-%m-%d %H:%M:%S"), "excludes": patterns,
                "hash_limit_mb": snap.get("hash_limit_mb", args.hash_limit), "files": now}
        p = snap_dir(root) / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=0)
        print(f"new snapshot '{p.stem}' taken: the next copy starts from now")
    return 0


def cmd_list(args, root: Path) -> int:
    d = snap_dir(root)
    snaps = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime) if d.is_dir() else []
    if not snaps:
        print(f"no snapshots in {d}")
    for p in snaps:
        with open(p, encoding="utf-8") as fh:
            s = json.load(fh)
        print(f"  {p.stem:<24} {s['created']}  {len(s['files'])} files")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # file names the console cannot show must not crash the script
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    def common(parser, top: bool) -> None:
        """The shared options, accepted before and after the command name."""
        d = (lambda v: v) if top else (lambda v: argparse.SUPPRESS)  # sub-parsers must not reset the defaults
        parser.add_argument("--root", default=d(None), help="folder to watch (default: the folder above tools/)")
        parser.add_argument("--exclude", action="append", default=d([]),
                            help="skip this name / pattern (repeatable)")
        parser.add_argument("--no-default-excludes", action="store_true", default=d(False),
                            help="do not skip .git, .venv, node_modules ...")
        parser.add_argument("--hash-limit", type=int, default=d(200),
                            help="no checksum for files above this many MB (default 200)")

    ap = argparse.ArgumentParser(description="Remember a folder's files; later list / copy what changed.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    common(ap, True)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("snapshot", help="remember the current state")
    common(p, False)
    p.add_argument("--name", help="snapshot name (default: date-time)")
    p = sub.add_parser("changes", help="list new / changed / deleted files since a snapshot")
    common(p, False)
    p.add_argument("--snapshot", help="snapshot name (default: the latest)")
    p = sub.add_parser("copy", help="copy new + changed files into TARGET, keeping the folder tree")
    common(p, False)
    p.add_argument("target")
    p.add_argument("--snapshot", help="snapshot name (default: the latest)")
    p.add_argument("--dry-run", action="store_true", help="only list what would be copied")
    p.add_argument("--update", action="store_true", help="take a new snapshot after copying")
    p = sub.add_parser("list", help="show the snapshots")
    common(p, False)
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    if not root.is_dir():
        raise SystemExit(f"error: folder not found: {root}")
    return {"snapshot": cmd_snapshot, "changes": cmd_changes, "copy": cmd_copy, "list": cmd_list}[args.cmd](args, root)


if __name__ == "__main__":
    sys.exit(main())

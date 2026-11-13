"""
edit.py - change the text field of one corpus line, also inside a .zst / .gz file, safely.

Only for corpus folders on a local (or mapped / UNC) drive, and only when the dataset has "editable": true in
viewer_config.json. One save:

  1. reads the current line (from the viewer's decompressed cache) and checks it is still the line the
     user edited (sha1 of the line, else 409 conflict: someone else changed it),
  2. replaces only the text field (the id and every other field stay; the JSON style of the file is kept),
  3. writes the whole file again (compressed like the original) to a temporary file next to it,
  4. decompresses that temporary file again and checks it is exactly the new content,
  5. keeps a copy of the untouched original the first time a file is edited (edits_dir/<dataset>/originals/),
  6. swaps the temporary file in (os.replace: the old file stays complete until the new one is) and puts the
     checked decompressed copy into the viewer's line cache (no second decompression),
  7. logs old and new text (edits_dir/<dataset>/edits.jsonl), so every edit can be undone.

    from nli_viewer.edit import CorpusEditor
    ed = CorpusEditor(dataset, edits_dir="viewer/.viewer_edits")
    ed.edit_text("books/part-00/shard-00000.jsonl.zst", 12, "new text", base_sha1)
    ed.edit_texts(path, [{"line": 12, "text": "...", "sha1": s1}, {"line": 40, ...}])   # one rewrite
    ed.undo(edit_id)
"""
from __future__ import annotations

import array
import contextlib
import gzip
import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, Dict, Iterator, List, Optional, Tuple

from .lines import CHUNK, _scan_offsets, decompressed_stream
from .storage import clean_path

if TYPE_CHECKING:  # pragma: no cover
    from .results import Dataset

try:
    import zstandard
except ImportError:  # pragma: no cover
    zstandard = None

__all__ = ["CorpusEditor", "EditError", "EditConflict", "line_sha1", "EDITABLE_SUFFIXES"]

EDITABLE_SUFFIXES = (".zst", ".zstd", ".gz", ".jsonl", ".json", ".ndjson", ".txt")


class EditError(ValueError):
    """The edit is not possible (wrong file type, not JSON, no text field ...): HTTP 400."""


class EditConflict(Exception):
    """The line changed since it was loaded: HTTP 409."""


def line_sha1(raw: bytes) -> str:
    return hashlib.sha1(raw).hexdigest()


def _dump(obj: Any, style: Tuple[bool, Tuple[str, str]]) -> bytes:
    ensure_ascii, seps = style
    return json.dumps(obj, ensure_ascii=ensure_ascii, separators=seps).encode("utf-8")


_STYLES = [(False, (",", ":")), (True, (", ", ": ")), (False, (", ", ": ")), (True, (",", ":"))]


def _style_of(raw: bytes, obj: Any) -> Tuple[bool, Tuple[str, str]]:
    """The json.dumps settings that reproduce this line exactly (compact, non-ASCII kept when none does)."""
    for style in _STYLES:
        if _dump(obj, style) == raw:
            return style
    # orjson writes the same as compact json.dumps except for some floats; non-ASCII stays as is
    return _STYLES[0] if any(b >= 0x80 for b in raw) or b"\\u" not in raw else (True, (",", ":"))


class CorpusEditor:
    """Edits the corpus lines of one dataset. Thread-safe: edits of the same file run one after another."""

    def __init__(self, dataset: "Dataset", edits_dir: str, zstd_level: int = 3):
        self.ds = dataset
        self.dir = Path(edits_dir) / dataset.name
        self.zstd_level = int(zstd_level)
        self._locks: Dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self._log_lock = threading.Lock()

    # ---- checks ---------------------------------------------------------------------------------

    @property
    def log_path(self) -> Path:
        return self.dir / "edits.jsonl"

    def problem(self, path: Optional[str] = None, member: Optional[str] = None) -> Optional[str]:
        """Why this file (or, path None, this dataset) cannot be edited; None = it can."""
        if self.ds.corpus.local_path("") is None:
            return "the corpus is not on a local drive (FTP / SFTP / S3 corpora are read-only)"
        if path is None:
            return None
        if member:
            return "lines inside a .zip archive cannot be edited"
        low = path.lower()
        if low.endswith(".zip"):
            return "lines inside a .zip archive cannot be edited"
        if not low.endswith(EDITABLE_SUFFIXES):
            return f"unsupported file type: {path}"
        if low.endswith((".zst", ".zstd")) and zstandard is None:
            return "editing .zst files needs the 'zstandard' package"
        return None

    def _lock(self, path: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(path, threading.Lock())

    def _text_field(self) -> Tuple[str, str]:
        latest = max(self.ds.runs(), key=lambda r: r.get("finished", ""), default={})
        st = latest.get("settings") or {}
        return (self.ds._text_field or st.get("text_field") or "text",
                self.ds._id_field or st.get("id_field") or "id")

    def _fresh_line_file(self, path: str):
        """Line file of the corpus file as it is on disk now (drops an index that may be out of date)."""
        self.ds._line_files.pop((self.ds.corpus.uri, path, None), None)
        return self.ds._line_file(self.ds.corpus, path, None)

    # ---- reading --------------------------------------------------------------------------------

    def read_line(self, path: str, line: int) -> Dict[str, Any]:
        """The current line: raw text, sha1, parsed text and id (for the editor)."""
        path = clean_path(path)
        lf = self.ds._line_file(self.ds.corpus, path, None)
        raw = lf.line(int(line))
        text_field, id_field = self._text_field()
        out: Dict[str, Any] = {"path": path, "line": int(line), "raw": raw.decode("utf-8", "replace"),
                               "sha1": line_sha1(raw), "text_field": text_field, "text": None, "id": None}
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                t = obj.get(text_field)
                out["text"] = t if isinstance(t, str) else None
                out["id"] = obj.get(id_field)
        except ValueError as exc:
            out["error"] = f"not valid JSON: {exc}"
        return out

    # ---- editing --------------------------------------------------------------------------------

    def edit_text(self, path: str, line: int, text: str, base_sha1: Optional[str] = None,
                  client: Optional[str] = None, undo_of: Optional[str] = None) -> Dict[str, Any]:
        """Set the text field of line `line` (1-based) of corpus file `path`. Returns the new line + the log entry."""
        out = self.edit_texts(path, [{"line": line, "text": text, "sha1": base_sha1}], client=client, undo_of=undo_of)
        res = {"changed": bool(out["entries"]), **out["lines"][0]}
        if out["entries"]:
            res["entry"] = out["entries"][0]
        return res

    def edit_texts(self, path: str, changes: List[Dict[str, Any]], client: Optional[str] = None,
                   undo_of: Optional[str] = None) -> Dict[str, Any]:
        """
        Several lines of one file in ONE rewrite: changes = [{"line": n, "text": "...", "sha1": "..."}, ...].
        All or nothing: one stale sha1 or bad line and nothing is written. Returns the new lines + log entries.
        """
        path = clean_path(path)
        why = self.problem(path)
        if why:
            raise EditError(why)
        if not changes:
            raise EditError("no changes")
        lines = [int(c.get("line", 0)) for c in changes]
        if len(set(lines)) != len(lines):
            raise EditError("the same line is changed twice in one save")
        for c in changes:
            if not isinstance(c.get("text"), str):
                raise EditError(f"line {c.get('line')}: text must be a string")
        text_field, id_field = self._text_field()
        t0 = time.perf_counter()
        entries: List[Dict[str, Any]] = []
        with self._lock(path):
            target = Path(self.ds.corpus.local_path(path))
            if not target.is_file():
                raise FileNotFoundError(path)
            old_fp = self.ds.corpus.fingerprint(path)
            lf = self._fresh_line_file(path)
            total = len(lf)
            plan = []  # (start, cut_end, new_raw, log entry)
            for c in sorted(changes, key=lambda c: int(c["line"])):
                line, text = int(c["line"]), c["text"]
                if not 1 <= line <= total:
                    raise EditError(f"line {line} out of range 1..{total}")
                old_raw = lf.line(line)
                if c.get("sha1") and line_sha1(old_raw) != c["sha1"]:
                    raise EditConflict(f"line {line} of {path} changed since it was loaded: reload and edit again")
                try:
                    obj = json.loads(old_raw)
                except ValueError as exc:
                    raise EditError(f"line {line} is not valid JSON: {exc}") from None
                if not isinstance(obj, dict):
                    raise EditError(f"line {line} is not a JSON object")
                old_text = obj.get(text_field)
                if not isinstance(old_text, str):
                    raise EditError(f"line {line} has no text field '{text_field}'")
                if text == old_text:
                    continue  # unchanged: nothing to write or log
                style = _style_of(old_raw, obj)
                obj[text_field] = text
                new_raw = _dump(obj, style)
                start, _ = lf._span(line)
                entry = {"edit": uuid.uuid4().hex[:12], "file": path, "line": line, "id": obj.get(id_field),
                         "field": text_field, "old": old_text, "new": text, "old_sha1": line_sha1(old_raw),
                         "new_sha1": line_sha1(new_raw), "client": client}
                # start + len(old_raw): the line ending (\n or \r\n) after the line is kept
                plan.append((start, start + len(old_raw), new_raw, entry))
            if plan:
                self._rewrite(path, target, lf.data_path, [(a, b, raw) for a, b, raw, _ in plan], old_fp)
                batch = uuid.uuid4().hex[:12] if len(plan) > 1 else None
                now, ts, secs = time.strftime("%Y-%m-%d %H:%M:%S"), time.time(), round(time.perf_counter() - t0, 3)
                for _, _, _, e in plan:
                    e = {"edit": e.pop("edit"), "time": now, "ts": ts, **e, "seconds": secs}
                    if batch:
                        e["batch"] = batch
                    if undo_of:
                        e["undo_of"] = undo_of
                    entries.append(e)
                self._log(entries)
        return {"changed": len(entries), "entries": entries, "seconds": round(time.perf_counter() - t0, 3),
                "lines": [self.read_line(path, n) for n in sorted(lines)]}

    def undo(self, edit_id: str, client: Optional[str] = None) -> Dict[str, Any]:
        """Put back the text an edit replaced (only when the line still holds that edit's text)."""
        entry = next((e for e in self.history() if e["edit"] == edit_id), None)
        if entry is None:
            raise KeyError(f"unknown edit '{edit_id}'")
        cur = self.read_line(entry["file"], entry["line"])
        if cur.get("text") != entry["new"] or str(cur.get("id")) != str(entry.get("id")):
            raise EditConflict("the line was changed again after this edit: undo the later edits first")
        return self.edit_text(entry["file"], entry["line"], entry["old"], cur["sha1"], client=client, undo_of=edit_id)

    def _rewrite(self, path: str, target: Path, data_path: str, repl: List[Tuple[int, int, bytes]],
                 old_fp: str) -> None:
        """New file next to the old one, checked, swapped in; the viewer's cache is filled from the check."""
        tmp = target.with_name(f"{target.name}.edit-{os.getpid()}-{uuid.uuid4().hex[:6]}.tmp")
        stage = self.ds.cache.root / "_staging" / uuid.uuid4().hex[:12]
        try:
            digest = self._write(tmp, target.name, data_path, repl)
            seeded = self._verify(tmp, target.name, digest, stage)
            self._backup(path, target)
            try:
                os.replace(tmp, target)
            except PermissionError as exc:
                raise EditError(f"cannot replace {path}: the file is open in another program ({exc})") from None
            self._forget(path, old_fp)
            with contextlib.suppress(OSError):  # only a speed-up: without it the next read rebuilds the cache
                self._seed(path, stage, *seeded)
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink()
            shutil.rmtree(stage, ignore_errors=True)

    # ---- file writing ---------------------------------------------------------------------------

    def _open_out(self, fh: BinaryIO, name: str):
        low = name.lower()
        if low.endswith((".zst", ".zstd")):
            # threads=-1: all CPU cores (about 3x faster on large files, same .zst format)
            cctx = zstandard.ZstdCompressor(level=self.zstd_level, write_checksum=True, threads=-1)
            return cctx.stream_writer(fh, closefd=False)
        if low.endswith(".gz"):
            return gzip.GzipFile(filename="", mode="wb", fileobj=fh, compresslevel=6, mtime=0)
        return None

    def _write(self, tmp: Path, name: str, data_path: str, repl: List[Tuple[int, int, bytes]]) -> str:
        """Writes the content with the replacements to tmp (compressed like `name`); sha256 of the content."""
        h = hashlib.sha256()
        with open(tmp, "wb") as fh:
            writer = self._open_out(fh, name)
            sink = writer if writer is not None else fh
            for chunk in _content(data_path, repl):
                h.update(chunk)
                sink.write(chunk)
            if writer is not None:
                writer.close()
            fh.flush()
            os.fsync(fh.fileno())
        return h.hexdigest()

    @staticmethod
    def _verify(tmp: Path, name: str, digest: str, stage: Path) -> Tuple[array.array, int, bool]:
        """Decompress tmp again and compare with the content written. The decompressed bytes go to stage/data
        (the viewer's cache copy of the new file) and the line starts are collected on the way."""
        h = hashlib.sha256()
        compressed = name.lower().endswith((".zst", ".zstd", ".gz"))
        stage.mkdir(parents=True, exist_ok=True)

        def chunks(fh):
            while True:
                b = fh.read(CHUNK)
                if not b:
                    return
                h.update(b)
                yield b

        with open(tmp, "rb") as raw, decompressed_stream(raw, name) as fh:
            if compressed:
                with open(stage / "data", "wb") as sink:
                    starts, size = _scan_offsets(chunks(fh), sink)
            else:
                starts, size = _scan_offsets(chunks(fh), None)
        if h.hexdigest() != digest:
            raise EditError("the rewritten file did not read back correctly; the original was not changed")
        return starts, size, compressed

    def _seed(self, path: str, stage: Path, starts: array.array, size: int, compressed: bool) -> None:
        """Put the checked copy into the line cache under the new file's fingerprint (no second decompression)."""
        cache = self.ds.cache
        fp = self.ds.corpus.fingerprint(path)
        key = cache.key(self.ds.corpus.uri, path, "", fp)
        d = cache.dir(key)
        with cache.lock(key):
            if (d / "meta.json").exists():
                return
            d.mkdir(parents=True, exist_ok=True)
            if compressed:
                os.replace(stage / "data", d / "data")
            with open(d / "lines.idx.tmp", "wb") as fh:
                fh.write(starts.tobytes())
            os.replace(d / "lines.idx.tmp", d / "lines.idx")
            meta = {"storage": self.ds.corpus.display_uri, "path": path, "member": None, "size": size,
                    "lines": len(starts), "seconds": 0, "created": time.time(), "from_edit": True}
            (d / "meta.json").write_text(json.dumps(meta), "utf-8")
        cache.trim(keep=d.name)

    def _backup(self, path: str, target: Path) -> None:
        """Copy of the untouched original, made once per file (later edits keep the first copy)."""
        dst = self.dir / "originals" / Path(path)
        if dst.exists():
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".tmp")
        shutil.copy2(target, tmp)
        os.replace(tmp, dst)

    def _forget(self, path: str, old_fp: str) -> None:
        """Drop the viewer's cached copy of the old file (the next read builds the new one)."""
        self.ds._line_files.pop((self.ds.corpus.uri, path, None), None)
        cache = self.ds.cache
        key = cache.key(self.ds.corpus.uri, path, "", old_fp)
        with cache.lock(key):
            shutil.rmtree(cache.dir(key), ignore_errors=True)

    # ---- log ------------------------------------------------------------------------------------

    def _log(self, entries: List[Dict[str, Any]]) -> None:
        with self._log_lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as fh:
                for e in entries:
                    fh.write(json.dumps(e, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())

    def history(self, path: Optional[str] = None, line: Optional[int] = None) -> List[Dict[str, Any]]:
        """Logged edits (oldest first), optionally of one file / line."""
        if not self.log_path.exists():
            return []
        path = clean_path(path) if path else None
        out = []
        with self._log_lock, open(self.log_path, encoding="utf-8") as fh:
            for raw in fh:
                with contextlib.suppress(ValueError):
                    e = json.loads(raw)
                    if (path is None or e.get("file") == path) and (line is None or e.get("line") == int(line)):
                        out.append(e)
        return out

    def edited_lines(self, path: str) -> Dict[int, int]:
        """line -> number of edits, for one file."""
        out: Dict[int, int] = {}
        for e in self.history(path):
            out[e["line"]] = out.get(e["line"], 0) + 1
        return out

    def since(self, path: str, line: int, after_ts: Optional[float]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Edits of this line made after `after_ts` (e.g. the decisions file's time) and the text before them."""
        edits = [e for e in self.history(path, line) if after_ts is None or e.get("ts", 0) > after_ts]
        return edits, (edits[0]["old"] if edits else None)


def _content(data_path: str, repl: List[Tuple[int, int, bytes]]) -> Iterator[bytes]:
    """data with each [start, cut_end) span replaced by its new bytes (spans sorted, not overlapping)."""
    with open(data_path, "rb") as fh:
        pos = 0
        for start, cut_end, new_raw in repl:
            left = start - pos
            while left > 0:
                b = fh.read(min(CHUNK, left))
                if not b:
                    raise EditError("cached copy of the file is shorter than its index; reload and try again")
                left -= len(b)
                yield b
            yield new_raw
            fh.seek(cut_end)
            pos = cut_end
        while True:
            b = fh.read(CHUNK)
            if not b:
                return
            yield b

"""
edit.py - change the text field of one corpus line, also inside a .zst / .gz file, a member of a .zip / .rar
archive or a row of a .parquet table, safely.

For corpus folders on a local (or mapped / UNC) drive and on FTP / SFTP / S3 (MinIO) servers, only when the
dataset has "editable": true in viewer_config.json (and, on a server, the account may write). One save:

  1. reads the current line (from the viewer's decompressed cache) and checks it is still the line the
     user edited (sha1 of the line, else 409 conflict: someone else changed it),
  2. replaces only the text field (the id and every other field stay; the JSON style of the file is kept),
  3. writes the whole file again (compressed like the original) to a temporary file next to it (server:
     a local temporary file); an archive is rebuilt with the new member (the other members unchanged; .rar
     with WinRAR's Rar tool), a .parquet table with the new texts (schema, other columns, compression kept),
  4. reads that temporary file again and checks it gives exactly the new content,
  5. keeps a copy of the untouched original the first time a file is edited (edits_dir/<dataset>/originals/),
  6. swaps the temporary file in (os.replace: the old file stays complete until the new one is; server: checks
     that the file was not changed there meanwhile, uploads under a temporary name and renames it over the
     original, S3: one PUT) and puts the
     checked decompressed copy into the viewer's line cache (no second decompression),
  7. logs old and new text (edits_dir/<dataset>/edits.jsonl), so every edit can be undone.

    from nli_viewer.edit import CorpusEditor
    ed = CorpusEditor(dataset, edits_dir="viewer/.viewer_edits")
    ed.edit_text("books/part-00/shard-00000.jsonl.zst", 12, "new text", base_sha1)
    ed.edit_texts(path, [{"line": 12, "text": "...", "sha1": s1}, {"line": 40, ...}])   # one rewrite
    ed.edit_texts("data.rar", [...], member="dir/a.jsonl")                              # archive member
    ed.insert_line(path, after=12, record={"id": "x-1", "text": "...", "expect": "keep"})   # new line 13
    ed.delete_line(path, 13, sha1)
    ed.undo(edit_id)

Inserted and deleted lines move the lines after them; the log keeps every insert / delete, so a line number from
before (e.g. in the filter's decisions) is mapped to the line's current number (map_forward / map_back).
"""
from __future__ import annotations

import array
import bisect
import contextlib
import gzip
import hashlib
import json
import os
import posixpath
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, Callable, Dict, Iterator, List, Optional, Tuple

from .lines import CHUNK, _scan_offsets, decompressed_stream, open_member
from .storage import StorageError, clean_path

import nli_formats  # noqa: E402  (project root, put on sys.path by .storage)

if TYPE_CHECKING:  # pragma: no cover
    from .results import Dataset

try:
    import zstandard
except ImportError:  # pragma: no cover
    zstandard = None

__all__ = ["CorpusEditor", "EditError", "EditConflict", "line_sha1", "EDITABLE_SUFFIXES"]

EDITABLE_SUFFIXES = (".zst", ".zstd", ".gz", ".jsonl", ".json", ".ndjson", ".txt", ".zip", ".rar", ".parquet",
                     ".arrow", ".feather")


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
        if not getattr(self.ds.corpus, "writable", False):
            return f"this kind of corpus storage cannot be written ({type(self.ds.corpus).__name__})"
        if path is None:
            return None
        low = path.lower()
        if not low.endswith(EDITABLE_SUFFIXES):
            return f"unsupported file type: {path}"
        if member and not nli_formats.is_archive(path):
            return f"{path} is not an archive"
        if low.endswith(".rar") and (nli_formats.rar_tool("unrar") is None or nli_formats.rar_tool("rar") is None):
            return "editing .rar files needs WinRAR's Rar tool (Rar.exe; Linux: rar) on this PC"
        if nli_formats.is_table(low) and not nli_formats.parquet_available():
            return f"editing {Path(path).suffix} files needs the 'pyarrow' package"
        inner = (member or "") if nli_formats.is_archive(path) else path
        if inner.lower().endswith((".zst", ".zstd")) and zstandard is None:
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

    def _fresh_line_file(self, path: str, member: Optional[str] = None):
        """Line file of the corpus file as it is on disk now (drops an index that may be out of date)."""
        self.ds._line_files.pop((self.ds.corpus.uri, path, member), None)
        return self.ds._line_file(self.ds.corpus, path, member)

    # ---- reading --------------------------------------------------------------------------------

    def read_line(self, path: str, line: int, member: Optional[str] = None) -> Dict[str, Any]:
        """The current line: raw text, sha1, parsed text and id (for the editor)."""
        path = clean_path(path)
        lf = self.ds._line_file(self.ds.corpus, path, member)
        raw = lf.line(int(line))
        text_field, id_field = self._text_field()
        out: Dict[str, Any] = {"path": path, "member": member, "line": int(line), "raw": raw.decode("utf-8", "replace"),
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
                  client: Optional[str] = None, undo_of: Optional[str] = None,
                  member: Optional[str] = None) -> Dict[str, Any]:
        """Set the text field of line `line` (1-based) of corpus file `path`. Returns the new line + the log entry."""
        out = self.edit_texts(path, [{"line": line, "text": text, "sha1": base_sha1}], client=client, undo_of=undo_of,
                              member=member)
        res = {"changed": bool(out["entries"]), **out["lines"][0]}
        if out["entries"]:
            res["entry"] = out["entries"][0]
        return res

    def edit_texts(self, path: str, changes: List[Dict[str, Any]], client: Optional[str] = None,
                   undo_of: Optional[str] = None, member: Optional[str] = None) -> Dict[str, Any]:
        """
        Several lines of one file (one member of a .zip / .rar) in ONE rewrite:
        changes = [{"line": n, "text": "...", "sha1": "..."}, ...].
        All or nothing: one stale sha1 or bad line and nothing is written. Returns the new lines + log entries.
        """
        path = clean_path(path)
        member = member or None
        if nli_formats.is_archive(path) and not member:
            raise EditError(f"{path} is an archive: say which member to edit")
        why = self.problem(path, member)
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
            local = self.ds.corpus.local_path(path)
            target = Path(local) if local else None  # None: on a server (FTP / SFTP / S3)
            if target is not None and not target.is_file():
                raise FileNotFoundError(path)
            if target is None and self.ds.corpus.stat(path).is_dir:
                raise FileNotFoundError(path)
            old_fp = self.ds.corpus.fingerprint(path)
            lf = self._fresh_line_file(path, member)
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
                entry = {"edit": uuid.uuid4().hex[:12], "file": path, **({"member": member} if member else {}),
                         "line": line, "id": obj.get(id_field),
                         "field": text_field, "old": old_text, "new": text, "old_sha1": line_sha1(old_raw),
                         "new_sha1": line_sha1(new_raw), "client": client}
                # start + len(old_raw): the line ending (\n or \r\n) after the line is kept
                plan.append((start, start + len(old_raw), new_raw, entry))
            if plan:
                texts = {e["line"] - 1: e["new"] for _, _, _, e in plan}
                self._rewrite(path, target, lf.data_path, [(a, b, raw) for a, b, raw, _ in plan], old_fp, member,
                              lambda src, dst: nli_formats.table_replace_texts(src, dst, text_field, texts,
                                                                              kind=Path(path).suffix))
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
                "lines": [self.read_line(path, n, member) for n in sorted(lines)]}

    def undo(self, edit_id: str, client: Optional[str] = None) -> Dict[str, Any]:
        """Undo one logged change: put the old text back, remove an inserted line, put a deleted line back.
        Only when the line still looks like that change left it (else: undo the later changes first)."""
        log = self._read_log()
        k = next((i for i, e in enumerate(log) if e["edit"] == edit_id), None)
        if k is None:
            raise KeyError(f"unknown edit '{edit_id}'")
        entry, member, kind = log[k], log[k].get("member"), log[k].get("kind", "text")
        later = _ops(log[k + 1:], entry["file"], member)
        if kind == "delete":
            if later:
                raise EditConflict("lines were inserted or deleted in this file after this delete: undo those first")
            return self._insert_raw(entry["file"], entry["line"] - 1, entry["raw"].encode("utf-8"), member,
                                    client=client, undo_of=edit_id, entry_extra={"id": entry.get("id"),
                                                                                 "new": entry.get("old", "")})
        line = map_forward(entry["line"], later)
        if line is None:
            raise EditConflict("this line was deleted later: undo that delete first")
        cur = self.read_line(entry["file"], line, member)
        if kind == "insert":
            if cur["sha1"] != entry.get("new_sha1"):
                raise EditConflict("the inserted line was changed later: undo those changes first")
            return self.delete_line(entry["file"], line, cur["sha1"], member, client=client, undo_of=edit_id)
        if cur.get("text") != entry["new"] or str(cur.get("id")) != str(entry.get("id")):
            raise EditConflict("the line was changed again after this edit: undo the later edits first")
        return self.edit_text(entry["file"], line, entry["old"], cur["sha1"], client=client, undo_of=edit_id,
                              member=member)

    # ---- inserting and deleting lines -----------------------------------------------------------

    def _open_for_change(self, path: str, member: Optional[str]):
        path = clean_path(path)
        member = member or None
        if nli_formats.is_archive(path) and not member:
            raise EditError(f"{path} is an archive: say which member to edit")
        why = self.problem(path, member)
        if why:
            raise EditError(why)
        return path, member

    def _target(self, path: str) -> Optional[Path]:
        local = self.ds.corpus.local_path(path)
        target = Path(local) if local else None
        if target is not None and not target.is_file():
            raise FileNotFoundError(path)
        if target is None and self.ds.corpus.stat(path).is_dir:
            raise FileNotFoundError(path)
        return target

    @staticmethod
    def _eol(lf, n: int) -> bytes:
        """Line ending after line n (b"" when the file ends without one)."""
        start, end = lf._span(n)
        with open(lf.data_path, "rb") as fh:
            fh.seek(start)
            tail = fh.read(end - start)[-2:]
        return b"\r\n" if tail == b"\r\n" else b"\n" if tail.endswith(b"\n") else b""

    def _id_exists(self, lf, value: Any, id_field: str) -> Optional[int]:
        """Line number of a line whose id is `value` (searches the bytes, parses only candidate lines)."""
        needles = {json.dumps(value, ensure_ascii=False).encode("utf-8"), json.dumps(value).encode("utf-8")}
        overlap = max(len(n) for n in needles) - 1
        starts = lf._starts
        checked = set()
        with open(lf.data_path, "rb") as fh:  # the decompressed cache copy, in blocks (big files: no RAM spike)
            base, prev = 0, b""
            while True:
                block = fh.read(CHUNK)
                if not block:
                    return None
                data = prev + block
                offset = base - len(prev)
                for needle in needles:
                    i = data.find(needle)
                    while i != -1:
                        n = bisect.bisect_right(starts, offset + i)
                        if n not in checked:
                            checked.add(n)
                            with contextlib.suppress(ValueError, IndexError):
                                obj = json.loads(lf.line(n))
                                if isinstance(obj, dict) and obj.get(id_field) == value:
                                    return n
                        i = data.find(needle, i + 1)
                base += len(block)
                prev = data[-overlap:] if overlap > 0 else b""

    def insert_line(self, path: str, after: int, record: Dict[str, Any], sha1: Optional[str] = None,
                    member: Optional[str] = None, client: Optional[str] = None) -> Dict[str, Any]:
        """
        Insert a new line after line `after` (0 = at the top; the number of lines = at the end). record must have
        the id field (not used yet in this file) and the text field. sha1: of the line the new one goes next to
        (line `after`, or line 1 when after = 0), to notice a file changed meanwhile.
        """
        path, member = self._open_for_change(path, member)
        text_field, id_field = self._text_field()
        if not isinstance(record, dict):
            raise EditError("the new line must be a JSON object")
        rid = record.get(id_field)
        if rid is None or (isinstance(rid, str) and not rid.strip()):
            raise EditError(f"the new line needs an '{id_field}'")
        if not isinstance(record.get(text_field), str):
            raise EditError(f"the new line needs a text field '{text_field}' (a string)")
        with self._lock(path):
            self._target(path)
            lf = self._fresh_line_file(path, member)
            total = len(lf)
            if not 0 <= int(after) <= total:
                raise EditError(f"insert position {after} out of range 0..{total}")
            after = int(after)
            near = after or (1 if total else 0)
            if near and sha1 and line_sha1(lf.line(near)) != sha1:
                raise EditConflict(f"line {near} of {path} changed since it was loaded: reload and insert again")
            dup = self._id_exists(lf, rid, id_field) if total else None
            if dup is not None:
                raise EditError(f"'{id_field}' {rid!r} is already used by line {dup}")
            style = (False, (",", ":"))
            if near:
                with contextlib.suppress(ValueError):
                    style = _style_of(lf.line(near), json.loads(lf.line(near)))
            if nli_formats.is_table(path):
                if not total:
                    raise EditError("cannot insert into an empty table (its columns are unknown here)")
                columns = list(json.loads(lf.line(1)).keys())
                extra = [k for k in record if k not in columns]
                if extra:
                    raise EditError(f"the table has no column {', '.join(map(repr, extra))}")
                record = {c: record.get(c) for c in columns}
                raw = nli_formats.parquet_dump(record)
            else:
                raw = _dump(record, style)
        return self._insert_raw(path, after, raw, member, client=client, record=record)

    def _insert_raw(self, path: str, after: int, raw: bytes, member: Optional[str], client: Optional[str] = None,
                    undo_of: Optional[str] = None, record: Optional[Dict[str, Any]] = None,
                    entry_extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        path, member = self._open_for_change(path, member)
        text_field, id_field = self._text_field()
        t0 = time.perf_counter()
        obj = record if record is not None else json.loads(raw)
        with self._lock(path):
            target = self._target(path)
            old_fp = self.ds.corpus.fingerprint(path)
            lf = self._fresh_line_file(path, member)
            total = len(lf)
            if not 0 <= after <= total:
                raise EditError(f"insert position {after} out of range 0..{total}")
            # the file's line ending: from the first line (the last one may have none)
            eol = (self._eol(lf, 1) if total else b"") or b"\n"
            if after < total:
                pos, _ = lf._span(after + 1)
                repl = (pos, pos, raw + eol)
            elif total == 0:
                repl = (0, 0, raw + b"\n")
            else:
                end = lf._size
                last_eol = self._eol(lf, total)
                repl = (end, end, raw + last_eol) if last_eol else (end, end, eol + raw)
            self._rewrite(path, target, lf.data_path, [repl], old_fp, member,
                          lambda src, dst: nli_formats.table_insert_row(src, dst, after, obj, kind=Path(path).suffix))
            entry = {"edit": uuid.uuid4().hex[:12], "time": time.strftime("%Y-%m-%d %H:%M:%S"), "ts": time.time(),
                     "kind": "insert", "file": path, **({"member": member} if member else {}), "line": after + 1,
                     "id": obj.get(id_field) if isinstance(obj, dict) else None, "field": text_field, "old": "",
                     "new": obj.get(text_field, "") if isinstance(obj, dict) else "",
                     "raw": raw.decode("utf-8"), "new_sha1": line_sha1(raw), "client": client,
                     "seconds": round(time.perf_counter() - t0, 3)}
            if entry_extra:
                entry.update({k: v for k, v in entry_extra.items() if v is not None})
            if undo_of:
                entry["undo_of"] = undo_of
            self._log([entry])
        return {"changed": 1, "entry": entry, **self.read_line(path, after + 1, member)}

    def delete_line(self, path: str, line: int, sha1: Optional[str] = None, member: Optional[str] = None,
                    client: Optional[str] = None, undo_of: Optional[str] = None) -> Dict[str, Any]:
        """Remove line `line`; the lines after it move up by one. The removed line is kept in the log (undo)."""
        path, member = self._open_for_change(path, member)
        text_field, id_field = self._text_field()
        t0 = time.perf_counter()
        line = int(line)
        with self._lock(path):
            target = self._target(path)
            old_fp = self.ds.corpus.fingerprint(path)
            lf = self._fresh_line_file(path, member)
            total = len(lf)
            if not 1 <= line <= total:
                raise EditError(f"line {line} out of range 1..{total}")
            raw = lf.line(line)
            if sha1 and line_sha1(raw) != sha1:
                raise EditConflict(f"line {line} of {path} changed since it was loaded: reload and delete again")
            start, end = lf._span(line)
            if line < total or self._eol(lf, line) or line == 1:
                repl = (start, end, b"")
            else:  # last line without a line ending: remove the ending of the line before instead
                pstart, _ = lf._span(line - 1)
                repl = (pstart + len(lf.line(line - 1)), end, b"")
            self._rewrite(path, target, lf.data_path, [repl], old_fp, member,
                          lambda src, dst: nli_formats.table_delete_row(src, dst, line - 1, kind=Path(path).suffix))
            obj: Dict[str, Any] = {}
            with contextlib.suppress(ValueError):
                loaded = json.loads(raw)
                obj = loaded if isinstance(loaded, dict) else {}
            entry = {"edit": uuid.uuid4().hex[:12], "time": time.strftime("%Y-%m-%d %H:%M:%S"), "ts": time.time(),
                     "kind": "delete", "file": path, **({"member": member} if member else {}), "line": line,
                     "id": obj.get(id_field), "field": text_field, "old": obj.get(text_field, "") or "", "new": "",
                     "raw": raw.decode("utf-8", "replace"), "old_sha1": line_sha1(raw), "client": client,
                     "seconds": round(time.perf_counter() - t0, 3)}
            if undo_of:
                entry["undo_of"] = undo_of
            self._log([entry])
        return {"changed": 1, "entry": entry, "deleted": line, "total_lines": total - 1}

    def _rewrite(self, path: str, target: Optional[Path], data_path: str, repl: List[Tuple[int, int, bytes]],
                 old_fp: str, member: Optional[str] = None,
                 table_op: Optional[Callable[[str, str], None]] = None) -> None:
        """New file next to the old one (server: a local one), checked, swapped in / uploaded; the viewer's cache
        is filled from the check. Archives get the new member, tables the new texts; the rest stays."""
        name = posixpath.basename(path)
        stage = self.ds.cache.root / "_staging" / uuid.uuid4().hex[:12]
        stage.mkdir(parents=True, exist_ok=True)
        tmp = (target.with_name(f"{target.name}.edit-{os.getpid()}-{uuid.uuid4().hex[:6]}.tmp") if target is not None
               else stage / f"upload-{name}")
        container = nli_formats.is_archive(path) or nli_formats.is_table(path)
        try:
            original: Optional[str] = None
            if not container:
                digest = self._write(tmp, name, data_path, repl)
                # a server file is read through the cache, so the cache needs the decompressed copy also when plain
                seeded = self._verify(tmp, name, digest, stage, keep_data=target is None)
            else:
                original = str(target) if target is not None else self._download(path, stage)
                if nli_formats.is_table(path):
                    digest = _digest(_content(data_path, repl))
                    try:
                        table_op(original, str(tmp))  # replace texts / insert a row / delete a row
                    except ValueError as exc:
                        raise EditError(str(exc)) from None
                else:
                    content = stage / ("member-" + posixpath.basename(member))
                    digest = self._write(content, member, data_path, repl)  # compressed like the member
                    if path.lower().endswith(".rar"):
                        try:
                            nli_formats.rar_replace_member(original, member, str(content), str(tmp))
                        except RuntimeError as exc:
                            raise EditError(str(exc)) from None
                    else:
                        _zip_replace(original, member, str(content), str(tmp))
                seeded = self._check(lambda: _container_stream(str(tmp), path, member), digest, stage)
            self._backup(path, target, downloaded=original if target is None else None)
            if target is not None:
                try:
                    os.replace(tmp, target)
                except PermissionError as exc:
                    raise EditError(f"cannot replace {path}: the file is open in another program ({exc})") from None
            else:
                if self.ds.corpus.fingerprint(path) != old_fp:
                    raise EditConflict(f"{path} was changed on the server since the viewer read it: reload and "
                                       "edit again")
                try:
                    self.ds.corpus.replace_file(path, str(tmp))
                except StorageError as exc:
                    raise EditError(f"upload failed, the file on the server was not changed: {exc}") from None
            self._forget(path, old_fp, member)
            with contextlib.suppress(OSError, StorageError):  # only a speed-up: else the next read rebuilds it
                self._seed(path, stage, *seeded, member=member)
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink()
            shutil.rmtree(stage, ignore_errors=True)

    def _download(self, path: str, stage: Path) -> str:
        """Server file -> local copy (archives and tables are rebuilt from a real file)."""
        dst = stage / ("original-" + posixpath.basename(path))
        with self.ds.corpus.open(path) as src, open(dst, "wb") as out:
            shutil.copyfileobj(src, out, CHUNK)
        return str(dst)

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
    def _verify(tmp: Path, name: str, digest: str, stage: Path, keep_data: bool = False) -> Tuple[array.array, int, bool]:
        """Decompress tmp again and compare with the content written. The decompressed bytes go to stage/data
        (the viewer's cache copy of the new file) and the line starts are collected on the way."""
        h = hashlib.sha256()
        compressed = keep_data or name.lower().endswith((".zst", ".zstd", ".gz"))  # True: cache needs the data
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

    @staticmethod
    def _check(open_stream, digest: str, stage: Path) -> Tuple[array.array, int, bool]:
        """Like _verify for archives / tables: open_stream() gives the new member / table as JSONL; its bytes must
        hash to digest. They become the cache copy (stage/data)."""
        h = hashlib.sha256()

        def chunks(fh):
            while True:
                b = fh.read(CHUNK)
                if not b:
                    return
                h.update(b)
                yield b

        stage.mkdir(parents=True, exist_ok=True)
        with open_stream() as fh, open(stage / "data", "wb") as sink:
            starts, size = _scan_offsets(chunks(fh), sink)
        if h.hexdigest() != digest:
            raise EditError("the rewritten file did not read back correctly; the original was not changed")
        return starts, size, True

    def _seed(self, path: str, stage: Path, starts: array.array, size: int, compressed: bool,
              member: Optional[str] = None) -> None:
        """Put the checked copy into the line cache under the new file's fingerprint (no second decompression)."""
        cache = self.ds.cache
        fp = self.ds.corpus.fingerprint(path)
        key = cache.key(self.ds.corpus.uri, path, member or "", fp)
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
            meta = {"storage": self.ds.corpus.display_uri, "path": path, "member": member, "size": size,
                    "lines": len(starts), "seconds": 0, "created": time.time(), "from_edit": True}
            (d / "meta.json").write_text(json.dumps(meta), "utf-8")
        cache.trim(keep=d.name)

    def _backup(self, path: str, target: Optional[Path], downloaded: Optional[str] = None) -> None:
        """Copy of the untouched original, made once per file (later edits keep the first copy). A file on a
        server is downloaded into the backup folder on this PC."""
        dst = self.dir / "originals" / Path(path)
        if dst.exists():
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".tmp")
        if target is not None:
            shutil.copy2(target, tmp)
        elif downloaded is not None:
            shutil.copyfile(downloaded, tmp)
        else:
            with self.ds.corpus.open(path) as src, open(tmp, "wb") as out:
                shutil.copyfileobj(src, out, CHUNK)
        os.replace(tmp, dst)

    def _forget(self, path: str, old_fp: str, member: Optional[str] = None) -> None:
        """Drop the viewer's cached copy of the old file (the next read builds the new one)."""
        for k in [k for k in self.ds._line_files if k[0] == self.ds.corpus.uri and k[1] == path]:
            self.ds._line_files.pop(k, None)  # every member of an archive: the file has a new version
        cache = self.ds.cache
        key = cache.key(self.ds.corpus.uri, path, member or "", old_fp)
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

    def _read_log(self) -> List[Dict[str, Any]]:
        if not self.log_path.exists():
            return []
        out = []
        with self._log_lock, open(self.log_path, encoding="utf-8") as fh:
            for raw in fh:
                with contextlib.suppress(ValueError):
                    out.append(json.loads(raw))
        return out

    def history(self, path: Optional[str] = None, line: Optional[int] = None,
                member: Optional[str] = None) -> List[Dict[str, Any]]:
        """Logged changes (oldest first), optionally of one file (archive member) / line. Each entry gets
        "current_line": where its line is now (inserts / deletes after it move it; None = deleted since)."""
        log = self._read_log()
        path = clean_path(path) if path else None
        out = []
        for k, e in enumerate(log):
            if path is not None and not (e.get("file") == path and e.get("member") == (member or None)):
                continue
            if e.get("kind") == "delete":
                cur = None
            else:
                cur = map_forward(e["line"], _ops(log[k + 1:], e["file"], e.get("member")))
            if line is not None and cur != int(line):
                continue
            out.append({**e, "current_line": cur})
        return out

    def structural_ops(self, path: str, member: Optional[str] = None,
                       after_ts: Optional[float] = None) -> List[Tuple[str, int]]:
        """Inserts / deletes of a file in log order, made after after_ts: [("insert" | "delete", line), ...]."""
        log = [e for e in self._read_log() if after_ts is None or e.get("ts", 0) > after_ts]
        return _ops(log, clean_path(path), member)

    def edited_lines(self, path: str, member: Optional[str] = None) -> Dict[int, int]:
        """line -> number of edits, for one file (archive member)."""
        out: Dict[int, int] = {}
        for e in self.history(path, member=member):
            n = e.get("current_line")
            if n is not None:
                out[n] = out.get(n, 0) + 1
        return out

    def since(self, path: str, line: int, after_ts: Optional[float],
              member: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Edits of this line made after `after_ts` (e.g. the decisions file's time) and the text before them."""
        edits = [e for e in self.history(path, line, member) if after_ts is None or e.get("ts", 0) > after_ts]
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


def _digest(chunks: Iterator[bytes]) -> str:
    h = hashlib.sha256()
    for b in chunks:
        h.update(b)
    return h.hexdigest()


@contextlib.contextmanager
def _container_stream(local: str, path: str, member: Optional[str]) -> Iterator[BinaryIO]:
    """The JSONL content of a (new) archive member or table."""
    if nli_formats.is_table(path):
        import io
        lines = (nli_formats.parquet_lines(local) if path.lower().endswith(".parquet")
                 else nli_formats.arrow_lines(local))
        with contextlib.closing(io.BufferedReader(nli_formats.IterStream(lines), buffer_size=1 << 20)) as fh:
            yield fh
    else:
        with open_member(local, member, kind=Path(path).suffix) as raw, decompressed_stream(raw, member) as fh:
            yield fh


def _zip_replace(src: str, member: str, content: str, dst: str) -> None:
    """dst = the .zip src with `member` replaced by the file content (same compression method; other members
    copied as they are, in the same order)."""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", allowZip64=True) as zout:
        zout.comment = zin.comment
        for info in zin.infolist():
            if info.filename == member:
                new = zipfile.ZipInfo(member, date_time=time.localtime()[:6])
                new.compress_type, new.external_attr = info.compress_type, info.external_attr
                with open(content, "rb") as fh, zout.open(new, "w", force_zip64=True) as out:
                    shutil.copyfileobj(fh, out, CHUNK)
            elif info.is_dir():
                zout.writestr(info, b"")
            else:
                with zin.open(info) as fh, zout.open(info, "w", force_zip64=True) as out:
                    shutil.copyfileobj(fh, out, CHUNK)


# ---- line numbers across inserts / deletes ----------------------------------------------------------

def _ops(log: List[Dict[str, Any]], path: str, member: Optional[str]) -> List[Tuple[str, int]]:
    return [(e["kind"], int(e["line"])) for e in log
            if e.get("kind") in ("insert", "delete") and e.get("file") == path and e.get("member") == (member or None)]


def map_forward(line: int, ops: List[Tuple[str, int]]) -> Optional[int]:
    """Line number before the ops -> after them (None: the line was deleted)."""
    for kind, at in ops:
        if kind == "insert":
            if line >= at:
                line += 1
        else:
            if line == at:
                return None
            if line > at:
                line -= 1
    return line


def map_back(line: int, ops: List[Tuple[str, int]]) -> Optional[int]:
    """Line number after the ops -> before them (None: the line was inserted by them)."""
    for kind, at in reversed(ops):
        if kind == "insert":
            if line == at:
                return None
            if line > at:
                line -= 1
        else:
            if line >= at:
                line += 1
    return line

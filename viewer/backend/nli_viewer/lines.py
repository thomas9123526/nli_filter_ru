"""
lines.py - jump to line N of a JSONL file, also when it is .gz / .zst / inside a .zip or .rar / a .parquet table
(row n = line n) / on FTP, SFTP or S3.

Compressed streams have no random access, so the first request for a file decompresses it once into a
disk cache together with an index of line start offsets; later requests seek straight to the line.
Plain local files are not copied: only their offset index is cached.

    from nli_viewer.lines import LineCache, LineFile
    cache = LineCache("./.viewer_cache", max_bytes=20e9)
    lf = LineFile(storage, "books/part-00/shard-00000.jsonl.zst", cache=cache)
    len(lf)            # number of lines
    lf.line(12)        # bytes of line 12 (1-based, line ending removed)
    lf.lines(10, 5)    # lines 10..14

Line numbers follow Python's `for n, line in enumerate(file, 1)`, the numbering nli_filter.py writes.
"""
from __future__ import annotations

import array
import contextlib
import gzip
import hashlib
import io
import json
import os
import shutil
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import BinaryIO, Dict, Iterator, List, Optional, Tuple

from .storage import Storage

import nli_formats  # noqa: E402  (project root, put on sys.path by .storage)

try:
    import zstandard
except ImportError:  # pragma: no cover
    zstandard = None

__all__ = ["LineCache", "LineFile", "decompressed_stream", "is_compressed", "archive_members", "CHUNK"]

CHUNK = 8 << 20
_COMPRESSED = (".zst", ".zstd", ".gz")


def is_compressed(name: str) -> bool:
    return name.lower().endswith(_COMPRESSED)


def _usable_member(name: str) -> bool:
    """Archive members the viewer reads: (compressed) JSONL, not archives or tables inside archives."""
    return name.lower().endswith(nli_formats.INPUT_SUFFIXES) and not nli_formats.needs_local_file(name)


def archive_members(local_path: str, kind: Optional[str] = None) -> List[str]:
    """Readable members of a local .zip / .rar file, in archive order ('/' separators). kind: '.zip' / '.rar' when
    the file name does not say it (e.g. a temporary file)."""
    if (kind or local_path).lower().endswith(".rar"):
        return [n for n in nli_formats.rar_members(local_path) if _usable_member(n)]
    with zipfile.ZipFile(local_path) as zf:
        return [i.filename for i in zf.infolist() if not i.is_dir() and _usable_member(i.filename)]


@contextlib.contextmanager
def open_member(local_path: str, member: str, kind: Optional[str] = None) -> Iterator[BinaryIO]:
    """Raw (still compressed if the member is .zst / .gz) bytes of one archive member."""
    if (kind or local_path).lower().endswith(".rar"):
        with nli_formats.open_rar_member(local_path, member) as fh:
            yield fh
    else:
        with zipfile.ZipFile(local_path) as zf:
            try:
                info = zf.getinfo(member)
            except KeyError:
                raise FileNotFoundError(f"{local_path}!{member}") from None
            with zf.open(info) as fh:
                yield fh


@contextlib.contextmanager
def decompressed_stream(raw: BinaryIO, name: str) -> Iterator[BinaryIO]:
    """Wrap a binary stream with the decompressor its name asks for (.zst / .gz / none)."""
    low = name.lower()
    if low.endswith((".zst", ".zstd")):
        if zstandard is None:
            raise RuntimeError("reading .zst needs the 'zstandard' package (pip install zstandard)")
        reader = zstandard.ZstdDecompressor(max_window_size=2 ** 31).stream_reader(raw, read_across_frames=True)
        try:
            yield reader
        finally:
            reader.close()
    elif low.endswith(".gz"):
        with gzip.GzipFile(fileobj=raw, mode="rb") as fh:
            yield fh
    else:
        yield raw


class LineCache:
    """Folder holding decompressed copies and line indexes, trimmed to max_bytes (least recently used first)."""

    def __init__(self, root: str, max_bytes: float = 20e9):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_bytes = int(max_bytes)
        self._locks: Dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def key(self, *parts: str) -> str:
        return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]

    def dir(self, key: str) -> Path:
        d = self.root / key[:2] / key
        return d

    def lock(self, key: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    def touch(self, key: str) -> None:
        d = self.dir(key)
        with contextlib.suppress(OSError):
            os.utime(d, None)

    def usage(self) -> int:
        return sum(f.stat().st_size for f in self.root.rglob("*") if f.is_file())

    def trim(self, keep: Optional[str] = None) -> None:
        """Remove least recently used entries until the cache fits max_bytes."""
        entries = []
        for d in self.root.glob("*/*"):
            if d.is_dir():
                size = sum(f.stat().st_size for f in d.iterdir() if f.is_file())
                entries.append((d.stat().st_mtime, size, d))
        total = sum(s for _, s, _ in entries)
        for _, size, d in sorted(entries):
            if total <= self.max_bytes:
                break
            if keep and d.name == keep:
                continue
            if self.lock(d.name).acquire(blocking=False):
                try:
                    shutil.rmtree(d, ignore_errors=True)
                    total -= size
                finally:
                    self.lock(d.name).release()

    def clear(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)


def _scan_offsets(chunks: Iterator[bytes], sink: Optional[BinaryIO]) -> Tuple[array.array, int]:
    """Line start offsets (+ total size) of a byte stream; optionally copies the bytes to sink."""
    starts = array.array("Q", [0])
    pos = 0
    for chunk in chunks:
        if sink is not None:
            sink.write(chunk)
        find = chunk.find
        i = find(b"\n")
        while i != -1:
            starts.append(pos + i + 1)
            i = find(b"\n", i + 1)
        pos += len(chunk)
    if starts[-1] == pos:  # file ends with a newline (or is empty): no extra line
        starts.pop()
    return starts, pos


def _read_chunks(fh: BinaryIO) -> Iterator[bytes]:
    while True:
        b = fh.read(CHUNK)
        if not b:
            return
        yield b


class LineFile:
    """Random access to the lines of one file (or one member of a .zip) on any Storage."""

    def __init__(self, storage: Storage, path: str, member: Optional[str] = None, cache: Optional[LineCache] = None):
        self.storage, self.path, self.member = storage, path, member
        self.cache = cache or LineCache(os.path.join(tempfile.gettempdir(), "nli_viewer_cache"))
        self._starts: Optional[array.array] = None
        self._size = 0
        self._data_path: Optional[str] = None
        self._lock = threading.Lock()

    # ---- index ----------------------------------------------------------------------------------

    def _ensure(self) -> None:
        if self._starts is not None:
            return
        with self._lock:
            if self._starts is not None:
                return
            fp = self.storage.fingerprint(self.path)
            key = self.cache.key(self.storage.uri, self.path, self.member or "", fp)
            d = self.cache.dir(key)
            idx, meta_p = d / "lines.idx", d / "meta.json"
            local = self.storage.local_path(self.path)
            direct = local is not None and self.member is None and not is_compressed(self.path) \
                and not nli_formats.needs_local_file(self.path)
            with self.cache.lock(key):
                if not meta_p.exists():
                    self._build(d, local if direct else None)
            meta = json.loads(meta_p.read_text("utf-8"))
            starts = array.array("Q")
            with open(idx, "rb") as fh:
                starts.frombytes(fh.read())
            self._starts, self._size = starts, meta["size"]
            self._data_path = local if direct else str(d / "data")
            self.cache.touch(key)

    def _build(self, d: Path, direct_path: Optional[str]) -> None:
        d.mkdir(parents=True, exist_ok=True)
        t0 = time.perf_counter()
        tmp_data = d / "data.tmp"
        if direct_path is not None:
            with open(direct_path, "rb") as fh:
                starts, size = _scan_offsets(_read_chunks(fh), None)
        elif nli_formats.is_archive(self.path) or self.member:
            starts, size = self._build_archive(d, tmp_data)
        elif nli_formats.is_table(self.path):
            starts, size = self._build_table(d, tmp_data)
        else:
            with self.storage.open(self.path) as raw, decompressed_stream(raw, self.path) as fh, \
                    open(tmp_data, "wb") as sink:
                starts, size = _scan_offsets(_read_chunks(fh), sink)
        with open(d / "lines.idx.tmp", "wb") as fh:
            fh.write(starts.tobytes())
        if tmp_data.exists():
            os.replace(tmp_data, d / "data")
        os.replace(d / "lines.idx.tmp", d / "lines.idx")
        meta = {"storage": self.storage.display_uri, "path": self.path, "member": self.member, "size": size,
                "lines": len(starts), "seconds": round(time.perf_counter() - t0, 3), "created": time.time()}
        (d / "meta.json").write_text(json.dumps(meta), "utf-8")
        self.cache.trim(keep=d.name)

    @contextlib.contextmanager
    def _local(self, d: Path) -> Iterator[str]:
        """A real file (archives and tables need one): the local file, or a download into the cache entry."""
        local = self.storage.local_path(self.path)
        if local is not None:
            yield local
            return
        downloaded = d / ("download.tmp" + Path(self.path).suffix)
        try:
            with self.storage.open(self.path) as src, open(downloaded, "wb") as dst:
                shutil.copyfileobj(src, dst, CHUNK)
            yield str(downloaded)
        finally:
            with contextlib.suppress(OSError):
                os.remove(downloaded)

    def _build_archive(self, d: Path, tmp_data: Path) -> Tuple[array.array, int]:
        with self._local(d) as local:
            names = archive_members(local)
            member = self.member or (names[0] if names else None)
            if member is None or member not in names:
                raise FileNotFoundError(f"{self.path}!{self.member}")
            with open_member(local, member) as raw, decompressed_stream(raw, member) as fh, \
                    open(tmp_data, "wb") as sink:
                return _scan_offsets(_read_chunks(fh), sink)

    def _build_table(self, d: Path, tmp_data: Path) -> Tuple[array.array, int]:
        with self._local(d) as local, open(tmp_data, "wb") as sink:
            return _scan_offsets(nli_formats.table_lines(local), sink)  # the download keeps the suffix

    # ---- access ---------------------------------------------------------------------------------

    def __len__(self) -> int:
        self._ensure()
        return len(self._starts)

    def _span(self, n: int) -> Tuple[int, int]:
        if not 1 <= n <= len(self._starts):
            raise IndexError(f"line {n} out of range 1..{len(self._starts)}")
        start = self._starts[n - 1]
        end = self._starts[n] if n < len(self._starts) else self._size
        return start, end

    def line(self, n: int) -> bytes:
        """Line n (1-based) without its line ending."""
        return self.lines(n, 1)[0]

    def lines(self, start: int, count: int) -> List[bytes]:
        """Up to count lines from line `start` (1-based)."""
        self._ensure()
        if count <= 0:
            return []
        last = min(len(self._starts), start + count - 1)
        a, _ = self._span(start)
        _, b = self._span(last)
        with open(self._data_path, "rb") as fh:
            fh.seek(a)
            blob = fh.read(b - a)
        out = []
        for n in range(start, last + 1):
            s, e = self._span(n)
            out.append(blob[s - a:e - a].rstrip(b"\r\n"))
        return out

    def iter_lines(self) -> Iterator[Tuple[int, bytes]]:
        """(line number, bytes) for every line, read from the cache in large blocks."""
        self._ensure()
        n = len(self._starts)
        step = 4096
        for first in range(1, n + 1, step):
            for k, b in enumerate(self.lines(first, step)):
                yield first + k, b

    @property
    def data_path(self) -> str:
        self._ensure()
        return self._data_path

"""
nli_formats.py - corpus formats besides (compressed) JSONL: .parquet / .arrow tables and .rar archives, plus the
helpers
shared by nli_models.py / nli_filter.py (reading) and the viewer (reading + editing).

Every format is read as JSONL lines, so line numbers mean the same everywhere:

  .jsonl .json .ndjson            one JSON object per line
  ... .gz .zst .zstd              the same, compressed
  .zip / .rar                     archives of such files ("members"); a member is named "archive.rar!dir/a.jsonl"
  .parquet .arrow .feather        a table: row n = line n, written as one JSON object per row (compact, UTF-8;
                                  values JSON has no type for, e.g. dates, as text). .arrow: Arrow IPC file format
                                  (also .feather) or stream format (Hugging Face datasets), detected

Tables need the 'pyarrow' package. .rar needs the RAR command-line tools: UnRAR (reading) and Rar (writing,
part of WinRAR), found in PATH, C:\\Program Files\\WinRAR, or the environment variables NLI_UNRAR / NLI_RAR.

    from nli_formats import stem, rar_members, open_rar_member, parquet_lines
    stem("shard-00001.jsonl.zst")             -> "shard-00001"
    for name in rar_members("x.rar"): ...      member names with "/" separators
    with open_rar_member("x.rar", "dir/a.jsonl") as fh: data = fh.read()
    for chunk in table_lines("x.parquet"): ...     JSONL bytes, ending with a newline (.parquet / .arrow)
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, BinaryIO, Dict, Iterator, List, Optional

__all__ = ["INPUT_SUFFIXES", "ARCHIVE_SUFFIXES", "COMPRESSED_SUFFIXES", "TABLE_SUFFIXES", "stem", "is_archive",
           "is_table", "needs_local_file", "rar_tool", "rar_members", "open_rar_member", "rar_replace_member",
           "parquet_available", "parquet_lines", "parquet_dump", "parquet_replace_texts", "IterStream",
           "table_lines", "table_replace_texts", "arrow_lines", "arrow_replace_texts", "table_problem",
           "member_compression"]

COMPRESSED_SUFFIXES = (".zst", ".zstd", ".gz")
ARCHIVE_SUFFIXES = (".zip", ".rar")
TABLE_SUFFIXES = (".parquet", ".arrow", ".feather")
INPUT_SUFFIXES = (".jsonl", ".json", ".ndjson") + COMPRESSED_SUFFIXES + ARCHIVE_SUFFIXES + TABLE_SUFFIXES


def stem(name: str) -> str:
    """'shard-00000.jsonl.zst' -> 'shard-00000', 'x.parquet' -> 'x' (the rule for output file names)."""
    changed = True
    while changed:
        changed = False
        for suf in INPUT_SUFFIXES:
            if name.lower().endswith(suf) and len(name) > len(suf):
                name, changed = name[: -len(suf)], True
    return name


def is_archive(name: str) -> bool:
    return name.lower().endswith(ARCHIVE_SUFFIXES)


def is_table(name: str) -> bool:
    return name.lower().endswith(TABLE_SUFFIXES)


def needs_local_file(name: str) -> bool:
    """Formats that need random access (a real file), not a stream: archives and tables."""
    return is_archive(name) or is_table(name)


def member_compression(member: str) -> Optional[str]:
    low = member.lower()
    return "zst" if low.endswith((".zst", ".zstd")) else "gz" if low.endswith(".gz") else None


class IterStream(io.RawIOBase):
    """Read-only stream over an iterator of byte chunks (e.g. parquet_lines())."""

    def __init__(self, chunks: Iterator[bytes], on_close=None):
        self._it, self._buf, self._on_close = chunks, b"", on_close

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        while not self._buf:
            try:
                self._buf = next(self._it)
            except StopIteration:
                return 0
        n = min(len(b), len(self._buf))
        b[:n], self._buf = self._buf[:n], self._buf[n:]
        return n

    def close(self) -> None:
        if not self.closed and self._on_close is not None:
            self._on_close()
        super().close()


# --------------------------------------------------------------------------------------------------
# RAR (command-line tools; RAR is a closed format, there is no pure-Python writer)
# --------------------------------------------------------------------------------------------------

_WINRAR_DIRS = [r"C:\Program Files\WinRAR", r"C:\Program Files (x86)\WinRAR"]


def rar_tool(kind: str = "unrar") -> Optional[str]:
    """Path of UnRAR (kind 'unrar', for reading; Rar also reads) or Rar (kind 'rar', for writing); None if missing."""
    env = os.environ.get("NLI_UNRAR" if kind == "unrar" else "NLI_RAR")
    if env and Path(env).is_file():
        return env
    names = ["unrar", "UnRAR.exe", "rar", "Rar.exe"] if kind == "unrar" else ["rar", "Rar.exe"]
    for n in names:
        found = shutil.which(n)
        if found:
            return found
    if os.name == "nt":
        for d in _WINRAR_DIRS:
            for n in names:
                p = Path(d) / n
                if p.is_file():
                    return str(p)
    return None


def _need(kind: str) -> str:
    tool = rar_tool(kind)
    if tool is None:
        what = "reading .rar files needs UnRAR" if kind == "unrar" else "writing .rar files needs Rar (WinRAR)"
        raise RuntimeError(f"{what}: install WinRAR (Windows) or rar/unrar (Linux), or set "
                           f"{'NLI_UNRAR' if kind == 'unrar' else 'NLI_RAR'} to its path")
    return tool


def _native(member: str) -> str:
    """Member name as the RAR tools of this system expect it (Windows: backslashes)."""
    return member.replace("/", "\\") if os.name == "nt" else member


def _run(args: List[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, **kw)


def rar_members(path: str) -> List[str]:
    """File names inside a .rar archive ('/' separators), folders left out, in archive order."""
    tool = _need("unrar")
    # -scfl: list names as UTF-8 (UnRAR 5+); older tools ignore unknown charset switches with an error, so retry
    res = _run([tool, "lb", "-scfl", path])
    if res.returncode != 0:
        res = _run([tool, "lb", path])
    if res.returncode != 0:
        raise RuntimeError(f"cannot list {path}: {(res.stderr or res.stdout).decode('utf-8', 'replace').strip()}")
    try:
        text = res.stdout.decode("utf-8")
    except UnicodeDecodeError:
        text = res.stdout.decode(sys.getfilesystemencoding(), "replace")
    names = [n.strip().replace("\\", "/") for n in text.splitlines() if n.strip()]
    # 'lb' also lists folders: a name that is the prefix of another name is a folder
    prefixes = {n.rsplit("/", 1)[0] for n in names if "/" in n}
    return [n for n in names if n not in prefixes]


def open_rar_member(path: str, member: str) -> BinaryIO:
    """Stream the (raw) bytes of one member; raises FileNotFoundError if it is not in the archive."""
    tool = _need("unrar")
    proc = subprocess.Popen([tool, "p", "-inul", path, _native(member)], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
    first = proc.stdout.read(1 << 16)
    if not first:
        rc = proc.wait()
        if rc != 0:
            raise FileNotFoundError(f"{path}!{member}")
    state = {"first": first}

    def chunks() -> Iterator[bytes]:
        if state["first"]:
            yield state.pop("first")
        while True:
            b = proc.stdout.read(1 << 20)
            if not b:
                break
            yield b
        if proc.wait() != 0:
            raise OSError(f"UnRAR failed reading {path}!{member} (exit code {proc.returncode})")

    def close() -> None:
        proc.stdout.close()
        if proc.poll() is None:
            proc.kill()
        proc.wait()

    return io.BufferedReader(IterStream(chunks(), close), buffer_size=1 << 20)


def rar_replace_member(archive: str, member: str, content_file: str, out_archive: str) -> None:
    """out_archive = archive with member replaced by content_file (other members unchanged; also solid archives)."""
    tool = _need("rar")
    shutil.copyfile(archive, out_archive)
    with tempfile.TemporaryDirectory(prefix="nli_rar_") as tmp:
        dst = Path(tmp) / Path(*member.split("/"))
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(content_file, dst)
        # run inside tmp so the stored name is the relative path = the member name; -o+ replaces it
        res = _run([tool, "a", "-idq", "-y", "-o+", os.path.abspath(out_archive), _native(member)], cwd=tmp)
    if res.returncode != 0:
        raise RuntimeError(f"Rar could not update {member}: {(res.stderr or res.stdout).decode('utf-8', 'replace')}")


# --------------------------------------------------------------------------------------------------
# Parquet (pyarrow)
# --------------------------------------------------------------------------------------------------

def parquet_available() -> bool:
    try:
        import pyarrow.parquet  # noqa: F401
        return True
    except ImportError:
        return False


def _pq():
    try:
        import pyarrow.parquet as pq
        return pq
    except ImportError:
        raise RuntimeError("reading .parquet files needs the 'pyarrow' package (pip install pyarrow)") from None


def parquet_dump(row: Dict[str, Any]) -> bytes:
    """One table row as a JSON line: compact, UTF-8, dates and other non-JSON values as text."""
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


def parquet_lines(source: Any, batch_rows: int = 4096) -> Iterator[bytes]:
    """JSONL bytes of a .parquet file (path or binary file object), one line per row, in row order."""
    pf = _pq().ParquetFile(source)
    for batch in pf.iter_batches(batch_size=batch_rows):
        rows = batch.to_pylist()
        if rows:
            yield b"\n".join(parquet_dump(r) for r in rows) + b"\n"


def _set_texts(table, field: str, texts: Dict[int, str]):
    """table with column `field` set to texts[row] (0-based rows); the column must be text."""
    import pyarrow as pa
    if field not in table.column_names:
        raise ValueError(f"the table has no column '{field}'")
    i = table.column_names.index(field)
    col = table.column(i)
    if not (pa.types.is_string(col.type) or pa.types.is_large_string(col.type)):
        raise ValueError(f"column '{field}' is {col.type}, not text")
    values = col.to_pylist()
    for row, text in texts.items():
        if not 0 <= row < len(values):
            raise ValueError(f"row {row + 1} out of range 1..{len(values)}")
        values[row] = text
    return table.set_column(i, table.schema.field(i), pa.array(values, type=col.type)), i


def parquet_replace_texts(src: str, dst: str, field: str, texts: Dict[int, str]) -> None:
    """dst = src with column `field` set to texts[row] (0-based rows); schema, other columns, compression and row
    group size stay as they were."""
    pq = _pq()
    pf = pq.ParquetFile(src)
    table, i = _set_texts(pf.read(), field, texts)
    meta = pf.metadata
    codec = meta.row_group(0).column(i).compression.lower() if meta.num_row_groups else "snappy"
    rows_per_group = meta.row_group(0).num_rows if meta.num_row_groups else None
    pq.write_table(table, dst, compression=None if codec == "uncompressed" else codec,
                   row_group_size=rows_per_group or None)


# --------------------------------------------------------------------------------------------------
# Arrow IPC (.arrow / .feather): file format, or stream format (Hugging Face datasets' .arrow files)
# --------------------------------------------------------------------------------------------------

def _arrow_open(path: str, source=None):
    """('file' | 'stream', reader) for an Arrow IPC file. Give `source` (an open pa.OSFile) to close it yourself.
    No memory map: Windows cannot replace a file that is still mapped."""
    _pq()  # clear message when pyarrow is missing
    import pyarrow as pa
    src = source if source is not None else pa.OSFile(path, "rb")
    try:
        return "file", pa.ipc.open_file(src)
    except pa.ArrowInvalid:
        src.seek(0)
        return "stream", pa.ipc.open_stream(src)


def _arrow_batches(kind: str, reader):
    if kind == "file":
        for k in range(reader.num_record_batches):
            yield reader.get_batch(k)
    else:
        yield from reader


def arrow_lines(path: str, batch_rows: int = 4096) -> Iterator[bytes]:
    """JSONL bytes of an Arrow IPC file (.arrow / .feather), one line per row, in row order."""
    import pyarrow as pa
    with pa.OSFile(path, "rb") as src:  # closed when done: the file may be replaced afterwards
        kind, reader = _arrow_open(path, src)
        for batch in _arrow_batches(kind, reader):
            for off in range(0, batch.num_rows, batch_rows):
                rows = batch.slice(off, batch_rows).to_pylist()
                if rows:
                    yield b"\n".join(parquet_dump(r) for r in rows) + b"\n"


def _arrow_compression(path: str, data_bytes: int) -> Optional[str]:
    """Body compression of an Arrow IPC file. pyarrow does not report it, so: a file much smaller than its data
    is compressed; the codec is told by the frame marker of the compressed buffers (zstd / lz4)."""
    size = os.path.getsize(path)
    if data_bytes == 0 or size >= 0.9 * data_bytes:
        return None
    with open(path, "rb") as fh:
        head = fh.read(4 << 20)
    if b"\x28\xb5\x2f\xfd" in head:
        return "zstd"
    if b"\x04\x22\x4d\x18" in head:
        return "lz4"
    return None


def arrow_replace_texts(src: str, dst: str, field: str, texts: Dict[int, str]) -> None:
    """dst = src with column `field` set to texts[row] (0-based rows), written like src: same IPC format (file /
    stream), schema with its metadata, record batch size and compression (zstd / lz4)."""
    import pyarrow as pa
    with pa.OSFile(src, "rb") as fh:  # read, then close: the file is replaced afterwards
        kind, reader = _arrow_open(src, fh)
        batches = list(_arrow_batches(kind, reader))
        table = pa.Table.from_batches(batches, schema=reader.schema)
    first = batches[0].num_rows if batches else None
    compression = _arrow_compression(src, table.nbytes)
    table, _ = _set_texts(table, field, texts)
    options = pa.ipc.IpcWriteOptions(compression=compression)
    opener = pa.ipc.new_file if kind == "file" else pa.ipc.new_stream
    with pa.OSFile(dst, "wb") as sink, opener(sink, table.schema, options=options) as writer:
        writer.write_table(table, max_chunksize=first or None)


# ---- any table ----------------------------------------------------------------------------------

def table_problem(name: str) -> Optional[str]:
    """Why this table cannot be read here (None = it can)."""
    return None if parquet_available() else f"reading {Path(name).suffix} files needs the 'pyarrow' package"


def table_lines(path: str) -> Iterator[bytes]:
    """JSONL bytes of a .parquet / .arrow / .feather file."""
    return parquet_lines(path) if path.lower().endswith(".parquet") else arrow_lines(path)


def table_replace_texts(src: str, dst: str, field: str, texts: Dict[int, str], kind: Optional[str] = None) -> None:
    """Replace texts in a table file; kind = the original's suffix when src has another name."""
    if (kind or src).lower().endswith(".parquet"):
        parquet_replace_texts(src, dst, field, texts)
    else:
        arrow_replace_texts(src, dst, field, texts)

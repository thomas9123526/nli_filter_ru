"""Viewing and editing .zip / .rar members and .parquet rows (local and on an FTP server)."""
import datetime
import gzip
import io
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from nli_viewer.config import DatasetConfig, DatasetRegistry, ViewerConfig
from nli_viewer.edit import EditError

import nli_formats

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")
HAVE_RAR = nli_formats.rar_tool("rar") is not None and nli_formats.rar_tool("unrar") is not None


def _rows(prefix, n=4):
    return [{"id": f"{prefix}{i}", "text": f"text {i} of {prefix}", "expect": "keep"} for i in range(1, n + 1)]


def _jsonl(rows):
    return ("\n".join(json.dumps(r) for r in rows) + "\n").encode()


@pytest.fixture()
def corpus(tmp_path):
    root = tmp_path / "corpus"
    (root / "arch").mkdir(parents=True)
    with zipfile.ZipFile(root / "arch" / "z.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("first.jsonl", _jsonl(_rows("zf")))
        z.writestr("dir/second.jsonl.gz", gzip.compress(_jsonl(_rows("zs"))))
        z.writestr("readme.txt", b"not a corpus file")
    t = pa.table({"id": [f"p{i}" for i in range(1, 6)], "text": [f"row {i} Пример" for i in range(1, 6)],
                  "n": list(range(5)), "day": [datetime.date(2024, 1, i) for i in range(1, 6)]})
    pq.write_table(t, root / "arch" / "t.parquet", compression="zstd", row_group_size=2)
    if HAVE_RAR:
        src = tmp_path / "rar_src"
        (src / "sub").mkdir(parents=True)
        (src / "a.jsonl").write_bytes(_jsonl(_rows("ra")))
        (src / "sub" / "b.jsonl").write_bytes(_jsonl(_rows("rb")))
        for name, solid in (("r.rar", []), ("solid.rar", ["-s"])):
            subprocess.run([nli_formats.rar_tool("rar"), "a", "-idq", "-y", *solid, str(root / "arch" / name),
                            "a.jsonl", nli_formats._native("sub/b.jsonl")], cwd=src, check=True)
    return root


def _ds(tmp_path, corpus_uri, **opts):
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    cfg = ViewerConfig(datasets=[DatasetConfig(name="f", corpus=corpus_uri, output=str(out), editable=True,
                                               corpus_options=opts)],
                       cache_dir=str(tmp_path / "cache"), edits_dir=str(tmp_path / "edits"), base_dir=str(tmp_path))
    return DatasetRegistry(cfg).get("f")


def _zip_members(path):
    with zipfile.ZipFile(path) as z:
        return {i.filename: z.read(i) for i in z.infolist()}


def test_zip_view_and_edit(tmp_path, corpus):
    ds = _ds(tmp_path, str(corpus))
    p = "arch/z.zip"
    first = ds.corpus_lines(p, 1, 10)
    assert first["members"] == ["first.jsonl", "dir/second.jsonl.gz"] and first["member"] == "first.jsonl"
    second = ds.corpus_lines(p, 1, 10, member="dir/second.jsonl.gz")
    assert [x["id"] for x in second["lines"]] == ["zs1", "zs2", "zs3", "zs4"] and second["editable"]
    before = _zip_members(corpus / p)
    with pytest.raises(EditError, match="member"):
        ds.editor.edit_text(p, 1, "x")
    out = ds.editor.edit_texts(p, [{"line": 2, "text": "zip edit ✓", "sha1": second["lines"][1]["sha1"]}],
                               member="dir/second.jsonl.gz")
    assert out["changed"] == 1 and out["lines"][0]["text"] == "zip edit ✓"
    after = _zip_members(corpus / p)
    assert list(after) == list(before)  # same members, same order
    assert after["first.jsonl"] == before["first.jsonl"] and after["readme.txt"] == before["readme.txt"]
    lines = gzip.decompress(after["dir/second.jsonl.gz"]).splitlines()
    assert json.loads(lines[1])["text"] == "zip edit ✓" and lines[0] == gzip.decompress(
        before["dir/second.jsonl.gz"]).splitlines()[0]
    assert ds.corpus_lines(p, 2, 1, member="dir/second.jsonl.gz")["lines"][0]["edits"] == 1
    assert ds.corpus_lines(p, 2, 1)["lines"][0]["edits"] == 0  # the other member has no edits
    ds.editor.undo(ds.editor.history(p, member="dir/second.jsonl.gz")[0]["edit"])
    assert gzip.decompress(_zip_members(corpus / p)["dir/second.jsonl.gz"]) == \
        gzip.decompress(before["dir/second.jsonl.gz"])


def test_parquet_view_and_edit(tmp_path, corpus):
    ds = _ds(tmp_path, str(corpus))
    p = "arch/t.parquet"
    view = ds.corpus_lines(p, 1, 10)
    assert view["members"] is None and [x["id"] for x in view["lines"]] == ["p1", "p2", "p3", "p4", "p5"]
    assert view["lines"][2]["text"] == "row 3 Пример"
    old_meta = pq.ParquetFile(corpus / p).metadata
    ds.editor.edit_texts(p, [{"line": 3, "text": "parquet edit", "sha1": view["lines"][2]["sha1"]},
                             {"line": 5, "text": "last row edit"}])
    t = pq.read_table(corpus / p)
    assert t.column("text").to_pylist() == ["row 1 Пример", "row 2 Пример", "parquet edit", "row 4 Пример",
                                            "last row edit"]
    assert t.column("day").to_pylist()[0] == datetime.date(2024, 1, 1) and t.column("n").to_pylist() == list(range(5))
    meta = pq.ParquetFile(corpus / p).metadata
    assert meta.num_row_groups == old_meta.num_row_groups == 3
    assert meta.row_group(0).column(1).compression == "ZSTD"
    assert ds.corpus_lines(p, 3, 1)["lines"][0]["text"] == "parquet edit"
    for e in reversed(ds.editor.history(p)):
        ds.editor.undo(e["edit"])
    assert pq.read_table(corpus / p).column("text").to_pylist()[2] == "row 3 Пример"


@pytest.mark.skipif(not HAVE_RAR, reason="needs WinRAR's Rar / UnRAR (or rar / unrar on Linux)")
@pytest.mark.parametrize("name", ["r.rar", "solid.rar"])
def test_rar_view_and_edit(tmp_path, corpus, name):
    ds = _ds(tmp_path, str(corpus))
    p = f"arch/{name}"
    view = ds.corpus_lines(p, 1, 10, member="sub/b.jsonl")
    assert view["members"] == ["a.jsonl", "sub/b.jsonl"] and [x["id"] for x in view["lines"]][:2] == ["rb1", "rb2"]
    ds.editor.edit_text(p, 1, "rar edit", view["lines"][0]["sha1"], member="sub/b.jsonl")
    with nli_formats.open_rar_member(str(corpus / p), "sub/b.jsonl") as fh:
        lines = fh.read().splitlines()
    assert json.loads(lines[0])["text"] == "rar edit" and json.loads(lines[1])["id"] == "rb2"
    with nli_formats.open_rar_member(str(corpus / p), "a.jsonl") as fh:
        assert fh.read() == _jsonl(_rows("ra"))  # the other member is unchanged
    assert nli_formats.rar_members(str(corpus / p)) == ["a.jsonl", "sub/b.jsonl"]
    ds.editor.undo(ds.editor.history(p, member="sub/b.jsonl")[0]["edit"])
    with nli_formats.open_rar_member(str(corpus / p), "sub/b.jsonl") as fh:
        assert fh.read() == _jsonl(_rows("rb"))


def test_formats_on_ftp(tmp_path, corpus):
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer
    import socket
    import threading
    auth = DummyAuthorizer()
    auth.add_user("w", "pw", str(corpus), perm="elradfmw")
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    server = FTPServer(("127.0.0.1", port), type("H", (FTPHandler,), {"authorizer": auth}))
    threading.Thread(target=server.serve_forever, kwargs={"timeout": 0.2}, daemon=True).start()
    try:
        ds = _ds(tmp_path, f"ftp://w:pw@127.0.0.1:{port}/")
        assert ds.members("arch/z.zip") == ["first.jsonl", "dir/second.jsonl.gz"]
        ds.editor.edit_text("arch/z.zip", 1, "zip on ftp", member="first.jsonl")
        ds.editor.edit_text("arch/t.parquet", 1, "parquet on ftp")
        assert json.loads(_zip_members(corpus / "arch/z.zip")["first.jsonl"].splitlines()[0])["text"] == "zip on ftp"
        assert pq.read_table(corpus / "arch/t.parquet").column("text").to_pylist()[0] == "parquet on ftp"
        assert (tmp_path / "edits" / "f" / "originals" / "arch" / "t.parquet").is_file()  # downloaded backup
    finally:
        server.close_all()


@pytest.mark.parametrize("kind,compression", [("file", None), ("file", "zstd"), ("stream", None), ("stream", "lz4")])
def test_arrow_view_and_edit(tmp_path, kind, compression):
    root = tmp_path / "corpus"
    root.mkdir()
    n = 3000
    schema = pa.schema([("id", pa.string()), ("text", pa.string()), ("n", pa.int64())],
                       metadata={b"huggingface": b'{"info": {"features": {}}}'})
    t = pa.table({"id": [f"a{i}" for i in range(n)], "text": [f"row {i} " + "filler words " * 20 for i in range(n)],
                  "n": list(range(n))}, schema=schema)
    p = root / "data.arrow"
    opener = pa.ipc.new_file if kind == "file" else pa.ipc.new_stream
    with pa.OSFile(str(p), "wb") as sink, opener(sink, schema, options=pa.ipc.IpcWriteOptions(
            compression=compression)) as w:
        w.write_table(t, max_chunksize=1000)
    size_before = p.stat().st_size
    ds = _ds(tmp_path, str(root))
    view = ds.corpus_lines("data.arrow", 1500, 2)
    assert [x["id"] for x in view["lines"]] == ["a1499", "a1500"]
    ds.editor.edit_texts("data.arrow", [{"line": 1500, "text": "arrow edit ✓", "sha1": view["lines"][0]["sha1"]}])
    with pa.OSFile(str(p), "rb") as fh:
        kind2, reader = nli_formats._arrow_open(str(p), fh)
        batches = list(nli_formats._arrow_batches(kind2, reader))
        new = pa.Table.from_batches(batches, schema=reader.schema)
    assert kind2 == kind and [b.num_rows for b in batches] == [1000, 1000, 1000]  # same layout and batch size
    assert new.schema.metadata == schema.metadata  # e.g. Hugging Face's dataset info stays
    assert new.column("text")[1499].as_py() == "arrow edit ✓" and new.column("text")[1500].as_py().startswith("row 1500")
    assert new.column("n").to_pylist() == list(range(n))
    # compression kept: a compressed file stays about as small (not ~5x bigger)
    assert nli_formats._arrow_compression(str(p), new.nbytes) == compression
    assert p.stat().st_size < 1.5 * size_before
    ds.editor.undo(ds.editor.history("data.arrow")[0]["edit"])
    assert ds.corpus_lines("data.arrow", 1500, 1)["lines"][0]["text"].startswith("row 1499")

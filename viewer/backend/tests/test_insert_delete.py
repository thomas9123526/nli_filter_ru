"""Inserting and deleting corpus lines: positions, decisions following their lines, undo, tables, archives, API."""
import datetime
import gzip
import json
import zipfile

import pytest
import zstandard
from fastapi.testclient import TestClient

from conftest import build_tree
from nli_viewer.api import EDIT_HEADER, create_app
from nli_viewer.config import DatasetConfig, DatasetRegistry, ViewerConfig
from nli_viewer.edit import EditConflict, EditError, map_back, map_forward

H = {EDIT_HEADER: "1"}


@pytest.fixture()
def tree(tmp_path):
    return build_tree(tmp_path / "tree")


def _cfg(tree, tmp_path):
    return ViewerConfig(datasets=[DatasetConfig(name="t", corpus=str(tree / "corpus"), output=str(tree / "out"),
                                                editable=True)],
                        cache_dir=str(tmp_path / "cache"), edits_dir=str(tmp_path / "edits"),
                        frontend_dir=str(tmp_path / "nofrontend"), base_dir=str(tmp_path))


@pytest.fixture()
def ds(tree, tmp_path):
    return DatasetRegistry(_cfg(tree, tmp_path)).get("t")


def _zst(p):
    return zstandard.ZstdDecompressor().stream_reader(open(p, "rb")).read()


def test_map_forward_and_back():
    ops = [("insert", 3), ("delete", 1), ("insert", 1)]
    for old in range(1, 8):
        new = map_forward(old, ops)
        if new is not None:
            assert map_back(new, ops) == old
    assert map_forward(1, ops) is None  # deleted
    assert map_back(1, ops) is None and map_back(3, ops) is None  # both inserted lines


def test_insert_and_delete_zst(ds, tree):
    rel = "a/x.jsonl.zst"
    original = _zst(tree / "corpus" / rel)
    near = ds.editor.read_line(rel, 2)
    out = ds.editor.insert_line(rel, 2, {"id": "new-1", "text": "A new line about Russia.", "expect": "filter"},
                                near["sha1"])
    assert out["line"] == 3 and out["id"] == "new-1"
    lines = _zst(tree / "corpus" / rel).splitlines()
    assert len(lines) == 6 and json.loads(lines[2]) == {"id": "new-1", "text": "A new line about Russia.",
                                                       "expect": "filter"}
    assert lines[2] == json.dumps(json.loads(lines[2])).encode()  # the file's JSON style
    assert lines[:2] + lines[3:] == original.splitlines()
    # decisions follow their lines: decision line 4 (ax-4) is now line 5
    rec = ds.record("a/x", line=4)
    assert rec["original"]["record"]["id"] == "ax-4" and rec["edit"]["line"] == 5 and rec["edit"]["moved"]
    assert rec["id_check"]["match"]
    page = ds.corpus_lines(rel, 1, 10)
    while page["decisions_pending"]:
        page = ds.corpus_lines(rel, 1, 10)
    assert page["lines"][2].get("inserted") and "row" not in page["lines"][2]
    assert page["lines"][4]["row"] == 4 and page["lines"][4]["id"] == "ax-4"
    # delete line 1: decision line 1 is gone, decision line 2 is now line 1
    first = ds.editor.read_line(rel, 1)
    ds.editor.delete_line(rel, 1, first["sha1"])
    assert "deleted" in ds.record("a/x", line=1)["original"]["error"]
    assert ds.record("a/x", line=2)["original"]["record"]["id"] == "ax-2"
    assert [json.loads(x)["id"] for x in _zst(tree / "corpus" / rel).splitlines()] == \
        ["ax-2", "new-1", "ax-3", "ax-4", "ax-5"]
    # undo both (latest first): the file is back to its original bytes
    log = ds.editor.history(rel)
    assert [e["kind"] for e in log] == ["insert", "delete"]
    ds.editor.undo(log[1]["edit"])
    ds.editor.undo(log[0]["edit"])
    assert _zst(tree / "corpus" / rel) == original
    assert ds.record("a/x", line=4)["edit"]["line"] == 4


def test_text_edit_history_follows_moves(ds):
    rel = "a/x.jsonl.zst"
    ds.editor.edit_text(rel, 4, "edited before the insert")
    ds.editor.insert_line(rel, 0, {"id": "top", "text": "first line now"})
    assert ds.editor.edited_lines(rel) == {5: 1, 1: 1}  # the edit moved with its line; the insert is line 1
    assert [e["current_line"] for e in ds.editor.history(rel, 5)] == [5]
    e = ds.editor.history(rel, 5)[0]
    ds.editor.undo(e["edit"])  # undo finds the line at its new place
    assert ds.editor.read_line(rel, 5)["id"] == "ax-4" and "Russia" in ds.editor.read_line(rel, 5)["text"]


def test_insert_checks(ds):
    rel = "a/x.jsonl.zst"
    with pytest.raises(EditError, match="already used by line 3"):
        ds.editor.insert_line(rel, 1, {"id": "ax-3", "text": "dup"})
    with pytest.raises(EditError, match="needs an 'id'"):
        ds.editor.insert_line(rel, 1, {"text": "no id"})
    with pytest.raises(EditError, match="text field"):
        ds.editor.insert_line(rel, 1, {"id": "z"})
    with pytest.raises(EditError, match="out of range"):
        ds.editor.insert_line(rel, 9, {"id": "z", "text": "x"})
    with pytest.raises(EditConflict):
        ds.editor.insert_line(rel, 1, {"id": "z", "text": "x"}, sha1="0" * 40)


def test_crlf_file_without_final_newline(ds, tree):
    rel = "b/z.jsonl"  # CRLF, no newline at the end
    p = tree / "corpus" / rel
    original = p.read_bytes()
    ds.editor.insert_line(rel, 5, {"id": "end", "text": "appended"})
    data = p.read_bytes()
    assert data == original + b"\r\n" + json.dumps({"id": "end", "text": "appended"}).encode()
    ds.editor.delete_line(rel, 6)
    assert p.read_bytes() == original
    ds.editor.delete_line(rel, 5)  # the last line: the CRLF before it goes too
    assert p.read_bytes() == b"\r\n".join(original.split(b"\r\n")[:4])
    for e in reversed(ds.editor.history(rel)):
        if e.get("undo_of") is None and e["kind"] == "delete" and e["line"] == 5:
            ds.editor.undo(e["edit"])
    assert p.read_bytes() == original


def test_gz_and_zip_member(ds, tree):
    ds.editor.insert_line("a/y.jsonl.gz", 0, {"id": "g0", "text": "gz top"})
    assert json.loads(gzip.decompress((tree / "corpus" / "a/y.jsonl.gz").read_bytes()).splitlines()[0])["id"] == "g0"
    with pytest.raises(EditError, match="member"):
        ds.editor.insert_line("c/w.zip", 0, {"id": "z0", "text": "zip"})
    ds.editor.insert_line("c/w.zip", 5, {"id": "z6", "text": "zip end"}, member="w1.jsonl")
    with zipfile.ZipFile(tree / "corpus" / "c/w.zip") as z:
        assert json.loads(z.read("w1.jsonl").splitlines()[-1])["id"] == "z6"
    ds.editor.delete_line("c/w.zip", 1, member="w1.jsonl")
    assert ds.corpus_lines("c/w.zip", 1, 1, member="w1.jsonl")["lines"][0]["id"] == "cw-2"


def test_parquet_rows(tmp_path):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    root = tmp_path / "corpus"
    root.mkdir()
    (tmp_path / "out").mkdir()
    t = pa.table({"id": ["p1", "p2", "p3"], "text": ["a", "b", "c"], "day": [datetime.date(2024, 1, i) for i in (1, 2, 3)]})
    pq.write_table(t, root / "t.parquet")
    cfg = ViewerConfig(datasets=[DatasetConfig(name="p", corpus=str(root), output=str(tmp_path / "out"), editable=True)],
                       cache_dir=str(tmp_path / "cache"), edits_dir=str(tmp_path / "edits"), base_dir=str(tmp_path))
    ds = DatasetRegistry(cfg).get("p")
    ds.editor.insert_line("t.parquet", 1, {"id": "new", "text": "inserted row", "day": "2024-05-06"})
    got = pq.read_table(root / "t.parquet")
    assert got.column("id").to_pylist() == ["p1", "new", "p2", "p3"]
    assert got.column("day").to_pylist()[1] == datetime.date(2024, 5, 6) and got.schema == t.schema
    with pytest.raises(EditError, match="no column"):
        ds.editor.insert_line("t.parquet", 0, {"id": "x", "text": "y", "color": "red"})
    with pytest.raises(EditError, match="does not fit"):
        ds.editor.insert_line("t.parquet", 0, {"id": "x", "text": "y", "day": "not a date"})
    ds.editor.delete_line("t.parquet", 3)  # p2
    assert pq.read_table(root / "t.parquet").column("id").to_pylist() == ["p1", "new", "p3"]
    for e in reversed([e for e in ds.editor.history("t.parquet")]):
        ds.editor.undo(e["edit"])
    assert pq.read_table(root / "t.parquet").equals(t)


def test_api_insert_delete(tree, tmp_path):
    with TestClient(create_app(_cfg(tree, tmp_path)), client=("127.0.0.1", 50000)) as c:
        rows = c.get("/api/datasets/t/corpus/lines", params={"path": "a/x.jsonl.zst", "count": 5}).json()["lines"]
        body = {"path": "a/x.jsonl.zst", "after": 1, "sha1": rows[0]["sha1"],
                "record": {"id": "api-1", "text": "from the API", "expect": "keep"}}
        assert c.post("/api/datasets/t/corpus/insert", json=body).status_code == 403  # no header
        r = c.post("/api/datasets/t/corpus/insert", json=body, headers=H)
        assert r.status_code == 200 and r.json()["line"] == 2
        stale = dict(body, after=0, sha1=rows[1]["sha1"], record={"id": "api-2", "text": "x"})  # not line 1's
        assert c.post("/api/datasets/t/corpus/insert", json=stale, headers=H).status_code == 409
        dup = dict(body, sha1="", record={"id": "api-1", "text": "again"})
        assert c.post("/api/datasets/t/corpus/insert", json=dup, headers=H).status_code == 400
        line2 = c.get("/api/datasets/t/corpus/lines", params={"path": "a/x.jsonl.zst", "start": 2,
                                                              "count": 1}).json()["lines"][0]
        r = c.post("/api/datasets/t/corpus/delete", headers=H,
                   json={"path": "a/x.jsonl.zst", "line": 2, "sha1": line2["sha1"]})
        assert r.status_code == 200 and r.json()["total_lines"] == 5
        edits = c.get("/api/datasets/t/corpus/edits", params={"path": "a/x.jsonl.zst"}).json()["edits"]
        assert [e["kind"] for e in edits] == ["insert", "delete"]
        assert c.post(f"/api/datasets/t/corpus/edits/{edits[1]['edit']}/undo", headers=H).status_code == 200


def test_api_accepts_null_member_like_the_page(tree, tmp_path):
    """The Corpus page sends "member": null for files that are not archives (regression: was a 422 error)."""
    with TestClient(create_app(_cfg(tree, tmp_path)), client=("127.0.0.1", 50000)) as c:
        line1 = c.get("/api/datasets/t/corpus/lines", params={"path": "b/z.jsonl", "count": 1}).json()["lines"][0]
        rec = {"id": "geo-1", "text": "Moscow traffic report.", "expect": "keep", "category": "geolocation",
               "has_keyword": True, "rule": None, "hard": None, "note": "location related sample1"}
        r = c.post("/api/datasets/t/corpus/insert", headers=H,
                   json={"path": "b/z.jsonl", "member": None, "after": 1, "sha1": line1["sha1"], "record": rec})
        assert r.status_code == 200, r.text
        assert json.loads(r.json()["raw"]) == rec  # null / true fields kept as they are
        new = c.get("/api/datasets/t/corpus/lines", params={"path": "b/z.jsonl", "start": 2, "count": 1}).json()
        r = c.post("/api/datasets/t/corpus/edit", headers=H, json={"path": "b/z.jsonl", "member": None, "line": 2,
                                                                  "text": "changed", "sha1": new["lines"][0]["sha1"]})
        assert r.status_code == 200, r.text
        r = c.post("/api/datasets/t/corpus/edit-batch", headers=H,
                   json={"path": "b/z.jsonl", "member": None, "changes": [{"line": 2, "text": "again", "sha1": None}]})
        assert r.status_code == 200, r.text
        r = c.post("/api/datasets/t/corpus/delete", headers=H, json={"path": "b/z.jsonl", "member": None, "line": 2,
                                                                    "sha1": None})
        assert r.status_code == 200, r.text

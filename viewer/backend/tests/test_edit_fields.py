"""Editing the other fields of a corpus line (expect, category, ...): set, add, remove, undo; the id stays."""
import datetime
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import build_tree
from nli_viewer.api import EDIT_HEADER, create_app
from nli_viewer.config import DatasetConfig, DatasetRegistry, ViewerConfig
from nli_viewer.edit import EditError

from test_edit import _content

H = {EDIT_HEADER: "1"}
REL = "a/x.jsonl.zst"


def _cfg(tree: Path, tmp: Path) -> ViewerConfig:
    return ViewerConfig(datasets=[DatasetConfig(name="t", corpus=str(tree / "corpus"), output=str(tree / "out"),
                                                editable=True)],
                        cache_dir=str(tmp / "cache"), edits_dir=str(tmp / "edits"),
                        frontend_dir=str(tmp / "nofrontend"), base_dir=str(tmp))


@pytest.fixture()
def tree(tmp_path):  # own copy: these tests change the corpus
    return build_tree(tmp_path / "tree")


@pytest.fixture()
def ds(tree, tmp_path):
    return DatasetRegistry(_cfg(tree, tmp_path)).get("t")


def test_set_add_remove_fields_and_undo(ds, tree):
    p = tree / "corpus" / REL
    before = _content(p)
    lines = before.split(b"\n")
    old = json.loads(lines[1])
    cur = ds.editor.read_line(REL, 2)
    out = ds.editor.edit_texts(REL, [{"line": 2, "sha1": cur["sha1"], "fields": {"expect": "filter", "category": "food"}}])
    assert out["changed"] == 1
    e = out["entries"][0]
    assert e["old"] == e["new"] == old["text"]  # the text did not change
    assert e["fields"] == {"expect": {"old": "keep", "new": "filter"},
                           "category": {"old": None, "new": "food", "added": True}}
    after = _content(p).split(b"\n")
    obj = json.loads(after[1])
    assert obj["expect"] == "filter" and obj["category"] == "food" and obj["id"] == old["id"] and obj["text"] == old["text"]
    assert list(obj)[: len(old)] == list(old)  # same key order; the new field at the end
    assert after[1] == json.dumps(obj).encode()  # the file's JSON style is kept
    assert [a for i, a in enumerate(after) if i != 1] == [b for i, b in enumerate(lines) if i != 1]
    # remove a field, then undo both edits: exactly the old bytes
    e2 = ds.editor.edit_texts(REL, [{"line": 2, "remove": ["category"], "text": "New text."}])["entries"][0]
    assert e2["fields"] == {"category": {"old": "food", "new": None, "removed": True}} and e2["new"] == "New text."
    assert "category" not in json.loads(_content(p).split(b"\n")[1])
    ds.editor.undo(e2["edit"])
    ds.editor.undo(e["edit"])
    assert _content(p) == before


def test_json_values_and_unchanged(ds):
    cur = ds.editor.read_line(REL, 1)
    out = ds.editor.edit_texts(REL, [{"line": 1, "sha1": cur["sha1"], "fields": {"score": 0.5, "tags": ["a", "b"], "ok": True}}])
    obj = json.loads(out["lines"][0]["raw"])
    assert obj["score"] == 0.5 and obj["tags"] == ["a", "b"] and obj["ok"] is True
    # the same values again: nothing written or logged
    again = ds.editor.edit_texts(REL, [{"line": 1, "fields": {"score": 0.5}}])
    assert again["changed"] == 0 and len(ds.editor.history(REL, 1)) == 1


def test_refused_changes(ds):
    with pytest.raises(EditError, match="id field"):
        ds.editor.edit_texts(REL, [{"line": 1, "fields": {"id": "other"}}])
    with pytest.raises(EditError, match="id field"):
        ds.editor.edit_texts(REL, [{"line": 1, "remove": ["id"]}])
    with pytest.raises(EditError, match="as the text"):
        ds.editor.edit_texts(REL, [{"line": 1, "fields": {"text": "x"}}])
    with pytest.raises(EditError, match="nothing to change"):
        ds.editor.edit_texts(REL, [{"line": 1}])
    with pytest.raises(EditError, match="needs a name"):
        ds.editor.edit_texts(REL, [{"line": 1, "fields": {" ": 1}}])
    assert ds.editor.history(REL) == []


def test_field_edit_does_not_mark_the_decision_stale(ds):
    """Changing expect / category keeps the filter's verdict valid: it is about the text."""
    rec = ds.record("a/x", line=1)
    ds.editor.edit_texts(REL, [{"line": 1, "sha1": rec["edit"]["sha1"], "fields": {"expect": "keep"}}])  # was "filter"
    rec = ds.record("a/x", line=1)
    assert rec["edit"]["edits"] == 1 and not rec["edit"]["edited_after_filter"]
    ds.editor.edit_text(REL, 1, "Today, " + rec["edit"]["text"])
    e = ds.record("a/x", line=1)["edit"]
    assert e["edited_after_filter"] and e["edits_after_filter"] == 1 and e["filtered_text"].startswith("Russia is")


def test_api_batch_with_fields(tree, tmp_path):
    with TestClient(create_app(_cfg(tree, tmp_path)), client=("127.0.0.1", 50000)) as c:
        line2 = {"path": REL, "start": 2, "count": 1}
        row = c.get("/api/datasets/t/corpus/lines", params=line2).json()["lines"][0]
        assert row["extra"]["expect"] == "keep"
        body = {"path": REL, "changes": [{"line": 2, "sha1": row["sha1"], "fields": {"expect": "filter"}}]}
        r = c.post("/api/datasets/t/corpus/edit-batch", json=body, headers=H)
        assert r.status_code == 200 and r.json()["changed"] == 1 and r.json()["entries"][0]["fields"]["expect"]["new"] == "filter"
        row = c.get("/api/datasets/t/corpus/lines", params=line2).json()["lines"][0]
        assert row["extra"]["expect"] == "filter" and row["edits"] == 1
        bad = {"path": REL, "changes": [{"line": 2, "fields": {"id": "x"}}]}
        assert c.post("/api/datasets/t/corpus/edit-batch", json=bad, headers=H).status_code == 400
        edits = c.get("/api/datasets/t/corpus/edits", params={"path": REL, "line": 2}).json()["edits"]
        r = c.post(f"/api/datasets/t/corpus/edits/{edits[-1]['edit']}/undo", headers=H)
        assert r.status_code == 200
        row = c.get("/api/datasets/t/corpus/lines", params=line2).json()["lines"][0]
        assert row["extra"]["expect"] == "keep"


def test_parquet_fields(tmp_path):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    root = tmp_path / "corpus"
    root.mkdir()
    t = pa.table({"id": ["p1", "p2", "p3"], "text": ["one", "two", "three"], "n": [0, 1, 2],
                  "day": [datetime.date(2024, 1, i) for i in (1, 2, 3)]})
    pq.write_table(t, root / "t.parquet")
    (tmp_path / "out").mkdir()
    cfg = ViewerConfig(datasets=[DatasetConfig(name="f", corpus=str(root), output=str(tmp_path / "out"), editable=True)],
                       cache_dir=str(tmp_path / "cache"), edits_dir=str(tmp_path / "edits"), base_dir=str(tmp_path))
    ds = DatasetRegistry(cfg).get("f")
    e = ds.editor.edit_texts("t.parquet", [{"line": 2, "fields": {"n": 7, "day": "2024-02-03"}, "text": "TWO"}])["entries"][0]
    got = pq.read_table(root / "t.parquet")
    assert got.schema == t.schema  # column types kept
    assert got.column("n").to_pylist() == [0, 7, 2] and got.column("text").to_pylist() == ["one", "TWO", "three"]
    assert got.column("day").to_pylist()[1] == datetime.date(2024, 2, 3)
    with pytest.raises(EditError, match="no column"):
        ds.editor.edit_texts("t.parquet", [{"line": 1, "fields": {"extra": 1}}])
    with pytest.raises(EditError, match="column"):
        ds.editor.edit_texts("t.parquet", [{"line": 1, "remove": ["n"]}])
    ds.editor.undo(e["edit"])
    assert pq.read_table(root / "t.parquet").column("n").to_pylist() == [0, 1, 2]

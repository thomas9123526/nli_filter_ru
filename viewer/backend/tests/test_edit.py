"""Editing corpus lines (edit.py + the /corpus API): .zst / .gz / plain files, safety checks, undo."""
import gzip
import json
import time
from pathlib import Path

import pytest
import zstandard
from fastapi.testclient import TestClient

from conftest import build_tree
from nli_viewer.api import EDIT_HEADER, create_app
from nli_viewer.config import DatasetConfig, DatasetRegistry, ViewerConfig
from nli_viewer.edit import EditConflict, EditError, line_sha1

H = {EDIT_HEADER: "1"}


def _cfg(tree: Path, tmp: Path, editable=True, **kw) -> ViewerConfig:
    return ViewerConfig(datasets=[DatasetConfig(name="t", corpus=str(tree / "corpus"), output=str(tree / "out"),
                                                editable=editable)],
                        cache_dir=str(tmp / "cache"), edits_dir=str(tmp / "edits"),
                        frontend_dir=str(tmp / "nofrontend"), base_dir=str(tmp), **kw)


@pytest.fixture()
def tree(tmp_path):  # own copy: these tests change the corpus
    return build_tree(tmp_path / "tree")


@pytest.fixture()
def ds(tree, tmp_path):
    return DatasetRegistry(_cfg(tree, tmp_path)).get("t")


def _content(p: Path) -> bytes:
    if p.name.endswith(".zst"):
        return zstandard.ZstdDecompressor().stream_reader(open(p, "rb")).read()
    if p.name.endswith(".gz"):
        return gzip.decompress(p.read_bytes())
    return p.read_bytes()


@pytest.mark.parametrize("rel,eol", [("a/x.jsonl.zst", b"\n"), ("a/y.jsonl.gz", b"\n"), ("b/z.jsonl", b"\r\n")])
def test_edit_rewrites_only_that_line(ds, tree, tmp_path, rel, eol):
    p = tree / "corpus" / rel
    before = _content(p).split(eol)
    cur = ds.editor.read_line(rel, 2)
    out = ds.editor.edit_text(rel, 2, "Bake the bread at 220 degrees. Ünïcödé ✓", cur["sha1"])
    assert out["changed"] and out["text"].startswith("Bake the bread") and out["id"] == cur["id"]
    after = _content(p).split(eol)
    assert len(after) == len(before)
    assert [a for i, a in enumerate(after) if i != 1] == [b for i, b in enumerate(before) if i != 1]
    obj = json.loads(after[1])
    assert obj["text"].endswith("Ünïcödé ✓") and obj["id"] == cur["id"] and obj["expect"] == "keep"
    # the file's JSON style (json.dumps defaults: ", " / ": ", non-ASCII escaped) is kept
    assert after[1] == json.dumps(obj).encode()
    # the original is backed up once, the edit is logged, the viewer reads the new line
    orig = tmp_path / "edits" / "t" / "originals" / rel
    assert _content(orig).split(eol)[1] == before[1]
    log = ds.editor.history(rel)
    assert len(log) == 1 and log[0]["old"] == "Preheat the oven to 200 degrees." and log[0]["line"] == 2
    assert ds.editor.read_line(rel, 2)["text"] == obj["text"]
    assert ds.corpus_lines(rel, 1, 5)["lines"][1]["edits"] == 1
    # a second edit keeps the first backup
    ds.editor.edit_text(rel, 2, "Third version.", ds.editor.read_line(rel, 2)["sha1"])
    assert _content(orig).split(eol)[1] == before[1]


def test_undo_restores_exact_bytes(ds, tree):
    rel = "a/x.jsonl.zst"
    before = _content(tree / "corpus" / rel)
    e1 = ds.editor.edit_text(rel, 3, "first change")["entry"]
    e2 = ds.editor.edit_text(rel, 3, "second change")["entry"]
    with pytest.raises(EditConflict):  # e1 is not the latest change of the line
        ds.editor.undo(e1["edit"])
    ds.editor.undo(e2["edit"])
    ds.editor.undo(e1["edit"])
    assert _content(tree / "corpus" / rel) == before
    assert [e.get("undo_of") for e in ds.editor.history(rel, 3)] == [None, None, e2["edit"], e1["edit"]]


def test_conflict_and_bad_input(ds):
    rel = "a/x.jsonl.zst"
    stale = ds.editor.read_line(rel, 1)["sha1"]
    ds.editor.edit_text(rel, 1, "changed elsewhere", stale)
    with pytest.raises(EditConflict):
        ds.editor.edit_text(rel, 1, "my change", stale)
    with pytest.raises(EditError, match="out of range"):
        ds.editor.edit_text(rel, 99, "x")
    with pytest.raises(EditError, match="zip"):
        ds.editor.edit_text("c/w.zip", 1, "x")
    assert ds.editor.edit_text(rel, 1, "changed elsewhere")["changed"] is False  # same text: file untouched


def test_record_after_edit_explains_the_filtered_text(ds):
    rel = "a/x.jsonl.zst"
    rec = ds.record("a/x", line=1)
    assert rec["edit"]["editable"] and not rec["edit"]["edited_after_filter"] and rec["edit"]["sha1"]
    ds.editor.edit_text(rel, 1, "Today, " + rec["edit"]["text"], rec["edit"]["sha1"])
    rec = ds.record("a/x", line=1)
    e = rec["edit"]
    assert e["edited_after_filter"] and e["edits_after_filter"] == 1 and e["text"].startswith("Today, ")
    assert e["filtered_text"].startswith("Russia is")
    # highlights still sit on the keyword: they are drawn on the text the run saw
    hit = next(m for m in rec["explanation"]["marks"] if m["kind"] == "hit")
    assert e["filtered_text"][hit["start"]:hit["end"]] == "Russia"


def test_not_editable_by_default(tree, tmp_path):
    ds = DatasetRegistry(_cfg(tree, tmp_path, editable=False)).get("t")
    assert ds.editor is None and "editing is off" in ds.edit_problem()
    rec = ds.record("a/x", line=1)
    assert rec["edit"]["editable"] is False and "editable" in rec["edit"]["problem"]


def test_api_edit_flow(tree, tmp_path):
    app = create_app(_cfg(tree, tmp_path))
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        st = c.get("/api/datasets/t/corpus/edit-status", params={"path": "a/x.jsonl.zst"}).json()
        assert st["editable"] and st["problem"] is None
        params = {"path": "a/x.jsonl.zst", "start": 1, "count": 5, "preview": 10}
        lines = c.get("/api/datasets/t/corpus/lines", params=params).json()
        # first look: the lines come at once, the decision links once the decisions table is built in the background
        assert lines["total_lines"] == 5 and lines["file_key"] == "a/x"
        for _ in range(100):
            if not lines["decisions_pending"]:
                break
            time.sleep(0.05)
            lines = c.get("/api/datasets/t/corpus/lines", params=params).json()
        assert not lines["decisions_pending"] and lines["lines"][0]["row"] == 1
        assert lines["lines"][0]["truncated"] and len(lines["lines"][0]["text"]) == 10
        sha = c.get("/api/datasets/t/corpus/lines", params={"path": "a/x.jsonl.zst", "start": 2,
                                                           "count": 1}).json()["lines"][0]["sha1"]
        body = {"path": "a/x.jsonl.zst", "line": 2, "text": "new text", "sha1": sha}
        assert c.post("/api/datasets/t/corpus/edit", json=body).status_code == 403          # no header
        r = c.post("/api/datasets/t/corpus/edit", json=body, headers=H)
        assert r.status_code == 200 and r.json()["text"] == "new text"
        assert c.post("/api/datasets/t/corpus/edit", json=body, headers=H).status_code == 409  # stale sha1
        # an archive needs the member: 400 without it
        assert c.post("/api/datasets/t/corpus/edit", json=dict(body, path="c/w.zip"), headers=H).status_code == 400
        edits = c.get("/api/datasets/t/corpus/edits", params={"path": "a/x.jsonl.zst"}).json()["edits"]
        assert len(edits) == 1
        r = c.post(f"/api/datasets/t/corpus/edits/{edits[0]['edit']}/undo", headers=H)
        assert r.status_code == 200 and r.json()["text"] == "Preheat the oven to 200 degrees."
        rec = c.get("/api/datasets/t/record", params={"file": "a/x", "line": 2}).json()
        assert rec["edit"]["editable"] and rec["edit"]["edits"] == 2
        assert c.get("/api/datasets/t/corpus/lines", params={"path": "a/x.jsonl.zst", "start": 9}).status_code == 404


def test_api_edit_refused_from_other_pcs(tree, tmp_path):
    with TestClient(create_app(_cfg(tree, tmp_path)), client=("192.168.1.20", 50000)) as c:
        st = c.get("/api/datasets/t/corpus/edit-status").json()
        assert not st["editable"] and "only allowed from the PC" in st["problem"]
        r = c.post("/api/datasets/t/corpus/edit", json={"path": "a/x.jsonl.zst", "line": 1, "text": "x"}, headers=H)
        assert r.status_code == 403
    # the viewer's own PC, opened by its network address (client address == the address it connected to)
    with TestClient(create_app(_cfg(tree, tmp_path)), base_url="http://192.168.1.5:8000",
                    client=("192.168.1.5", 50000)) as c:
        assert c.get("/api/datasets/t/corpus/edit-status").json()["editable"]
    with TestClient(create_app(_cfg(tree, tmp_path, edit_allow_remote=True)), client=("192.168.1.20", 1)) as c:
        r = c.post("/api/datasets/t/corpus/edit", json={"path": "a/x.jsonl.zst", "line": 1, "text": "x"}, headers=H)
        assert r.status_code == 200


def test_line_sha1_matches_record(ds):
    rec = ds.record("b/z", line=3)
    raw = ds.corpus_line("b/z.jsonl", 3)
    assert rec["edit"]["sha1"] == line_sha1(raw)


@pytest.mark.parametrize("rel,eol", [("a/x.jsonl.zst", b"\n"), ("b/z.jsonl", b"\r\n")])
def test_batch_edit_is_one_rewrite(ds, tree, rel, eol):
    p = tree / "corpus" / rel
    before = _content(p).split(eol)
    shas = {n: ds.editor.read_line(rel, n)["sha1"] for n in (1, 3, 5)}
    out = ds.editor.edit_texts(rel, [{"line": 5, "text": "five", "sha1": shas[5]},
                                     {"line": 1, "text": "one", "sha1": shas[1]},
                                     {"line": 3, "text": ds.editor.read_line(rel, 3)["text"], "sha1": shas[3]}])
    assert out["changed"] == 2 and [x["line"] for x in out["lines"]] == [1, 3, 5]  # line 3 unchanged
    after = _content(p).split(eol)
    assert json.loads(after[0])["text"] == "one" and json.loads(after[4])["text"] == "five"
    assert after[1:4] == before[1:4]
    log = ds.editor.history(rel)
    assert len(log) == 2 and log[0]["batch"] == log[1]["batch"]
    # all or nothing: one stale sha1 and no line is written
    with pytest.raises(EditConflict):
        ds.editor.edit_texts(rel, [{"line": 2, "text": "two", "sha1": ds.editor.read_line(rel, 2)["sha1"]},
                                   {"line": 1, "text": "uno", "sha1": shas[1]}])
    assert _content(p).split(eol) == after
    with pytest.raises(EditError, match="twice"):
        ds.editor.edit_texts(rel, [{"line": 2, "text": "a"}, {"line": 2, "text": "b"}])


def test_save_fills_the_cache(ds, tree):
    rel = "a/x.jsonl.zst"
    ds.editor.edit_text(rel, 2, "cached right away")
    fp = ds.corpus.fingerprint(rel)
    d = ds.cache.dir(ds.cache.key(ds.corpus.uri, rel, "", fp))
    meta = json.loads((d / "meta.json").read_text())
    assert meta["from_edit"] and meta["lines"] == 5
    assert (d / "data").read_bytes() == _content(tree / "corpus" / rel)
    assert ds.corpus_lines(rel, 2, 1)["lines"][0]["text"] == "cached right away"
    assert not (ds.cache.root / "_staging").exists() or not any((ds.cache.root / "_staging").iterdir())


def test_api_batch(tree, tmp_path):
    with TestClient(create_app(_cfg(tree, tmp_path)), client=("127.0.0.1", 50000)) as c:
        rows = c.get("/api/datasets/t/corpus/lines", params={"path": "a/y.jsonl.gz", "count": 3}).json()["lines"]
        body = {"path": "a/y.jsonl.gz", "changes": [{"line": r["line"], "text": f"t{r['line']}", "sha1": r["sha1"]}
                                                   for r in rows]}
        assert c.post("/api/datasets/t/corpus/edit-batch", json=body).status_code == 403  # no header
        r = c.post("/api/datasets/t/corpus/edit-batch", json=body, headers=H)
        assert r.status_code == 200 and r.json()["changed"] == 3
        assert [x["text"] for x in r.json()["lines"]] == ["t1", "t2", "t3"]
        assert c.post("/api/datasets/t/corpus/edit-batch", json=body, headers=H).status_code == 409


def test_corpus_only_dataset(tree, tmp_path):
    """No output yet: browse and edit the corpus before running nli_filter.py; results appear later."""
    import shutil
    later = tmp_path / "out_later"
    cfg = ViewerConfig(datasets=[DatasetConfig(name="none", corpus=str(tree / "corpus"), editable=True),
                                 DatasetConfig(name="later", corpus=str(tree / "corpus"), output=str(later),
                                               editable=True)],
                       cache_dir=str(tmp_path / "cache"), edits_dir=str(tmp_path / "edits"),
                       frontend_dir=str(tmp_path / "nofrontend"), base_dir=str(tmp_path))
    with TestClient(create_app(cfg), client=("127.0.0.1", 50000)) as c:
        assert [d["error"] for d in c.get("/api/datasets").json()["datasets"]] == [None, None]
        for name in ("none", "later"):
            ov = c.get(f"/api/datasets/{name}").json()
            assert ov["files"] == 0 and ov["output_ready"] is False
            lines = c.get(f"/api/datasets/{name}/corpus/lines", params={"path": "a/x.jsonl.zst", "count": 2}).json()
            assert lines["total_lines"] == 5 and lines["file_key"] is None and not lines["decisions_pending"]
        r = c.post("/api/datasets/later/corpus/edit", headers=H,
                   json={"path": "a/x.jsonl.zst", "line": 1, "text": "edited before filtering"})
        assert r.status_code == 200
        # nli_filter.py writes the output folder: the dataset picks it up (rescan forced here)
        shutil.copytree(tree / "out", later)
        c.post("/api/datasets/later/refresh")
        ov = c.get("/api/datasets/later").json()
        assert ov["files"] == 4 and ov["output_ready"] is True
        rec = c.get("/api/datasets/later/record", params={"file": "a/x", "line": 1}).json()
        assert rec["edit"]["text"] == "edited before filtering"


def test_config_without_output(tmp_path, tree):
    from nli_viewer.config import load_config
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"datasets": [{"name": "c", "corpus": str(tree / "corpus")}]}))
    assert load_config(str(p)).datasets[0].output == ""
    p.write_text(json.dumps({"datasets": [{"name": "c"}]}))
    with pytest.raises(ValueError, match="corpus"):
        load_config(str(p))

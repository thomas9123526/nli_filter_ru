"""Review tools: per-keyword stats, decisions across files (review order), golden set labels."""
import json

import pytest
from fastapi.testclient import TestClient

from nli_viewer.api import create_app
from nli_viewer.config import DatasetConfig, ViewerConfig
from nli_viewer.golden import GoldenStore
from nli_viewer.results import _keyword_flags


@pytest.fixture()
def client(tree, tmp_path):
    cfg = ViewerConfig(datasets=[DatasetConfig(name="t", corpus=str(tree / "corpus"), output=str(tree / "out"))],
                       cache_dir=str(tmp_path / "cache"), frontend_dir=str(tmp_path / "nofrontend"),
                       project_dir=str(tmp_path / "project"))
    (tmp_path / "project").mkdir()
    with TestClient(create_app(cfg), client=("127.0.0.1", 50000), headers={"X-Viewer-Edit": "1"}) as c:
        c.project = tmp_path / "project"
        yield c


def _wait_ready(client, path, params=None):
    # the first call starts building the per-file indexes in the background
    import time
    for _ in range(100):
        r = client.get(path, params=params or {}).json()
        if not r.get("pending"):
            return r
        time.sleep(0.1)
    raise AssertionError("indexes not ready")


def test_keyword_stats(client):
    r = _wait_ready(client, "/api/datasets/t/keywords")
    assert r["files"] == 4
    by = {k["keyword"].lower(): k for k in r["keywords"]}
    # per file: a-1 'Russia' filter, a-3 'Russian' rule (keep), a-4 'Russian' filter -> x4 files
    ru, rn = by["russia"], by["russian"]
    assert ru["hits"] == 4 and ru["lines"] == 4 and ru["filter"] == 4 and ru["about_hits"] == 4
    assert rn["hits"] == 8 and rn["lines"] == 8 and rn["filter"] == 4 and rn["keep"] == 4 and rn["rule_hits"] == 4
    assert rn["reasons"] == {"about_country": 4, "rules_incidental": 4}
    assert rn["labelled"] == 8 and rn["wrong"] == 0 and rn["only_lines"] == 8
    assert ru["in_list"] is False  # the test run's summary has no keyword list


def test_flags():
    base = {"hits": 30, "lines": 30, "keep": 29, "filter": 1, "rule_hits": 0, "wrong": 0, "level": "B",
            "audited": 0, "audit_keep": 0}
    assert [f["kind"] for f in _keyword_flags(base)] == ["noisy"]
    assert [f["kind"] for f in _keyword_flags(dict(base, hits=0))] == ["unused"]
    a = dict(base, level="A", keep=0, filter=30, audited=10, audit_keep=6)
    assert [f["kind"] for f in _keyword_flags(a)] == ["broad"]
    assert [f["kind"] for f in _keyword_flags(dict(a, audited=0, audit_keep=0))] == ["no_audit"]
    assert "wrong" in [f["kind"] for f in _keyword_flags(dict(base, keep=1, wrong=2))]


def test_lines_across_files_and_filters(client):
    r = _wait_ready(client, "/api/datasets/t/lines", {"kw": "RUSSIAN"})
    assert r["total"] == 8 and {x["file"] for x in r["rows"]} == {"a/x", "a/y", "b/z", "c/w"}
    r = client.get("/api/datasets/t/lines", params={"kw": "russian", "kw_state": "rule"}).json()
    assert r["total"] == 4 and all(x["reason"] == "rules_incidental" for x in r["rows"])
    r = client.get("/api/datasets/t/lines", params={"scored": True, "sort": "review", "limit": 3}).json()
    assert r["total"] == 8 and len(r["rows"]) == 3 and all(x["c1"] is not None for x in r["rows"])
    assert r["thresholds"] == {"check1": 0.8, "check2": 0.8}
    r = client.get("/api/datasets/t/lines", params={"labelled": False}).json()
    assert r["total"] == 0  # every test line has an expect label
    r = client.get("/api/datasets/t/lines", params={"single_kw": True}).json()
    assert r["total"] == 12


def test_golden_labels_go_to_their_own_file(client, tree):
    before = (tree / "corpus" / "b" / "z.jsonl").read_bytes()
    r = client.post("/api/datasets/t/golden", json={"file": "b/z", "row": 1, "expect": "filter", "note": "clear"}).json()
    assert r["count"] == 1 and r["entry"]["text"].startswith("Russia is the largest")
    path = client.project / "golden" / "t.jsonl"
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["expect"] == "filter" and rows[0]["source"] == {"dataset": "t", "file": "b/z", "line": 1, "id": "bz-1"}
    assert rows[0]["id"] == "bz-1" and rows[0]["category"] == "review"
    assert (tree / "corpus" / "b" / "z.jsonl").read_bytes() == before  # the corpus is untouched
    # relabel, then shown on the lines list, then removed
    client.post("/api/datasets/t/golden", json={"file": "b/z", "row": 1, "expect": "keep"})
    lines = _wait_ready(client, "/api/datasets/t/lines", {"q": "bz-1"})
    assert lines["rows"][0]["golden"] == "keep"
    g = client.get("/api/datasets/t/golden").json()
    assert g["count"] == 1 and g["labels"] == {"b/z#1": "keep"}
    assert client.post("/api/datasets/t/golden", json={"file": "b/z", "row": 1, "expect": ""}).json()["count"] == 0
    assert client.post("/api/datasets/t/golden", json={"file": "b/z", "row": 1, "expect": "maybe"}).status_code in (400, 422)
    # saving needs the edit header (like saving keyword / hypothesis files)
    assert client.post("/api/datasets/t/golden", json={"file": "b/z", "row": 1, "expect": "keep"},
                       headers={"X-Viewer-Edit": ""}).status_code == 403


def test_golden_store_names(tmp_path):
    g = GoldenStore(tmp_path)
    with pytest.raises(ValueError):
        g.path("../evil")
    g.set("d", "f", 3, "text", "keep")
    assert g.summary("d")["expect"] == {"keep": 1}


def test_lexicon_from_the_keyword_file_of_older_runs(tmp_path):
    from nli_viewer.results import _read_lexicon
    f = tmp_path / "kw.txt"
    f.write_text("# c\nRussia\nSiberia\tB\tRegion\ta region of Russia\ta brand | an idiom\tSiberia\s+\d+\nStalin\tA\n",
                 encoding="utf-8")
    m = _read_lexicon(str(f))
    assert m["siberia"] == {"keyword": "Siberia", "type": "region", "gloss": "a region of Russia",
                            "other": ["a brand", "an idiom"], "exclude": ["Siberia\s+\d+"]}
    assert m["stalin"] == {"keyword": "Stalin", "level": "A"} and "russia" not in m
    assert _read_lexicon(str(tmp_path / "missing.txt")) == {}

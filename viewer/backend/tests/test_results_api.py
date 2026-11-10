import json

import pytest
from fastapi.testclient import TestClient

from nli_viewer.api import create_app
from nli_viewer.config import DatasetConfig, ViewerConfig, load_config
from nli_viewer.explain import build_segments, explain
from nli_viewer.lines import LineCache
from nli_viewer.results import Dataset, stem
from nli_viewer.storage import open_storage


@pytest.fixture()
def ds(tree, tmp_path):
    return Dataset("t", open_storage(str(tree / "corpus")), open_storage(str(tree / "out")),
                   LineCache(str(tmp_path / "cache")))


def test_stem():
    assert stem("shard-00000.jsonl.zst") == "shard-00000"
    assert stem("a.json") == "a" and stem("x.zip") == "x" and stem(".zst") == ".zst"


def test_files_and_mapping(ds):
    files = {f.key: f for f in ds.files()}
    assert sorted(files) == ["a/x", "a/y", "b/z", "c/w"]
    assert files["a/x"].corpus_path == "a/x.jsonl.zst"
    assert files["a/x"].decisions_path == "a/x.decisions.jsonl.zst"
    assert files["c/w"].corpus_path == "c/w.zip"
    ov = ds.overview()
    assert ov["files"] == 4 and ov["totals"]["lines"] == 20
    assert ov["totals"]["decisions"] == {"filter": 8, "keep": 12}
    assert ov["evaluation"]["accuracy"] == 1.0
    assert ov["run"]["models"]["fast"]["model"] == "modernbert"


def test_query_filters_and_facets(ds):
    idx = ds.decisions("a/x")
    assert idx.query()["total"] == 5
    assert [r["line"] for r in idx.query(decision="filter")["rows"]] == [1, 4]
    assert idx.query(reason="rules_incidental,no_text")["total"] == 2
    assert idx.query(q="a/x-3".replace("/", ""))["total"] == 1
    assert idx.query(kw="Russian")["total"] == 2
    assert idx.query(min_score=0.95)["total"] == 2
    assert idx.query(judged=True)["total"] == 2
    assert idx.query(mismatch=True)["total"] == 0
    rows = idx.query(sort="score", desc=True, limit=2)["rows"]
    assert rows[0]["c1"] == 0.97
    f = idx.facets()
    assert f["decisions"] == {"filter": 2, "keep": 3} and f["labelled"] == 5 and f["keywords"]["Russia"] == 1


@pytest.mark.parametrize("key", ["a/x", "a/y", "b/z", "c/w"])
def test_record_matches_original(ds, key):
    for line in range(1, 6):
        rec = ds.record(key, line=line)
        assert rec["original"]["available"], rec["original"]
        assert rec["id_check"]["match"]
        assert rec["original"]["record"]["id"] == rec["decision"]["id"]
    rec = ds.record(key, line=4)
    ex = rec["explanation"]
    assert ex["verdict"]["decision"] == "filter"
    assert ex["check1"]["rows"][0]["hypothesis"] == "This text is about Russia."
    assert ex["check1"]["rows"][0]["judged"] is True
    text = "".join(s["text"] for s in ex["segments"])
    assert text == rec["original"]["record"]["text"]
    hit = next(m for m in ex["marks"] if m["kind"] == "hit")
    assert text[hit["start"]:hit["end"]] == rec["decision"]["hits"][0]["kw"]
    assert rec["nav"] == {"prev": 3, "next": 5, "prev_match": 3, "next_match": 5, "position": 4, "matches": 5}
    assert ds.record(key, row=4, decision="filter")["nav"]["prev_match"] == 1


def test_rewritten_output_is_reloaded(tree, tmp_path):
    import os, shutil, time
    work = tmp_path / "copy"
    shutil.copytree(tree, work)
    d = Dataset("t", open_storage(str(work / "corpus")), open_storage(str(work / "out")),
                LineCache(str(tmp_path / "cache")))
    assert d.decisions("b/z").query(decision="filter")["total"] == 2
    p = work / "out" / "b" / "z.decisions.jsonl"
    rows = [json.loads(x) for x in p.read_text().splitlines()]
    for r in rows:
        r["decision"] = "keep"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    os.utime(p, (time.time() + 10, time.time() + 10))
    d.refresh(force=True)
    assert d.decisions("b/z").query(decision="filter")["total"] == 0
    assert d.record("b/z", line=1)["decision"]["decision"] == "keep"


def test_record_errors(ds):
    with pytest.raises(KeyError):
        ds.record("nope", line=1)
    with pytest.raises(KeyError):
        ds.record("a/x", line=99)


def test_simulate(ds):
    same = ds.simulate(0.8, 0.8)
    assert same["flips"] == [] and same["simulated"]["counts"]["filter"] == 8
    assert same["current"]["metrics"]["accuracy"] == 1.0
    strict = ds.simulate(0.99, 0.8, sweep=[0.5, 0.99])
    assert strict["simulated"]["counts"]["to_keep"] == 8 and strict["simulated"]["counts"]["filter"] == 0
    assert strict["simulated"]["metrics"]["recall"] == 0.0
    assert [s["filter"] for s in strict["sweep"]] == [8, 0]
    lax2 = ds.simulate(0.8, 0.05)  # every check-2 score 0.1 >= 0.05: all rescued
    assert lax2["simulated"]["counts"]["filter"] == 0


def test_find_id(ds):
    m = ds.find_id("ay-2")
    assert len(m) == 1 and m[0]["file"] == "a/y" and m[0]["line"] == 2


def test_segments_excerpt():
    text = "x" * 5000 + "Russia" + "y" * 5000
    marks = [{"id": 0, "start": 5000, "end": 5006}]
    segs, ex = build_segments(text, marks, max_chars=1000, context=100)
    assert ex
    assert [s.get("gap") for s in segs if "gap" in s] == [4900, 4900]
    assert "".join(s.get("text", "") for s in segs) == "x" * 100 + "Russia" + "y" * 100
    segs, ex = build_segments(text, marks)
    assert not ex and "".join(s["text"] for s in segs) == text


def test_explain_without_text():
    info = explain(None, {"line": 1, "decision": "keep", "reason": "no_text"}, {})
    assert info["segments"] == [] and info["verdict"]["reason"] == "no_text"


@pytest.fixture()
def client(tree, tmp_path):
    cfg = ViewerConfig(datasets=[DatasetConfig(name="t", corpus=str(tree / "corpus"), output=str(tree / "out")),
                                 DatasetConfig(name="broken", corpus=str(tmp_path / "missing"), output=str(tree))],
                       cache_dir=str(tmp_path / "cache"), frontend_dir=str(tmp_path / "nofrontend"))
    with TestClient(create_app(cfg)) as c:
        yield c


def test_api(client):
    assert client.get("/api/health").json()["status"] == "ok"
    ds = client.get("/api/datasets").json()["datasets"]
    assert [d["name"] for d in ds] == ["t", "broken"] and ds[1]["error"]
    assert client.get("/api/datasets/t").json()["files"] == 4
    assert len(client.get("/api/datasets/t/files").json()["files"]) == 4
    r = client.get("/api/datasets/t/decisions", params={"file": "a/x", "decision": "filter"}).json()
    assert r["total"] == 2 and r["facets"]["total"] == 5 and r["file"]["key"] == "a/x"
    rec = client.get("/api/datasets/t/record", params={"file": "c/w", "line": 4}).json()
    assert rec["original"]["record"]["id"] == "cw-4"
    assert client.get("/api/datasets/t/find", params={"id": "bz-1"}).json()["matches"][0]["file"] == "b/z"
    raw = client.get("/api/datasets/t/raw", params={"path": "a/y.jsonl.gz", "line": 2, "count": 2}).json()
    assert raw["total_lines"] == 5 and json.loads(raw["lines"][0])["id"] == "ay-2"
    assert [e["name"] for e in client.get("/api/datasets/t/browse", params={"path": "a"}).json()["entries"]] == \
        ["x.jsonl.zst", "y.jsonl.gz"]
    assert client.get("/").json()["api"] == "/api/datasets"
    sim = client.get("/api/datasets/t/simulate", params={"check1": 0.99, "check2": 0.8, "sweep": True}).json()
    assert sim["simulated"]["counts"]["to_keep"] == 8 and len(sim["sweep"]) == 10
    assert client.get("/api/datasets/t/simulate", params={"check1": 2, "check2": 0.8}).status_code == 422


def test_api_errors(client):
    assert client.get("/api/datasets/nope").status_code == 404
    assert client.get("/api/datasets/t/record", params={"file": "nope", "line": 1}).status_code == 404
    assert client.get("/api/datasets/t/record", params={"file": "a/x"}).status_code == 400
    assert client.get("/api/datasets/t/raw", params={"path": "../../etc/passwd"}).status_code == 400
    assert client.get("/api/datasets/t/raw", params={"path": "a/y.jsonl.gz", "line": 99}).status_code == 404
    assert client.get("/api/datasets/t/browse", params={"path": "..\\.."}).status_code == 400
    assert client.get("/api/datasets/broken").status_code == 404


def test_api_over_ftp_sftp_and_s3(tree, ftp_server, sftp_server, s3_server, tmp_path):
    cfg = ViewerConfig(datasets=[
        DatasetConfig(name="ftp", corpus=ftp_server + "/corpus", output=ftp_server + "/out"),
        # corpus on SFTP, results on local disk: the mixed set-up of a real run
        DatasetConfig(name="sftp", corpus=sftp_server + "/corpus", output=str(tree / "out"),
                      corpus_options={"host_key_check": "off"}),
        # corpus and results both on SFTP
        DatasetConfig(name="sftp2", corpus=sftp_server + "/corpus", output=sftp_server + "/out",
                      corpus_options={"host_key_check": "off"}, output_options={"host_key_check": "off"}),
        # corpus on FTP, results on S3: storages can be mixed freely
        DatasetConfig(name="mixed", corpus=ftp_server + "/corpus", output=f"s3://nli/data/out?endpoint={s3_server}",
                      output_options={"access_key": "test", "secret_key": "test"}),
        DatasetConfig(name="s3", corpus=f"s3://nli/data/corpus?endpoint={s3_server}",
                      output=f"s3://nli/data/out?endpoint={s3_server}",
                      corpus_options={"access_key": "test", "secret_key": "test"},
                      output_options={"access_key": "test", "secret_key": "test"})],
        cache_dir=str(tmp_path / "cache"), frontend_dir=str(tmp_path / "x"))
    with TestClient(create_app(cfg)) as c:
        for name in ("ftp", "sftp", "sftp2", "mixed", "s3"):
            assert c.get(f"/api/datasets/{name}").json()["files"] == 4
            rec = c.get(f"/api/datasets/{name}/record", params={"file": "a/x", "line": 4}).json()
            assert rec["original"]["record"]["id"] == "ax-4" and rec["explanation"]["verdict"]["decision"] == "filter"
            rec = c.get(f"/api/datasets/{name}/record", params={"file": "c/w", "line": 2}).json()
            assert rec["original"]["record"]["id"] == "cw-2"


def test_config_file(tmp_path, monkeypatch, tree):
    monkeypatch.setenv("SECRET_PW", "pw123")
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({"datasets": [{"name": "t", "corpus": "corpus", "output": "ftp://u:${SECRET_PW}@h/x"}],
                             "cache_max_gb": 1}).replace('"datasets"', '// comment\n "datasets"', 1))
    cfg = load_config(str(p))
    assert cfg.datasets[0].output == "ftp://u:pw123@h/x" and cfg.cache_max_gb == 1
    p.write_text(json.dumps({"datasets": [{"name": "bad name", "corpus": "a", "output": "b"}]}))
    with pytest.raises(ValueError):
        load_config(str(p))

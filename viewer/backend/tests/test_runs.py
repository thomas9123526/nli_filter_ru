"""Run nli_filter.py from the viewer (started by nli_playground.py): default arguments, secrets, a real run."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from conftest import build_tree
from nli_viewer.api import EDIT_HEADER, create_app
from nli_viewer.config import DatasetConfig, ViewerConfig
from nli_viewer.runs import join_command, split_command

import nli_playground

H = {EDIT_HEADER: "1"}


def test_split_and_join():
    assert split_command('python nli_filter.py "D:\\my data\\corpus" --country Russia') == \
        ["D:\\my data\\corpus", "--country", "Russia"]
    assert join_command(["D:\\my data", "--x", "1"]) == '"D:\\my data" --x 1'


@pytest.fixture()
def app(tmp_path):
    tree = build_tree(tmp_path / "tree")
    summary = tree / "out" / "summary.json"
    run = json.loads(summary.read_text())
    run["command"] = "nli_filter.py old_corpus --judge-model none --max-windows 6 --output-dir somewhere"
    summary.write_text(json.dumps(run))
    pg = nli_playground.Playground(None, None, nli_playground.Jobs(tmp_path / "jobs"))  # --no-models
    server = nli_playground.serve(pg, "127.0.0.1", 0)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    cfg = ViewerConfig(datasets=[
        DatasetConfig(name="t", corpus=str(tree / "corpus"), output=str(tree / "out")),
        DatasetConfig(name="new", corpus=str(tree / "corpus"), output=str(tmp_path / "out_new")),
        DatasetConfig(name="sftp", corpus="sftp://reader@203.0.113.9:22/data/corpus", output=str(tmp_path / "o2"),
                      corpus_options={"password": "s3cret", "host_key_check": "off"})],
        cache_dir=str(tmp_path / "cache"), frontend_dir=str(tmp_path / "nofrontend"), base_dir=str(tmp_path),
        playground_url=url)
    with TestClient(create_app(cfg), client=("127.0.0.1", 50000)) as c:
        yield c, tree, tmp_path
    server.shutdown()
    server.server_close()


def test_default_args(app):
    c, tree, tmp_path = app
    d = c.get("/api/datasets/t/run/defaults").json()
    assert d["args"][:3] == [str(tree / "corpus"), "--output-dir", str(tree / "out")]
    assert d["args"][3:] == ["--judge-model", "none", "--max-windows", "6", "--overwrite"]  # last run + overwrite
    assert d["service"]["running"] and not d["problems"]
    d = c.get("/api/datasets/new/run/defaults").json()
    assert d["args"] == [str(tree / "corpus"), "--output-dir", str(tmp_path / "out_new")]  # nothing to take over
    d = c.get("/api/datasets/sftp/run/defaults").json()
    assert d["args"][0] == "sftp://reader:${NLI_CORPUS_PASSWORD}@203.0.113.9:22/data/corpus?host_key_check=off"
    assert "s3cret" not in json.dumps(d) and d["env_names"] == ["NLI_CORPUS_PASSWORD"]


def test_run_and_follow(app):
    c, tree, tmp_path = app
    out = tmp_path / "out_new"
    body = {"command": f'"{tree / "corpus"}" --output-dir "{out}" --keywords-report'}  # no models needed
    assert c.post("/api/datasets/new/run", json=body).status_code == 403  # no header
    job = c.post("/api/datasets/new/run", json=body, headers=H).json()
    assert job["state"] == "running" and job["args"][-1] == "--keywords-report"
    for _ in range(300):
        job = c.get(f"/api/runs/{job['id']}").json()
        if job["state"] != "running":
            break
        time.sleep(0.1)
    assert job["state"] == "done", job["output"][-20:]
    assert job["returncode"] == 0 and job["output"]
    assert (out / "keywords_report.json").is_file()
    assert c.get("/api/runs").json()["jobs"][0]["id"] == job["id"]


def test_one_run_at_a_time_and_stop(app):
    c, tree, tmp_path = app
    slow = {"args": [str(tree / "corpus"), "--output-dir", str(tmp_path / "o3"), "--keywords-report"]}
    first = c.post("/api/datasets/new/run", json=slow, headers=H).json()
    second = c.post("/api/datasets/new/run", json=slow, headers=H)
    if first["state"] == "running" and c.get(f"/api/runs/{first['id']}").json()["state"] == "running":
        assert second.status_code == 409 and "already going" in second.json()["detail"]
        stopped = c.post(f"/api/runs/{first['id']}/stop", headers=H).json()
        assert stopped["id"] == first["id"]


def test_refused_from_other_pc(app, tmp_path):
    c, tree, _ = app
    with TestClient(c.app, client=("192.168.1.20", 1)) as other:
        r = other.post("/api/datasets/new/run", json={"command": "x --output-dir y"}, headers=H)
        assert r.status_code == 403


def test_progress_files(tmp_path):
    import os
    tree = build_tree(tmp_path / "tree")
    prog = tree / "out" / "progress"
    prog.mkdir()
    now = time.time()
    common = {"version": 1, "host": "h200", "pid": 1, "files_needed": 10, "files_total": 12, "files_skipped": 2}
    (prog / "a.json").write_text(json.dumps({**common, "run_id": "a", "state": "running", "started_ts": now - 60,
                                             "updated_ts": now - 5, "bytes_total": 1000, "bytes_done": 400,
                                             "files_done": 4, "lines": 500, "lines_per_second": 20.0,
                                             "eta_seconds": 90, "current": {"input": "x.zst", "size": 100}}))
    (prog / "b.json").write_text(json.dumps({**common, "run_id": "b", "state": "running", "started_ts": now - 50,
                                             "updated_ts": now - 5, "bytes_total": 1000, "bytes_done": 600,
                                             "files_done": 6, "lines": 700, "lines_per_second": 30.0, "eta_seconds": 40}))
    dead = prog / "c.json"  # said "running", nothing for 10 minutes
    dead.write_text(json.dumps({**common, "run_id": "c", "state": "running", "started_ts": now - 900,
                                "updated_ts": now - 600, "bytes_total": 1000, "bytes_done": 10}))
    os.utime(dead, (now - 600, now - 600))
    slow = prog / "e.json"  # writes every 300 s, last write 200 s ago: still fine (warning only after 3 x 300 s)
    slow.write_text(json.dumps({**common, "run_id": "e", "state": "running", "started_ts": now - 1000,
                                "updated_ts": now - 200, "every_seconds": 300, "bytes_total": 10, "bytes_done": 1}))
    os.utime(slow, (now - 200, now - 200))
    old = prog / "d.json"  # finished two days ago: not shown
    old.write_text(json.dumps({**common, "run_id": "d", "state": "done", "started_ts": now - 200000,
                               "updated_ts": now - 172800}))
    os.utime(old, (now - 172800, now - 172800))
    cfg = ViewerConfig(datasets=[DatasetConfig(name="t", corpus=str(tree / "corpus"), output=str(tree / "out"))],
                       cache_dir=str(tmp_path / "cache"), frontend_dir=str(tmp_path / "nofrontend"),
                       base_dir=str(tmp_path))
    with TestClient(create_app(cfg)) as c:
        r = c.get("/api/datasets/t/progress").json()
        assert [x["run_id"] for x in r["runs"]] == ["b", "a", "c", "e"]
        assert [x["stale"] for x in r["runs"]] == [False, False, True, False]
        assert r["runs"][3]["stale_after"] == 900
        comb = r["combined"]
        assert comb["runs"] == 3 and comb["percent"] == round(100 * 1001 / 2010, 1) and comb["files_done"] == 10 and comb["eta_seconds"] == 90
        assert comb["lines_per_second"] == 50.0
        # the progress folder is not taken for results
        assert len(c.get("/api/datasets/t/files").json()["files"]) == 4
        # no progress folder at all
        (prog / "a.json").unlink(), (prog / "b.json").unlink(), dead.unlink(), old.unlink(), slow.unlink()
        prog.rmdir()
        assert c.get("/api/datasets/t/progress").json() == {"runs": [], "combined": None, "stale_seconds": 120.0}

"""Corpus page: "Label with a policy" (live labels for the page's lines) and "Save as a labelling run"."""
import json

import pytest
from fastapi.testclient import TestClient

from nli_viewer.api import EDIT_HEADER, create_app
from nli_viewer.config import DatasetConfig, ViewerConfig
from nli_viewer.playground import Playground


@pytest.fixture()
def project(tmp_path):
    proj = tmp_path / "proj"
    (proj / "policy").mkdir(parents=True)
    (proj / "policy" / "p1.json").write_text("{}", encoding="utf-8")
    corpus = proj / "corpus" / "sub"
    corpus.mkdir(parents=True)
    lines = [{"id": "a", "text": "Moscow and Kyiv."}, {"id": "b", "text": ""}, "not json",
             {"id": "c", "text": "x" * 20001}, {"id": "d", "text": "Russia is big."}]
    (corpus / "f.jsonl").write_text("".join((json.dumps(x) if isinstance(x, dict) else x) + "\n" for x in lines),
                                    encoding="utf-8")
    return proj


@pytest.fixture()
def client(tmp_path, project):
    cfg = ViewerConfig(datasets=[DatasetConfig(name="c", corpus=str(project / "corpus"))],
                       cache_dir=str(tmp_path / "cache"), edits_dir=str(tmp_path / "edits"),
                       frontend_dir=str(tmp_path / "nofrontend"), base_dir=str(tmp_path), project_dir=str(project),
                       playground_url="http://127.0.0.1:9")
    with TestClient(create_app(cfg), client=("127.0.0.1", 50000)) as c:
        yield c


def test_label_lines_reads_full_texts_and_skips(client, monkeypatch):
    calls = []

    def fake_label(self, body):
        calls.append(body)
        n = len(body["texts"])
        return {"rows": [{"line": i + 1, "action": "kept", "paragraphs": []} for i in range(n)],
                "clean": body["texts"], "rewrites": [[] for _ in range(n)], "seconds": 0.5,
                "pairs": {"fast": 3 * n, "judge": 0}, "models": {"fast": "m", "judge": None}, "policy": {"labels": {}}}
    monkeypatch.setattr(Playground, "label", fake_label)
    r = client.post("/api/datasets/c/label-lines",
                    json={"path": "sub/f.jsonl", "lines": [1, 2, 3, 4, 5], "policy": "policy/p1.json", "use_judge": False})
    assert r.status_code == 200, r.text
    d = r.json()
    assert [x["line"] for x in d["results"]] == [1, 5] and d["results"][0]["text"] == "Moscow and Kyiv."
    assert {s["line"] for s in d["skipped"]} == {2, 3, 4}
    assert calls[0]["policy"] == "policy/p1.json" and calls[0]["use_judge"] is False and calls[0]["all_labels"] is False
    assert d["pairs"]["fast"] == 6


def test_label_lines_validation(client):
    body = {"path": "sub/f.jsonl", "lines": [1], "policy": "policy/nope.json"}
    assert client.post("/api/datasets/c/label-lines", json=body).status_code == 400
    body["policy"] = "../secret.json"
    assert client.post("/api/datasets/c/label-lines", json=body).status_code == 400
    body.update(policy="policy/p1.json", lines=list(range(1, 102)))
    assert client.post("/api/datasets/c/label-lines", json=body).status_code == 400
    body["lines"] = [1]
    assert client.post("/api/datasets/c/label-lines", json=body).status_code in (502, 503)  # no model service


def test_label_run_start(client, project, monkeypatch):
    body = {"path": "sub/f.jsonl", "policy": "policy/p1.json", "output_dir": "out_label_c_f", "use_judge": False}
    assert client.post("/api/datasets/c/label-run", json=body).status_code == 403  # no edit header
    h = {EDIT_HEADER: "1"}
    for bad in ("../x", "a/b", ""):
        assert client.post("/api/datasets/c/label-run", json=dict(body, output_dir=bad), headers=h).status_code == 400
    (project / "dataset" / "taken").mkdir(parents=True)
    (project / "dataset" / "taken" / "x.txt").write_text("x", encoding="utf-8")
    assert client.post("/api/datasets/c/label-run", json=dict(body, output_dir="taken"), headers=h).status_code == 409
    started = []
    monkeypatch.setattr(Playground, "start_job", lambda self, args, env, label, script="nli_filter.py":
                        started.append((args, env, label, script)) or {"id": "j1", "state": "running"})
    r = client.post("/api/datasets/c/label-run", json=body, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["run"] == "out_label_c_f"
    args, env, label, script = started[0]
    assert script == "nli_label.py" and args[0] == "run"
    assert args[1].replace("\\", "/").endswith("corpus/sub/f.jsonl")
    assert args[args.index("--output-dir") + 1].replace("\\", "/").endswith("proj/dataset/out_label_c_f")
    assert "--write-clean" in args and args[args.index("--judge-model") + 1] == "none"
    assert args[args.index("--policy") + 1] == "policy/p1.json"

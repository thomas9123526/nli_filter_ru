"""Run page: apply another policy (redecide, started through the model service) and compare two runs."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nli_viewer.api import EDIT_HEADER, create_app
from nli_viewer.config import ViewerConfig
from nli_viewer.playground import Playground

H = {EDIT_HEADER: "1"}
REAL_POLICY = Path(__file__).resolve().parents[3] / "policy" / "russia_llm_policy_v2.json"


def para(s, e, action, reason="keep_label", labels=()):
    return {"span": [s, e], "action": action, "reason": reason, "labels": list(labels), "scores": {}, "tokens": 5}


def write_run(d: Path, rows, policy="policy/p.json", redecide=None):
    d.mkdir(parents=True)
    (d / "in.labels.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (d / "in.summary.json").write_text(json.dumps({"input": "x/in.jsonl", "name": "in", "stats": {"lines": len(rows)}}),
                                       encoding="utf-8")
    s = {"policy": {"path": policy, "labels": {}}, "files": [{"input": "x/in.jsonl", "name": "in"}], "stats": {}}
    if redecide:
        s["redecide"] = redecide
    (d / "summary.json").write_text(json.dumps(s), encoding="utf-8")


@pytest.fixture()
def project(tmp_path):
    proj = tmp_path / "proj"
    (proj / "policy").mkdir(parents=True)
    (proj / "policy" / "p.json").write_text(REAL_POLICY.read_text(encoding="utf-8"), encoding="utf-8")
    a = [{"line": 1, "id": "d1", "action": "kept", "paragraphs": [para(0, 10, "keep"), para(12, 30, "keep")]},
         {"line": 2, "id": "d2", "action": "untouched"},
         {"line": 3, "id": "d3", "action": "review", "paragraphs": [para(0, 40, "review", "review_label", ["history"])]}]
    b = [{"line": 1, "id": "d1", "action": "edited",
          "paragraphs": [para(0, 10, "keep"), para(12, 30, "remove", "remove_label", ["culture"])]},
         {"line": 2, "id": "d2", "action": "untouched"},
         {"line": 3, "id": "d3", "action": "review", "paragraphs": [para(0, 40, "review", "review_label", ["history"])]}]
    write_run(proj / "dataset" / "run_a", a)
    write_run(proj / "dataset" / "run_b", b, policy="policy/p2.json", redecide={"from": "run_a"})
    return proj


@pytest.fixture()
def client(tmp_path, project):
    cfg = ViewerConfig(datasets=[], cache_dir=str(tmp_path / "cache"), edits_dir=str(tmp_path / "edits"),
                       frontend_dir=str(tmp_path / "nofe"), base_dir=str(tmp_path), project_dir=str(project),
                       playground_url="http://127.0.0.1:9")
    with TestClient(create_app(cfg), client=("127.0.0.1", 50000)) as c:
        yield c


def test_compare_totals_moves_and_items(client):
    r = client.get("/api/labels/compare", params={"a": "run_a", "b": "run_b"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["files"] == 1 and d["lines"] == 3 and d["changed_lines"] == 1 and d["notes"] == []
    assert d["paragraph_moves"] == {"keep>remove": 1} and d["doc_moves"] == {"kept>edited": 1}
    assert d["totals"]["a"]["paragraphs"] == {"keep": 2, "review": 1}
    assert d["totals"]["b"]["paragraphs"] == {"keep": 1, "remove": 1, "review": 1}
    assert d["policy"] == {"a": "policy/p.json", "b": "policy/p2.json"} and d["redecide"]["b"] == {"from": "run_a"}
    it = d["items"][0]
    assert it["line"] == 1 and it["doc"] == {"a": "kept", "b": "edited"}
    assert it["paragraphs"] == [{"span": [12, 30], "move": "keep>remove",
                                 "a": {"action": "keep", "reason": "keep_label", "labels": []},
                                 "b": {"action": "remove", "reason": "remove_label", "labels": ["culture"]}}]
    # filters
    assert client.get("/api/labels/compare", params={"a": "run_a", "b": "run_b", "change": "keep>review"}).json()["total"] == 0
    assert client.get("/api/labels/compare", params={"a": "run_a", "b": "run_b", "change": "doc:kept>edited"}).json()["total"] == 1
    assert client.get("/api/labels/compare", params={"a": "run_a", "b": "nope"}).status_code == 404


def test_redecide_starts_a_job(client, project, monkeypatch):
    seen = {}

    def fake(self, args, env, label, script="nli_filter.py"):
        seen.update(args=args, script=script, label=label)
        return {"id": "j1", "state": "running"}
    monkeypatch.setattr(Playground, "start_job", fake)
    r = client.post("/api/labels/run_a/redecide", json={"policy": "policy/p.json", "output_dir": "run_a_rd1",
                                                        "write_clean": True, "review_as": "remove"}, headers=H)
    assert r.status_code == 200, r.text
    assert seen["script"] == "nli_label.py" and seen["args"][0] == "redecide"
    assert seen["args"][1].endswith("run_a") and "--write-clean" in seen["args"]
    assert seen["args"][seen["args"].index("--policy") + 1] == "policy/p.json"
    assert seen["args"][seen["args"].index("--review-as") + 1] == "remove"
    assert Path(seen["args"][seen["args"].index("--output-dir") + 1]) == project / "dataset" / "run_a_rd1"
    # the editor's unsaved policy: written to dataset/.policy_drafts/, checked first
    data = json.loads((project / "policy" / "p.json").read_text(encoding="utf-8"))
    data["no_subject"] = "review"
    r = client.post("/api/labels/run_a/redecide", json={"policy_data": data, "output_dir": "run_a_rd2"}, headers=H)
    assert r.status_code == 200 and r.json()["policy"] == "dataset/.policy_drafts/run_a_rd2.json"
    assert json.loads((project / "dataset" / ".policy_drafts" / "run_a_rd2.json").read_text(encoding="utf-8"))["no_subject"] == "review"
    data["no_subject"] = "drop"
    assert client.post("/api/labels/run_a/redecide", json={"policy_data": data, "output_dir": "run_a_rd3"}, headers=H).status_code == 400


def test_redecide_refusals(client):
    body = {"policy": "policy/p.json", "output_dir": "run_b"}
    assert client.post("/api/labels/run_a/redecide", json=body, headers=H).status_code == 409   # exists
    assert client.post("/api/labels/run_a/redecide", json={**body, "output_dir": "../x"}, headers=H).status_code == 400
    assert client.post("/api/labels/run_a/redecide", json={**body, "policy": "../p.json", "output_dir": "ok1"}, headers=H).status_code == 400
    assert client.post("/api/labels/nope/redecide", json={**body, "output_dir": "ok2"}, headers=H).status_code == 404
    assert client.post("/api/labels/run_a/redecide", json={**body, "output_dir": "ok3"}).status_code == 403

"""Policy editor (/label/policy): read a policy as JSON, check it with nli_label.py's rules, save with a backup."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nli_viewer.api import EDIT_HEADER, create_app
from nli_viewer.config import ViewerConfig

H = {EDIT_HEADER: "1"}
REAL_POLICY = Path(__file__).resolve().parents[3] / "policy" / "russia_llm_policy_v2.json"


@pytest.fixture()
def project(tmp_path):
    proj = tmp_path / "proj"
    (proj / "policy").mkdir(parents=True)
    (proj / "keywords").mkdir()
    data = json.loads(REAL_POLICY.read_text(encoding="utf-8"))
    for f in ([data["keywords_file"]] if isinstance(data["keywords_file"], str) else data["keywords_file"]):
        (proj / f).write_text("Russia\n", encoding="utf-8")
    for k in ("place_names_file", "place_name_exceptions_file"):
        if data.get(k):
            (proj / data[k]).write_text("", encoding="utf-8")
    (proj / "policy" / "p.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return proj


@pytest.fixture()
def client(tmp_path, project):
    cfg = ViewerConfig(datasets=[], cache_dir=str(tmp_path / "cache"), edits_dir=str(tmp_path / "edits"),
                       frontend_dir=str(tmp_path / "nofe"), base_dir=str(tmp_path), project_dir=str(project),
                       playground_url="http://127.0.0.1:9")
    with TestClient(create_app(cfg), client=("127.0.0.1", 50000)) as c:
        yield c


def raw(c, path="policy/p.json"):
    r = c.get("/api/labels/policy/raw", params={"path": path})
    assert r.status_code == 200, r.text
    return r.json()


def test_raw_and_check(client):
    d = raw(client)
    assert d["sha"] and d["data"]["labels"]["reports_or_debunks"]["softens"] == ["hostility_*", "violence_call"]
    assert d["check"]["ok"] and d["check"]["errors"] == [] and d["check"]["warnings"] == []
    bad = json.loads(json.dumps(d["data"]))
    bad["no_subject"] = "drop"
    bad["labels"]["war"]["threshold"] = 1.5
    bad["run_if"]["2"].append("nope")
    bad["keywords_file"] = ["keywords/missing.txt"]
    chk = client.post("/api/labels/policy/check", json={"data": bad}).json()
    assert not chk["ok"]
    text = " | ".join(chk["errors"])
    assert "no_subject must be" in text and "label war: threshold" in text and "unknown label 'nope'" in text
    assert chk["warnings"] == ["keywords_file keywords/missing.txt does not exist"]


def test_save_backup_and_conflict(client, project):
    d = raw(client)
    data = d["data"]
    del data["labels"]["reports_or_debunks"]
    data["no_subject"] = "review"
    r = client.post("/api/labels/policy/save", json={"path": "policy/p.json", "data": data, "base_sha": d["sha"]}, headers=H)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["backup"].startswith("policy/.backup/p.") and (project / res["backup"]).is_file()
    saved = (project / "policy" / "p.json").read_text(encoding="utf-8")
    assert "\r\n" not in saved and "reports_or_debunks" not in saved and '"no_subject": "review"' in saved
    assert "рашисты" in saved  # written as UTF-8, not \\u escapes
    # the old sha is stale now: refused
    r = client.post("/api/labels/policy/save", json={"path": "policy/p.json", "data": data, "base_sha": d["sha"]}, headers=H)
    assert r.status_code == 409


def test_save_refuses_invalid_and_needs_the_header(client):
    d = raw(client)
    bad = d["data"]
    bad["labels"]["war"]["decision"] = "maybe"
    assert client.post("/api/labels/policy/save", json={"path": "policy/p.json", "data": bad}, headers=H).status_code == 400
    assert client.post("/api/labels/policy/save", json={"path": "policy/p.json", "data": raw(client)["data"]}).status_code == 403


def test_save_as_new_file(client, project):
    d = raw(client)
    r = client.post("/api/labels/policy/save", json={"path": "policy/p.json", "data": d["data"], "save_as": "policy/p_v3.json"}, headers=H)
    assert r.status_code == 200 and r.json()["path"] == "policy/p_v3.json" and r.json()["backup"] is None
    assert (project / "policy" / "p_v3.json").is_file()
    again = client.post("/api/labels/policy/save", json={"path": "policy/p.json", "data": d["data"], "save_as": "policy/p_v3.json"}, headers=H)
    assert again.status_code == 409
    assert client.post("/api/labels/policy/save", json={"path": "policy/p.json", "data": d["data"], "save_as": "../x.json"}, headers=H).status_code == 400
    assert client.get("/api/labels/policy/raw", params={"path": "../secret.json"}).status_code == 400

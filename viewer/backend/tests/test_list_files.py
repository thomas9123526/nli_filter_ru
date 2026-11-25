"""/label/files: keyword lists and place-name tables of a labelling policy, checked and saved with a backup."""
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nli_viewer.api import EDIT_HEADER, create_app
from nli_viewer.config import ViewerConfig

H = {EDIT_HEADER: "1"}
REAL = Path(__file__).resolve().parents[3]


@pytest.fixture()
def project(tmp_path):
    proj = tmp_path / "proj"
    (proj / "keywords").mkdir(parents=True)
    (proj / "policy").mkdir()
    for f in ("keywords/russia_v3.txt", "keywords/ukraine.txt", "policy/place_names_ru.csv",
              "policy/place_name_exceptions_ru.txt", "policy/russia_llm_policy_v2.json"):
        shutil.copy(REAL / f, proj / f)
    (proj / "keywords" / "crlf.txt").write_bytes(b"# a list\r\nRussia\r\n")
    return proj


@pytest.fixture()
def client(tmp_path, project):
    cfg = ViewerConfig(datasets=[], cache_dir=str(tmp_path / "cache"), edits_dir=str(tmp_path / "edits"),
                       frontend_dir=str(tmp_path / "nofe"), base_dir=str(tmp_path), project_dir=str(project),
                       playground_url="http://127.0.0.1:9")
    with TestClient(create_app(cfg), client=("127.0.0.1", 50000)) as c:
        yield c


def test_list_marks_the_policys_files(client):
    d = client.get("/api/labels/files", params={"policy": "policy/russia_llm_policy_v2.json"}).json()
    used = {f["path"]: f["used_by_policy"] for f in d["files"]}
    assert used["keywords/russia_v3.txt"] == "keywords_file" and used["keywords/ukraine.txt"] == "keywords_file"
    assert used["policy/place_names_ru.csv"] == "place_names_file"
    assert used["policy/place_name_exceptions_ru.txt"] == "place_name_exceptions_file"
    assert used["keywords/crlf.txt"] is None
    assert {f["path"]: f["kind"] for f in d["files"]}["policy/place_names_ru.csv"] == "place_names"


def test_raw_check_and_preview(client):
    r = client.get("/api/labels/files/raw", params={"path": "keywords/ukraine.txt"}).json()
    assert r["kind"] == "keywords" and r["check"]["ok"] and r["check"]["entries"] > 40
    bad = client.post("/api/labels/files/check", json={"path": "keywords/ukraine.txt", "text": "Ukraine\tZ\tcountry\n"}).json()
    assert not bad["ok"] and bad["errors"]
    dup = client.post("/api/labels/files/check", json={"path": "keywords/ukraine.txt", "text": "Kyiv\nkyiv\n"}).json()
    assert dup["ok"] and "listed twice" in dup["warnings"][0]
    t = client.get("/api/labels/files/raw", params={"path": "policy/place_names_ru.csv"}).json()["text"]
    p = client.post("/api/labels/files/check", json={"path": "policy/place_names_ru.csv", "text": t + "Uzhhorod,Uzhgorod,,\n",
                                                     "sample": "From Kyiv to Uzhhorod. The Kyiv Independent wrote.",
                                                     "policy": "policy/russia_llm_policy_v2.json"}).json()
    assert p["ok"] and p["preview"]["text"] == "From Kiev to Uzhgorod. The Kyiv Independent wrote."  # exception kept
    ex = client.post("/api/labels/files/check", json={"path": "policy/place_name_exceptions_ru.txt", "text": "kyiv(\n"}).json()
    assert not ex["ok"] and "line 1" in ex["errors"][0]


def test_save_backup_conflict_and_line_endings(client, project):
    r = client.get("/api/labels/files/raw", params={"path": "keywords/crlf.txt"}).json()
    assert r["text"] == "# a list\nRussia\n" and r["crlf"]
    s = client.post("/api/labels/files/save", json={"path": "keywords/crlf.txt", "text": "# a list\nRussia\nMoscow",
                                                    "base_sha": r["sha"]}, headers=H)
    assert s.status_code == 200, s.text
    assert (project / "keywords" / "crlf.txt").read_bytes() == b"# a list\r\nRussia\r\nMoscow\r\n"  # CRLF kept
    assert (project / s.json()["backup"]).read_bytes() == b"# a list\r\nRussia\r\n"
    stale = client.post("/api/labels/files/save", json={"path": "keywords/crlf.txt", "text": "x\n", "base_sha": r["sha"]}, headers=H)
    assert stale.status_code == 409
    assert client.post("/api/labels/files/save", json={"path": "keywords/crlf.txt", "text": "Russia\tQ\n"}, headers=H).status_code == 400
    assert client.post("/api/labels/files/save", json={"path": "keywords/crlf.txt", "text": "Russia\n"}).status_code == 403
    assert client.get("/api/labels/files/raw", params={"path": "../secret.txt"}).status_code == 400
    assert client.get("/api/labels/files/raw", params={"path": "policy/russia_llm_policy_v2.json"}).status_code == 400

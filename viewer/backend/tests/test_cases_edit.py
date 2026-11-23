"""Try page "Edit cases": save an edited case set (validation, conflict, backup, corpus rebuild)."""
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nli_viewer.api import EDIT_HEADER, create_app
from nli_viewer.config import ViewerConfig

H = {EDIT_HEADER: "1"}
REAL_TOOLS = Path(__file__).resolve().parents[3] / "tools"


def case(cid, text="Moscow is big.", exp="keep", **t):
    return {"id": cid, "group": "G", "title": cid, "what": "w",
            "texts": [{"text": text, "from": "x", "labels_yes": [], "expected_action": exp, "note": "", **t}]}


@pytest.fixture()
def project(tmp_path):
    proj = tmp_path / "proj"
    (proj / "labels").mkdir(parents=True)
    (proj / "tools").mkdir()
    shutil.copy(REAL_TOOLS / "build_cases_corpus.py", proj / "tools" / "build_cases_corpus.py")
    (proj / "labels" / "cases_v1.json").write_text(json.dumps({"version": 1, "cases": [case("old:1")]}), encoding="utf-8")
    (proj / "labels" / "cases_v2.json").write_text(json.dumps({"version": 1, "cases": [case("a:1")]}), encoding="utf-8")
    (proj / "labels" / "russia_llm_cases_v1.json").write_text(json.dumps(
        {"version": 1, "policy": "policy/p.json", "corpus": "test_corpus_cases_ru", "cases": [case("r:1")]}),
        encoding="utf-8")
    return proj


@pytest.fixture()
def client(tmp_path, project):
    cfg = ViewerConfig(datasets=[], cache_dir=str(tmp_path / "cache"), edits_dir=str(tmp_path / "edits"),
                       frontend_dir=str(tmp_path / "nofe"), base_dir=str(tmp_path), project_dir=str(project),
                       playground_url="http://127.0.0.1:9")
    with TestClient(create_app(cfg), client=("127.0.0.1", 50000)) as c:
        yield c


def load(c, f):
    return c.get("/api/labels/cases", params={"file": f}).json()


def test_save_backup_and_corpus(client, project):
    pytest.importorskip("zstandard")
    d = load(client, "labels/russia_llm_cases_v1.json")
    assert d["sha"]
    d["cases"].append(case("r:2", "Ukraine has joined NATO.", "review", acceptable=["keep"]))
    d["cases"][0]["texts"][0]["note"] = "edited"
    r = client.post("/api/labels/cases/save", json={"file": d["file"], "data": d, "base_sha": d["sha"]}, headers=H)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["cases"] == 2 and res["texts"] == 2 and res["corpus"] == {"path": "dataset/test_corpus_cases_ru", "files": 2, "lines": 2}
    saved = json.loads((project / "labels" / "russia_llm_cases_v1.json").read_text(encoding="utf-8"))
    assert saved["cases"][0]["texts"][0]["note"] == "edited" and "file" not in saved and "sha" not in saved
    assert saved["corpus"] == "test_corpus_cases_ru" and saved["edited"]
    assert (project / res["backup"]).is_file()
    assert len(list((project / "dataset" / "test_corpus_cases_ru").rglob("*.jsonl.zst"))) == 2
    # the old sha is stale now: a second save from the old page is refused
    r = client.post("/api/labels/cases/save", json={"file": d["file"], "data": d, "base_sha": d["sha"]}, headers=H)
    assert r.status_code == 409


def test_corpus_rebuilt_only_for_the_newest_cases_vN(client, project):
    pytest.importorskip("zstandard")
    old = load(client, "labels/cases_v1.json")
    r = client.post("/api/labels/cases/save", json={"file": old["file"], "data": old, "base_sha": old["sha"]}, headers=H)
    assert r.status_code == 200 and r.json()["corpus"] is None
    new = load(client, "labels/cases_v2.json")
    r = client.post("/api/labels/cases/save", json={"file": new["file"], "data": new, "base_sha": new["sha"]}, headers=H)
    assert r.json()["corpus"]["path"] == "dataset/test_corpus_cases"


@pytest.mark.parametrize("bad, msg", [
    ({"cases": []}, "non-empty"),
    ({"cases": [case("x"), case("x")]}, "used twice"),
    ({"cases": [case("x", text="  ")]}, "text is empty"),
    ({"cases": [case("x", exp="delete")]}, "expected_action"),
    ({"cases": [case("x", acceptable=["maybe"])]}, "acceptable"),
    ({"cases": [dict(case("x"), texts=[])]}, "at least one text"),
    ({"cases": [case("x")], "corpus": "../policy"}, "corpus"),
])
def test_save_validation(client, bad, msg):
    r = client.post("/api/labels/cases/save", json={"file": "labels/cases_v2.json", "data": bad}, headers=H)
    assert r.status_code == 400 and msg in r.json()["detail"]


def test_save_guarded_and_known_files_only(client):
    d = load(client, "labels/cases_v2.json")
    assert client.post("/api/labels/cases/save", json={"file": d["file"], "data": d}).status_code == 403
    assert client.post("/api/labels/cases/save", json={"file": "labels/x.json", "data": d}, headers=H).status_code == 404


def test_topics_list_and_add(client, project):
    assert client.get("/api/labels/topics").json()["topics"] == []          # no file yet: empty list
    (project / "labels" / "topic_labels.json").write_text(json.dumps({"about": "x", "topics": ["History", "Politics"]}),
                                                          encoding="utf-8")
    assert client.get("/api/labels/topics").json()["topics"] == ["History", "Politics"]
    assert client.post("/api/labels/topics", json={"topic": "Sport"}).status_code == 403   # no edit header
    r = client.post("/api/labels/topics", json={"topic": "  Sports &  Fitness "}, headers=H).json()
    assert r["added"] == "Sports & Fitness" and r["topics"][-1] == "Sports & Fitness"
    assert client.post("/api/labels/topics", json={"topic": "history"}, headers=H).json()["added"] is None  # known
    assert client.post("/api/labels/topics", json={"topic": 'bad"one'}, headers=H).status_code == 400
    saved = json.loads((project / "labels" / "topic_labels.json").read_text(encoding="utf-8"))
    assert saved["topics"] == ["History", "Politics", "Sports & Fitness"] and saved["about"] == "x"


def test_case_topic_saved_and_in_the_corpus(client, project):
    pytest.importorskip("zstandard")
    import zstandard
    d = load(client, "labels/russia_llm_cases_v1.json")
    d["cases"][0]["texts"][0]["topic"] = "History"
    r = client.post("/api/labels/cases/save", json={"file": d["file"], "data": d, "base_sha": d["sha"]}, headers=H)
    assert r.status_code == 200, r.text
    f = next((project / "dataset" / "test_corpus_cases_ru").rglob("*.jsonl.zst"))
    line = json.loads(zstandard.ZstdDecompressor().decompressobj().decompress(f.read_bytes()).decode().splitlines()[0])
    assert line["topic"] == "History"
    d = load(client, "labels/russia_llm_cases_v1.json")
    d["cases"][0]["texts"][0]["topic"] = 5
    r = client.post("/api/labels/cases/save", json={"file": d["file"], "data": d, "base_sha": d["sha"]}, headers=H)
    assert r.status_code == 400 and "topic" in r.json()["detail"]

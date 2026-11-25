"""/label/docs: the documents test set (labels/russia_llm_docs_v1.json) edited in the viewer: checked like
tools/build_russia_llm_docs.py, saved with a backup, its corpus rebuilt."""
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nli_viewer.api import EDIT_HEADER, create_app
from nli_viewer.config import ViewerConfig

H = {EDIT_HEADER: "1"}
REAL = Path(__file__).resolve().parents[3]
F = "labels/russia_llm_docs_v1.json"
LONG = ("Moscow announced a new railway line to the Pacific coast this week. The project will take ten years, cost "
        "several billion roubles and connect three regions that have no direct link today, the ministry said.")


@pytest.fixture()
def project(tmp_path):
    proj = tmp_path / "proj"
    for d in ("labels", "policy", "tools", "keywords"):
        (proj / d).mkdir(parents=True)
    for f in (F, "policy/russia_llm_policy_v2.json", "tools/build_russia_llm_docs.py", "keywords/russia_v3.txt",
              "keywords/ukraine.txt", "policy/place_names_ru.csv", "policy/place_name_exceptions_ru.txt"):
        shutil.copy(REAL / f, proj / f)
    return proj


@pytest.fixture()
def client(tmp_path, project, monkeypatch):
    cfg = ViewerConfig(datasets=[], cache_dir=str(tmp_path / "cache"), edits_dir=str(tmp_path / "edits"),
                       frontend_dir=str(tmp_path / "nofe"), base_dir=str(tmp_path), project_dir=str(project),
                       playground_url="http://127.0.0.1:9")
    with TestClient(create_app(cfg), client=("127.0.0.1", 50000)) as c:
        yield c


def test_load_add_document_save_and_rebuild(client, project):
    pytest.importorskip("zstandard")
    d = client.get("/api/labels/docs", params={"file": F}).json()
    assert d["sha"] and d["min_chars"] == 200 and len(d["docs"]) >= 10
    n = len(d["docs"])
    d["docs"].append({"id": "doc99_railway", "group": "facts_and_false_claims", "file": "railway", "title": "Railway",
                      "paragraphs": [{"text": LONG, "expected_action": "keep", "note": "a fact"},
                                     {"text": LONG.replace("Moscow", "Kyiv"), "expected_action": "review", "acceptable": ["keep"], "note": "x"}]})
    chk = client.post("/api/labels/docs/check", json={"file": F, "data": d}).json()
    assert chk["ok"], chk["errors"]
    assert chk["doc_actions"][-1] == "review"
    r = client.post("/api/labels/docs/save", json={"file": F, "data": d, "base_sha": d["sha"]}, headers=H)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["docs"] == n + 1 and res["corpus"] == "dataset/test_corpus_docs_ru"
    assert (project / res["backup"]).is_file()
    saved = json.loads((project / F).read_text(encoding="utf-8"))
    new = saved["docs"][-1]
    assert new["text"] == LONG + "\n\n" + LONG.replace("Moscow", "Kyiv") and new["expected_doc_action"] == "review"
    assert "sha" not in saved and "file" not in saved and "min_chars" not in saved and saved["edited"]
    assert (project / "dataset" / "test_corpus_docs_ru" / "facts_and_false_claims" / "railway.jsonl.zst").is_file()
    # the old sha is stale now
    assert client.post("/api/labels/docs/save", json={"file": F, "data": d, "base_sha": d["sha"]}, headers=H).status_code == 409


def test_problems_refuse_the_save(client):
    d = client.get("/api/labels/docs", params={"file": F}).json()
    bad = json.loads(json.dumps(d))
    bad["docs"][0]["paragraphs"][0]["expected_action"] = "maybe"
    bad["docs"][1]["id"] = bad["docs"][0]["id"]
    chk = client.post("/api/labels/docs/check", json={"file": F, "data": bad}).json()
    text = " | ".join(chk["errors"])
    assert not chk["ok"] and "expected must be one of" in text and "id listed twice" in text
    short = json.loads(json.dumps(d))
    short["docs"][0]["paragraphs"].insert(1, {"text": "Moscow is big.", "expected_action": "keep", "note": ""})
    chk = client.post("/api/labels/docs/check", json={"file": F, "data": short}).json()
    assert not chk["ok"] and "do not split as written" in chk["errors"][0] and "at least 200" in chk["errors"][0]
    assert client.post("/api/labels/docs/save", json={"file": F, "data": short}, headers=H).status_code == 400
    assert client.post("/api/labels/docs/save", json={"file": F, "data": d}).status_code == 403
    assert client.get("/api/labels/docs", params={"file": "labels/nope.json"}).status_code == 404

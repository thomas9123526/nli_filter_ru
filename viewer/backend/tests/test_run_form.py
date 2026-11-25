"""/label/ "Start a run" form: what it offers (corpora, test sets, policies) and "Run a test set"."""
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nli_viewer.api import EDIT_HEADER, create_app
from nli_viewer.config import ViewerConfig
from nli_viewer.playground import Playground

H = {EDIT_HEADER: "1"}
REAL = Path(__file__).resolve().parents[3]


@pytest.fixture()
def project(tmp_path):
    proj = tmp_path / "proj"
    for d in ("labels", "policy", "tools", "dataset/corp_a/sub", "dataset/run_x"):
        (proj / d).mkdir(parents=True)
    shutil.copy(REAL / "policy" / "russia_llm_policy_v2.json", proj / "policy" / "russia_llm_policy_v2.json")
    shutil.copy(REAL / "labels" / "russia_llm_cases_v1.json", proj / "labels" / "russia_llm_cases_v1.json")
    (proj / "labels" / "cases_v1.json").write_text(json.dumps({"cases": []}), encoding="utf-8")  # no "corpus": not offered
    for t in ("label_test_set.py", "build_cases_corpus.py", "build_russia_llm_docs.py"):
        shutil.copy(REAL / "tools" / t, proj / "tools" / t)
    (proj / "dataset" / "corp_a" / "sub" / "a.jsonl").write_text('{"text": "x"}\n', encoding="utf-8")
    (proj / "dataset" / "corp_a" / "b.jsonl").write_text('{"text": "y"}\n', encoding="utf-8")
    (proj / "dataset" / "run_x" / "summary.json").write_text(json.dumps({"policy": {"path": "p"}}), encoding="utf-8")
    (proj / "dataset" / "run_x" / "in.labels.jsonl").write_text("", encoding="utf-8")
    return proj


@pytest.fixture()
def client(tmp_path, project):
    cfg = ViewerConfig(datasets=[], cache_dir=str(tmp_path / "cache"), edits_dir=str(tmp_path / "edits"),
                       frontend_dir=str(tmp_path / "nofe"), base_dir=str(tmp_path), project_dir=str(project),
                       playground_url="http://127.0.0.1:9")
    with TestClient(create_app(cfg), client=("127.0.0.1", 50000)) as c:
        yield c


def test_form_offers_corpora_test_sets_policies(client):
    d = client.get("/api/labels/forms/run").json()
    assert d["corpora"] == [{"path": "dataset/corp_a", "files": 2}]  # run_x is a run folder, not a corpus
    assert [t["file"] for t in d["test_sets"]] == ["labels/russia_llm_cases_v1.json"]
    t = d["test_sets"][0]
    assert t["kind"] == "cases" and t["items"] > 10 and t["corpus"] == "dataset/test_corpus_cases_ru"
    assert t["policy"] == "policy/russia_llm_policy_v2.json" and t["output"] == "out_label_russia_llm_cases_v1"
    assert d["policies"] == ["policy/russia_llm_policy_v2.json"]


def test_run_test_set_builds_the_corpus_and_starts(client, project, monkeypatch):
    pytest.importorskip("zstandard")
    seen = {}
    monkeypatch.setattr(Playground, "start_job", lambda self, args, env, label, script="nli_filter.py":
                        seen.update(args=args, script=script) or {"id": "j", "state": "running"})
    r = client.post("/api/labels/test-sets/run", json={"file": "labels/russia_llm_cases_v1.json", "use_judge": False}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["run"] == "out_label_russia_llm_cases_v1" and r.json()["kind"] == "cases"
    corpus = project / "dataset" / "test_corpus_cases_ru"
    assert corpus.is_dir() and any(corpus.rglob("*.jsonl.zst"))
    a = seen["args"]
    assert seen["script"] == "nli_label.py" and a[0] == "run" and Path(a[1]) == corpus.resolve()
    assert a[a.index("--policy") + 1] == "policy/russia_llm_policy_v2.json"
    assert Path(a[a.index("--output-dir") + 1]) == (project / "dataset" / "out_label_russia_llm_cases_v1").resolve()
    assert "--overwrite" in a and "--write-clean" in a and a[a.index("--judge-model") + 1] == "none"


def test_run_test_set_refusals(client):
    assert client.post("/api/labels/test-sets/run", json={"file": "labels/cases_v1.json"}, headers=H).status_code == 404
    assert client.post("/api/labels/test-sets/run", json={"file": "labels/russia_llm_cases_v1.json", "output_dir": "../x"},
                       headers=H).status_code == 400
    assert client.post("/api/labels/test-sets/run", json={"file": "labels/russia_llm_cases_v1.json"}).status_code == 403

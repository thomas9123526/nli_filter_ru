"""Labels pages: nli_label.py run folders listed, browsed, one document's flow, starting a run."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import build_tree
from nli_viewer.api import EDIT_HEADER, create_app
from nli_viewer.config import DatasetConfig, ViewerConfig

TEXT = ("Weather in London.\n\nThe Russian ballet star toured Moscow with a new film.\n\n"
        "Moscow scientists explain the algorithm.")


@pytest.fixture()
def project(tmp_path):
    proj = tmp_path / "proj"
    (proj / "policy").mkdir(parents=True)
    (proj / "policy" / "russia_policy.json").write_text("{}", encoding="utf-8")
    (proj / "in.jsonl").write_text(json.dumps({"id": "d1", "text": TEXT}) + "\n" +
                                   json.dumps({"id": "d2", "text": "Nothing here."}) + "\n", encoding="utf-8")
    run = proj / "out_label_t"
    run.mkdir()
    s1, e1 = TEXT.index("The Russian"), TEXT.index("film.") + 5
    s2 = TEXT.index("Moscow scientists")
    rows = [{"line": 1, "id": "d1", "gate": True, "hits": [{"kw": "Russian", "span": [s1 + 4, s1 + 11]}],
             "paragraphs": [
                 {"span": [s1, e1], "action": "remove", "reason": "remove_label", "labels": ["culture"],
                  "scores": {"involves": 0.97, "culture": 0.91, "science": 0.02}, "tokens": 14},
                 {"span": [s2, len(TEXT)], "action": "keep", "reason": "keep_label", "labels": ["science"],
                  "scores": {"involves": 0.95, "culture": 0.03, "science": 0.9}, "tokens": 10}],
             "labels": ["culture", "science"], "tokens": 40, "tokens_removed": 14, "review": False,
             "action": "edited"},
            {"line": 2, "id": "d2", "gate": False, "tokens": 4, "action": "untouched"}]
    (run / "in.labels.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (run / "in.summary.json").write_text(json.dumps({"input": str(proj / "in.jsonl"), "name": "in",
                                                     "stats": {"lines": 2, "docs": {"edited": 1, "untouched": 1}}}),
                                         encoding="utf-8")
    pol = {"labels": {"involves": {"level": 0, "decision": "gate", "threshold": 0.5, "hypothesis": "G"},
                      "culture": {"level": 1, "decision": "remove", "threshold": 0.8, "hypothesis": "C"},
                      "science": {"level": 1, "decision": "keep", "threshold": 0.8, "hypothesis": "S"}},
           "run_if": {"1": ["involves"]}, "conflict": "review", "path": "policy/russia_policy.json"}
    (run / "summary.json").write_text(json.dumps({"finished": "2026-11-20 12:00:00", "policy": pol,
                                                  "settings": {"text_field": "text"},
                                                  "stats": {"lines": 2, "tokens": 44, "tokens_removed": 14,
                                                            "docs": {"edited": 1, "untouched": 1}}}),
                                      encoding="utf-8")
    other = proj / "out_filter"  # an nli_filter.py run: not a label run
    other.mkdir()
    (other / "summary.json").write_text(json.dumps({"stats": {}}), encoding="utf-8")
    return proj


@pytest.fixture()
def client(tmp_path, project):
    tree = build_tree(tmp_path / "tree")
    cfg = ViewerConfig(datasets=[DatasetConfig(name="t", corpus=str(tree / "corpus"), output=str(tree / "out"))],
                       cache_dir=str(tmp_path / "cache"), edits_dir=str(tmp_path / "edits"),
                       frontend_dir=str(tmp_path / "nofrontend"), base_dir=str(tmp_path), project_dir=str(project),
                       playground_url="http://127.0.0.1:9")
    with TestClient(create_app(cfg), client=("127.0.0.1", 50000)) as c:
        yield c


def test_list_and_run(client):
    r = client.get("/api/labels").json()
    assert [x["name"] for x in r["runs"]] == ["out_label_t"]
    assert r["runs"][0]["docs"] == {"edited": 1, "untouched": 1}
    run = client.get("/api/labels/out_label_t").json()
    assert run["files"][0]["name"] == "in"
    assert client.get("/api/labels/policies").json()["policies"] == ["policy/russia_policy.json"]
    assert client.get("/api/labels/out_filter").status_code == 404
    assert client.get("/api/labels/..").status_code in (400, 404)


def test_docs_filters(client):
    d = client.get("/api/labels/out_label_t/docs", params={"file": "in"}).json()
    assert d["total"] == 1 and d["rows"][0]["paragraphs"] == {"remove": 1, "keep": 1}  # gated only by default
    assert client.get("/api/labels/out_label_t/docs", params={"file": "in", "gated": "false"}).json()["total"] == 2
    assert client.get("/api/labels/out_label_t/docs", params={"file": "in", "label": "sport"}).json()["total"] == 0
    assert client.get("/api/labels/out_label_t/docs",
                      params={"file": "in", "para_action": "remove"}).json()["total"] == 1


def test_doc_flow(client):
    d = client.get("/api/labels/out_label_t/doc", params={"file": "in", "line": 1}).json()
    assert d["text"] == TEXT and d["problem"] is None
    assert d["row"]["paragraphs"][0]["action"] == "remove"
    assert d["policy"]["labels"]["culture"]["decision"] == "remove"
    assert d["policy_path"] == "policy/russia_policy.json"  # for the Try page's "Try this paragraph"
    assert client.get("/api/labels/out_label_t/doc", params={"file": "in", "line": 9}).status_code == 404


def test_start_guarded_and_validated(client):
    body = {"command": "python nli_label.py run in.jsonl --output-dir out_x"}
    assert client.post("/api/labels/start", json=body).status_code == 403          # no edit header
    h = {EDIT_HEADER: "1"}
    assert client.post("/api/labels/start", json={"command": "rm -rf x"}, headers=h).status_code == 400
    assert client.post("/api/labels/start", json={"command": "run in.jsonl"}, headers=h).status_code == 400
    r = client.post("/api/labels/start", json=body, headers=h)
    assert r.status_code in (502, 503)  # validated; the model service is not running in tests


def test_cases_and_try(client, project):
    assert client.get("/api/labels/cases").status_code == 404          # no cases file yet
    (project / "labels").mkdir(exist_ok=True)
    (project / "labels" / "cases_v1.json").write_text(json.dumps(
        {"version": 1, "cases": [{"id": "x:yes", "group": "g", "title": "t", "what": "w", "texts": []}]}),
        encoding="utf-8")
    d = client.get("/api/labels/cases").json()
    assert d["file"] == "labels/cases_v1.json" and d["cases"][0]["id"] == "x:yes"
    assert client.post("/api/labels/try", json={"texts": []}).status_code == 400
    assert client.post("/api/labels/try", json={"texts": ["a"] * 21}).status_code == 400
    assert client.post("/api/labels/try", json={"texts": ["Russia."]}).status_code in (502, 503)  # no service


def test_other_case_sets(client, project):
    lab = project / "labels"
    lab.mkdir(exist_ok=True)
    for name, cid in (("cases_v1.json", "a"), ("cases_v2.json", "b"), ("russia_llm_cases_v1.json", "ru"),
                      ("cases_v1_results.json", "no")):
        (lab / name).write_text(json.dumps({"version": 1, "cases": [{"id": cid, "group": "g", "title": "t",
                                                                      "what": "w", "texts": []}]}), encoding="utf-8")
    f = client.get("/api/labels/case-files").json()
    assert f["files"] == ["labels/cases_v1.json", "labels/cases_v2.json", "labels/russia_llm_cases_v1.json"]
    assert f["newest"] == "labels/cases_v2.json"
    assert client.get("/api/labels/cases").json()["cases"][0]["id"] == "b"
    d = client.get("/api/labels/cases", params={"file": "labels/russia_llm_cases_v1.json"}).json()
    assert d["file"] == "labels/russia_llm_cases_v1.json" and d["cases"][0]["id"] == "ru"
    assert client.get("/api/labels/cases", params={"file": "labels/cases_v1_results.json"}).status_code == 404
    assert client.get("/api/labels/cases", params={"file": "../secret.json"}).status_code == 404


def test_server_input_without_reopen_and_shard_progress(client, project):
    run = project / "out_label_t"
    fs = json.loads((run / "in.summary.json").read_text(encoding="utf-8"))
    fs["input"] = "sftp://reader@example.invalid/corpus/in.jsonl"   # stored without password, no reopen
    (run / "in.summary.json").write_text(json.dumps(fs), encoding="utf-8")
    d = client.get("/api/labels/out_label_t/doc", params={"file": "in", "line": 1}).json()
    assert d["text"] is None and "environment variable" in d["problem"]
    for k, state in ((0, "done"), (1, "running")):
        (run / f"progress.shard{k}of2.json").write_text(json.dumps(
            {"state": state, "command": "nli_label.py run x", "shard": f"{k}/2", "started": "2026-11-20 10:00:00",
             "updated": "2026-11-20 10:00:00", "files_total": 3, "files_done": 1 + k, "lines_done": 10}),
            encoding="utf-8")
    p = client.get("/api/labels").json()["runs"][0]["progress"]
    assert p["shards"] == 2 and p["files_done"] == 3 and p["files_total"] == 6 and p["state"] in ("running", "stale")


def test_dataset_output_can_be_a_label_run(tmp_path, project):
    """viewer_config "output" pointing at an nli_label.py run: the dataset links to the labelling pages."""
    import shutil
    tree = build_tree(tmp_path / "tree")
    outside = tmp_path / "elsewhere" / "label_run"  # a run folder outside the project folder
    shutil.copytree(project / "out_label_t", outside)
    cfg = ViewerConfig(datasets=[DatasetConfig(name="filt", corpus=str(tree / "corpus"), output=str(tree / "out")),
                                 DatasetConfig(name="lab_in", corpus=str(project), output=str(project / "out_label_t")),
                                 DatasetConfig(name="lab_out", corpus=str(project), output=str(outside))],
                       cache_dir=str(tmp_path / "cache"), edits_dir=str(tmp_path / "edits"),
                       frontend_dir=str(tmp_path / "nofrontend"), base_dir=str(tmp_path), project_dir=str(project),
                       playground_url="http://127.0.0.1:9")
    with TestClient(create_app(cfg), client=("127.0.0.1", 50000)) as c:
        rows = {r["name"]: r for r in c.get("/api/datasets").json()["datasets"]}
        assert "label_run" not in rows["filt"]
        assert rows["lab_in"]["label_run"] == "out_label_t" and rows["lab_in"]["error"] is None
        assert rows["lab_out"]["label_run"] == "lab_out"
        assert c.get("/api/datasets/lab_out").json()["label_run"] == "lab_out"
        runs = {r["name"] for r in c.get("/api/labels").json()["runs"]}
        assert {"out_label_t", "lab_out"} <= runs
        assert c.get("/api/labels/lab_out").json()["files"][0]["name"] == "in"
        d = c.get("/api/labels/lab_out/doc", params={"file": "in", "line": 1}).json()
        assert d["row"]["action"] == "edited"


def test_labels_file_as_zst(client, project):
    """nli_label.py --compress zst writes <name>.labels.jsonl.zst: the pages read it like the plain file."""
    zstandard = pytest.importorskip("zstandard")
    run = project / "out_label_t"
    plain = run / "in.labels.jsonl"
    (run / "in.labels.jsonl.zst").write_bytes(zstandard.ZstdCompressor().compress(plain.read_bytes()))
    plain.unlink()
    docs = client.get("/api/labels/out_label_t/docs", params={"file": "in"}).json()
    assert docs["total"] >= 1 and docs["rows"][0]["line"] == 1
    d = client.get("/api/labels/out_label_t/doc", params={"file": "in", "line": 1}).json()
    assert d["row"]["action"] == "edited" and len(d["row"]["paragraphs"]) == 2

"""Dynamic datasets (auto_datasets): run folders paired with their corpus, the most recent run per corpus shown."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from nli_viewer import discover as D
from nli_viewer.api import create_app
from nli_viewer.config import DatasetConfig, ViewerConfig


def run(folder, kind, finished, inp, running=False):
    folder.mkdir(parents=True)
    s = {"finished": finished, "files": [{"input": inp, "name": "a", "status": "done"}], "stats": {"lines": 1}}
    if kind == "label":
        s["policy"] = {"path": "policy/p.json", "labels": {}}
    (folder / "summary.json").write_text(json.dumps(s), encoding="utf-8")
    if running:
        (folder / "progress.json").write_text(json.dumps({"state": "running", "command": "nli_label.py run"}),
                                              encoding="utf-8")


@pytest.fixture()
def proj(tmp_path):
    p = tmp_path / "proj"
    ds = p / "dataset"
    for c in ("test_corpus", "test_corpus_cases_ru", "test_corpus_docs_ru"):
        (ds / c / "a").mkdir(parents=True)
        (ds / c / "a" / "x.jsonl").write_text('{"id": 1, "text": "Moscow."}\n', encoding="utf-8")
    run(ds / "out_test_corpus", "filter", "2026-11-01 10:00:00", "dataset/test_corpus/a/x.jsonl")
    run(ds / "out_label_ru_v1", "label", "2026-11-23 10:00:00", r"dataset\test_corpus_cases_ru\a\x.jsonl")
    run(ds / "out_label_ru_v2", "label", "2026-11-23 12:00:00", r"dataset\test_corpus_cases_ru\a\x.jsonl")
    run(ds / "out_label_ru_judge", "label", "2026-11-23 11:00:00", r"dataset\test_corpus_cases_ru\a\x.jsonl")
    run(ds / "out_label_docs", "label", "2026-11-23 13:00:00", "dataset/test_corpus_docs_ru/a/x.jsonl")
    run(ds / "out_old_layout", "filter", "2026-11-02 10:00:00", r".\test_corpus\a\x.jsonl")  # before the move
    run(ds / "out_gone", "label", "2026-11-20 10:00:00", "dataset/test_corpus_deleted/a/x.jsonl")
    run(ds / "out_single", "filter", "2026-11-03 10:00:00", "test_russia.jsonl")
    run(ds / "out_server", "filter", "2026-11-03 10:00:00", "sftp://u@host/corpus/x.jsonl.zst")
    run(ds / "out_now", "label", "2026-11-24 09:00:00", "dataset/test_corpus/a/x.jsonl", running=True)
    (ds / "out_broken").mkdir()
    return p


def test_scan_pairs_runs_with_their_corpus(proj):
    runs = {r.path.name: r for r in D.scan(proj, proj / "dataset")}
    assert runs["out_label_ru_v2"].status == D.IN_USE                   # the most recent of three
    assert runs["out_label_ru_v1"].status == D.OLDER and runs["out_label_ru_v1"].newer == "out_label_ru_v2"
    assert runs["out_label_ru_judge"].status == D.OLDER
    assert runs["out_old_layout"].status == D.IN_USE                    # .\test_corpus\… found in dataset/
    assert runs["out_old_layout"].corpus.name == "test_corpus"
    assert runs["out_test_corpus"].status == D.OLDER                    # same corpus, same kind, older
    assert runs["out_label_docs"].status == D.IN_USE
    assert runs["out_gone"].status == D.NO_CORPUS
    assert runs["out_single"].status == D.SINGLE_FILE
    assert runs["out_server"].status == D.SERVER
    assert runs["out_now"].status == D.RUNNING                          # never picked while it runs
    assert runs["out_broken"].status == D.BROKEN
    rep = D.report(list(runs.values()), proj)
    assert "dataset\\out_gone" in rep.replace("/", "\\") and "safe to remove" in rep


def test_auto_datasets_skip_configured_pairs_and_names(proj):
    runs = D.scan(proj, proj / "dataset")
    ru = str((proj / "dataset" / "test_corpus_cases_ru").resolve())
    out = str((proj / "dataset" / "out_label_ru_v2").resolve())
    auto = {a["name"]: a for a in D.auto_datasets(runs, {"mine": (ru, out), "test_corpus": ("x", "y")})}
    assert "test_corpus_cases_ru-labels" not in auto                     # configured already (same pair)
    assert "auto-test_corpus" in auto                                    # name taken by the config
    assert auto["test_corpus_docs_ru-labels"]["output"].endswith("out_label_docs")


def test_viewer_shows_configured_plus_dynamic(proj, tmp_path):
    cfg = ViewerConfig(datasets=[DatasetConfig(name="mine", corpus=str(proj / "dataset" / "test_corpus"))],
                       cache_dir=str(tmp_path / "cache"), edits_dir=str(tmp_path / "edits"),
                       frontend_dir=str(tmp_path / "nofe"), base_dir=str(tmp_path), project_dir=str(proj),
                       playground_url="http://127.0.0.1:9", auto_datasets=str(proj / "dataset"))
    with TestClient(create_app(cfg), client=("127.0.0.1", 50000)) as c:
        rows = {r["name"]: r for r in c.get("/api/datasets").json()["datasets"]}
        assert rows["mine"]["auto"] is False
        assert rows["test_corpus_cases_ru-labels"]["auto"] is True
        assert rows["test_corpus_cases_ru-labels"]["label_run"] == "out_label_ru_v2"
        assert rows["test_corpus"]["auto"] is True and rows["test_corpus"]["output"].endswith("out_old_layout")
        # a newer run appears: the dynamic dataset follows it
        time.sleep(0.01)
        run(proj / "dataset" / "out_label_ru_v3", "label", "2026-11-23 18:00:00",
            "dataset/test_corpus_cases_ru/a/x.jsonl")
        rows = {r["name"]: r for r in c.get("/api/datasets").json()["datasets"]}
        assert rows["test_corpus_cases_ru-labels"]["label_run"] == "out_label_ru_v3"
        rf = c.get("/api/run-folders").json()
        st = {r["folder"].replace("\\", "/"): r["status"] for r in rf["runs"]}
        assert st["dataset/out_label_ru_v2"] == D.OLDER and st["dataset/out_broken"] == D.BROKEN
        assert any("out_gone" in x for x in rf["remove_invalid"])
        removed = [x.split("'")[1].replace("\\", "/") for x in rf["remove_invalid"] + rf["remove_unused"]]
        assert "dataset/out_label_ru_v3" not in removed and "dataset/out_now" not in removed  # in use / running
        assert "dataset/out_label_ru_v2" in removed


def test_cli_runs_report(proj, tmp_path, capsys):
    from nli_viewer.cli import main
    cfgf = tmp_path / "viewer_config.json"
    cfgf.write_text(json.dumps({"project_dir": str(proj), "auto_datasets": str(proj / "dataset"), "datasets": []}),
                    encoding="utf-8")
    assert main(["runs", "--config", str(cfgf)]) == 0
    out = capsys.readouterr().out
    assert "out_label_ru_v2" in out and "in use" in out and "Remove-Item" in out and "out_broken" in out


def test_delete_run_folders_with_safety(proj, tmp_path):
    from nli_viewer.api import EDIT_HEADER
    H = {EDIT_HEADER: "1"}
    cfg = ViewerConfig(datasets=[DatasetConfig(name="mine", corpus=str(proj / "dataset" / "test_corpus"),
                                               output=str(proj / "dataset" / "out_label_ru_judge"))],
                       cache_dir=str(tmp_path / "cache"), edits_dir=str(tmp_path / "edits"),
                       frontend_dir=str(tmp_path / "nofe"), base_dir=str(tmp_path), project_dir=str(proj),
                       playground_url="http://127.0.0.1:9", auto_datasets=str(proj / "dataset"))
    ds = proj / "dataset"
    with TestClient(create_app(cfg), client=("127.0.0.1", 50000)) as c:
        r = c.post("/api/run-folders/delete", headers=H, json={"folders": [
            "out_label_ru_v1", "out_gone", "out_broken",             # older / corpus missing / broken: deleted
            "out_label_ru_v2",                                       # in use (newest for its corpus): kept
            "out_label_ru_judge",                                    # a configured dataset's output: kept
            "out_now",                                               # running: kept
            "test_corpus", "../proj", "nope"]})                      # not run folders: refused
        assert r.status_code == 200, r.text
        d = r.json()
        assert sorted(d["deleted"]) == ["out_broken", "out_gone", "out_label_ru_v1"]
        why = {f["folder"]: f["error"] for f in d["failed"]}
        assert "in use" in why["out_label_ru_v2"] and "in use" in why["out_label_ru_judge"]
        assert "running" in why["out_now"] and "not a run folder" in why["test_corpus"] and "nope" in why
        assert not (ds / "out_label_ru_v1").exists() and (ds / "out_label_ru_v2").is_dir() and (ds / "test_corpus").is_dir()
        # explicitly allowed: a folder in use goes too
        d = c.post("/api/run-folders/delete", headers=H, json={"folders": ["out_label_ru_v2"], "allow_in_use": True}).json()
        assert d["deleted"] == ["out_label_ru_v2"] and not (ds / "out_label_ru_v2").exists()
        assert c.post("/api/run-folders/delete", json={"folders": ["out_single"]}).status_code == 403

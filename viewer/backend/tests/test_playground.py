"""The "Try settings" panel: viewer <-> nli_playground.py (with a stand-in model), shared hypothesis / keyword files."""
import json

import pytest
from fastapi.testclient import TestClient

from conftest import build_tree
from nli_viewer.api import EDIT_HEADER, create_app
from nli_viewer.config import DatasetConfig, ViewerConfig

import nli_playground

H = {EDIT_HEADER: "1"}


class StandIn:
    """Scores like a model: 0.97 for texts about Russia's size / history, 0.95 'company' for brewing."""

    def __init__(self, name):
        self.name, self.devices, self.mode = name, ["cpu"], "single"

    def score(self, premises, hypotheses):
        out = []
        for p, h in zip(premises, hypotheses):
            p, h = p.lower(), h.lower()
            if "company or brand" in h:
                out.append(0.95 if "brewing" in p else 0.05)
            elif "language" in h or "weather" in h:
                out.append(0.02)
            else:
                out.append(0.97 if ("largest" in p or "crisis" in p) else 0.1)
        return out

    def close(self):
        pass


@pytest.fixture()
def setup(tmp_path):
    tree = build_tree(tmp_path / "tree")
    project = tmp_path / "project"
    (project / "hypotheses").mkdir(parents=True)
    (project / "keywords").mkdir()
    (project / "keywords" / "russia.txt").write_text("# test\nRussia\nRussian\n", encoding="utf-8")
    server = nli_playground.serve(nli_playground.Playground(StandIn("fast"), StandIn("judge")), "127.0.0.1", 0)
    cfg = ViewerConfig(datasets=[DatasetConfig(name="t", corpus=str(tree / "corpus"), output=str(tree / "out"))],
                       cache_dir=str(tmp_path / "cache"), edits_dir=str(tmp_path / "edits"),
                       frontend_dir=str(tmp_path / "nofrontend"), base_dir=str(tmp_path),
                       playground_url=f"http://127.0.0.1:{server.server_address[1]}", project_dir=str(project))
    with TestClient(create_app(cfg), client=("127.0.0.1", 50000)) as c:
        yield c, project
    server.shutdown()
    server.server_close()


def test_status_and_resources(setup):
    c, project = setup
    r = c.get("/api/playground").json()
    assert r["service"]["running"] and r["service"]["fast"] == "fast"
    assert [k["name"] for k in r["keywords"]] == ["russia"] and r["keywords"][0]["count"] == 2
    assert r["builtin_hypotheses"]["check1"]["topic"].startswith("This text is about {country}")
    assert {"name": "Russia", "adj": "Russian"} in r["countries"]


def test_run_lines(setup):
    c, _ = setup
    body = {"path": "a/x.jsonl.zst", "lines": [1, 2, 3, 4], "settings": {"keywords": "Russia\nRussian\n"}}
    import time
    for _ in range(100):  # the first run starts building the saved run's decisions table (for "previous")
        r = c.post("/api/datasets/t/playground/run", json=body)
        assert r.status_code == 200, r.text
        if not r.json()["previous_pending"]:
            break
        time.sleep(0.05)
    res = r.json()["results"]
    assert [x["decision"]["decision"] for x in res] == ["filter", "keep", "keep", "filter"]
    assert [x["decision"]["reason"] for x in res][:3] == ["about_country", "no_keyword", "rules_incidental"]
    first = res[0]
    assert first["explanation"]["text_available"] and first["explanation"]["check1"]["rows"][0]["hypothesis"]
    assert first["previous"]["decision"] == "filter" and first["previous"]["row"] == 1  # the saved run, to compare
    # other hypotheses: check 1 says no -> kept
    body["settings"] = {"check1": {"weather": "This text is about the weather in {country}."}, "check2": {}}
    res = c.post("/api/datasets/t/playground/run", json=body).json()["results"]
    assert res[0]["decision"]["reason"] == "check1_negative"
    assert res[0]["explanation"]["check1"]["rows"][0]["hypothesis"] == "This text is about the weather in Russia."
    bad = dict(body, settings={"check1": {"x": "about {land}"}})
    r = c.post("/api/datasets/t/playground/run", json=bad)
    assert r.status_code == 400 and "only {country}" in r.json()["detail"]


def test_save_files(setup):
    c, project = setup
    data = {"description": "weather test", "check1": {"w": "About the weather in {country}."}, "check2": {}}
    assert c.post("/api/playground/hypotheses", json={"name": "weather", "data": data}).status_code == 403  # no header
    r = c.post("/api/playground/hypotheses", json={"name": "weather", "data": data}, headers=H)
    assert r.status_code == 200 and r.json()["backup"] is None
    assert json.loads((project / "hypotheses" / "weather.json").read_text(encoding="utf-8")) == data
    r = c.post("/api/playground/hypotheses", json={"name": "weather", "data": data}, headers=H)
    assert r.status_code == 400 and "exists" in r.json()["detail"]
    r = c.post("/api/playground/hypotheses", json={"name": "weather", "data": data, "overwrite": True}, headers=H)
    assert r.json()["backup"] and (project / "hypotheses" / "weather.json").is_file()
    assert c.post("/api/playground/hypotheses", json={"name": "../x", "data": data}, headers=H).status_code == 400
    r = c.post("/api/playground/keywords", json={"name": "russia", "text": "Russia\nMoscow", "overwrite": True},
               headers=H)
    assert r.status_code == 200 and (project / "keywords" / "russia.txt").read_text() == "Russia\nMoscow\n"
    names = [h["name"] for h in c.get("/api/playground").json()["hypotheses"]]
    assert names == ["weather"]


def test_service_not_running(tmp_path):
    tree = build_tree(tmp_path / "tree")
    cfg = ViewerConfig(datasets=[DatasetConfig(name="t", corpus=str(tree / "corpus"), output=str(tree / "out"))],
                       cache_dir=str(tmp_path / "cache"), frontend_dir=str(tmp_path / "nofrontend"),
                       base_dir=str(tmp_path), playground_url="http://127.0.0.1:9")
    with TestClient(create_app(cfg)) as c:
        s = c.get("/api/playground").json()["service"]
        assert not s["running"] and "nli_playground.py" in s["error"]
        r = c.post("/api/datasets/t/playground/run", json={"path": "a/x.jsonl.zst", "lines": [1]})
        assert r.status_code == 502 and "not running" in r.json()["detail"]

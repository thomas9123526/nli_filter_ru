"""Output modes in the viewer: the schema editor (check / save / preview), the non-English config editor, a simple-mode
run's rows and one line, the run list's mode and unit, Explain-this-line settings passed to the model service."""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nli_viewer.api import EDIT_HEADER, create_app
from nli_viewer.config import ViewerConfig

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
H = {EDIT_HEADER: "1"}

POLICY = {
    "country": "Russia", "keywords_file": None, "markers": ["special military operation"],
    "paragraphs": {"min_chars": 20, "max_chars": 400}, "conflict": "review",
    "labels": {
        "involves": {"level": 0, "decision": "gate", "threshold": 0.5, "hypothesis": "GATE"},
        "culture": {"level": 1, "decision": "remove", "threshold": 0.8, "hypothesis": "CULTURE"},
        "science": {"level": 1, "decision": "keep", "threshold": 0.8, "hypothesis": "SCIENCE"},
    },
    "run_if": {"1": ["involves", "@marker"]},
}
TEXTS = ["A long paragraph about Russian ballet and every film the theatre made, long enough here.",
         "A long paragraph about Russian algorithm research in physics, also long enough here.",
         "No keyword at all in this line."]


class Fake:
    CUES = {"GATE": ["russia"], "CULTURE": ["ballet"], "SCIENCE": ["physics"]}

    def __init__(self):
        self.fast_pairs = self.judge_pairs = 0

    def score(self, premises, hyps):
        out = [(0.95, None, 0.95) if any(c in p.lower() for c in self.CUES.get(h, [])) else (0.05, None, 0.05)
               for p, h in zip(premises, hyps)]
        self.fast_pairs += len(out)
        return out


@pytest.fixture()
def project(tmp_path, monkeypatch):
    import nli_label
    proj = tmp_path / "proj"
    (proj / "policy").mkdir(parents=True)
    (proj / "output").mkdir()
    (proj / "policy" / "p.json").write_text(json.dumps(POLICY), encoding="utf-8")
    (proj / "policy" / "non_english.json").write_text((ROOT / "policy" / "non_english.json").read_text(encoding="utf-8"),
                                                      encoding="utf-8")
    (proj / "output" / "simple_schema.json").write_text((ROOT / "output" / "simple_schema.json").read_text(encoding="utf-8"),
                                                        encoding="utf-8")
    inp = proj / "dataset" / "corpus" / "in.jsonl"
    inp.parent.mkdir(parents=True)
    inp.write_text("".join(json.dumps({"id": f"d{i}", "text": t}) + "\n" for i, t in enumerate(TEXTS, 1)), encoding="utf-8")
    monkeypatch.setattr(nli_label, "build_scorer", lambda args: (Fake(), None, None))
    pol = str(proj / "policy" / "p.json")
    assert nli_label.main(["run", "--compress", "none", str(inp), "--output-dir", str(proj / "dataset" / "out_detail"),
                           "--policy", pol]) == 0
    schema = json.loads((proj / "output" / "simple_schema.json").read_text(encoding="utf-8"))
    schema["evidence"] = "decided"
    (proj / "output" / "ev.json").write_text(json.dumps(schema), encoding="utf-8")
    assert nli_label.main(["run", "--compress", "none", str(inp), "--output-dir", str(proj / "dataset" / "out_simple"),
                           "--policy", pol, "--output-mode", "simple", "--decision-unit", "line",
                           "--schema", str(proj / "output" / "ev.json")]) == 0
    return proj


@pytest.fixture()
def client(tmp_path, project):
    cfg = ViewerConfig(datasets=[], cache_dir=str(tmp_path / "cache"), edits_dir=str(tmp_path / "edits"),
                       frontend_dir=str(tmp_path / "nofe"), base_dir=str(tmp_path), project_dir=str(project),
                       playground_url="http://127.0.0.1:9")
    with TestClient(create_app(cfg), client=("127.0.0.1", 50000)) as c:
        yield c


def test_run_list_mode_and_unit(client):
    runs = {r["name"]: r for r in client.get("/api/labels").json()["runs"]}
    assert runs["out_simple"]["mode"] == "simple" and runs["out_simple"]["unit"] == "line"
    assert runs["out_detail"]["mode"] == "detail" and runs["out_detail"]["unit"] == "paragraph"


def test_simple_rows_filters_and_counts(client):
    r = client.get("/api/labels/simple/out_simple/rows", params={"file": "in"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["total"] == 3 and d["counts"]["decision"] == {"remove": 1, "keep": 1, "untouched": 1}
    assert d["can_open"] and d["fields"]["line"] == "ln" and d["evidence"] == "decided"
    assert d["rows"][0]["decision"] == "remove" and d["rows"][0]["keywords"] == {"russian": 1}
    d = client.get("/api/labels/simple/out_simple/rows", params={"file": "in", "decision": "keep"}).json()
    assert d["total"] == 1 and d["rows"][0]["line"] == 2
    d = client.get("/api/labels/simple/out_simple/rows", params={"file": "in", "reason": "no_keyword"}).json()
    assert [x["line"] for x in d["rows"]] == [3]
    d = client.get("/api/labels/simple/out_simple/rows", params={"file": "in", "keyword": "russian"}).json()
    assert d["total"] == 2
    assert client.get("/api/labels/simple/out_detail/rows", params={"file": "in"}).status_code == 404


def test_simple_line_text_hits_evidence(client):
    d = client.get("/api/labels/simple/out_simple/line", params={"file": "in", "line": 1}).json()
    assert d["text"] == TEXTS[0] and d["row"]["decision"] == "remove"
    assert d["hits"][0]["kw"] == "Russian" and d["evidence"]["paragraphs"][0]["action"] == "remove"
    assert d["policy_data"]["labels"]["culture"] and d["settings"]["decision_unit"] == "line"
    d2 = client.get("/api/labels/simple/out_simple/line", params={"file": "in", "line": 2}).json()
    assert d2["evidence"] is None  # evidence: decided = remove / review only


def test_schema_editor_check_save_preview(client, project):
    files = client.get("/api/labels/config/schema/files").json()["files"]
    assert "output/simple_schema.json" in files
    raw = client.get("/api/labels/config/schema/raw", params={"path": "output/simple_schema.json"}).json()
    assert raw["check"]["ok"] and "keyword_counts" in raw["check"]["info"]["sources"]
    bad = dict(raw["data"], fields=[{"name": "a", "from": "nope"}])
    c = client.post("/api/labels/config/schema/check", json={"data": bad}).json()
    assert not c["ok"] and "unknown source" in c["errors"][0]
    data = dict(raw["data"], include=["remove", "keep"])
    r = client.post("/api/labels/config/schema/save", json={"path": "output/simple_schema.json", "data": data,
                                                             "base_sha": raw["sha"]}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["backup"].startswith("output/.backup/")
    again = client.post("/api/labels/config/schema/save", json={"path": "output/simple_schema.json", "data": data,
                                                                 "base_sha": raw["sha"]}, headers=H)
    assert again.status_code == 409  # changed since it was loaded
    assert client.post("/api/labels/config/schema/save", json={"path": "output/x.json", "data": data},
                       headers=H).status_code == 404  # no such file (use save_as for a new one)
    assert client.post("/api/labels/config/schema/save", json={"path": "output/simple_schema.json", "data": bad,
                                                                "save_as": "output/new.json"}, headers=H).status_code == 400
    assert client.post("/api/labels/config/schema/save", json={"path": "../x.json", "data": data},
                       headers=H).status_code == 400
    pv = client.post("/api/labels/config/schema/preview", json={"data": data, "run": "out_detail"}).json()
    assert pv["read"] == 3 and pv["included"] == 2  # untouched left out by include
    assert pv["rows"][0]["decision"] == "edited" or pv["rows"][0]["decision"] == "removed"
    assert pv["rows"][0]["reason"] == "culture"
    assert client.post("/api/labels/config/schema/preview", json={"data": data, "run": "out_simple"}).status_code == 404


def test_non_english_editor(client, project):
    assert client.get("/api/labels/config/non_english/files").json()["files"] == ["policy/non_english.json"]
    assert "policy/non_english.json" not in client.get("/api/labels/policies").json()["policies"]
    raw = client.get("/api/labels/config/non_english/raw", params={"path": "policy/non_english.json"}).json()
    assert raw["check"]["ok"] and raw["check"]["info"]["enabled"] == ["arabic"]
    data = json.loads(json.dumps(raw["data"]))
    data["scripts"]["japanese"]["enabled"] = True
    data["keywords"] = "remove"
    r = client.post("/api/labels/config/non_english/save", json={"path": "policy/non_english.json", "data": data,
                                                                  "base_sha": raw["sha"]}, headers=H)
    assert r.status_code == 200, r.text
    saved = json.loads((project / "policy" / "non_english.json").read_text(encoding="utf-8"))
    assert saved["keywords"] == "remove" and saved["scripts"]["japanese"]["enabled"] is True
    data["keywords"] = "delete"
    c = client.post("/api/labels/config/non_english/check", json={"data": data}).json()
    assert not c["ok"] and "keywords must be" in c["errors"][0]
    assert client.post("/api/labels/config/non_english/save", json={"path": "policy/non_english.json", "data": data},
                       headers=H).status_code == 400
    assert client.post("/api/labels/config/schema/save", json={"path": "output/simple_schema.json", "data": data}
                       ).status_code in (400, 403)  # no edit header


def test_try_passes_the_runs_settings(client, monkeypatch):
    sent = {}
    from nli_viewer.playground import Playground
    monkeypatch.setattr(Playground, "label", lambda self, body: sent.update(body) or {"rows": []})
    r = client.post("/api/labels/try", json={"texts": ["x"], "policy_data": POLICY, "decision_unit": "line",
                                              "review_as": "remove", "uncertain_band": [0.5, 0.9], "all_labels": False})
    assert r.status_code == 200, r.text
    assert sent["decision_unit"] == "line" and sent["review_as"] == "remove" and sent["uncertain_band"] == [0.5, 0.9]
    assert client.post("/api/labels/try", json={"texts": ["x"], "decision_unit": "doc"}).status_code == 400

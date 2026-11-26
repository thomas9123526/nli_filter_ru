"""The Experiment page's API: the base (a run's line, its recorded policy), the draft check, draft and base run through
the model service (with reused scores), saving only on an explicit confirm (save as new never overwrites; replace needs
the file name typed again and the loaded version), and applying the draft to a run (redecide)."""
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
        "involves": {"level": 0, "decision": "gate", "threshold": 0.5, "hypothesis": "This text is about Russia's size."},
        "culture": {"level": 1, "decision": "remove", "threshold": 0.8, "hypothesis": "This text is about a crisis."},
    },
    "run_if": {"1": ["involves", "@marker"]},
}
TEXT = ("Russia is the largest country and its crisis is long, long enough here.\n\n"
        "A second paragraph about Russian weather only, long enough to count here.")


class StandIn:
    def __init__(self, name):
        self.name, self.devices, self.mode = name, ["cpu"], "single"
        self.calls = 0

    def score(self, premises, hypotheses):
        self.calls += len(premises)
        return [0.97 if ("largest" in p.lower() or "crisis" in p.lower()) else 0.1 for p in premises]

    def close(self):
        pass


class Fake:
    def __init__(self):
        self.fast_pairs = self.judge_pairs = 0

    def score(self, premises, hyps):
        return [(0.97, None, 0.97) if ("largest" in p.lower() or "crisis" in p.lower()) else (0.1, None, 0.1)
                for p in premises]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    import nli_label
    import nli_playground
    proj = tmp_path / "proj"
    (proj / "policy").mkdir(parents=True)
    (proj / "policy" / "p.json").write_text(json.dumps(POLICY), encoding="utf-8")
    inp = proj / "dataset" / "corpus" / "in.jsonl"
    inp.parent.mkdir(parents=True)
    inp.write_text(json.dumps({"id": "d1", "text": TEXT}) + "\n", encoding="utf-8")
    monkeypatch.setattr(nli_label, "build_scorer", lambda args: (Fake(), None, None))
    assert nli_label.main(["run", "--compress", "none", str(inp), "--output-dir", str(proj / "dataset" / "out_r"),
                           "--policy", str(proj / "policy" / "p.json")]) == 0
    fast = StandIn("fast")
    pg = nli_playground.serve(nli_playground.Playground(fast, None), "127.0.0.1", 0)
    cfg = ViewerConfig(datasets=[], cache_dir=str(tmp_path / "cache"), edits_dir=str(tmp_path / "edits"),
                       frontend_dir=str(tmp_path / "nofe"), base_dir=str(tmp_path), project_dir=str(proj),
                       playground_url=f"http://127.0.0.1:{pg.server_address[1]}")
    with TestClient(create_app(cfg), client=("127.0.0.1", 50000)) as c:
        yield c, proj, fast
    pg.shutdown()


def test_base_from_a_run(env):
    c, proj, _ = env
    b = c.get("/api/labels/lab/base", params={"run": "out_r", "file": "in", "line": 1, "para": 0}).json()
    assert b["text"] == TEXT and b["paragraph"].startswith("Russia is the largest")
    assert b["policy_data"]["labels"].keys() == POLICY["labels"].keys() and "recorded by run" in b["policy_from"]
    assert b["policy_path"] == "policy/p.json" and b["policy_sha"] and b["file_differs"] is False
    plain = c.get("/api/labels/lab/base", params={"policy": "policy/p.json"}).json()
    assert plain["text"] is None and plain["policy_from"] == "the file policy/p.json"


def test_check_and_try_draft_vs_base_reuses_scores(env):
    c, _, fast = env
    draft = json.loads(json.dumps(POLICY))
    draft["labels"]["weather"] = {"level": 1, "decision": "keep", "threshold": 0.5, "hypothesis": "This text is about weather."}
    assert c.post("/api/labels/lab/check", json={"data": draft}).json()["ok"]
    bad = dict(draft, conflict="maybe")
    assert not c.post("/api/labels/lab/check", json={"data": bad}).json()["ok"]
    body = {"texts": [TEXT], "all_labels": False, "use_judge": False, "reuse_scores": True}
    rb = c.post("/api/labels/try", json=dict(body, policy_data=POLICY)).json()
    n1 = fast.calls
    rd = c.post("/api/labels/try", json=dict(body, policy_data=draft)).json()
    assert rd["pairs"]["reused"] >= 3  # gate x2 and culture: scored by the first call
    assert fast.calls - n1 == 1  # only the new label on the open paragraph
    assert [p["action"] for p in rb["rows"][0]["paragraphs"]] == ["remove", "pass"]
    assert [p["action"] for p in rd["rows"][0]["paragraphs"]] == ["review", "pass"]  # keep + remove = conflict (review)


def test_save_only_on_confirm(env):
    c, proj, _ = env
    f = proj / "policy" / "p.json"
    before = f.read_text(encoding="utf-8")
    sha = c.get("/api/labels/lab/base", params={"policy": "policy/p.json"}).json()["policy_sha"]
    draft = json.loads(before)
    draft["labels"]["culture"]["threshold"] = 0.7
    r = c.post("/api/labels/lab/save", headers=H, json={"data": draft, "save_as": "policy/p_v2.json"})
    assert r.status_code == 200 and (proj / "policy" / "p_v2.json").is_file()
    assert c.post("/api/labels/lab/save", headers=H, json={"data": draft, "save_as": "policy/p_v2.json"}).status_code == 409
    assert c.post("/api/labels/lab/save", headers=H, json={"data": draft, "replace": "policy/p.json",
                                                            "base_sha": sha}).status_code == 400  # no confirm
    assert c.post("/api/labels/lab/save", headers=H, json={"data": draft, "replace": "policy/p.json", "confirm": "p",
                                                            "base_sha": sha}).status_code == 400  # wrong name
    assert c.post("/api/labels/lab/save", json={"data": draft, "replace": "policy/p.json", "confirm": "p.json",
                                                "base_sha": sha}).status_code == 403  # no edit header
    assert f.read_text(encoding="utf-8") == before
    assert c.post("/api/labels/lab/save", headers=H, json={"data": draft, "replace": "policy/p.json", "confirm": "p.json",
                                                            "base_sha": "0" * 40}).status_code == 409  # changed since
    r = c.post("/api/labels/lab/save", headers=H, json={"data": draft, "replace": "policy/p.json", "confirm": "p.json",
                                                         "base_sha": sha})
    assert r.status_code == 200 and r.json()["backup"].startswith("policy/.backup/")
    assert json.loads(f.read_text(encoding="utf-8"))["labels"]["culture"]["threshold"] == 0.7
    bad = dict(draft, conflict="maybe")
    assert c.post("/api/labels/lab/save", headers=H, json={"data": bad, "save_as": "policy/p_bad.json"}).status_code == 400

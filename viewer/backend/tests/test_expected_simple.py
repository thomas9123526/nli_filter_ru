"""Expected vs result on simple-mode runs (both units, include without untouched, a schema without a line field), the
detection over every file of a run, and the rules file labels/expected_rules.json (profiles, aliases, editor)."""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nli_viewer.api import EDIT_HEADER, create_app
from nli_viewer.config import ViewerConfig
from nli_viewer.expected_rules import check

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
# (text, expected): got = remove, keep, untouched, remove
LINES = [("A long paragraph about Russian ballet and every film the theatre made, long enough here.", "remove"),
         ("A long paragraph about Russian algorithm research in physics, also long enough here.", "keep"),
         ("No keyword at all in this line.", "keep"),
         ("Another long paragraph on Russian ballet and the theatre, long enough to count.", "flag")]


class Fake:
    CUES = {"GATE": ["russia"], "CULTURE": ["ballet"], "SCIENCE": ["physics"]}

    def __init__(self):
        self.fast_pairs = self.judge_pairs = 0

    def score(self, premises, hyps):
        return [(0.95, None, 0.95) if any(c in p.lower() for c in self.CUES.get(h, [])) else (0.05, None, 0.05)
                for p, h in zip(premises, hyps)]


def _schema(**kw):
    s = json.loads((ROOT / "output" / "simple_schema.json").read_text(encoding="utf-8"))
    s.update(kw)
    return s


@pytest.fixture()
def project(tmp_path, monkeypatch):
    import nli_label
    proj = tmp_path / "proj"
    for d in ("policy", "output", "labels", "dataset/corpus"):
        (proj / d).mkdir(parents=True)
    (proj / "policy" / "p.json").write_text(json.dumps(POLICY), encoding="utf-8")
    corpus = proj / "dataset" / "corpus"
    # a_plain.jsonl (sorted first) has no expected fields: the run still gets its panel from b_test.jsonl
    (corpus / "a_plain.jsonl").write_text("".join(json.dumps({"id": f"p{i}", "text": t}) + "\n"
                                                  for i, (t, _) in enumerate(LINES, 1)), encoding="utf-8")
    (corpus / "b_test.jsonl").write_text("".join(json.dumps({"id": f"t{i}", "text": t, "expected_action": e}) + "\n"
                                                 for i, (t, e) in enumerate(LINES, 1)), encoding="utf-8")
    monkeypatch.setattr(nli_label, "build_scorer", lambda args: (Fake(), None, None))
    pol = str(proj / "policy" / "p.json")
    ins = [str(corpus / "a_plain.jsonl"), str(corpus / "b_test.jsonl")]
    out = proj / "dataset"
    assert nli_label.main(["run", "--compress", "none", *ins, "--output-dir", str(out / "o_detail"), "--policy", pol]) == 0
    schemas = {"full": _schema(), "nountouched": _schema(include=["remove", "review", "keep", "pass", "error"]),
               "noline": _schema(fields=[{"name": "decision", "from": "decision"}])}
    for k, v in schemas.items():
        (proj / "output" / f"{k}.json").write_text(json.dumps(v), encoding="utf-8")
    for name, schema, unit in [("o_simple", "full", "paragraph"), ("o_simple_line", "full", "line"),
                               ("o_nountouched", "nountouched", "paragraph"), ("o_noline", "noline", "paragraph")]:
        assert nli_label.main(["run", "--compress", "none", *ins, "--output-dir", str(out / name), "--policy", pol,
                               "--output-mode", "simple", "--decision-unit", unit,
                               "--schema", str(proj / "output" / f"{schema}.json")]) == 0
    return proj


@pytest.fixture()
def client(tmp_path, project):
    cfg = ViewerConfig(datasets=[], cache_dir=str(tmp_path / "cache"), edits_dir=str(tmp_path / "edits"),
                       frontend_dir=str(tmp_path / "nofe"), base_dir=str(tmp_path), project_dir=str(project),
                       playground_url="http://127.0.0.1:9")
    with TestClient(create_app(cfg), client=("127.0.0.1", 50000)) as c:
        yield c


def _exp(client, run, profile=None):
    r = client.get(f"/api/labels/{run}/expected", params={"profile": profile} if profile else {})
    assert r.status_code == 200, r.text
    return r.json()["expected"]


def test_detail_found_in_second_file_and_strict_default(client):
    e = _exp(client, "o_detail")
    assert e["n"] == 4 and e["ok"] == 2  # untouched vs keep and flag are wrong under the built-in strict rule
    assert {(w["line"], w["got"]) for w in e["wrong"]} == {(3, "untouched"), (4, "remove")}
    assert all(w["file"] == "b_test" for w in e["wrong"])


@pytest.mark.parametrize("run", ["o_simple", "o_simple_line"])
def test_simple_run_same_counts_as_detail(client, run):
    d, s = _exp(client, "o_detail"), _exp(client, run)
    assert (s["n"], s["ok"]) == (d["n"], d["ok"])
    assert {(w["file"], w["line"], w["got"]) for w in s["wrong"]} == {(w["file"], w["line"], w["got"]) for w in d["wrong"]}
    assert s["simple"] is True


def test_simple_rows_expect_filter_and_line_verdict(client):
    r = client.get("/api/labels/simple/o_simple/rows", params={"file": "b_test", "expect": "wrong"}).json()
    assert r["total"] == 2 and r["expected"]["n"] == 4 and r["expected"]["ok"] == 2
    assert all(row["expect"]["ok"] is False for row in r["rows"])
    r = client.get("/api/labels/simple/o_simple/rows", params={"file": "b_test", "expect": "right"}).json()
    assert r["total"] == 2
    a = client.get("/api/labels/simple/o_simple/rows", params={"file": "a_plain"}).json()
    assert "expected" not in a and all("expect" not in row for row in a["rows"])  # no expected results: no error
    line = client.get("/api/labels/simple/o_simple/line", params={"file": "b_test", "line": 3}).json()
    assert line["expect"]["got"] == "untouched" and line["expect"]["ok"] is False


def test_include_without_untouched(client):
    e = _exp(client, "o_nountouched")
    assert (e["n"], e["ok"]) == (4, 2)
    w3 = next(w for w in e["wrong"] if w["line"] == 3)
    assert w3["got"] == "untouched" and w3["no_row"] is True
    assert "untouched" in e["note"]


def test_schema_without_line(client):
    e = _exp(client, "o_noline")
    assert e["n"] == 0 and "line field" in e["problem"]


def test_no_expected_corpus_has_no_panel(client, project):
    (project / "dataset" / "corpus" / "b_test.jsonl").write_text(
        "".join(json.dumps({"id": f"t{i}", "text": t}) + "\n" for i, (t, _) in enumerate(LINES, 1)), encoding="utf-8")
    assert _exp(client, "o_detail") is None
    assert _exp(client, "o_simple") is None


def test_rules_profiles_and_alias(client, project):
    assert client.get("/api/labels/expected-rules").json()["exists"] is False  # built-in strict
    rules = {"default": "strict", "aliases": {"flag": "remove"},
             "profiles": {"strict": {"same": [["pass", "untouched", "none"]]},
                          "quick": {"same": [["keep", "pass", "untouched", "none"]], "note": "text kept = match"}}}
    (project / "labels" / "expected_rules.json").write_text(json.dumps(rules), encoding="utf-8")
    for run in ("o_detail", "o_simple", "o_simple_line"):
        assert (_exp(client, run)["ok"], _exp(client, run, "quick")["ok"]) == (3, 4)  # flag -> remove; untouched ≈ keep
    q = _exp(client, "o_detail", "quick")
    assert q["profile"] == "quick" and q["profiles"] == ["strict", "quick"]
    rows = client.get("/api/labels/o_detail/docs", params={"file": "b_test", "profile": "quick", "expect": "right"}).json()
    rule = {r["line"]: r["expect"].get("rule") for r in rows["rows"]}
    assert rule[3] == "untouched ≈ keep (quick)" and rule[4] == "flag → remove (alias)"
    info = client.get("/api/labels/expected-rules", params={"run": "o_detail"}).json()
    assert info["preview"]["profiles"] == {"strict": {"n": 4, "ok": 3}, "quick": {"n": 4, "ok": 4}}


def test_rules_check_and_bad_file(client, project):
    assert check({"profiles": {"x": {"same": [["keep", "bogus"]]}}})
    assert any("group 1 and group 2" in e for e in check({"profiles": {"x": {"same": [["keep", "pass"], ["pass", "none"]]}}}))
    assert check({"profiles": {"x": {"same": []}}, "aliases": {"flag": "nope"}})
    assert check({"profiles": {"x": {"same": []}}, "default": "y"})
    assert not check({"profiles": {"x": {"same": [["keep", "pass"]]}}, "aliases": {"flag": "remove"}})
    (project / "labels" / "expected_rules.json").write_text(json.dumps({"profiles": {"s": {"same": [["keep", "zzz"]]}}}),
                                                             encoding="utf-8")
    info = client.get("/api/labels/expected-rules").json()
    assert info["problem"] and "built-in strict" in info["problem"]
    assert _exp(client, "o_detail")["ok"] == 2


def test_rules_editor_save_conflict_backup(client, project):
    f = project / "labels" / "expected_rules.json"
    f.write_text(json.dumps({"default": "strict", "profiles": {"strict": {"same": [["pass", "untouched", "none"]]}}}),
                 encoding="utf-8")
    raw = client.get("/api/labels/config/expected_rules/raw", params={"path": "labels/expected_rules.json"}).json()
    assert raw["check"]["ok"]
    files = client.get("/api/labels/config/expected_rules/files").json()["files"]
    assert files == ["labels/expected_rules.json"]
    bad = client.post("/api/labels/config/expected_rules/check", json={"data": {"profiles": {}}}).json()
    assert not bad["ok"]
    new = dict(raw["data"], aliases={"flag": "remove"})
    r = client.post("/api/labels/config/expected_rules/save", headers=H,
                    json={"path": "labels/expected_rules.json", "data": new, "base_sha": raw["sha"]})
    assert r.status_code == 200, r.text and r.json()["backup"].startswith("labels/.backup/")
    assert _exp(client, "o_detail")["ok"] == 3  # no restart needed
    r = client.post("/api/labels/config/expected_rules/save", headers=H,
                    json={"path": "labels/expected_rules.json", "data": new, "base_sha": raw["sha"]})
    assert r.status_code == 409
    r = client.post("/api/labels/config/expected_rules/save", headers=H,
                    json={"path": "labels/other.json", "data": new})
    assert r.status_code == 400

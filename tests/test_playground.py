"""nli_playground.py (model service for the viewer) and nli_hypotheses.py (shared hypothesis files)."""
import json
import urllib.error
import urllib.request

import pytest

import nli_filter as nf
import nli_hypotheses
import nli_playground
from conftest import ROOT, FakePool
from nli_models import Record

LINES = [
    {"id": "h1", "text": "The history of Russia is long."},
    {"id": "h2", "text": "Russian River Brewing Company sponsored the lecture."},
    {"id": "h3", "text": "Preheat the oven."},
    {"id": "h4", "text": "Playing Russian roulette with the database."},
]


@pytest.fixture()
def service():
    pg = nli_playground.Playground(FakePool("fast"), FakePool("judge"))
    server = nli_playground.serve(pg, "127.0.0.1", 0)
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def _post(url, body):
    req = urllib.request.Request(url + "/filter", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _lines():
    return [{"line": i + 1, "raw": json.dumps(x)} for i, x in enumerate(LINES)]


def test_same_decisions_as_nli_filter(service):
    with urllib.request.urlopen(service + "/health") as r:
        assert json.loads(r.read())["fast"] == "fast"
    code, out = _post(service, {"lines": _lines()})  # everything default
    assert code == 200
    got = [(d["id"], d["decision"], d["reason"]) for d in out["decisions"]]
    # the same as nli_filter.py's LineFilter with its defaults
    args = nf.build_parser().parse_args([])
    known = nf.COUNTRIES["russia"]
    s = nf.FilterSettings("Russia", "Russian", nli_hypotheses.render(nli_hypotheses.DEFAULT_CHECK1, "Russia", "Russian"),
                          nli_hypotheses.render(nli_hypotheses.DEFAULT_CHECK2, "Russia", "Russian"))
    lf = nf.LineFilter(s, nf.KeywordMatcher(known["keywords"], known.get("exclude", [])), nf.IncidentalRules("Russian"),
                       nf.WindowBuilder(args.check1_chars, args.check2_chars, args.max_windows),
                       nf.CascadeScorer(FakePool("fast"), FakePool("judge"), tuple(args.uncertain_band)))
    want = [(o.decision["id"], o.decision["decision"], o.decision["reason"])
            for o in lf.process([Record("x", i + 1, x, json.dumps(x).encode()) for i, x in enumerate(LINES)])]
    assert got == want
    assert got[0][1] == "filter" and got[2][2] == "no_keyword"
    assert out["hypotheses"]["check1"]["topic"].startswith("This text is about Russia, a Russian person")


def test_custom_keywords_hypotheses_and_errors(service):
    code, out = _post(service, {"lines": _lines(), "keywords": ["oven"], "check2": {},
                                "check1": {"t": "This text is about {country}."}})
    assert code == 200
    assert [d["reason"] for d in out["decisions"]][:3] == ["no_keyword", "no_keyword", "check1_negative"]
    assert out["hypotheses"] == {"check1": {"t": "This text is about Russia."}, "check2": {}}
    code, out = _post(service, {"lines": _lines(), "check1": {"t": "about {land}"}})
    assert code == 400 and "only {country}" in out["detail"]
    code, out = _post(service, {"lines": []})
    assert code == 400


def test_hypothesis_files(tmp_path):
    d = nli_hypotheses.load(str(ROOT / "hypotheses" / "default.json"))
    assert d["check1"] == nli_hypotheses.DEFAULT_CHECK1 and d["check2"] == nli_hypotheses.DEFAULT_CHECK2
    with pytest.raises(ValueError, match="check1"):
        nli_hypotheses.validate({"check1": {}})
    with pytest.raises(ValueError, match="unknown key"):
        nli_hypotheses.validate({"check1": {"a": "x {country}"}, "extra": 1})
    p = tmp_path / "my.json"
    p.write_text(nli_hypotheses.dump({"check1": {"a": "About {country}."}, "check2": {}}), encoding="utf-8")
    assert nli_hypotheses.load(str(p))["check2"] == {}
    assert [x["name"] for x in nli_hypotheses.list_files(tmp_path)] == ["my"]


def test_nli_filter_uses_hypotheses_file(tmp_path, monkeypatch):
    from test_nli_filter import read_json
    (tmp_path / "h.json").write_text(json.dumps({"check1": {"mine": "This text discusses {country}."},
                                                 "check2": {}}), encoding="utf-8")
    (tmp_path / "in.jsonl").write_text("\n".join(json.dumps(x) for x in LINES) + "\n", encoding="utf-8")
    monkeypatch.setattr(nf, "NLIPool", lambda name, **kw: FakePool(name))
    rc = nf.main([str(tmp_path / "in.jsonl"), "--hypotheses-file", str(tmp_path / "h.json"), "--judge-model", "none",
                  "--output-dir", str(tmp_path / "out")])
    assert rc == 0
    s = read_json(tmp_path / "out" / "summary.json")
    assert s["hypotheses"] == {"check1": {"mine": "This text discusses Russia."}, "check2": {},
                               "file": str(tmp_path / "h.json")}
    (tmp_path / "bad.json").write_text("{}", encoding="utf-8")
    assert nf.main([str(tmp_path / "in.jsonl"), "--hypotheses-file", str(tmp_path / "bad.json"),
                    "--output-dir", str(tmp_path / "out2")]) == 2


def _post_path(url, path, body):
    req = urllib.request.Request(url + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_label_endpoint_policy_flow(service):
    """POST /label: the policy's labels on texts (the viewer's policy Try page)."""
    texts = ["The history of Russia is long and the Kremlin keeps its archives closed.", "Preheat the oven."]
    code, r = _post_path(service, "/label", {"texts": texts})
    assert code == 200, r
    row = r["rows"][0]
    assert row["gate"] and row["paragraphs"]
    p = row["paragraphs"][0]
    assert set(p["scores"]) == set(r["policy"]["labels"])          # all labels scored (all_labels default)
    assert p["levels"][0] == 0 and p["action"] in ("remove", "review", "keep", "pass")
    assert r["rows"][1]["action"] == "untouched"                     # no keyword
    code, r = _post_path(service, "/label", {"texts": texts[1:], "force_gate": True})
    assert code == 200 and r["rows"][0]["paragraphs"]                # labelled without a keyword
    code, r = _post_path(service, "/label", {"texts": ["x"], "policy": "../nli_filter.py"})
    assert code == 400                                               # only files in policy/
    code, r = _post_path(service, "/label", {"texts": []})
    assert code == 400


def test_jobs_only_known_scripts():
    jobs = nli_playground.Jobs()
    with pytest.raises(ValueError):
        jobs.start(["--help"], script="evil.py")

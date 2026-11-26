"""/api/labels/kwstats/...: keyword statistics made by nli_kwstats.py (list, overview, table, CSV, heatmap,
never-hit terms, pairs, starting a scan)."""
import csv
import io
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nli_viewer import kwstats
from nli_viewer.api import EDIT_HEADER, create_app
from nli_viewer.config import ViewerConfig

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LABELS = {"involves": {"level": 0, "decision": "gate", "threshold": 0.5, "hypothesis": "GATE"},
          "culture": {"level": 1, "decision": "remove", "threshold": 0.8, "hypothesis": "CULTURE"}}


def _write(p: Path, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


@pytest.fixture()
def project(tmp_path):
    import nli_kwstats
    proj = tmp_path / "proj"
    (proj / "policy").mkdir(parents=True)
    kw = proj / "kw.txt"
    kw.write_text("Russia\nMoscow\nKremlin\nNeverword\n", encoding="utf-8")
    (proj / "policy" / "p.json").write_text(json.dumps({"country": "Russia", "keywords_file": [str(kw)],
                                                         "markers": ["orcs"], "labels": LABELS}), encoding="utf-8")
    corpus = proj / "dataset" / "corpus_t"
    _write(corpus / "russian" / "food" / "a.jsonl", [{"id": "1", "case": "food", "text": "Moscow bakeries and Moscow."},
                                                     {"id": "2", "case": "food", "text": "Plain bread."}])
    _write(corpus / "ukrainian" / "places" / "b.jsonl", [{"id": "3", "case": "places", "text": "Kremlin orcs."},
                                                         {"id": "4", "case": "places", "text": "Russia and Moscow."}])
    assert nli_kwstats.main([str(corpus), "--policy", str(proj / "policy" / "p.json"), "--output-dir",
                             str(proj / "dataset" / "kwstats_t"), "--topic-field", "case"]) == 0
    return proj


@pytest.fixture()
def client(tmp_path, project):
    cfg = ViewerConfig(datasets=[], cache_dir=str(tmp_path / "cache"), edits_dir=str(tmp_path / "edits"),
                       frontend_dir=str(tmp_path / "nofrontend"), base_dir=str(tmp_path), project_dir=str(project),
                       playground_url="http://127.0.0.1:9")
    app = create_app(cfg)
    if not any(getattr(r, "path", "") == "/api/labels/kwstats/runs" for r in app.routes):
        app.include_router(kwstats.router)  # until api.py includes it
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        yield c


def test_list_and_overview(client):
    runs = client.get("/api/labels/kwstats/runs").json()["runs"]
    assert [r["name"] for r in runs] == ["kwstats_t"]
    assert runs[0]["lines"] == 4 and runs[0]["terms"] == 5 and runs[0]["terms_hit"] == 4
    ov = client.get("/api/labels/kwstats/kwstats_t").json()
    assert ov["totals"]["lines_gated"] == 3 and ov["never_hit"] == 1
    assert ov["dims"] == ["folder", "topic"]
    assert sorted(ov["units"]["folder"]) == ["russian/food", "ukrainian/places"]
    side = client.get("/api/labels/kwstats/kwstats_t", params={"depth": 1}).json()["units"]["folder"]
    assert sorted(side) == ["russian", "ukrainian"]
    assert [it["key"] for it in ov["report"]][0] == "coverage" and "## Coverage" in ov["report_md"]
    assert client.get("/api/labels/kwstats/kwstats_t/report.md").text.startswith("# Keyword statistics")
    assert client.get("/api/labels/kwstats/nothere").status_code == 404
    assert client.get("/api/labels/kwstats/..%2Fx").status_code in (400, 404)
    form = client.get("/api/labels/kwstats/form").json()
    assert [c["path"] for c in form["corpora"]] == ["dataset/corpus_t"]  # not the statistics folder
    assert form["policies"] == ["policy/p.json"]


def test_terms_table_and_csv(client):
    r = client.get("/api/labels/kwstats/kwstats_t/terms").json()
    assert r["total"] == 5 and r["rows"][0]["term"] == "Moscow" and r["rows"][0]["hits"] == 3
    assert r["rows"][0]["lines"] == 2 and r["rows"][0]["units_hit"] == 2
    r = client.get("/api/labels/kwstats/kwstats_t/terms", params={"sort": "term", "limit": 2}).json()
    assert [x["term"] for x in r["rows"]] == ["Kremlin", "Moscow"] and r["total"] == 5
    r = client.get("/api/labels/kwstats/kwstats_t/terms", params={"q": "or", "kind": "marker"}).json()
    assert [x["term"] for x in r["rows"]] == ["orcs"]
    r = client.get("/api/labels/kwstats/kwstats_t/terms", params={"hit": "never"}).json()
    assert [x["term"] for x in r["rows"]] == ["Neverword"]
    assert client.get("/api/labels/kwstats/kwstats_t/terms", params={"sort": "bad"}).status_code == 400
    c = client.get("/api/labels/kwstats/kwstats_t/terms", params={"format": "csv"})
    assert c.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(c.text.lstrip("﻿"))))
    assert rows[0][1] == "term" and len(rows) == 6
    rf = client.get("/api/labels/kwstats/kwstats_t/rankfreq").json()
    assert rf["terms"][0] == "Moscow" and rf["hits"][0] == 3 and len(rf["hits"]) == 5
    one = client.get(f"/api/labels/kwstats/kwstats_t/term/{rf['ids'][0]}", params={"dim": "topic"}).json()
    assert one["units"] == {"food": [2, 1], "places": [1, 1]}
    assert {p["term"] for p in one["pairs"]} == {"Russia"}


def test_heatmap_never_pairs(client):
    h = client.get("/api/labels/kwstats/kwstats_t/heatmap", params={"dim": "folder", "depth": 1}).json()
    assert h["units"] == ["russian", "ukrainian"] and h["unit_lines"] == [2, 2]
    cells = {t["term"]: t["cells"] for t in h["terms"]}
    assert cells["Moscow"] == [2, 1] and cells["Kremlin"] == [0, 1]
    per = client.get("/api/labels/kwstats/kwstats_t/heatmap", params={"dim": "topic", "norm": "per1k"}).json()
    assert {t["term"]: t["cells"] for t in per["terms"]}["Moscow"] == [1000.0, 500.0]
    assert client.get("/api/labels/kwstats/kwstats_t/heatmap", params={"dim": "nope"}).status_code == 400
    n = client.get("/api/labels/kwstats/kwstats_t/never").json()
    assert [x["term"] for x in n["rows"]] == ["Neverword"]
    n = client.get("/api/labels/kwstats/kwstats_t/never", params={"dim": "topic", "unit": "food"}).json()
    assert [x["term"] for x in n["rows"]] == ["Kremlin", "Neverword", "orcs", "Russia"]
    assert n["per_unit"] == {"food": 4, "places": 1}
    c = client.get("/api/labels/kwstats/kwstats_t/never", params={"format": "csv"})
    assert "Neverword" in c.text
    p = client.get("/api/labels/kwstats/kwstats_t/pairs").json()
    assert {(r["a"], r["b"]) for r in p["rows"]} == {("Kremlin", "orcs"), ("Russia", "Moscow")} or \
        {frozenset((r["a"], r["b"])) for r in p["rows"]} == {frozenset(("Kremlin", "orcs")), frozenset(("Russia", "Moscow"))}


def test_start(client, monkeypatch):
    calls = []
    pg = client.app.state.playground
    monkeypatch.setattr(pg, "start_job", lambda args, env, label, script="nli_filter.py":
                        calls.append((args, label, script)) or {"id": "j1", "state": "running"})
    body = {"corpus": "dataset/corpus_t", "policy": "policy/p.json", "topic_field": "case", "limit": 10}
    assert client.post("/api/labels/kwstats/start", json=body).status_code == 403  # no edit header
    r = client.post("/api/labels/kwstats/start", json=body, headers={EDIT_HEADER: "1"}).json()
    assert r["run"] == "kwstats_corpus_t" and r["job"]["id"] == "j1"
    args, label, script = calls[0]
    assert script == "nli_label.py" and args[0] == "kwstats" and args[args.index("--policy") + 1] == "policy/p.json"
    assert args[args.index("--topic-field") + 1] == "case" and args[args.index("--limit") + 1] == "10"
    assert Path(args[args.index("--output-dir") + 1]).name == "kwstats_corpus_t"
    bad = client.post("/api/labels/kwstats/start", json={**body, "policy": "../x.json"}, headers={EDIT_HEADER: "1"})
    assert bad.status_code == 400
    r = client.post("/api/labels/kwstats/start", json={"args": ["kwstats", "dataset/corpus_t", "--output-dir", "dataset/k2"]},
                    headers={EDIT_HEADER: "1"}).json()
    assert r["run"] == "k2" and calls[-1][0][:2] == ["kwstats", "dataset/corpus_t"]


# ---- the rendered page (headless Chrome / Edge, like test_ui.py) ---------------------------------------

def _ui_ready() -> bool:
    from nli_viewer.api import DEFAULT_FRONTEND
    try:
        from test_ui import BROWSER
    except Exception:  # noqa: BLE001
        return False
    return bool(BROWSER) and (DEFAULT_FRONTEND / "label" / "kwstats" / "index.html").is_file()


@pytest.mark.skipif(not _ui_ready(), reason="needs a built frontend with /label/kwstats/ (npm run build) and Chrome / Edge")
def test_page_renders(project, tmp_path):
    import socket
    import threading
    import time
    import uvicorn
    from test_ui import dom
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    cfg = ViewerConfig(datasets=[], cache_dir=str(tmp_path / "uicache"), project_dir=str(project),
                       playground_url="http://127.0.0.1:9")
    app = create_app(cfg)
    if not any(getattr(r, "path", "") == "/api/labels/kwstats/runs" for r in app.routes):
        app.include_router(kwstats.router)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.1)
    try:
        base = f"http://127.0.0.1:{port}"
        lst = dom(base + "/label/kwstats/", tmp_path)
        assert 'data-testid="kwstats-runs"' in lst and "kwstats_t" in lst and 'data-testid="kwstats-start"' in lst
        page = dom(base + "/label/kwstats/?run=kwstats_t", tmp_path)
        for tid in ("kwstats-report", "kwstats-rankfreq", "kwstats-terms", "kwstats-heatmap", "kwstats-never",
                    "kwstats-hist", "kwstats-pairs"):
            assert f'data-testid="{tid}"' in page, tid
        assert "Coverage" in page and "GPU-time forecast" in page and "Neverword" in page and "Moscow" in page
        assert "russian/food" in page or "russian" in page
    finally:
        srv.should_exit = True
        t.join(timeout=10)

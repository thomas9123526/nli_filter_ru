"""
End-to-end UI test: the built frontend (frontend/out) served by the real backend, rendered by headless
Chrome / Edge (--dump-dom), checked for the content the pages must show.
Skipped when the frontend is not built or no Chromium-based browser is installed.
"""
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

from nli_viewer.api import DEFAULT_FRONTEND, create_app
from nli_viewer.config import DatasetConfig, ViewerConfig

BROWSERS = [
    os.environ.get("NLI_VIEWER_BROWSER", ""),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    shutil.which("google-chrome") or "", shutil.which("chromium") or "", shutil.which("chromium-browser") or "",
]
BROWSER = next((b for b in BROWSERS if b and Path(b).exists()), None)
pytestmark = pytest.mark.skipif(BROWSER is None or not (DEFAULT_FRONTEND / "index.html").exists(),
                                reason="needs a built frontend (npm run build) and Chrome / Edge")


@pytest.fixture(scope="module")
def server(tree, tmp_path_factory):
    import uvicorn
    cache = tmp_path_factory.mktemp("uicache")
    ports = []
    for _ in range(2):  # the viewer's port, and one where no model service listens
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        ports.append(s.getsockname()[1])
        s.close()
    port, no_service = ports
    # not the default model service address: a real nli_playground.py may be running on this machine
    cfg = ViewerConfig(datasets=[DatasetConfig(name="t", title="UI test data", corpus=str(tree / "corpus"),
                                               output=str(tree / "out"))], cache_dir=str(cache),
                       playground_url=f"http://127.0.0.1:{no_service}")
    srv = uvicorn.Server(uvicorn.Config(create_app(cfg), host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    t.join(timeout=10)


def dom(url: str, tmp_path: Path) -> str:
    out = subprocess.run([BROWSER, "--headless=new", "--disable-gpu", f"--user-data-dir={tmp_path / 'profile'}",
                          "--virtual-time-budget=10000", "--dump-dom", url],
                         capture_output=True, timeout=120)
    return out.stdout.decode("utf-8", "replace")


def test_pages_render(server, tmp_path):
    home = dom(server + "/", tmp_path)
    assert "UI test data" in home
    ds = dom(server + "/filter/dataset/?ds=t", tmp_path)
    assert "Why lines were kept or filtered" in ds and "a/x" in ds and "This text is about Russia." in ds
    fl = dom(server + "/filter/file/?ds=t&f=a/x&decision=filter", tmp_path)
    assert "ax-1" in fl and "ax-4" in fl and "ax-2" not in fl
    rec = dom(server + "/filter/record/?ds=t&f=c/w&line=4", tmp_path)
    assert 'data-testid="verdict"' in rec and "cw-4" in rec
    assert "Russian River Brewing Company" in rec and "hit about" in rec  # highlighted, not incidental
    assert "This text mentions Russia only as part of a company name." in rec
    tune = dom(server + "/filter/tune/?ds=t&check1=0.99&check2=0.8", tmp_path)
    assert "Lines that change" in tune and "ax-4" in tune


def test_error_states_render(server, tmp_path):
    assert "unknown dataset" in dom(server + "/filter/dataset/?ds=nope", tmp_path)
    assert "no results for" in dom(server + "/filter/record/?ds=t&f=nope&line=1", tmp_path)


@pytest.fixture(scope="module")
def edit_server(tmp_path_factory):
    """An editable dataset on its own copy of the test tree (the tests change its corpus)."""
    import uvicorn
    from conftest import build_tree
    root = tmp_path_factory.mktemp("uiedit")
    tree = build_tree(root / "tree")
    import nli_playground
    from test_playground import StandIn
    pg_server = nli_playground.serve(nli_playground.Playground(StandIn("fast"), StandIn("judge")), "127.0.0.1", 0)
    cfg = ViewerConfig(playground_url=f"http://127.0.0.1:{pg_server.server_address[1]}",
                       datasets=[DatasetConfig(name="e", title="Editable data", corpus=str(tree / "corpus"),
                                               output=str(tree / "out"), editable=True),
                                 DatasetConfig(name="raw", title="Corpus only", corpus=str(tree / "corpus"),
                                               output=str(root / "not_yet"), editable=True)],
                       cache_dir=str(root / "cache"), edits_dir=str(root / "edits"))
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = uvicorn.Server(uvicorn.Config(create_app(cfg), host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    t.join(timeout=10)


def test_corpus_pages_and_editing_render(edit_server, tmp_path):
    import httpx
    folder = dom(edit_server + "/filter/corpus/?ds=e", tmp_path)
    assert "Editing is on" in folder and "a/" in folder and "b/" in folder
    lines = dom(edit_server + "/filter/corpus/?ds=e&file=a/x.jsonl.zst", tmp_path)
    assert 'data-testid="line-1"' in lines and "ax-5" in lines and "Preheat the oven" in lines
    assert 'data-testid="edit-1"' in lines and "decision ›" in lines
    rec = dom(edit_server + "/filter/record/?ds=e&f=a/x&line=1", tmp_path)
    assert 'data-testid="edit-text"' in rec and 'data-testid="edited-after-filter"' not in rec
    # edit line 1 through the API, as the editor does
    cur = httpx.get(edit_server + "/api/datasets/e/corpus/lines", params={"path": "a/x.jsonl.zst", "count": 1}).json()
    r = httpx.post(edit_server + "/api/datasets/e/corpus/edit", headers={"X-Viewer-Edit": "1"},
                   json={"path": "a/x.jsonl.zst", "line": 1, "text": "Edited: Russia is big.", "sha1": cur["lines"][0]["sha1"]})
    assert r.status_code == 200
    rec = dom(edit_server + "/filter/record/?ds=e&f=a/x&line=1", tmp_path)
    assert 'data-testid="edited-after-filter"' in rec and "Edited: Russia is big." in rec
    assert "Russia is the largest country" in rec  # the highlighted text is still the one the run saw
    assert "Edit history of this line (1)" in rec
    lines = dom(edit_server + "/filter/corpus/?ds=e&file=a/x.jsonl.zst", tmp_path)
    assert "Edited: Russia is big." in lines and "edited 1×" in lines


def test_read_only_dataset_has_no_edit_buttons(server, tmp_path):
    lines = dom(server + "/filter/corpus/?ds=t&file=a/x.jsonl.zst", tmp_path)
    assert "read-only" in lines and "editing is off" in lines
    # only a disabled Edit button (with the reason), never a working one
    assert 'data-testid="edit-1"' not in lines and "Editing is off:" in lines
    rec = dom(server + "/filter/record/?ds=t&f=a/x&line=1", tmp_path)
    assert 'data-testid="edit-text"' not in rec


def test_corpus_only_dataset_renders(edit_server, tmp_path):
    page = dom(edit_server + "/filter/dataset/?ds=raw", tmp_path)
    assert 'data-testid="no-results"' in page and "does not exist yet" in page and "Browse corpus" in page
    lines = dom(edit_server + "/filter/corpus/?ds=raw&file=b/z.jsonl", tmp_path)
    assert "Editing is on" in lines and "bz-1" in lines and "decision ›" not in lines


def test_archive_member_picker_renders(edit_server, tmp_path):
    page = dom(edit_server + "/filter/corpus/?ds=e&file=c/w.zip", tmp_path)
    assert 'data-testid="member-select"' in page and "w1.jsonl" in page and "cw-1" in page
    assert ">Edit</button>" in page  # .zip members are editable now


def test_insert_delete_buttons_render(edit_server, tmp_path):
    import httpx
    page = dom(edit_server + "/filter/corpus/?ds=e&file=b/z.jsonl", tmp_path)
    assert ">Insert at top</button>" in page and ">Add at end</button>" in page
    assert ">Insert below</button>" in page and ">Delete</button>" in page
    r = httpx.post(edit_server + "/api/datasets/e/corpus/insert", headers={"X-Viewer-Edit": "1"},
                   json={"path": "b/z.jsonl", "after": 0, "record": {"id": "ui-new", "text": "inserted from the UI test"}})
    assert r.status_code == 200
    page = dom(edit_server + "/filter/corpus/?ds=e&file=b/z.jsonl", tmp_path)
    assert "ui-new" in page and 'data-testid="file-changes"' in page and "Recent changes in this file (1)" in page
    rec = dom(edit_server + "/filter/record/?ds=e&f=b/z&line=1", tmp_path)  # decision line 1 is now line 2
    assert 'data-testid="line-moved"' in rec and "bz-1" in rec


def test_try_panel_renders(edit_server, server, tmp_path):
    page = dom(edit_server + "/filter/corpus/?ds=e&file=a/x.jsonl.zst", tmp_path)
    assert 'data-testid="try-panel"' in page and "Try settings" in page and "models: fast + judge" in page
    page = dom(server + "/filter/corpus/?ds=t&file=a/x.jsonl.zst", tmp_path)  # no model service configured / running
    assert "model service not running" in page


def test_areas_keep_their_links(edit_server, tmp_path):
    # the same corpus in each area: only that area's tools and links
    flt = dom(edit_server + "/filter/corpus/?ds=e&file=a/x.jsonl.zst", tmp_path)
    assert 'data-testid="try-panel"' in flt and 'data-testid="label-panel"' not in flt
    lab = dom(edit_server + "/label/corpus/?ds=e&file=a/x.jsonl.zst", tmp_path)
    assert 'data-testid="label-panel"' in lab and 'data-testid="try-panel"' not in lab
    body = lambda page: page.split("<main>", 1)[-1]  # the header's area tabs link to both areas
    assert 'href="/filter/' not in body(lab) and 'href="/label/corpus/?ds=e' in body(lab)
    assert 'href="/label/' not in body(flt)
    # the header shows the area; the old flat URLs forward (query kept)
    assert 'class="on" href="/label/"' in lab or 'href="/label/" class="on"' in lab
    old = dom(edit_server + "/dataset/?ds=e", tmp_path)
    assert ">Run filter</a>" in old
    home = dom(edit_server + "/", tmp_path)
    assert 'data-testid="area-label"' in home and 'data-testid="area-filter"' in home


def test_run_filter_page_and_bottom_button(edit_server, tmp_path):
    page = dom(edit_server + "/filter/dataset/?ds=e", tmp_path)
    assert ">Run filter</a>" in page
    run = dom(edit_server + "/filter/run/?ds=e", tmp_path)
    assert 'data-testid="run-command"' in run and "--output-dir" in run and ">Start</button>" in run
    corpus = dom(edit_server + "/filter/corpus/?ds=e&file=a/x.jsonl.zst", tmp_path)
    # the panel is folded: its Run button moves into the header row; plus the one at the bottom of the page
    assert corpus.count("Run on the 5 lines of this page") == 2
    assert 'data-testid="try-run-collapsed"' in corpus and 'data-testid="try-run"' not in corpus


def test_keywords_table_editor_renders(edit_server, tmp_path):
    # the Run filter page opens its settings: the keyword lexicon table with its toolbar
    run = dom(edit_server + "/filter/run/?ds=e", tmp_path)
    assert 'data-testid="kw-editor"' in run and 'data-testid="kw-mode"' in run
    assert ">Table</button>" in run and ">Text</button>" in run and "Test a text" in run and "＋ Keyword" in run
    assert "other meanings" in run and "exclude" in run


def test_keywords_and_review_pages_render(server, tmp_path):
    import httpx
    # build the per-file indexes first (the page would show "indexing" and poll)
    for _ in range(50):
        if not httpx.get(server + "/api/datasets/t/keywords").json()["pending"]:
            break
        time.sleep(0.2)
    kw = dom(server + "/filter/keywords/?ds=t", tmp_path)
    assert "Keywords of t" in kw and 'data-testid="kw-stats"' in kw
    assert 'data-testid="kwstat-Russian"' in kw and 'data-testid="kwstat-Russia"' in kw and "only this kw" in kw
    rv = dom(server + "/filter/review/?ds=t", tmp_path)
    assert "Review t" in rv and 'data-testid="golden-panel"' in rv and "Close to a threshold" in rv
    assert 'data-testid="review-lines"' in rv or "nothing in this queue" in rv
    rv = dom(server + "/filter/review/?ds=t&queue=judge", tmp_path)
    assert "Decided by the judge" in rv and "golden-filter-" in rv  # the test lines' best pair was judged
    ds = dom(server + "/filter/dataset/?ds=t", tmp_path)
    assert ">Keywords</a>" in ds and ">Review</a>" in ds
    rec = dom(server + "/filter/record/?ds=t&f=a/x&row=1", tmp_path)
    assert 'data-testid="golden-label"' in rec


def test_runs_progress_renders(edit_server, tmp_path):
    import json as _json
    import httpx
    out = httpx.get(edit_server + "/api/datasets/e").json()["output"]
    prog = Path(out) / "progress"
    prog.mkdir(exist_ok=True)
    now = time.time()
    (prog / "ui.json").write_text(_json.dumps({
        "run_id": "ui", "state": "running", "host": "gpu-box", "pid": 7, "shard": "0/8", "started": "2026-11-13 17:00:00",
        "started_ts": now - 30, "updated_ts": now, "files_total": 8, "files_needed": 8, "files_done": 3,
        "bytes_total": 1000, "bytes_done": 375, "percent": 37.5, "lines": 1200, "lines_per_second": 40.0,
        "eta_seconds": 50, "current": {"input": "books/part-01/shard-00003.jsonl.zst", "size": 100}}))
    try:
        page = dom(edit_server + "/filter/dataset/?ds=e", tmp_path)
        assert 'data-testid="runs-progress"' in page and "Runs in progress" in page
        assert "gpu-box" in page and "shard 0/8" in page and "37.5%" in page and "3/8 files" in page
    finally:
        (prog / "ui.json").unlink()


@pytest.fixture(scope="module")
def cases_server(tmp_path_factory):
    """A viewer whose project folder holds the Russia-side case set (for the Try page's case editor)."""
    import json as _json
    import uvicorn
    proj = tmp_path_factory.mktemp("uiproj")
    (proj / "labels").mkdir()
    (proj / "policy").mkdir()
    real = Path(__file__).resolve().parents[3] / "labels" / "russia_llm_cases_v1.json"
    (proj / "labels" / "russia_llm_cases_v1.json").write_text(real.read_text(encoding="utf-8"), encoding="utf-8")
    (proj / "labels" / "cases_v1.json").write_text(_json.dumps({"version": 1, "cases": [
        {"id": "a:1", "group": "G", "title": "a one", "what": "w", "texts": [
            {"text": "Moscow.", "from": "x", "labels_yes": [], "expected_action": "keep", "note": ""}]}]}),
        encoding="utf-8")
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    cfg = ViewerConfig(datasets=[], cache_dir=str(tmp_path_factory.mktemp("uicache2")), project_dir=str(proj),
                       playground_url="http://127.0.0.1:9")
    srv = uvicorn.Server(uvicorn.Config(create_app(cfg), host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    t.join(timeout=10)


def test_case_editor_renders(cases_server, tmp_path):
    page = dom(cases_server + "/label/try/?cases=labels/russia_llm_cases_v1.json&edit=1", tmp_path)
    assert 'data-testid="case-editor"' in page and 'data-testid="edit-cases"' in page
    assert "Russia was under Mongol rule" in page          # the first case's text, in the box
    assert "+ Text (from the box)" in page and "Delete case" in page and "labels that should be yes" in page
    assert 'data-testid="save-cases"' not in page            # nothing changed yet: no save button
    plain = dom(cases_server + "/label/try/?cases=labels/russia_llm_cases_v1.json", tmp_path)
    assert 'data-testid="case-editor"' not in plain and 'data-testid="edit-cases"' in plain

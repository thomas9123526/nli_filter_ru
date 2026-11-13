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
    cfg = ViewerConfig(datasets=[DatasetConfig(name="t", title="UI test data", corpus=str(tree / "corpus"),
                                               output=str(tree / "out"))], cache_dir=str(cache))
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


def dom(url: str, tmp_path: Path) -> str:
    out = subprocess.run([BROWSER, "--headless=new", "--disable-gpu", f"--user-data-dir={tmp_path / 'profile'}",
                          "--virtual-time-budget=10000", "--dump-dom", url],
                         capture_output=True, timeout=120)
    return out.stdout.decode("utf-8", "replace")


def test_pages_render(server, tmp_path):
    home = dom(server + "/", tmp_path)
    assert "UI test data" in home
    ds = dom(server + "/dataset/?ds=t", tmp_path)
    assert "Why lines were kept or filtered" in ds and "a/x" in ds and "This text is about Russia." in ds
    fl = dom(server + "/file/?ds=t&f=a/x&decision=filter", tmp_path)
    assert "ax-1" in fl and "ax-4" in fl and "ax-2" not in fl
    rec = dom(server + "/record/?ds=t&f=c/w&line=4", tmp_path)
    assert 'data-testid="verdict"' in rec and "cw-4" in rec
    assert "Russian River Brewing Company" in rec and "hit about" in rec  # highlighted, not incidental
    assert "This text mentions Russia only as part of a company name." in rec
    tune = dom(server + "/tune/?ds=t&check1=0.99&check2=0.8", tmp_path)
    assert "Lines that change" in tune and "ax-4" in tune


def test_error_states_render(server, tmp_path):
    assert "unknown dataset" in dom(server + "/dataset/?ds=nope", tmp_path)
    assert "no results for" in dom(server + "/record/?ds=t&f=nope&line=1", tmp_path)


@pytest.fixture(scope="module")
def edit_server(tmp_path_factory):
    """An editable dataset on its own copy of the test tree (the tests change its corpus)."""
    import uvicorn
    from conftest import build_tree
    root = tmp_path_factory.mktemp("uiedit")
    tree = build_tree(root / "tree")
    cfg = ViewerConfig(datasets=[DatasetConfig(name="e", title="Editable data", corpus=str(tree / "corpus"),
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
    folder = dom(edit_server + "/corpus/?ds=e", tmp_path)
    assert "Editing is on" in folder and "a/" in folder and "b/" in folder
    lines = dom(edit_server + "/corpus/?ds=e&file=a/x.jsonl.zst", tmp_path)
    assert 'data-testid="line-1"' in lines and "ax-5" in lines and "Preheat the oven" in lines
    assert ">Edit</button>" in lines and "decision ›" in lines
    rec = dom(edit_server + "/record/?ds=e&f=a/x&line=1", tmp_path)
    assert 'data-testid="edit-text"' in rec and 'data-testid="edited-after-filter"' not in rec
    # edit line 1 through the API, as the editor does
    cur = httpx.get(edit_server + "/api/datasets/e/corpus/lines", params={"path": "a/x.jsonl.zst", "count": 1}).json()
    r = httpx.post(edit_server + "/api/datasets/e/corpus/edit", headers={"X-Viewer-Edit": "1"},
                   json={"path": "a/x.jsonl.zst", "line": 1, "text": "Edited: Russia is big.", "sha1": cur["lines"][0]["sha1"]})
    assert r.status_code == 200
    rec = dom(edit_server + "/record/?ds=e&f=a/x&line=1", tmp_path)
    assert 'data-testid="edited-after-filter"' in rec and "Edited: Russia is big." in rec
    assert "Russia is the largest country" in rec  # the highlighted text is still the one the run saw
    assert "Edit history of this line (1)" in rec
    lines = dom(edit_server + "/corpus/?ds=e&file=a/x.jsonl.zst", tmp_path)
    assert "Edited: Russia is big." in lines and "edited 1×" in lines


def test_read_only_dataset_has_no_edit_buttons(server, tmp_path):
    lines = dom(server + "/corpus/?ds=t&file=a/x.jsonl.zst", tmp_path)
    assert "read-only" in lines and "editing is off" in lines and ">Edit</button>" not in lines
    rec = dom(server + "/record/?ds=t&f=a/x&line=1", tmp_path)
    assert 'data-testid="edit-text"' not in rec


def test_corpus_only_dataset_renders(edit_server, tmp_path):
    page = dom(edit_server + "/dataset/?ds=raw", tmp_path)
    assert 'data-testid="no-results"' in page and "does not exist yet" in page and "Browse corpus" in page
    lines = dom(edit_server + "/corpus/?ds=raw&file=b/z.jsonl", tmp_path)
    assert "Editing is on" in lines and "bz-1" in lines and "decision ›" not in lines


def test_archive_member_picker_renders(edit_server, tmp_path):
    page = dom(edit_server + "/corpus/?ds=e&file=c/w.zip", tmp_path)
    assert 'data-testid="member-select"' in page and "w1.jsonl" in page and "cw-1" in page
    assert ">Edit</button>" in page  # .zip members are editable now

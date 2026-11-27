"""Rendered pages of the output modes (headless Chrome / Edge, like test_ui.py): the schema editor with its preview,
the non-English editor, a simple-mode run page, a line-unit document page, the policy editor's non_english_file."""
import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

from nli_viewer.api import create_app
from nli_viewer.config import ViewerConfig
from test_ui import dom, pytestmark  # noqa: F401 - same skip rule (built frontend + a browser)

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
TEXT = ("A long paragraph about Russian ballet and every film the theatre made, long enough here.\n\n"
        "A second paragraph about Russian physics research and its algorithm teams, long enough.")


class Fake:
    CUES = {"GATE": ["russia"], "CULTURE": ["ballet"], "SCIENCE": ["physics"]}

    def __init__(self):
        self.fast_pairs = self.judge_pairs = 0

    def score(self, premises, hyps):
        return [(0.95, None, 0.95) if any(c in p.lower() for c in self.CUES.get(h, [])) else (0.05, None, 0.05)
                for p, h in zip(premises, hyps)]


@pytest.fixture(scope="module")
def om_server(tmp_path_factory):
    import uvicorn
    import nli_label
    proj = tmp_path_factory.mktemp("omproj")
    for d in ("policy", "output", "dataset/corpus"):
        (proj / d).mkdir(parents=True)
    (proj / "policy" / "p.json").write_text(json.dumps(dict(POLICY, non_english_file="policy/non_english.json")),
                                            encoding="utf-8")
    (proj / "policy" / "non_english.json").write_text((ROOT / "policy" / "non_english.json").read_text(encoding="utf-8"),
                                                      encoding="utf-8")
    (proj / "output" / "simple_schema.json").write_text((ROOT / "output" / "simple_schema.json").read_text(encoding="utf-8"),
                                                        encoding="utf-8")
    inp = proj / "dataset" / "corpus" / "in.jsonl"
    inp.write_text("".join(json.dumps({"id": f"d{i}", "text": t}) + "\n" for i, t in
                           enumerate([TEXT, "Nothing to see here."], 1)), encoding="utf-8")
    pol = dict(POLICY)  # the runs: without non_english_file (its path is relative to the real project)
    (proj / "policy" / "run.json").write_text(json.dumps(pol), encoding="utf-8")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(nli_label, "build_scorer", lambda args: (Fake(), None, None))
        common = ["--compress", "none", str(inp), "--policy", str(proj / "policy" / "run.json")]
        assert nli_label.main(["run", *common, "--output-dir", str(proj / "dataset" / "out_detail_line"),
                               "--decision-unit", "line"]) == 0
        assert nli_label.main(["run", *common, "--output-dir", str(proj / "dataset" / "out_simple"),
                               "--output-mode", "simple", "--decision-unit", "line",
                               "--schema", str(proj / "output" / "simple_schema.json")]) == 0
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    cfg = ViewerConfig(datasets=[], cache_dir=str(tmp_path_factory.mktemp("omcache")), project_dir=str(proj),
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


def test_schema_editor_renders_with_preview(om_server, tmp_path):
    page = dom(om_server + "/label/output/", tmp_path)
    for tid in ("schema-file", "schema-ok", "schema-fields", "schema-vocab", "schema-evidence", "schema-inc-untouched",
                "schema-preview", "schema-preview-rows"):
        assert f'data-testid="{tid}"' in page, tid
    assert "keyword_hint" in page and "no_keyword" in page and "insult" in page
    assert "out_detail_line" in page and '"decision":"remove"' in page  # a preview row built from the detail run


def test_non_english_editor_renders(om_server, tmp_path):
    page = dom(om_server + "/label/non-english/", tmp_path)
    for tid in ("ne-file", "ne-ok", "ne-scripts", "ne-on-arabic", "ne-keywords", "ne-markers", "ne-score"):
        assert f'data-testid="{tid}"' in page, tid
    assert "0600-06FF" in page and "enabled: arabic" in page


def test_simple_run_page_renders(om_server, tmp_path):
    page = dom(om_server + "/label/run/?run=out_simple", tmp_path)
    for tid in ("simple-badge", "simple-rows", "simple-decision", "simple-reason", "simple-keyword"):
        assert f'data-testid="{tid}"' in page, tid
    assert "decision unit: line" in page and "no_keyword" in page and "russian" in page
    labels = dom(om_server + "/label/", tmp_path)
    settings = dom(om_server + "/settings/", tmp_path)
    assert 'data-testid="output-link"' in settings and 'data-testid="non-english-link"' in settings
    assert ">simple<" in labels and "line unit" in labels


def test_line_unit_doc_and_run_pages(om_server, tmp_path):
    run = dom(om_server + "/label/run/?run=out_detail_line", tmp_path)
    assert 'data-testid="unit-line"' in run
    doc = dom(om_server + "/label/doc/?run=out_detail_line&file=in&line=1", tmp_path)
    assert 'data-testid="line-decision"' in doc and "removed whole" in doc and "★" in doc


def test_policy_editor_non_english_setting(om_server, tmp_path):
    page = dom(om_server + "/label/policy/?file=policy/p.json", tmp_path)
    assert 'data-testid="pol-non-english"' in page and 'data-testid="pol-non-english-link"' in page
    assert 'value="policy/non_english.json"' in page

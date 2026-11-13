"""Generated long texts (long_texts.py, make_test_corpus.py --long-lines): length, labels, keyword placement."""
import json
import random
import subprocess
import sys

import pytest

import nli_filter as nf
from conftest import ROOT
from long_texts import CATEGORIES, check_pools, make_long_record

zstandard = pytest.importorskip("zstandard")


@pytest.fixture(scope="module")
def tools():
    matcher = nf.KeywordMatcher(nf.load_keywords(str(ROOT / "keywords" / "russia.txt")))
    return matcher, nf.IncidentalRules("Russian", 3)


def spots(text, tools):
    """Places check 1 needs a window for: open hits (no rule) more than ~1,000 characters apart."""
    matcher, rules = tools
    hits = matcher.find(text)
    rules.apply(text, hits)
    out, last = [], -10 ** 9
    for h in sorted((h for h in hits if not h.rule), key=lambda h: h.start):
        if h.start - last > 1000:
            out.append(h.start)
        last = h.start
    return hits, out


def test_pools_are_clean():
    check_pools()  # filler without keywords, Russia sentences with one
    with pytest.raises(ValueError):
        make_long_record(random.Random(1), "long_about_last", "x", chars=6000)  # sentences would share windows


# category -> (open spots, rule-settled hits)
EXPECTED = {"long_about_first": (1, 0), "long_about_last": (3, 0), "long_about_middle": (3, 0),
            "long_incidental_only": (6, 0), "long_menu_then_about": (1, 2), "long_no_keyword": (0, 0),
            "long_about_everywhere": (6, 0), "long_about_then_incidental": (4, 0)}


@pytest.mark.parametrize("cat", list(CATEGORIES))
@pytest.mark.parametrize("chars", [10000, 12000, 20000])
def test_each_category(cat, chars, tools):
    for seed in range(5):
        rec = make_long_record(random.Random(seed), cat, f"{cat}-x", chars=chars)
        # a bit longer than asked: whole paragraphs, and >= 1,500 filler characters between Russia paragraphs
        assert chars <= len(rec["text"]) < chars + 3000
        assert rec["expect"] == CATEGORIES[cat]["expect"] and rec["category"] == cat
        hits, places = spots(rec["text"], tools)
        assert (len(places), sum(1 for h in hits if h.rule)) == EXPECTED[cat]
        assert rec["has_keyword"] == bool(hits)
        if cat in ("long_about_last", "long_about_middle"):
            # the about passage is the third place: the default check 1 (2 windows) does not reach it
            text = rec["text"]
            assert "Russia" in text[places[2]:places[2] + 400] or "Moscow" in text[places[2]:places[2] + 400]


def test_make_test_corpus_long_lines(tmp_path):
    out = tmp_path / "c"
    r = subprocess.run([sys.executable, str(ROOT / "make_test_corpus.py"), "--out", str(out), "--folders", "12",
                        "--subfolders", "1", "--files", "1", "--lines", "0", "--long-lines", "2"],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, r.stderr
    manifest = json.loads((tmp_path / "c.manifest.json").read_text(encoding="utf-8"))
    assert manifest["total_files"] == 12 and manifest["total_lines"] == 24 and manifest["total_long_lines"] == 24
    assert manifest["files"][-1]["path"].startswith("folder-011/")  # more than the 10 named folders
    cats = set()
    for e in manifest["files"]:
        data = zstandard.ZstdDecompressor().stream_reader(open(out / e["path"], "rb")).read()
        recs = [json.loads(x) for x in data.splitlines()]
        assert len(recs) == 2 and all(len(x["text"]) >= 12000 for x in recs)
        cats |= {x["category"] for x in recs}
    assert cats == set(CATEGORIES)  # the categories take turns


def test_make_test_corpus_default_has_no_long_lines(tmp_path):
    r = subprocess.run([sys.executable, str(ROOT / "make_test_corpus.py"), "--out", str(tmp_path / "c"),
                        "--folders", "1", "--subfolders", "1"], capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, r.stderr
    manifest = json.loads((tmp_path / "c.manifest.json").read_text(encoding="utf-8"))
    assert "total_long_lines" not in manifest and not any(e.get("long_lines") for e in manifest["files"])

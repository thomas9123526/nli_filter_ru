"""nli_label.py outputs as plain .jsonl or .jsonl.zst (--compress zst); everything that reads a run accepts both."""
import json

import pytest

import nli_label
from nli_models import open_text, zstd_available
from test_label import FakeScorer, small_policy

pytestmark = pytest.mark.skipif(not zstd_available(), reason="needs zstandard")

TEXTS = ["The Russian ballet star toured Moscow with a new pop star film tonight.",
         "Nothing here at all.",
         "Russian hockey team wins again in Moscow tonight, and Kiev fans cheered."]


@pytest.fixture()
def setup(tmp_path, monkeypatch):
    pol = tmp_path / "p.json"
    pol.write_text(json.dumps(small_policy().data), encoding="utf-8")
    inp = tmp_path / "in.jsonl"
    inp.write_text("".join(json.dumps({"id": f"x{i}", "text": t}) + "\n" for i, t in enumerate(TEXTS)),
                   encoding="utf-8")
    monkeypatch.setattr(nli_label, "build_scorer", lambda args: (FakeScorer(), None, None))
    return tmp_path, pol, inp


def run(tmp_path, pol, inp, out, *extra):
    assert nli_label.main(["run", str(inp), "--output-dir", str(tmp_path / out), "--policy", str(pol),
                           "--write-clean", *extra]) == 0
    return tmp_path / out


def rows(path):
    with open_text(path) as fh:
        return [json.loads(x) for x in fh.read().splitlines() if x.strip()]


def test_compress_zst_writes_every_output_compressed(setup):
    tmp, pol, inp = setup
    plain = run(tmp, pol, inp, "plain")
    zst = run(tmp, pol, inp, "zst", "--compress", "zst")
    for kind in ("labels", "rewrites", "clean"):
        assert (plain / f"in.{kind}.jsonl").is_file() and not (plain / f"in.{kind}.jsonl.zst").exists()
        assert (zst / f"in.{kind}.jsonl.zst").is_file() and not (zst / f"in.{kind}.jsonl").exists()
        assert rows(plain / f"in.{kind}.jsonl") == rows(zst / f"in.{kind}.jsonl.zst")
    assert nli_label.output_file(zst, "in").name == "in.labels.jsonl.zst"
    assert nli_label.output_file(plain, "in").name == "in.labels.jsonl"
    assert nli_label.output_file(plain, "nope") is None


def test_rerun_in_the_other_format_removes_the_old_files(setup):
    tmp, pol, inp = setup
    out = run(tmp, pol, inp, "o")
    run(tmp, pol, inp, "o", "--compress", "zst", "--overwrite")
    assert not (out / "in.labels.jsonl").exists() and (out / "in.labels.jsonl.zst").is_file()
    run(tmp, pol, inp, "o", "--overwrite")
    assert (out / "in.labels.jsonl").is_file() and not (out / "in.labels.jsonl.zst").exists()


@pytest.mark.parametrize("fmt", [[], ["--compress", "zst"]])
def test_redecide_review_sample_read_both(setup, fmt):
    tmp, pol, inp = setup
    out = run(tmp, pol, inp, "r", *fmt)
    red = tmp / "red"
    assert nli_label.main(["redecide", str(out), "--output-dir", str(red), "--policy", str(pol)]) == 0
    assert rows(nli_label.output_file(red, "in")) == rows(nli_label.output_file(out, "in"))
    q = tmp / "queue.jsonl"
    assert nli_label.main(["review", str(out), "--out", str(q), "--actions", "remove", "review", "keep"]) == 0
    assert q.is_file()
    s = tmp / "sample.jsonl"
    assert nli_label.main(["sample", str(out), "--out", str(s), "--policy", str(pol), "--random", "2"]) == 0
    assert s.is_file()

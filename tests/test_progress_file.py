"""nli_filter.py writes OUTPUT_DIR/progress/<run>.json while it runs (the viewer's 'Runs in progress')."""
import gzip
import json

import pytest

import nli_filter as nf
from conftest import FakePool
from nli_models import JsonlSource

TEXTS = ["The history of Russia is long.", "Preheat the oven.", "Moscow traffic report.", "Russian roulette."]


def _inputs(folder, n_files=3, lines=40, noise=0):
    import random
    rng = random.Random(1)
    folder.mkdir(parents=True, exist_ok=True)
    for k in range(n_files):
        rows = [json.dumps({"id": f"{k}-{i}", "text": TEXTS[i % 4],
                            "pad": "".join(rng.choice("abcdefghij") for _ in range(noise))}) for i in range(lines)]
        (folder / f"f{k}.jsonl.gz").write_bytes(gzip.compress(("\n".join(rows) + "\n").encode()))
    return folder


def _progress(out):
    files = sorted((out / "progress").glob("*.json"))
    return [json.loads(p.read_text(encoding="utf-8")) for p in files]


@pytest.fixture(autouse=True)
def fake_models(monkeypatch):
    monkeypatch.setattr(nf, "NLIPool", lambda name, **kw: FakePool(name))


def test_progress_file_of_a_run(tmp_path):
    inp = _inputs(tmp_path / "in")
    out = tmp_path / "out"
    assert nf.main([str(inp), "--judge-model", "none", "--output-dir", str(out)]) == 0
    [p] = _progress(out)
    assert p["state"] == "done" and p["files_total"] == 3 and p["files_needed"] == 3 and p["files_done"] == 3
    assert p["lines"] == 120 and p["percent"] == 100.0 and p["bytes_done"] == p["bytes_total"] > 0
    assert p["current"] is None and p["ended"] and p["pid"] and p["host"] and "--output-dir" in p["command"]
    assert p["fast_model"] == "modernbert" and p["eta_seconds"] is None
    # a second run without --overwrite: everything skipped, its own progress file
    assert nf.main([str(inp), "--judge-model", "none", "--output-dir", str(out)]) == 0
    second = [x for x in _progress(out) if x["run_id"] != p["run_id"]][0]
    assert second["files_skipped"] == 3 and second["files_needed"] == 0 and second["state"] == "done"


def test_no_progress_file(tmp_path):
    inp = _inputs(tmp_path / "in", n_files=1)
    assert nf.main([str(inp), "--judge-model", "none", "--output-dir", str(tmp_path / "out"), "--no-progress-file"]) == 0
    assert not (tmp_path / "out" / "progress").exists()


def test_failed_run_says_so(tmp_path, monkeypatch):
    inp = _inputs(tmp_path / "in", n_files=1)

    def boom(*a, **kw):
        raise RuntimeError("GPU fell over")
    monkeypatch.setattr(nf.LineFilter, "process", boom)
    with pytest.raises(RuntimeError):
        nf.main([str(inp), "--judge-model", "none", "--output-dir", str(tmp_path / "out")])
    [p] = _progress(tmp_path / "out")
    assert p["state"] == "failed" and "GPU fell over" in p["error"]


def test_progress_during_a_run(tmp_path):
    inp = _inputs(tmp_path / "in", n_files=2, lines=6000, noise=400)  # ~1 MB compressed each
    out = tmp_path / "out"
    seen = []
    real = nf.ProgressFile.update

    def spy(self, force=False, **fields):
        real(self, force=True, **fields)  # write every time, to watch it grow
        if self.data.get("state") == "running":
            seen.append((self.data.get("bytes_done", 0), self.data.get("lines", 0)))
    nf.ProgressFile.update = spy
    try:
        assert nf.main([str(inp), "--judge-model", "none", "--output-dir", str(out), "--chunk-lines", "100"]) == 0
    finally:
        nf.ProgressFile.update = real
    bytes_seen = [b for b, _ in seen]
    assert bytes_seen == sorted(bytes_seen) and len(set(bytes_seen)) > 3  # grows while the files are read
    assert _progress(out)[0]["percent"] == 100.0


def test_bytes_read_counts_the_file(tmp_path):
    inp = _inputs(tmp_path / "in", n_files=1)
    src = JsonlSource(str(inp / "f0.jsonl.gz"))
    assert len(list(src.records())) == 40
    assert src.bytes_read == (inp / "f0.jsonl.gz").stat().st_size


def test_progress_every_is_respected(tmp_path):
    inp = _inputs(tmp_path / "in", n_files=6)
    writes = []
    real = nf.ProgressFile.update

    def count(self, force=False, **fields):
        before = self._last
        real(self, force=force, **fields)
        if self._last != before:
            writes.append(force)
    nf.ProgressFile.update = count
    try:
        assert nf.main([str(inp), "--judge-model", "none", "--output-dir", str(tmp_path / "out"),
                        "--progress-every", "300"]) == 0
    finally:
        nf.ProgressFile.update = real
    assert writes == [True, True]  # only the first and the final write in a short run (not one per file)
    [p] = _progress(tmp_path / "out")
    assert p["every_seconds"] == 300 and p["state"] == "done" and p["files_done"] == 6

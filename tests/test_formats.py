"""nli_filter.py / nli_models.py input: .rar members and .parquet rows (nli_formats.py)."""
import json
import subprocess

import pytest

import nli_filter as nf
import nli_formats
from nli_models import JsonlSource, expand_inputs
from test_nli_filter import read_json, run

TEXTS = ["The history of Russia is long.", "Preheat the oven to 200 degrees.", "Moscow is the capital of Russia."]
HAVE_RAR = nli_formats.rar_tool("rar") is not None and nli_formats.rar_tool("unrar") is not None


def test_names_and_suffixes():
    assert nf._stem("x.parquet") == "x" and nf._stem("y.rar") == "y" and nf._stem("a.jsonl.zst") == "a"
    assert ".parquet" in nf._INPUT_SUFFIXES and ".rar" in nf._INPUT_SUFFIXES


def test_parquet_input(tmp_path):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    (tmp_path / "in").mkdir()
    pq.write_table(pa.table({"id": ["p1", "p2", "p3"], "text": TEXTS, "n": [1, 2, 3]}), tmp_path / "in" / "t.parquet")
    files = expand_inputs([str(tmp_path / "in")])
    assert [f.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for f in files] == ["t.parquet"]
    recs = list(JsonlSource(files[0]).records())
    assert [(r.line, r.data["id"], r.data["text"]) for r in recs] == [(1, "p1", TEXTS[0]), (2, "p2", TEXTS[1]),
                                                                        (3, "p3", TEXTS[2])]
    run(files, tmp_path / "out", write_split=False)
    s = read_json(tmp_path / "out" / "t.summary.json")
    assert s["stats"]["lines"] == 3 and s["stats"]["decisions"]["filter"] == 2


@pytest.mark.skipif(not HAVE_RAR, reason="needs WinRAR's Rar / UnRAR (or rar / unrar on Linux)")
def test_rar_input(tmp_path):
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "a.jsonl").write_text("\n".join(json.dumps({"id": f"a{i}", "text": t}) for i, t in enumerate(TEXTS)) + "\n")
    (src / "sub" / "b.jsonl").write_text(json.dumps({"id": "b0", "text": TEXTS[0]}) + "\n")
    (src / "readme.txt").write_text("not a corpus file")
    (tmp_path / "in").mkdir()
    subprocess.run([nli_formats.rar_tool("rar"), "a", "-idq", "-y", str(tmp_path / "in" / "r.rar"), "a.jsonl",
                    nli_formats._native("sub/b.jsonl"), "readme.txt"], cwd=src, check=True)
    recs = list(JsonlSource(str(tmp_path / "in" / "r.rar")).records())
    assert [(r.source.split("!", 1)[1], r.line, r.data["id"]) for r in recs] == [
        ("a.jsonl", 1, "a0"), ("a.jsonl", 2, "a1"), ("a.jsonl", 3, "a2"), ("sub/b.jsonl", 1, "b0")]
    run(expand_inputs([str(tmp_path / "in")]), tmp_path / "out", write_split=False)
    decisions = [json.loads(x) for x in (tmp_path / "out" / "r.decisions.jsonl").read_text().splitlines()]
    assert [(d["source"], d["line"]) for d in decisions] == [("a.jsonl", 1), ("a.jsonl", 2), ("a.jsonl", 3),
                                                             ("sub/b.jsonl", 1)]


@pytest.mark.parametrize("kind", ["file", "stream"])
def test_arrow_input(tmp_path, kind):
    pa = pytest.importorskip("pyarrow")
    (tmp_path / "in").mkdir()
    t = pa.table({"id": ["p1", "p2", "p3"], "text": TEXTS})
    opener = pa.ipc.new_file if kind == "file" else pa.ipc.new_stream
    with pa.OSFile(str(tmp_path / "in" / "t.arrow"), "wb") as sink, opener(sink, t.schema) as w:
        w.write_table(t)
    files = expand_inputs([str(tmp_path / "in")])
    recs = list(JsonlSource(files[0]).records())
    assert [(r.line, r.data["id"]) for r in recs] == [(1, "p1"), (2, "p2"), (3, "p3")]
    run(files, tmp_path / "out", write_split=False)
    assert read_json(tmp_path / "out" / "t.summary.json")["stats"]["decisions"]["filter"] == 2

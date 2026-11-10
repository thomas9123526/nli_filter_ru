"""Tests for nli_models.py: registry, devices, batching, readers / writers, and (slow) real model scoring."""
import gzip
import json
import zipfile

import pytest

import nli_models as nm
from conftest import MODELS, models_available


def test_registry_names_and_aliases():
    for name in ("modernbert", "fast", "ModernBERT-large-zeroshot-v2.0", "MoritzLaurer/ModernBERT-large-zeroshot-v2.0"):
        assert nm.ModelRegistry.spec(name).key == "modernbert"
    assert nm.ModelRegistry.spec("judge").key == "deberta"
    assert nm.ModelRegistry.spec("multilingual").key == "bge-m3"
    assert nm.ModelRegistry.spec("nope") is None
    with pytest.raises(ValueError):
        nm.ModelRegistry(MODELS).resolve("nope")


def test_registry_missing_folder(tmp_path):
    with pytest.raises(FileNotFoundError):
        nm.ModelRegistry(tmp_path).resolve("deberta")


def test_resolve_devices():
    assert nm.resolve_devices("cpu") == ["cpu"]
    assert nm.resolve_devices("cpu*3") == ["cpu", "cpu", "cpu"]
    assert nm.resolve_devices("0,1") == ["cuda:0", "cuda:1"]
    assert nm.resolve_device("cuda") == "cuda:0"


@pytest.mark.parametrize("n,bs,tok", [(0, 4, None), (1, 4, None), (37, 8, None), (37, 32, 600), (100, 100, 2000)])
def test_plan_batches(n, bs, tok):
    lengths = [((i * 37) % 900) + 10 for i in range(n)]
    batches = nm.plan_batches(lengths, bs, tok, max_length=512)
    flat = sorted(i for b in batches for i in b)
    assert flat == list(range(n))
    for b in batches:
        assert len(b) <= bs
        if tok and len(b) > 1:
            longest = max(min(512, lengths[i] / 4 + 4) for i in b)
            assert longest * len(b) <= tok


def lines(n=5):
    return [json.dumps({"id": i, "text": f"t{i}"}) for i in range(1, n + 1)]


def test_sources_every_format(tmp_path):
    data = ("\n".join(lines()) + "\n").encode()
    (tmp_path / "a.jsonl").write_bytes(data.replace(b"\n", b"\r\n"))
    (tmp_path / "b.jsonl.gz").write_bytes(gzip.compress(data))
    with zipfile.ZipFile(tmp_path / "c.zip", "w") as z:
        z.writestr("c1.jsonl", data)
        z.writestr("c2.jsonl", data[:20] + b"\n\n{bad\n")
        z.writestr("readme.txt", b"skip me")
    if nm.zstd_available():
        import zstandard
        (tmp_path / "d.jsonl.zst").write_bytes(zstandard.ZstdCompressor().compress(data))
    files = nm.expand_inputs([str(tmp_path)])
    assert [f.split("\\")[-1].split("/")[-1] for f in files][:3] == ["a.jsonl", "b.jsonl.gz", "c.zip"]
    for f in files:
        recs = list(nm.JsonlSource(f).records())
        good = [r for r in recs if r.error is None]
        assert good[0].data == {"id": 1, "text": "t1"} and good[0].line == 1
    zrecs = list(nm.JsonlSource(tmp_path / "c.zip").records())
    assert {r.source.split("!")[-1] for r in zrecs} == {"c1.jsonl", "c2.jsonl"}
    errors = [r.error.split(":")[0] for r in zrecs if r.error]
    assert errors == ["bad_json", "blank", "bad_json"]
    assert len(list(nm.iter_records([str(tmp_path)], limit=7))) == 7


def test_expand_inputs_glob_dedupe_missing(tmp_path):
    (tmp_path / "x.jsonl").write_text("{}\n")
    assert len(nm.expand_inputs([str(tmp_path / "*.jsonl"), str(tmp_path / "x.jsonl"), str(tmp_path)])) == 1
    with pytest.raises(FileNotFoundError):
        nm.expand_inputs([str(tmp_path / "missing.jsonl")])
    with pytest.raises(FileNotFoundError):
        nm.expand_inputs([str(tmp_path / "*.zst")])


@pytest.mark.parametrize("suffix", [".jsonl", ".jsonl.gz", ".jsonl.zst"])
def test_atomic_output_roundtrip(tmp_path, suffix):
    if suffix.endswith(".zst") and not nm.zstd_available():
        pytest.skip("zstandard not installed")
    p = tmp_path / f"o{suffix}"
    with nm.AtomicOutput(p) as fh:
        fh.write("ä一\n")
    assert [r.raw.decode() for r in nm.JsonlSource(p).records(parse=False)] == ["ä一"]
    assert list(tmp_path.iterdir()) == [p]


def test_atomic_output_removed_on_error(tmp_path):
    with pytest.raises(RuntimeError):
        with nm.AtomicOutput(tmp_path / "o.jsonl") as fh:
            fh.write("x\n")
            raise RuntimeError("boom")
    assert list(tmp_path.iterdir()) == []


def test_json_helpers():
    assert nm.json_loads(nm.json_dumps({"a": "ü"})) == {"a": "ü"}


# ---------------------------------------------------------------- real model (slow)

slow = pytest.mark.skipif(not models_available("ModernBERT-large-zeroshot-v2.0"), reason="models/ not present")


@pytest.mark.slow
@slow
def test_modernbert_scores_and_pool_modes():
    pytest.importorskip("torch")
    nm.quiet_transformers()
    model = nm.NLIModel("modernbert", device="cpu", max_length=128)
    premises = ["Moscow is the capital of Russia.", "Preheat the oven to 200 degrees.", "Language: Russian"]
    hyp = "This text is about Russia."
    s = model.score_pairs(premises, hyp, batch_size=2)
    assert s[0] > 0.8 and s[1] < 0.2
    assert model.classify("Moscow is the capital of Russia.", ["Russia", "cooking"],
                          template="This text is about {}.")["Russia"] > 0.8
    model.release()
    with nm.NLIPool("modernbert", devices="cpu*2", mode="thread", max_length=128, batch_size=2) as pool:
        futs = [pool.submit(premises, hyp) for _ in range(3)]
        for f in futs:
            assert [round(x, 4) for x in f.result()] == [round(x, 4) for x in s]
        assert pool.stats()["pairs"] == 9

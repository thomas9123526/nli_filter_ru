# H200 readiness check (2026-11-09)

Review of the code for the 8 × H200 machine (Ubuntu 24.04, Python 3.12). The development PC has no GPU, so the CUDA path has **not run yet**: the first-run checks below give the real answer.

## Fixed in this review

| Problem | Fix |
|---|---|
| Language-name rule scanned the whole text with a ~120-word regex for every line with a hit: ~0.4 MB/s on long texts, days per TB | Only hits that can be a language name are checked ("Russia", "Moscow" cost nothing); only ±300 characters around the hit are searched; word lists compiled as a trie (13× faster, identical matches) |
| Each GPU worker process used thread pools as large as the machine; 16 workers = hundreds of competing threads | Capped at 4 CPU threads per GPU worker (`--cpu-threads` to change) |
| Shard copies overwrote each other's `summary.json` | One `summary.shard-K-of-N.json` per copy; new `--report` combines all per-file summaries (no model loaded) |

## Measured speed (one process, development PC)

| Stage | Speed |
|---|---|
| Read + JSON parse | ~200–450 MB/s |
| Read + parse + keywords + rules + windows | **~39 MB/s ≈ 7 h per TB** (Python 3.10 and 3.12) |
| GPU work, default cascade, 8 H200 | ~3 h per TB (estimate, not measured) |

One run on all 8 GPUs would be limited by its single CPU process. Use `run_shards.sh` (several copies per GPU, each on its own files):

```bash
./run_shards.sh "/data/corpus/**/*.zst" /data/nli_out 2 --batch-size 256 --judge-batch-size 128 --write-split
```

## Tested on the development PC

| Test | Result |
|---|---|
| Test file, default cascade | accuracy 0.938, precision 1.000, recall 0.860: same as the first run (faster rules changed no decision) |
| Python 3.12, `process` mode, without orjson and zstandard | works (plain-JSON fallback) |
| `run_shards.sh` in Git Bash, 2 copies + `--report` | works; Unix line endings, bash syntax check passed |

## Not tested: needs the H200 machine

- The CUDA code: models in bfloat16 on GPU, ModernBERT's attention on GPU, the out-of-memory retry, 16+ GPU worker processes at once.
- Real throughput, batch sizes, and the right number of copies per GPU.
- bfloat16 scores differ slightly from float32 on CPU: lines very close to the 0.8 threshold can flip.

## First run on the machine (~10 minutes)

```bash
python nli_models.py --check all --device cuda:0                                # all three models load and score on GPU
python nli_filter.py test_russia.jsonl --device cuda --mode process --output-dir out_test   # accuracy should be close to 0.938
./run_shards.sh dataset/test_corpus out_tc 2                                            # copies side by side + report
```

If all three pass, start the full corpus. Details: `linux_h200.md`.

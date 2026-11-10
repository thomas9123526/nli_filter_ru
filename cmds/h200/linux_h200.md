# Running on the 8 × H200 machine (Ubuntu 24.04)

How to run `nli_models.py` and `nli_filter.py` on several GPUs.

> **Status:** the multi-GPU path uses the same code that was tested on CPU (`single`, `thread` and `process` modes gave identical results), but it has **not been run on a GPU yet**. Do the short test run (step 3) before the full corpus.

## 1. What to copy to the machine

| What | Notes |
|---|---|
| `nli_models.py`, `nli_filter.py`, `nli_storage.py`, `run_shards.sh` | Keep them in the same folder; `chmod +x run_shards.sh`. `nli_filter.py` needs `nli_storage.py` (corpus input from FTP / SFTP / S3) |
| `models/` | The three model folders. If they are elsewhere, pass `--models-root /path/to/models` |
| `test_russia.jsonl` | For the test run |
| `pkgs/` | Offline Python packages (see step 2) |

## 2. Python environment

Required: `torch 2.11.0+cu128`, `transformers 5.20.2` (see `pkgs/README.md`), NVIDIA driver **570 or newer**.
Optional but recommended: `orjson`, `pyahocorasick`. Needed for `.zst` files: `zstandard`.
Only for a corpus on a server: `paramiko` (`sftp://`), `boto3` (`s3://`, `minio://`); see `pkgs/whl_files.txt` and
`cmds/setup/remote_corpus.md`.

`zstandard` is **not in `pkgs/` yet**. On a machine with internet:

```bash
pip download zstandard --python-version 3.12 --platform manylinux2014_x86_64 --only-binary=:all: -d pkgs/linux
```

Then on the H200 machine:

```bash
source /path/to/venv/bin/activate
pip install --no-index --find-links pkgs/linux zstandard
python -c "import torch; print(torch.__version__, torch.cuda.device_count())"   # expect 2.11.0+cu128 8
```

## 3. Check and test

```bash
# Models load and score correctly on one GPU
python nli_models.py --list-models
python nli_models.py --check all --device cuda:0

# Short test on all 8 GPUs (97 lines, prints accuracy / precision / recall)
python nli_filter.py test_russia.jsonl --device cuda --mode process --output-dir out_test
```

Watch `nvidia-smi` in a second terminal while it runs.

## 4. How the GPUs are used

| Option | Meaning |
|---|---|
| `--device cuda` | All visible GPUs (8) |
| `--device cuda:0,cuda:1` | Only these GPUs |
| `--device cuda:3` | One GPU |
| `--mode process` | One worker process per GPU **per model**. With the default fast model (ModernBERT) and judge (DeBERTa) that is 16 processes: both models on every GPU, a few GB each out of 141 GB |
| `--mode thread` | One worker thread per GPU in a single process. Lower overhead to start, but Python's GIL can limit 8 GPUs |
| dtype | bfloat16 automatically on GPU (`--dtype` to override) |
| out of memory | A batch that does not fit is halved and retried |

## 5. Why several copies: the CPU stage

One `nli_filter.py` process reads, decompresses, parses and keyword-scans the text itself; only the NLI scoring runs on the GPUs. Measured on the development PC (i7-8700K, one process, ~4 KB texts, 18 % with a keyword):

| Stage | Speed per process |
|---|---|
| Read + JSON parse | ~200–450 MB/s |
| Read + parse + keywords + rules + windows | **~39 MB/s ≈ 7 h per TB** |

The GPU estimate for the default cascade is ~3 h per TB on 8 H200 (20 % hit rate; not measured yet). So **one run on all 8 GPUs (option A) is limited by its single CPU process**; running several copies with `--shard` (option B, `run_shards.sh`) splits the CPU work. With 16 copies the CPU stage drops to well under an hour per TB (the H200 server has 100+ cores).

## 6. Full corpus: option B, `run_shards.sh` (recommended)

```bash
chmod +x run_shards.sh
./run_shards.sh "/data/corpus/**/*.zst" /data/nli_out 2 \
    --batch-size 256 --judge-batch-size 128 --write-split
```

- Arguments: `INPUT OUTPUT_DIR [COPIES_PER_GPU] [extra nli_filter.py options]`. `2` copies per GPU = 16 copies, each with its own `--shard K/16` (a disjoint set of files) and GPU (`cuda:K mod 8`).
- Each copy loads its own fast model and judge: with 2 copies per GPU that is 4 models per GPU, a few GB each.
- Logs: `/data/nli_out/logs/shard-K.log` (`tail -f /data/nli_out/logs/shard-0.log`).
- Each copy writes `summary.shard-K-of-N.json`; at the end the script runs `nli_filter.py --report`, which combines all per-file summaries into one report (`summary.report.json`) and prints it.
- Ctrl+C stops all copies. Running the same command again skips finished files.
- `PYTHON=python3 ./run_shards.sh ...` picks the interpreter; `NLI_DEVICES="0 1 2 3" ./run_shards.sh ...` uses only those GPUs.
- Files are dealt out by count, not size: very uneven file sizes make some copies finish later.

Report at any time, also while a run is going (no models are loaded):

```bash
python nli_filter.py --report --output-dir /data/nli_out
```

## 7. Full corpus: option A, one run on all GPUs

```bash
python nli_filter.py "/data/corpus/**/*.zst" --device cuda --mode process \
    --batch-size 256 --judge-batch-size 128 --write-split --output-dir /data/nli_out
```

- Simplest, but limited by one CPU process (~7 h per TB, section 5). Fine for small corpora and tests.
- Quote the glob so bash passes it to the script; `**` searches all subfolders. A folder path (`/data/corpus`) also works and finds `.jsonl .json .gz .zst .zip` recursively.
- GPU worker processes use 4 CPU threads each by default (`--cpu-threads` to change), so 16 workers do not compete for all cores.

## 8. Outputs

For every input file (the input folder structure is mirrored under `--output-dir`):

| File | Content |
|---|---|
| `<name>.decisions.jsonl.zst` | One record per input line: `decision` (keep/filter), `reason`, keyword hits, check-1 and check-2 scores, windows |
| `<name>.summary.json` | Counts for that file; also marks the file as done |
| `<name>.kept.jsonl.zst`, `<name>.filtered.jsonl.zst` | The original lines, split (with `--write-split`) |
| `summary.json` | Summary of the whole run (also printed at the end); with `--shard`: `summary.shard-K-of-N.json` per copy |
| `summary.report.json` | Combined report written by `--report` (and by `run_shards.sh` at the end) |

Outputs are `.zst` when the input was compressed (`--compress zst|gz|none` to choose).

## 9. Stopping and resuming

- Finished files have a `.summary.json` and are skipped when the same command is run again; an interrupted file is redone from its start.
- A file that `--limit` stopped inside is marked partial and processed again in full by the next run.
- `--overwrite` redoes all files.
- Output files are written under a temporary name and renamed when complete, so a crash never leaves a half-written output file.

## 10. Tuning

| Option | Default | Advice |
|---|---|---|
| `--batch-size` | 32 | Start at 256 on the H200; raise while `nvidia-smi` shows free memory |
| `--judge-batch-size` | = `--batch-size` | DeBERTa is slower and has no fast attention; 128 is a good start |
| `--max-batch-tokens` | none | Caps a batch by size in tokens; useful when text lengths vary a lot |
| `--chunk-lines` | 512 | Lines per work unit; keep the default for big runs |
| `--inflight` | 2 × workers | Work units processed at once |
| `--judge-model none` | DeBERTa on | ModernBERT only: faster, slightly less accurate |
| `--limit N` | all | Stop after N lines, for quick trials |

## 11. Scoring only (no filter logic)

`nli_models.py` scores texts against your own hypotheses on all GPUs:

```bash
python nli_models.py --model modernbert --input "/data/corpus/**/*.zst" \
    --hypothesis "This text is about Russia." \
    --device cuda --mode process --batch-size 256 --out scores.jsonl.zst
```

## 12. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `torch.cuda.device_count()` is 0 | Driver older than 570, or a CPU-only torch build installed |
| `.zst input needs the 'zstandard' package` | Install `zstandard` (step 2) |
| `model '...' not found under ...` | Pass `--models-root` with the folder that holds the three model folders |
| GPUs often idle | The CPU stage is the limit: use `run_shards.sh` (section 6), or more copies per GPU |
| A shard FAILED in `run_shards.sh` | Read `OUTPUT_DIR/logs/shard-K.log`; fix and run the same command again |
| A worker process died | Usually host or GPU out of memory: lower `--batch-size` |

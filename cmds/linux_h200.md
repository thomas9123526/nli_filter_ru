# Running on the 8 × H200 machine (Ubuntu 24.04)

How to run `nli_models.py` and `nli_filter.py` on several GPUs.

> **Status:** the multi-GPU path uses the same code that was tested on CPU (`single`, `thread` and `process` modes gave identical results), but it has **not been run on a GPU yet**. Do the short test run (step 3) before the full corpus.

## 1. What to copy to the machine

| What | Notes |
|---|---|
| `nli_models.py`, `nli_filter.py` | Keep them in the same folder |
| `models/` | The three model folders. If they are elsewhere, pass `--models-root /path/to/models` |
| `test_russia.jsonl` | For the test run |
| `pkgs/` | Offline Python packages (see step 2) |

## 2. Python environment

Required: `torch 2.11.0+cu128`, `transformers 5.20.2` (see `pkgs/README.md`), NVIDIA driver **570 or newer**.
Optional but recommended: `orjson`, `pyahocorasick`. Needed for `.zst` files: `zstandard`.

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

## 5. Full corpus: option A, one run on all GPUs

```bash
python nli_filter.py "/data/corpus/**/*.zst" --device cuda --mode process \
    --batch-size 256 --judge-batch-size 128 --write-split --output-dir /data/nli_out
```

- Quote the glob so bash passes it to the script; `**` searches all subfolders. A folder path (`/data/corpus`) also works and finds `.jsonl .json .gz .zst .zip` recursively.
- One main process reads, decompresses and keyword-scans every file; the GPUs only score. If the GPUs are often idle in `nvidia-smi`, the reading is the limit: use option B.

## 6. Full corpus: option B, 8 copies, one per GPU (recommended for many files)

```bash
for i in 0 1 2 3 4 5 6 7; do
  python nli_filter.py "/data/corpus/**/*.zst" --device cuda:$i --shard $i/8 \
      --batch-size 256 --judge-batch-size 128 --write-split --output-dir /data/nli_out \
      > log_gpu$i.txt 2>&1 &
done
wait
```

- `--shard i/8` gives each copy every 8th file, so each copy has its own CPU process for reading.
- Progress is in `log_gpu0.txt` … `log_gpu7.txt` (`tail -f log_gpu0.txt`).
- Each copy writes its own `summary.json` into the output folder, so the last one to finish overwrites it. The per-file `*.summary.json` files are always complete.

## 7. Outputs

For every input file (the input folder structure is mirrored under `--output-dir`):

| File | Content |
|---|---|
| `<name>.decisions.jsonl.zst` | One record per input line: `decision` (keep/filter), `reason`, keyword hits, check-1 and check-2 scores, windows |
| `<name>.summary.json` | Counts for that file; also marks the file as done |
| `<name>.kept.jsonl.zst`, `<name>.filtered.jsonl.zst` | The original lines, split (with `--write-split`) |
| `summary.json` | Summary of the whole run (also printed at the end) |

Outputs are `.zst` when the input was compressed (`--compress zst|gz|none` to choose).

## 8. Stopping and resuming

- Finished files have a `.summary.json` and are skipped when the same command is run again; an interrupted file is redone from its start.
- `--overwrite` redoes all files.
- Output files are written under a temporary name and renamed when complete, so a crash never leaves a half-written output file.

## 9. Tuning

| Option | Default | Advice |
|---|---|---|
| `--batch-size` | 32 | Start at 256 on the H200; raise while `nvidia-smi` shows free memory |
| `--judge-batch-size` | = `--batch-size` | DeBERTa is slower and has no fast attention; 128 is a good start |
| `--max-batch-tokens` | none | Caps a batch by size in tokens; useful when text lengths vary a lot |
| `--chunk-lines` | 512 | Lines per work unit; keep the default for big runs |
| `--inflight` | 2 × workers | Work units processed at once |
| `--judge-model none` | DeBERTa on | ModernBERT only: faster, slightly less accurate |
| `--limit N` | all | Stop after N lines, for quick trials |

## 10. Scoring only (no filter logic)

`nli_models.py` scores texts against your own hypotheses on all GPUs:

```bash
python nli_models.py --model modernbert --input "/data/corpus/**/*.zst" \
    --hypothesis "This text is about Russia." \
    --device cuda --mode process --batch-size 256 --out scores.jsonl.zst
```

## 11. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `torch.cuda.device_count()` is 0 | Driver older than 570, or a CPU-only torch build installed |
| `.zst input needs the 'zstandard' package` | Install `zstandard` (step 2) |
| `model '...' not found under ...` | Pass `--models-root` with the folder that holds the three model folders |
| GPUs often idle | Reading is the limit: use option B (step 6) |
| A worker process died | Usually host or GPU out of memory: lower `--batch-size` |

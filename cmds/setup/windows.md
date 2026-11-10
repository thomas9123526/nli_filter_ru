# Running on Windows (PowerShell)

How to run `nli_models.py` and `nli_filter.py` on a Windows PC: the CPU-only development PC, or a PC with a GPU (e.g. RTX 5090).
The same commands are in `00_setup.ps1`, `01_nli_models.ps1` and `02_nli_filter.ps1`, ready to copy.

All commands run from the project folder:

```powershell
cd D:\hkc\nli_filter2
```

## 1. Setup (once per terminal)

The plain `python` on this PC is Python 3.10 **without torch**. Use the venv that has torch and transformers:

```powershell
# Once per user account: allow local scripts so the venv can be activated (no admin needed)
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
# ...or only for the current terminal
Set-ExecutionPolicy -Scope Process Bypass

# Activate the venv; the prompt then starts with "(.venv)"
D:\hkc\nli_country_filter\.venv\Scripts\Activate.ps1

# Check: expect D:\hkc\nli_country_filter\.venv\Scripts\python.exe 2.11.0+cu128
python -c "import sys, torch; print(sys.executable, torch.__version__)"

# Needed only for .zst files
python -m pip install zstandard
```

In **cmd.exe** activate with `D:\hkc\nli_country_filter\.venv\Scripts\activate.bat`.
Without activating, call the venv Python by its full path:

```powershell
D:\hkc\nli_country_filter\.venv\Scripts\python.exe .\nli_filter.py --device cpu --chunk-lines 16
```

In VS Code: Ctrl+Shift+P → "Python: Select Interpreter" → the `.venv` one; new terminals then activate it automatically.

## 2. The two scripts

| Script | What it does |
|---|---|
| `nli_models.py` | Loads a model and scores texts against hypotheses you give. No keywords, rules or filter decision. Also a library for other code |
| `nli_filter.py` | The country filter: keywords → CPU rules → check 1 (about the country?) → check 2 (only incidental?) → keep / filter. Writes decisions and a summary |

The input file is a plain argument for `nli_filter.py`, but `--input FILE` for `nli_models.py`. All options: `python .\nli_filter.py --help`, `python .\nli_models.py --help`.

## 3. `nli_models.py`: check and score

```powershell
# Show the three models and whether they are found in .\models
python .\nli_models.py --list-models

# Load each model on CPU and score three sample pairs (~30 s)
python .\nli_models.py --check all --device cpu

# Score two texts directly
python .\nli_models.py --model modernbert --device cpu --text "The Kremlin announced new sanctions." --text "Set display language to Russian." --labels "Russia,a language setting" --template "This text is about {}."

# Score every line of test_russia.jsonl with ModernBERT
python .\nli_models.py --model modernbert --input test_russia.jsonl --hypothesis "This text is about Russia." --device cpu --out out_modernbert\scores.jsonl

# Several labels with DeBERTa over a folder, compressed output
python .\nli_models.py --model deberta --input corpus\ --labels "film,song,history" --template "This text is about a Russian {}." --device cpu --out scores.jsonl.zst

# Also list hypotheses scoring >= 0.8; two CPU worker threads; first 12 lines only
python .\nli_models.py --model deberta --device "cpu*2" --mode thread --input corpus\web --limit 12 --hypothesis "This text is about Russia." --threshold 0.8 --out scores.jsonl.zst
```

Without `--out` the scores are printed to the console, one JSON line per input line.

## 4. `nli_filter.py`: test file

Default input is `test_russia.jsonl`, default output folder `.\nli_filter_out`.

| Models | Command |
|---|---|
| ModernBERT + DeBERTa judge for scores 0.6–0.95 (default, ~2 min on CPU) | `python .\nli_filter.py --device cpu --chunk-lines 16` |
| ModernBERT only | `python .\nli_filter.py --judge-model none --device cpu --chunk-lines 16` |
| DeBERTa only (slower) | `python .\nli_filter.py --fast-model deberta --judge-model none --device cpu --chunk-lines 16` |
| bge-m3 only (multilingual) | `python .\nli_filter.py --fast-model bge-m3 --judge-model none --device cpu --chunk-lines 16` |

The same with every option written out, own output folder:

```powershell
python .\nli_filter.py D:\hkc\nli_filter2\test_russia.jsonl --fast-model modernbert --judge-model none --device cpu --output-dir out_modernbert --chunk-lines 16
```

Because the test file has an `expect` field, the summary at the end shows accuracy, precision, recall, F1, a table per category and the mistaken lines (`--show 30` prints up to 30).

## 5. Nested test corpus of `.zst` files

`make_test_corpus.py` builds `test_corpus\` from `test_russia.jsonl`: 5 folders × 3 sub folders, each with 1–2 `.jsonl.zst` files of 20–40 lines. The lines are copied unchanged, so the evaluation (`expect`, `category`) still works. It needs `zstandard`.

```powershell
python .\make_test_corpus.py
python .\make_test_corpus.py --force --folders 5 --subfolders 3 --files 1-2 --lines 20-40 --seed 7
python .\nli_filter.py test_corpus --device cpu --judge-model none --output-dir out_test_corpus
```

| Option | Default | Meaning |
|---|---|---|
| `--source` | `test_russia.jsonl` | JSONL to sample lines from |
| `--out` | `test_corpus` | Output folder |
| `--folders` / `--subfolders` | 5 / 3 | Folder tree size (up to 10 named top folders) |
| `--files` | `1-2` | `.zst` files per sub folder (N or MIN-MAX) |
| `--lines` | `20-40` | Lines per file (N or MIN-MAX) |
| `--seed` | 42 | Same seed = same corpus |
| `--force` | off | Replace an existing output folder |

The list of files, line counts and line ids is written to `test_corpus.manifest.json`, next to the folder (not inside, or the filter would read it as input). The default corpus has about 800 lines: about 5 minutes with ModernBERT only on CPU; use `--limit` for a quicker trial.

## 6. `nli_filter.py`: your own files

Replace the example paths with your own.

```powershell
# One file
python .\nli_filter.py D:\data\some.jsonl --device cpu --output-dir out_test

# All .zst files under a folder, also write the kept / filtered lines
python .\nli_filter.py "D:\data\corpus\**\*.zst" --device cpu --write-split --output-dir out_corpus

# A whole folder (finds .jsonl .json .gz .zst .zip recursively), first 250 lines only
python .\nli_filter.py D:\data\corpus --device cpu --judge-model none --limit 250 --write-split --output-dir out_corpus

# Split the files over several runs: run 0/2 and 1/2 (e.g. in two terminals)
python .\nli_filter.py D:\data\corpus --shard 0/2 --device cpu --output-dir out_corpus
python .\nli_filter.py D:\data\corpus --shard 1/2 --device cpu --output-dir out_corpus

# Redo files that are already finished
python .\nli_filter.py D:\data\corpus --device cpu --output-dir out_corpus --overwrite
```

Another country: China has a built-in keyword list; any other country needs the adjective and a keyword file.

```powershell
python .\nli_filter.py "shards\**\*.zst" --country China --device cpu
python .\nli_filter.py D:\data\corpus --country Japan --country-adj Japanese --keywords-file keywords\japan.txt --device cpu
```

## 7. Single, thread and process modes

| Mode | Use |
|---|---|
| `--mode single` | Everything in one thread; simplest, for tests (default with one device) |
| `--mode thread` | Worker threads sharing the model; low memory |
| `--mode process` | One worker process per device per model; each process loads its own copy |

On a CPU, more workers do not make it faster (they share the same cores); these commands are for testing the modes:

```powershell
python .\nli_filter.py D:\data\corpus --mode thread --device "cpu*2" --judge-model none --limit 250 --cpu-threads 3 --output-dir out_thread
python .\nli_filter.py D:\data\corpus --mode process --device "cpu*2" --judge-model none --limit 250 --cpu-threads 3 --output-dir out_process
```

`--mode process` loads the model once per worker: with 16 GB RAM keep the judge off (`--judge-model none`) and use at most 2 CPU workers.

## 8. GPU on Windows (RTX 5090)

Needs the CUDA build of torch (`2.11.0+cu128`, driver 570 or newer; see `pkgs/README.md`).

```powershell
python .\nli_models.py --check all --device cuda:0
python .\nli_filter.py "D:\data\corpus\**\*.zst" --device cuda:0 --batch-size 128 --write-split --output-dir out_corpus
```

For the 8 × H200 Ubuntu machine see `linux_h200.md`.

## 9. Progress on the console

A progress line about every 10 seconds:

```
WARNING nli_filter: progress: 64 lines (2 lines/s), NLI pairs fast 140 judge 9
```

It updates only when a work unit of `--chunk-lines` lines (default 512) is finished. On small files use `--chunk-lines 16` to see progress sooner; keep the default for big runs. `-v` also shows model loading and a line per finished file.

## 10. Outputs

In `--output-dir` (input folder structure mirrored):

| File | Content |
|---|---|
| `<name>.decisions.jsonl[.zst]` | One record per input line: `decision` (keep/filter), `reason`, keyword hits, check-1 and check-2 scores, windows |
| `<name>.summary.json` | Counts for that file; also marks the file as done |
| `<name>.kept.jsonl[.zst]`, `<name>.filtered.jsonl[.zst]` | The original lines, split (with `--write-split`) |
| `summary.json` | Summary of the whole run (also printed at the end) |

Outputs are `.zst` when the input was compressed (`--compress zst|gz|none` to choose). Finished files are skipped when the same command runs again; `--overwrite` redoes them.

## 11. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `No module named 'torch'` / `PyTorch is required` | The venv is not active: step 1 |
| `running scripts is disabled on this system` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then activate again |
| `unrecognized arguments: ... --output-dir` with `nli_models.py` | Filter options go to `nli_filter.py`; `nli_models.py` takes `--input`, `--hypothesis`, `--out` |
| `.zst input needs the 'zstandard' package` | `python -m pip install zstandard` |
| `--country-adj is required` | Only Russia and China are built in; give `--country-adj` and `--keywords-file` |
| `model '...' not found under ...` | Pass `--models-root` with the folder holding the three model folders |
| No progress for a long time | Lower `--chunk-lines` (step 9) |

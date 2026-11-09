# Testing with the `test_corpus` folder

How to build the nested test corpus of `.zst` files and run `nli_filter.py` on it.

## 1. Before you start (Windows, PowerShell)

```powershell
D:\hkc\nli_country_filter\.venv\Scripts\Activate.ps1
cd D:\hkc\nli_filter2
```

If activation fails with "running scripts is disabled", run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once (see `windows.md`). Building and reading `.zst` files needs `zstandard`: `python -m pip install zstandard`.

## 2. Build the corpus

```powershell
python .\make_test_corpus.py            # creates test_corpus\ (refuses if it exists)
python .\make_test_corpus.py --force    # rebuild it
```

The result: 5 folders × 3 sub folders, each with 1–2 `.jsonl.zst` files of 20–40 lines taken from `test_russia.jsonl` (27 files, 811 lines with the default seed). The file list is in `test_corpus.manifest.json`, next to the folder. Options: see `windows.md` section 5.

The generated lines still carry the test labels `expect` and `category`, so the summary can report accuracy. The real corpus has only `id` and `text`; the filter works the same, only without the evaluation part.

## 3. Run the filter

| What | Command | Time on CPU |
|---|---|---|
| Quick check: first 60 lines, ModernBERT only | `python .\nli_filter.py test_corpus --device cpu --judge-model none --limit 60 --chunk-lines 16 --output-dir out_test_corpus` | ~1 min |
| Whole corpus, ModernBERT only | `python .\nli_filter.py test_corpus --device cpu --judge-model none --chunk-lines 16 --output-dir out_test_corpus --overwrite` | ~5 min |
| Whole corpus with the DeBERTa judge, also write kept/filtered lines | `python .\nli_filter.py test_corpus --device cpu --chunk-lines 16 --write-split --output-dir out_test_corpus_judge` | ~10+ min |

- The filter finds all `.zst` files in `test_corpus` and its sub folders by itself.
- `--limit 60` means 60 lines **in total**, not per file: files are read in sorted order, so only the first 2–3 files are processed. Drop `--limit` to process every file.
- A file the limit stopped inside is marked `partial (--limit)` and is processed again (in full) by the next run.
- Files that are already finished in the output folder are skipped. `--overwrite` redoes them (needed above because the quick check already wrote to `out_test_corpus`).
- `--chunk-lines 16` makes the progress line appear sooner; keep the default (512) for big runs.

## 4. Parallel modes (testing)

```powershell
python .\nli_filter.py test_corpus --mode thread --device "cpu*2" --judge-model none --limit 200 --cpu-threads 3 --output-dir out_tc_thread
python .\nli_filter.py test_corpus --mode process --device "cpu*2" --judge-model none --limit 200 --cpu-threads 3 --output-dir out_tc_process
```

On a CPU these are not faster than the single mode (the workers share the same cores); they test that the modes work. Results should match the single mode.

## 5. H200 machine (Ubuntu, bash)

```bash
python make_test_corpus.py
python nli_filter.py test_corpus --device cuda --mode process --output-dir out_test_corpus
```

More on multi-GPU runs: `linux_h200.md`.

## 6. Outputs

In the output folder, the same tree as `test_corpus`:

| File | Content |
|---|---|
| `books\part-00\shard-00000.decisions.jsonl.zst` | One record per input line: `decision`, `reason`, keyword hits, scores |
| `books\part-00\shard-00000.summary.json` | Counts for that file; marks it as done |
| `...kept.jsonl.zst`, `...filtered.jsonl.zst` | Original lines, split (with `--write-split`) |
| `summary.json` | Whole run; also printed at the end, with accuracy and a per-category table |

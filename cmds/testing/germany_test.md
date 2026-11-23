# Testing the filter for Germany, step by step

English texts, target country Germany; keywords mostly English, some German, Chinese and Japanese.
Run every command from `D:\hkc\nli_filter2` with the venv active:

```powershell
cd D:\hkc\nli_filter2
D:\hkc\nli_country_filter\.venv\Scripts\Activate.ps1
```

## Test files

| File | Content |
|---|---|
| `keywords\germany.txt` | 38 keywords: English, German (München, deutsch ...), Chinese (德国, 德國, 德意志), Japanese (ドイツ, 独逸). Used automatically with `--country Germany` |
| `test_germany.jsonl` | 99 English test lines with `expect` / `category` labels, same categories as `test_russia.jsonl` |
| `dataset\test_corpus_de\` | Folder corpus built from it: 5 folders x 3 sub folders, 23 `.zst` files, 643 lines |

`dataset/test_corpus_de` was made with:

```powershell
python .\make_test_corpus.py --source test_germany.jsonl --out dataset/test_corpus_de
```

## Step 1: quick test, one model, the test file

```powershell
python .\nli_filter.py test_germany.jsonl --country Germany --country-adj German --judge-model none --device cpu --output-dir out_de_step1
```

Result (2026-11-10, ModernBERT only, CPU, 64 s):

| Metric | Value |
|---|---|
| accuracy | 0.909 |
| precision | 1.000 (no line filtered wrongly; all traps kept) |
| recall | 0.795 (9 lines about Germany missed) |

The misses are about cities, football, cars, beer and literature: the default check-1 hypothesis only names
country, person, film, song and history (e.g. "Bayern Munich won the Bundesliga ..." scored 0.022).

## Step 2: the folder corpus, then the viewer

**2a. Filter** (about 7 minutes on CPU):

```powershell
python .\nli_filter.py dataset/test_corpus_de --country Germany --country-adj German --judge-model none --device cpu --output-dir dataset/out_test_corpus_de
```

**2b. Add the dataset** to `viewer\viewer_config.json` (comma after the previous entry's `}`):

```json
    {
      "name": "test_corpus_de",
      "title": "Test corpus (Germany, ModernBERT only)",
      "corpus": "../dataset/test_corpus_de",
      "output": "../dataset/out_test_corpus_de"
    }
```

**2c. Start the viewer** (stop a running one with `Ctrl+C` first; the config is read at start-up):

```powershell
cd D:\hkc\nli_filter2\viewer
.\start_viewer.ps1
```

Open http://127.0.0.1:8000.

**2d. What to check:**

1. **Datasets page:** the Germany dataset is listed with 643 lines.
2. **Dataset page:** totals and accuracy match the console summary.
3. **File page:** click **wrong vs expected**, open a missed line, and compare its check-1 score with 0.8.
4. **Tune thresholds page:** move check 1 down to 0.4 and see how many misses would be caught, and whether
   false positives appear.

## The result folders

Each `--output-dir` gets its own folder, so runs never overwrite each other and can be compared.

| Folder | Made by | Input | Contents |
|---|---|---|---|
| `out_de_step1` | step 1 | `test_germany.jsonl` (1 file, 99 lines) | `summary.json`, `test_germany.summary.json`, `test_germany.decisions.jsonl` |
| `dataset/out_test_corpus_de` | step 2a | `dataset\test_corpus_de\` (23 `.zst` files, 643 lines) | `summary.json`, plus a `.summary.json` and a `.decisions.jsonl.zst` for each of the 23 files, in the corpus's folder structure |

Use `dataset/out_test_corpus_de` in the viewer: the config pairs it with `dataset/test_corpus_de`. `out_de_step1` was only
the quick check.

Folder names are free to choose. A name that says how the result was made is easier to compare later,
e.g. `out_de_modernbert`, `out_de_cascade`, `out_de_hyp2`. `summary.json` also records the exact command
of every run.

To keep the test folders out of git, add to `.gitignore`:

```
dataset/test_corpus_de/**
dataset/out_test_corpus_de/**
out_de_step1/**
```

What is in the files: see `cmds\explain\how_it_works.md`.

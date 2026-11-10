# Using one model on its own

There are two ways to use one model alone. All commands run from `D:\hkc\nli_filter2` with the venv active.

Models: `modernbert` (fastest), `deberta` (most accurate on English, slowest), `bge-m3` (multilingual).

## 1. Filter with one model only

By default `nli_filter.py` uses two models: ModernBERT as the fast model, and DeBERTa as the judge for
unsure scores. `--fast-model` picks the one model, and `--judge-model none` turns the judge off.

```powershell
# ModernBERT only
python .\nli_filter.py test_corpus --fast-model modernbert --judge-model none --output-dir out_modernbert

# DeBERTa only
python .\nli_filter.py test_corpus --fast-model deberta --judge-model none --output-dir out_deberta

# bge-m3 only
python .\nli_filter.py test_corpus --fast-model bge-m3 --judge-model none --output-dir out_bgem3
```

- To test on the single file, use `test_russia.jsonl` instead of `test_corpus`. Leaving the input out
  also works, because `test_russia.jsonl` is the default.
- Give each model its own `--output-dir` so the results can be compared side by side. Each run prints
  its summary, with accuracy when lines have an `expect` label.
- To compare the models in the viewer, add each output folder to `viewer\viewer_config.json` as a dataset
  (see `cmds\viewer\viewer.md`).

## 2. Score text directly with one model (no filtering)

`nli_models.py` loads one model and scores texts against hypotheses:

```powershell
# Is the model found and does it load?
python .\nli_models.py --list-models
python .\nli_models.py --check deberta

# Score one sentence
python .\nli_models.py --model bge-m3 --text "Moscow announced new sanctions today." --hypothesis "This text is about Russia."

# Score a whole file, write the scores to a file
python .\nli_models.py --model deberta --input test_russia.jsonl --hypothesis "This text is about Russia." --out scores_deberta.jsonl
```

| Option | Meaning |
|---|---|
| `--model modernbert \| deberta \| bge-m3` | which model to use |
| `--device cpu` / `--device cuda:0` | where to run it (default: GPU if there is one) |
| `--limit 50` | quick try on the first 50 lines |

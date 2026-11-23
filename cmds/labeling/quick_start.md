# Quick start: from a corpus to labelled paragraphs

Run everything from `D:\hkc\nli_filter2`. Python: the one with torch + transformers (on this computer:
`C:\Users\ThinkVision\AppData\Local\Programs\Python\Python312\python.exe`; in the commands below just `python`).
For `.zst` input you also need `zstandard` (offline: `pip install --no-index --find-links pkgs\windows-py312 zstandard`).

## 0. Check that it works (no models, seconds)

```powershell
python -m pytest tests\test_label.py -q
python nli_names.py --text "Flights from Kiev to Kharkov; Chicken Kiev stays."
```

## 1. A sample of documents that pass the gate

From big corpus files (`.parquet`, `.jsonl`, `.jsonl.zst`), pick random documents that hit a keyword or marker:

```powershell
python tools\make_gated_subset.py corpus_olmo\dclm --n 400 --seed 1 --out corpus_olmo\seed_docs.jsonl
```

`corpus_olmo\dclm` has two OLMo-mix web files (allenai/olmo-mix-1124, DCLM part, 2 × ~270 MB, 152,826 documents),
downloaded on 2026-11-20 for the first labelling round. 3.67 % of the documents pass the gate.

## 2. Score every label on those paragraphs

```powershell
python nli_label.py run corpus_olmo\seed_docs.jsonl --output-dir out_label_seed --all-labels --judge-model none --limit 80
```

- `--all-labels` scores all 25 labels on every paragraph (no cascade). This is needed so `sample` can find likely-yes
  and near-miss paragraphs for every label.
- `--judge-model none`: ModernBERT only. Use the default judge (DeBERTa) for real runs on a GPU.
- `--limit 80`: the first 80 documents (~200 paragraphs, ~1 hour on this CPU; minutes on a GPU).

## 3. Pick paragraphs to hand-label

```powershell
python nli_label.py sample out_label_seed --out labels\seed.jsonl --random 80 --top 3 --near 3 --low 1
```

80 random paragraphs + per label the 3 highest scores, 3 nearest the threshold and 1 random low score.
`labels\seed.jsonl` is already there (made on 2026-11-20, with draft labels by Claude to check: see
[hand_labeling.md](hand_labeling.md)). Next rounds: `--exclude labels\seed.jsonl --out labels\round2.jsonl`.

## 4. Label them

Open `tools\label_tool.html` in Chrome or Edge, click **Open labels file…**, choose `labels\seed.jsonl`.
Answer the labels, press **Enter** for "done & next". **Save** writes the file back. Details: [hand_labeling.md](hand_labeling.md).

## 5. Measure the labels and pick thresholds

```powershell
python nli_label.py eval labels\seed.jsonl --judge-model none
```

It scores the labelled paragraphs (cached in `labels\seed.jsonl.scores.json`, so the next eval only scores what is
new) and prints precision / recall per label at the policy threshold, plus suggested thresholds.
Only items marked **done** count. `--include-drafts` also counts unchecked drafts (to try the tool, not for decisions).
Put the thresholds you choose into `policy\russia_policy.json`. See [thresholds.md](thresholds.md).

## 6. Label a corpus

```powershell
python nli_label.py run corpus_olmo\dclm --output-dir out_label_dclm --write-clean --group-field source
python nli_label.py report out_label_dclm
```

Outputs and the report: [outputs.md](outputs.md). A rerun skips files that are done (`--overwrite` redoes them).

## Corpus on a server (ftp / ftps / sftp / s3 / minio)

The same addresses as `nli_filter.py` (`cmds\setup\remote_corpus.md`): a folder, one file or a pattern.

```powershell
$env:NLI_CORPUS_PASSWORD = "..."     # the password goes in an environment variable, not in the command
python nli_label.py run 'sftp://download:${NLI_CORPUS_PASSWORD}@192.168.170.200/home/download/hkc_test/test_corpus' --policy policy\russia_policy_v3.json --output-dir out_label_sftp_v3 --write-clean
python nli_label.py run "s3://bucket/corpus/**/*.jsonl.zst?endpoint=http://minio:9000" --output-dir out_label_s3
```

- **Passwords are never written or printed**: the command, `summary.json`, `progress.json`, the per-file
  summaries, logs and errors show `user:***@host`.
- **Use `${NLI_CORPUS_PASSWORD}`** rather than the password itself, **in single quotes** in PowerShell (`'sftp://…'`):
  in double quotes PowerShell replaces `${…}` itself (with its own, empty variable) before `nli_label.py` sees it.
  The run then stores the `${…}` form as `reopen`, so `sample`, `review`, `redecide` and the viewer's document page can
  open the file again later, as long as the variable is set where they run. With a literal password nothing can
  reopen the file: they say so.
- Each file is downloaded to `--download-dir` (default `<output-dir>\.download`) while the previous one is labelled,
  and deleted when done. A failed download is retried (`--retries`, default 3), then skipped: the run goes on, and
  the next run with the same `--output-dir` fetches only what is missing.
- **`--shard K/N`** splits the files over machines or GPUs: `--shard 0/4` … `--shard 3/4`, same `--output-dir`
  (shared disk) or one each. Every shard writes `summary.shardKofN.json` and `progress.shardKofN.json`, plus
  `summary.json` merged from all finished files (the last shard's is complete). The viewer combines the shards'
  progress.

## Common options of `run`

| Option | Default | Meaning |
|---|---|---|
| `--policy FILE` | `policy\russia_policy.json` | Another policy file (copy it to try changes) |
| `--write-clean` | off | Also write `<name>.clean.jsonl.zst` (removed paragraphs cut out, names rewritten) |
| `--compress` | `zst` | `none` = plain `.jsonl` outputs (labels, rewrites, clean) instead of `.jsonl.zst` |
| `--compress zst` | none | Compress the clean output |
| `--review-as remove` | keep | What the clean output does with "review" paragraphs |
| `--all-labels` | off | Score every label on every paragraph (for sampling; slower) |
| `--no-rewrite` | off | No place-name rewrite |
| `--group-field F` | none | Break the composition down by field F (e.g. `source`) |
| `--fast-model` / `--judge-model` | modernbert / deberta | `bge-m3` for Ukrainian / Russian-language text |
| `--device` | auto | `cpu`, `cuda`, `cuda:0,cuda:1` … |
| `--limit N` | all | First N lines per file |

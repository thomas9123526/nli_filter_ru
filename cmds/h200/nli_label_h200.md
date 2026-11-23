# nli_label.py on 8 × H200: every argument, sizing a run, launching it

This is the reference for large `nli_label.py` runs (hundreds of GB to TB). It lists every argument with its
default and the setting to use on the 8 × H200 machine, explains how to measure a run's speed before committing to the
full corpus, and how to start, watch, stop and resume it.

## Which document covers what

| Document | Tool | Content |
|---|---|---|
| **this file** | `nli_label.py` | All arguments, H200 settings, sizing, `run_label_shards.sh` |
| `cmds\h200\linux_h200.md` | `nli_filter.py` | The H200 machine: environment, checks, `run_shards.sh`, outputs, troubleshooting (sections 1–3 and 12 apply to both tools) |
| `cmds\h200\batch_size_and_vllm.md` | both | Choosing the batch size and copies per GPU by measurement; why not vLLM |
| `cmds\h200\h200_readiness.md` | `nli_filter.py` | Review of the scripts for multi-GPU runs |
| `shard_commands.py` | `nli_filter.py` | Writes the command lines for N copies |
| `cmds\labeling\quick_start.md` | `nli_label.py` | The labelling workflow (sample → hand-label → eval → run); short option table |
| `cmds\labeling\outputs.md` | `nli_label.py` | What a run writes, the report, `review`, `redecide` |

## 1. Where the time goes

A run has three stages. Each needs its own lever.

| Stage | Runs on | Speed (one process) | Lever |
|---|---|---|---|
| Read, decompress, keyword-scan, split paragraphs | 1 CPU core | about 40 MB/s (measured for `nli_filter.py`; `nli_label.py` does the same work plus paragraph splitting) | **more copies** (`--shard`) |
| Score (paragraph, hypothesis) pairs with ModernBERT | GPU | thousands of pairs/s per H200 (to be measured, section 4) | `--batch-size`, copies per GPU |
| Re-score the uncertain pairs with the DeBERTa judge | GPU | ~2–3 × slower per pair, on ~10–20 % of the pairs | `--uncertain-band`, `--judge-model none` |

**Only paragraphs with a keyword reach the models.** For a web corpus that is a few percent of the documents, so the
CPU stage over the whole corpus often matters as much as the GPU stage. 1 TB at 40 MB/s is about 7 hours for one
process, but about 25 minutes for 16 copies. That is why the recommended launch runs 2 copies per GPU.

Model work per labelled paragraph (the cascade only runs later levels when needed):

| Policy | Pairs per paragraph (typical) |
|---|---|
| Russia-side v2 (`policy\russia_llm_policy_v2.json`) | ~13: gate + 5 subjects + 7 framing (+ hate labels on gate-negative paragraphs) |
| A's v5 (`policy\russia_policy_v5.json`) | ~25–35: gate + 14 subjects + 19 framing |

## 2. Every argument of `nli_label.py run`

`python nli_label.py run INPUTS... --output-dir DIR [options]`. `-v` (more log lines) goes **before** `run`.

### Input and output

| Argument | Default | What it does | On 8 × H200 |
|---|---|---|---|
| `INPUTS` | (required) | Files, folders (searched recursively), globs, or server addresses (`ftp://`, `sftp://`, `s3://`, `minio://`). `.jsonl`, `.jsonl.zst`, `.jsonl.gz`, `.parquet`, … | A folder or glob of many files: sharding splits by file |
| `--output-dir` | (required) | Folder for the outputs. One `<name>.summary.json` per finished file marks it done | One folder for all copies (the shards share it) |
| `--write-clean` | off | Also write `<name>.clean.jsonl.zst`: removed paragraphs cut out, place names rewritten, emptied documents dropped | On for the training-data run; off for measuring |
| `--compress` | `zst` | `zst`: every output as `.jsonl.zst`; `none`: plain `.jsonl` | Keep `zst` (5–10 × smaller) |
| `--limit N` | all | Only the first N lines of each file | For the sizing run (section 4) |
| `--overwrite` | off | Redo files that are already finished | Off: a rerun resumes |
| `--chunk-lines` | 64 | Lines handed to the models at once (all their paragraphs are batched together) | 256–512 on a GPU; larger chunks give fuller batches |

### Policy and decisions

| Argument | Default | What it does | On 8 × H200 |
|---|---|---|---|
| `--policy` | `policy\russia_policy.json` (v1) | The policy file: labels, thresholds, decisions, exceptions, keywords, place names | **Always give it** (e.g. `policy/russia_llm_policy_v2.json` or `policy/russia_policy_v5.json`) |
| `--all-labels` | off | Score every label on every gated paragraph (no cascade). Decisions are the same; only more scores are stored | Off (2–3 × more pairs); on only for a hand-label sample run |
| `--review-as` | `keep` | What the clean copy does with `review` paragraphs (`keep` or `remove`); they are counted either way | A policy decision for the training set |
| `--min-doc-chars` | 50 | A document shorter than this after cleaning counts as removed | Default |
| `--no-rules` | off | Turn off the cheap rules that mark incidental keywords (language menus, company names) | Off |

### Place names

| Argument | Default | What it does |
|---|---|---|
| `--no-rewrite` | off | No place-name rewrite in the clean copy |
| `--place-names` | the policy's `place_names_file`, else `policy\place_names.csv` | The mapping table (overrides the policy's) |
| `--place-name-exceptions` | the policy's, else `policy\place_name_exceptions.txt` | Patterns that are never rewritten |

### Fields of the input lines

| Argument | Default | What it does |
|---|---|---|
| `--text-field` | `text` | The field with the document text |
| `--id-field` | `id` | Copied into the labels rows (empty = none) |
| `--group-field` | none | Break the composition report down by this field (e.g. `source`) |
| `--topic-field` | the policy's, else none | The corpus' own topic field (dot path for nested: `metadata.topic`); see `cmds\labeling\russia_llm.md` |
| `--topic-mode` | the policy's, else `hint` | `hint`, `trust` or `off` for the topic field |

### Models

| Argument | Default | What it does | On 8 × H200 |
|---|---|---|---|
| `--fast-model` | `modernbert` | Scores every pair: `modernbert`, `deberta`, `bge-m3` (multilingual), or a folder | `modernbert` for English-heavy data; `bge-m3` for much Russian / Ukrainian text (measure first) |
| `--judge-model` | `deberta` | Re-scores pairs inside the uncertain band; `none` = off | Keep `deberta` for the real run (0 wrongly removed on the cases vs 2 without) |
| `--uncertain-band LOW HIGH` | `0.6 0.95` | Fast scores in this range go to the judge | Default; a narrower band (e.g. `0.6 0.9`) sends fewer pairs to the judge |
| `--device` | `auto` | `cuda:0`, `cuda:0,cuda:1`, `cpu`, … | One GPU per copy (`run_label_shards.sh` sets it) |
| `--mode` | `auto` | `single`, `thread` or `process` when one copy uses several devices; `auto` = single for one device | Leave `auto` with one GPU per copy |
| `--dtype` | `auto` | `auto` = bfloat16 on H200 (fp16 on older GPUs, fp32 on CPU) | Default |
| `--batch-size` | 32 | Pairs per model call, for the fast model and the judge | **256** to start; raise while lines/s improves (section 4) |
| `--max-length` | 512 | Tokens per (paragraph, hypothesis) pair; longer pairs are cut | Default: paragraphs are at most 2,000 characters (~500 tokens) |
| `--workers-per-device` | 1 | Model copies per device inside one process | 1 (use 2 processes per GPU instead) |
| `--inflight` | 1 on one device | Chunks scored at once inside one process | Default with one GPU per copy |
| `--models-root` | `models/` | Where the model folders are | Default when the models are copied with the project |
| `--cpu-threads` | torch default | Threads for CPU scoring | Not used on GPU |

### Splitting the work, server input

| Argument | Default | What it does | On 8 × H200 |
|---|---|---|---|
| `--shard K/N` | none | Only every N-th file, starting at K. Copies with the same `--output-dir` share one run folder; the last one to finish writes the complete `summary.json` | `run_label_shards.sh` gives each copy its shard |
| `--download-dir` | `<output-dir>/.download` | Where server files are downloaded while the previous one is labelled; deleted when done | A fast local disk |
| `--retries` | 3 | Download retries before a file is skipped (a rerun retries it) | Default |

### The other commands

| Command | Main arguments | Use |
|---|---|---|
| `report RUN` | – | Print a run's composition again |
| `review RUN --out FILE` | `--actions review remove …`, `--policy`, `--context` | The human-review queue as a hand-label file |
| `redecide RUN --output-dir NEW` | `--policy`, `--write-clean`, `--compress`, `--review-as`, `--topic-field` | Apply a changed policy from the stored scores, no models (minutes even for a big run) |
| `sample RUN --out FILE` | `--random`, `--top`, `--near`, `--low`, `--label`, `--exclude` | Pick paragraphs to hand-label |
| `eval LABELS...` | `--policy`, `--target-recall`, `--miss`, model arguments | Per-label precision / recall and thresholds from hand labels |

`python nli_label.py <command> --help` prints the same list for each command.

## 3. Launch: `run_label_shards.sh`

`run_label_shards.sh` starts `COPIES_PER_GPU × GPUs` copies, each on one GPU with its own `--shard`, all into one
output folder, then prints the merged report. Logs go to `OUTPUT_DIR/logs/shard-K.log`.

```bash
# the real run: 2 copies per GPU = 16 copies on 8 H200s
./run_label_shards.sh /data/corpus /data/label_out 2 \
    --policy policy/russia_llm_policy_v2.json --write-clean --batch-size 256 --chunk-lines 256

# only some GPUs, or another Python
NLI_DEVICES="0 1 2 3" PYTHON=python3 ./run_label_shards.sh /data/corpus /data/label_out 2 --policy ...
```

The same by hand (one line per copy; K = 0 … 15, GPU = K mod 8):

```bash
python nli_label.py run /data/corpus --policy policy/russia_llm_policy_v2.json --output-dir /data/label_out \
    --write-clean --batch-size 256 --chunk-lines 256 --device cuda:3 --shard 3/16 > /data/label_out/logs/shard-3.log 2>&1 &
```

- **Resume:** run the same command again. Finished files are skipped; a file that was half done starts again.
- **Stop:** Ctrl+C stops all copies (the script forwards it). Outputs are written atomically, so a stopped file
  leaves no half file behind.
- **Watch:** `tail -f /data/label_out/logs/shard-*.log`, `nvidia-smi -l 5`, or the viewer's **Labelling runs**
  page (it combines the shards' `progress.shardKofN.json`).
- **Many files help:** sharding works per file. With fewer files than copies, some copies have nothing to do; with
  a few huge files, one copy may run long after the others finish.

## 4. Sizing a run before the full corpus

Measure on a slice of the real corpus, on the real machine, with the real settings. Estimates from other machines are
only good to an order of magnitude.

1. **Run the slice:** the same command as the real run, with `--limit` and a test folder. For example 20,000 lines
   per file, on all 16 copies:
   ```bash
   ./run_label_shards.sh /data/corpus /data/label_size 2 --policy policy/russia_llm_policy_v2.json \
       --batch-size 256 --chunk-lines 256 --limit 20000
   ```
2. **Read `/data/label_size/summary.json`:**

   | Field | Meaning |
   |---|---|
   | `stats.lines` | Lines read |
   | `stats.docs.untouched` / `stats.lines` | Share with no keyword (never reaches a model) |
   | `stats.paragraphs` | Paragraphs labelled, per action |
   | `timing.fast_pairs`, `timing.judge_pairs` | Model pairs (fast, judge) |
   | `timing.run_seconds` | Wall time of the last copy (each shard's own: `summary.shardKofN.json`) |

3. **Scale up:** `full hours ≈ run_seconds × (lines in the corpus ÷ stats.lines) ÷ 3600`. Count the lines with the
   manifest or `zstd -dc … | wc -l` on a few files, then extrapolate by size. This assumes the slice is like the rest
   of the corpus. If the corpus mixes sources, take the slice from all of them.
4. **Tune, then measure again** (as in `batch_size_and_vllm.md`):

   | `nvidia-smi` shows | Then |
   |---|---|
   | GPU use low (< 50 %) | The CPU stage is the limit: 3 copies per GPU, or more files |
   | GPU use high, memory < 70 % | `--batch-size 512` |
   | Memory near full, or out-of-memory errors | Halve `--batch-size` |
   | Judge pairs > 25 % of fast pairs | Consider `--uncertain-band 0.6 0.9` (check the cases first) |

   Stop when lines/s no longer improves.

**Rough expectation before measuring** (an estimate, not a measurement: 1 TB of text ≈ 250 M documents, 3 % with a
keyword, 3,000–5,000 ModernBERT pairs/s per H200, judge on):

| Policy | Keyword share 1 % | 3 % | 10 % |
|---|---|---|---|
| Russia-side v2 | ~1.5 h | ~3–4 h | ~10–12 h |
| A's v5 | ~2.5 h | ~6–7 h | ~20–25 h |

1 trillion tokens is about 4 TB of text: multiply by 4.

## 5. Checklist before a full run

- [ ] `python nli_label.py run <one small file> --policy … --device cuda:0 --limit 100 --output-dir /tmp/t` works (models load, CUDA seen, output written)
- [ ] The policy is the one you mean (`summary.json` → `policy.path`), its thresholds come from `eval` where possible
- [ ] Sizing run done (section 4); the extrapolated time fits the window
- [ ] Disk space: the clean copy is about the size of the input; the labels are much smaller (one short row per line,
      plus the scores of labelled paragraphs); read the real ratio from the sizing run's output folder
- [ ] `--write-clean` and `--review-as` set as the training set needs
- [ ] Output folder on a local disk; `--download-dir` on a fast disk for server input
- [ ] After the run: `nli_label.py report`, a look at the review queue (`review`), spot checks in the viewer

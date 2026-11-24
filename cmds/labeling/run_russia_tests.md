# Run `nli_label.py` on the Russia-side test data

Both commands use the Russia-side policy and write into `dataset\`, so the viewer finds the results by itself. Run
them in `D:\hkc\nli_filter2` (`py -3.12 …` on the development PC; `python …` inside a venv, see
`cmds\setup\python_launcher.md`).

## In one command, from the JSON file

`nli_label.py` reads JSON-lines corpora (one document per line). A test-set file such as
`labels\russia_llm_docs_v1.json` or `labels\russia_llm_cases_v1.json` is one JSON object with everything inside, so
it cannot be given to `nli_label.py` directly. `tools\label_test_set.py` does all three steps in one go: builds the
file's corpus in `dataset\` (as the builders and the viewer's Save do), runs `nli_label.py` with the policy named in
the file, then prints expected vs result.

```powershell
py -3.12 tools\label_test_set.py labels\russia_llm_docs_v1.json
py -3.12 tools\label_test_set.py labels\russia_llm_cases_v1.json --output-dir dataset\out_label_ru_v2_judge
py -3.12 tools\label_test_set.py labels\russia_llm_cases_v1.json --fresh -- --judge-model none
```

| Option | Meaning |
|---|---|
| `--output-dir` | Default `dataset\out_label_<file name>` (e.g. `dataset\out_label_russia_llm_docs_v1`) |
| `--policy` | Default: the policy named in the file (`"policy"`) |
| `--fresh` | Delete the output folder first (no leftovers of deleted or renamed cases); without it, `--overwrite` is used |
| `--no-clean` | No clean copy (`--write-clean` is the default) |
| `--details` | Every text / paragraph in the comparison, not only the misses |
| `-- …` | Everything after `--` goes to `nli_label.py run` unchanged: `--judge-model none`, `--topic-field topic --topic-mode trust`, … |

The run lands in `dataset\` like any other: the viewer's run page and "Expected vs result" work on it.

The step-by-step commands below do the same by hand.

## 1. The multi-paragraph test documents (`dataset\test_corpus_docs_ru`)

```powershell
py -3.12 nli_label.py run dataset\test_corpus_docs_ru --policy policy\russia_llm_policy_v2.json --output-dir dataset\out_label_docs_ru_judge --write-clean --overwrite
```

The corpus is built from `labels\russia_llm_docs_v1.json` (`py -3.12 tools\build_russia_llm_docs.py --corpus-only`
rebuilds it after editing that file, or on another computer: `dataset\` is not in git).

## 2. The cases (`labels\russia_llm_cases_v1.json`)

`nli_label.py` does not read the `.json` case file itself: it runs on the **corpus made from it**,
`dataset\test_corpus_cases_ru` (one `.jsonl.zst` per case). The viewer rebuilds that corpus on every **Save** in the
case editor. After editing the JSON by hand, rebuild it first:

```powershell
py -3.12 tools\build_cases_corpus.py --cases labels\russia_llm_cases_v1.json
py -3.12 nli_label.py run dataset\test_corpus_cases_ru --policy policy\russia_llm_policy_v2.json --output-dir dataset\out_label_ru_v2_judge --write-clean --overwrite
```

## Options

| Option | Why |
|---|---|
| `--overwrite` | Replaces the run in that folder. Without it, files that are done already are skipped (nothing changes) |
| a new `--output-dir` (e.g. `dataset\out_label_ru_v2_judge_2`), without `--overwrite` | Keeps the old run for comparison; the viewer shows the **newest** run per corpus (`auto_datasets`) |
| `--judge-model none` | Faster, ModernBERT only (the DeBERTa judge is on by default) |
| `--compress none` | Plain `.jsonl` outputs to open in an editor (default `.jsonl.zst`) |
| `--topic-field topic --topic-mode trust` (or `hint` / `off`) | Tests the topic modes on case texts that have a topic (set in the case editor) |

Each run takes about 2–3 minutes on the development PC's CPU with the judge.

## See the results

- **Viewer**: reload the run page, e.g. http://localhost:8000/label/run/?run=out_label_ru_v2_judge (or
  `out_label_docs_ru_judge`). The **Expected vs result** panel at the top lists every line that does not match;
  details in `cmds\viewer\labels_pages.md`.
- **Terminal**:
  ```powershell
  py -3.12 tools\compare_cases.py dataset\out_label_ru_v2_judge --corpus dataset\test_corpus_cases_ru
  py -3.12 tools\compare_docs.py dataset\out_label_docs_ru_judge --corpus dataset\test_corpus_docs_ru
  ```
  (`--details` lists every text / paragraph, not only the ones that do not match.)

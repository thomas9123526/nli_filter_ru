# The benchmark corpus (`dataset\corpus_benchmark`)

Made 2026-11-25 from the collected benchmark in `dataset\benchmark\` by `tools\build_benchmark_corpus.py`; since
2026-11-27 every source field is kept (the clarity tags among them) and sets without a side are accepted. The
benchmark keeps growing, so the builder takes every `benchmark_ru_llm_<name>_v<N>.jsonl` it finds; the number of files
and lines is printed by each build and written to the manifest (e.g. on 2026-11-27: 40 files, 440 lines). The source
files are not changed.

## Folder structure

There is one folder per side and topic. Every file name is unique, so a labelling run's outputs never clash.

```
dataset/corpus_benchmark/
  russian/companies/russian_companies__v1.jsonl.zst    v1: one sentence per line
  russian/companies/russian_companies__v2.jsonl.zst    v2: the same kind of item as several paragraphs
  russian/<topic>/…
  ukrainian/<topic>/…
  shared/contested_history/contested_history__v1.jsonl.zst     sets without a side
  shared/negative_controls/negative_controls__v1.jsonl.zst
dataset/corpus_benchmark.manifest.json                 every file, its lines, decisions and clarity counts
```

| Source file (`dataset\benchmark\`) | Side | Case | Corpus file |
|---|---|---|---|
| `benchmark_ru_llm_russian_<topic>_v<N>.jsonl` | `russian` | `russian_<topic>` | `russian\<topic>\russian_<topic>__v<N>.jsonl.zst` |
| `benchmark_ru_llm_ukrainian_<topic>_v<N>.jsonl` | `ukrainian` | `ukrainian_<topic>` | `ukrainian\<topic>\ukrainian_<topic>__v<N>.jsonl.zst` |
| any other `benchmark_ru_llm_<name>_v<N>.jsonl` (e.g. `contested_history`, `negative_controls`) | `shared` | `<name>` | `shared\<name>\<name>__v<N>.jsonl.zst` |

A new set needs no code change. Files without `_v<N>` (`benchmark_ru_llm_long_docs.jsonl`,
`benchmark_ru_llm_mixed_docs.jsonl`) and `benchmark-clue-candidates.md` are not part of the corpus (the builder prints
"skip …").

## A line

**Every source field is kept**: `text`, `decision`, `label`, `note`, the clarity tags `clarity` (clear / hard /
ambiguous) and `clarity_reason`, and set-specific fields such as `topic` (contested_history), `country` and
`gate_expected` (negative_controls), and any field added later. A source field `group` (negative_controls: clean / …)
is kept as **`control_group`**, because the corpus's `group` is the side. On any other name clash the builder's field
wins. No field except `text` is required: a line without `clarity` is built as before (real corpora never have tags).

These fields are added:

| Field | Example | Meaning |
|---|---|---|
| `id` | `ukrainian_traditions_v2#11` | `<case>_v<N>#<k>`, where k is the 1-based line number in the source file |
| `item` | `ukrainian_traditions#11` | Links the v1 and v2 versions of the same item. Only written when all versions of the case have the same number of lines |
| `expected_action` | `flag` | A copy of `decision`, read by the viewer's "Expected vs result" panel |
| `case`, `group` | `ukrainian_traditions`, `ukrainian` | The viewer's case and group columns (`group` = side: russian / ukrainian / shared) |
| `variant` | `v2` | v1 = one sentence, v2 = several paragraphs |
| `source` | `dataset/benchmark/benchmark_ru_llm_ukrainian_traditions_v2.jsonl` | Where the line came from |

```json
{"id": "negative_controls_v1#1", "item": "negative_controls#1", "text": "The Bialowieza Forest on the border of Belarus and Poland …",
 "expected_action": "keep", "case": "negative_controls", "group": "shared", "variant": "v1",
 "control_group": "clean", "country": "Belarus", "decision": "keep", "label": "none (neighbouring country)",
 "gate_expected": false, "clarity": "clear", "clarity_reason": "nature text with no link to either side", "note": "real",
 "source": "dataset/benchmark/benchmark_ru_llm_negative_controls_v1.jsonl"}
```

Ids, cases, file names and line numbers of the russian / ukrainian sets are the same as before 2026-11-27, so older
runs stay valid. `nli_label.py` reads only `id` and `text`; the other fields are only for the viewer (a run on a corpus
with or without the extra fields gives the same labels; see `tests\test_build_benchmark_corpus.py`).

At the end the builder prints the lines per side and per clarity value, and the lines without `clarity`; the manifest
records the same (`lines_per_side`, `clarity`, `no_clarity`, and `clarity` / `decisions` per file).

## Options

| Option | Meaning |
|---|---|
| `--src DIR` | the benchmark folder (default `dataset\benchmark`) |
| `--out DIR` | the corpus folder (default `dataset\corpus_benchmark`); the manifest is `<DIR>.manifest.json` next to it |
| `--sides russian[,ukrainian,shared]` | build only these sides (default: all) |
| `--flat` | no `<side>\` folder level: `<topic>\<case>__v<N>.jsonl.zst` |

## Rebuild and label it

After editing or adding `dataset\benchmark\*.jsonl` (each build replaces its corpus folder):

```powershell
# the full corpus: russian, ukrainian and shared sets
py -3 tools\build_benchmark_corpus.py
# the Russian-side corpus: only the russian_* sets, flat (<topic>\russian_<topic>__v<N>.jsonl.zst);
# contested_history and negative_controls are not in it
py -3 tools\build_benchmark_corpus.py --sides russian --flat --out dataset\corpus_benchmark_russian

python nli_label.py run dataset\corpus_benchmark --policy policy\russia_llm_policy_v2.json --output-dir dataset\out_label_benchmark --write-clean
```

The corpora also appear in the viewer's Start-a-run form on `/label/`. The run page shows "Expected vs result"
from `expected_action`.

## Open points

1. **The `flag` lines.** These are mostly `hostility_ukrainians` lines (e.g. on 2026-11-27: 22 lines, 20 of them
   `hostility_ukrainians`, 2 `general_hostility`). nli_label never gives
   a paragraph the action "flag", so the viewer always shows these lines as not matching. Should they count as
   `remove` (the agreed symmetric rule: hate both ways is removed), or stay `flag` because that is what this benchmark
   means? Not decided yet.
2. **Sets whose v1 and v2 have different line counts** (e.g. on 2026-11-27 the companies sets: Russian 10 / 8,
   Ukrainian 11 / 9) cannot be matched by line number, so their files have no `item` field. In the other sets, line k
   of v1 and line k of v2 are assumed to be the same item.
3. **Neither the benchmark nor the corpus is in git.** `.gitignore` ignores everything under `dataset/`. Only
   `tools\build_benchmark_corpus.py` and this page are committed. An exception for `dataset/benchmark/` can be added
   if the source files should be in git.

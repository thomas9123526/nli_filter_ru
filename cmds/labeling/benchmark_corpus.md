# The benchmark corpus (`dataset\corpus_benchmark`)

Made 2026-11-25 from the collected benchmark in `dataset\benchmark\` by `tools\build_benchmark_corpus.py`. It holds 28
`.jsonl.zst` files with 288 lines. The source files are not changed.

## Folder structure

There is one folder per side and topic. Every file name is unique, so a labelling run's outputs never clash.

```
dataset/corpus_benchmark/
  russian/companies/russian_companies__v1.jsonl.zst    v1: one sentence per line
  russian/companies/russian_companies__v2.jsonl.zst    v2: the same kind of item as several paragraphs
  russian/famous_people/…  food/…  media/…  persons/…  places/…  traditions/…
  ukrainian/  (the same 7 topics)
dataset/corpus_benchmark.manifest.json                 every file, its line count and its decisions
```

| Source file (`dataset\benchmark\`) | Corpus file |
|---|---|
| `benchmark_ru_llm_<side>_<topic>_v<N>.jsonl` | `corpus_benchmark\<side>\<topic>\<side>_<topic>__v<N>.jsonl.zst` |

`benchmark-clue-candidates.md` (the list of clue types) is not part of the corpus.

## A line

Your fields are kept: `text`, `decision`, `label`, `note`. These fields are added:

| Field | Example | Meaning |
|---|---|---|
| `id` | `ukrainian_traditions_v2#11` | `<side>_<topic>_v<N>#<k>`, where k is the 1-based line number in the source file |
| `item` | `ukrainian_traditions#11` | Links the v1 and v2 versions of the same item. Only written when both files have the same number of lines |
| `expected_action` | `flag` | A copy of `decision`, read by the viewer's "Expected vs result" panel |
| `case`, `group` | `ukrainian_traditions`, `ukrainian` | The viewer's case and group columns |
| `variant` | `v2` | v1 = one sentence, v2 = several paragraphs |
| `source` | `dataset/benchmark/benchmark_ru_llm_ukrainian_traditions_v2.jsonl` | Where the line came from |

```json
{"id": "ukrainian_traditions_v2#11", "item": "ukrainian_traditions#11", "text": "Poltava people are not real people. …",
 "expected_action": "flag", "case": "ukrainian_traditions", "group": "ukrainian", "variant": "v2",
 "decision": "flag", "label": "hostility_ukrainians", "note": "synthetic; dehumanising language",
 "source": "dataset/benchmark/benchmark_ru_llm_ukrainian_traditions_v2.jsonl"}
```

The decisions across all 288 lines are keep 171, remove 67, review 36 and flag 14.

## Rebuild and label it

```powershell
py -3 tools\build_benchmark_corpus.py          # after editing dataset\benchmark\*.jsonl (replaces the corpus folder)
python nli_label.py run dataset\corpus_benchmark --policy policy\russia_llm_policy_v2.json --output-dir dataset\out_label_benchmark --write-clean
```

The corpus also appears in the viewer's Start-a-run form on `/label/`. The run page shows "Expected vs result"
from `expected_action`.

## Open points

1. **The 14 `flag` lines.** These are all `hostility_ukrainians` lines in the Ukrainian files. nli_label never gives
   a paragraph the action "flag", so the viewer always shows these lines as not matching. Should they count as
   `remove` (the agreed symmetric rule: hate both ways is removed), or stay `flag` because that is what this benchmark
   means? Not decided yet.
2. **The companies files have different line counts in v1 and v2:**
   - Russian: 10 in v1, 8 in v2.
   - Ukrainian: 11 in v1, 9 in v2.

   Their lines cannot be matched by line number, so those 4 files have no `item` field. In the other 24 files, line k
   of v1 and line k of v2 are assumed to be the same item.
3. **Neither the benchmark nor the corpus is in git.** `.gitignore` ignores everything under `dataset/`. Only
   `tools\build_benchmark_corpus.py` and this page are committed. An exception for `dataset/benchmark/` can be added
   if the source files should be in git.

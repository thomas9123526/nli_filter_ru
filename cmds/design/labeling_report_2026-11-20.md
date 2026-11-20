# Report 2026-11-20: from one-question filter to policy labelling

Built while you were away, following your project summary (*russia-filter-labeling-summary.md*).
Start with [cmds/labeling/README.md](../labeling/README.md) and [quick_start.md](../labeling/quick_start.md).

## What changed and why

`nli_filter.py` asked one question per line ("is it about Russia?") and removed whole lines. That is **wider than
A's policy**: its check-1 hypotheses included `geography`, `history`, `army` and `region`, so geography and factual
war content were removed, which the policy says to keep. The new tool follows the guide instead:

| Guide | Built |
|---|---|
| Gate: entity lists + backstop hypothesis | keywords + marker terms + level-0 label `involves_russia` |
| Level 1 subjects, each its own decision | 12 labels in `policy/russia_policy.json` |
| Level 2 narratives, only after politics / war / history | 10 narrative labels + flag + near-miss guard, cascade via `run_if` |
| Paragraph level | documents split into paragraphs; only paragraphs with a hit are labelled and removed |
| Place-name rewrite with a mapping table, logged | `nli_names.py`, `policy/place_names.csv` (48 rows), exceptions file |
| Labels as columns, never delete raw data | `<name>.labels.jsonl`; clean copy only with `--write-clean` |
| Token-weighted composition | the `run` / `report` table, by action, label and group |
| Hand-label ~200 first, threshold per label | `sample` → `tools/label_tool.html` → `eval` (P/R/F1, suggested thresholds, CRC) |
| Policy change = rerun the filter, not relabel | `redecide`: new thresholds / decisions from stored scores, no models |
| Wikidata entity lists (next step in the guide) | `keywords/russia_candidates.txt`: 200 candidates to review |

`nli_filter.py`, the viewer and all earlier tools are unchanged.

## New files

| File | What |
|---|---|
| `nli_label.py` | `run`, `sample`, `eval`, `report`, `redecide` |
| `nli_names.py` | place-name rewrite (also alone: `python nli_names.py --text "…"`) |
| `policy/russia_policy.json` | all labels: hypothesis, threshold, decision, level; markers; `run_if`; conflict rule |
| `policy/place_names.csv`, `policy/place_name_exceptions.txt` | rewrite table and exceptions |
| `tools/label_tool.html` | hand-labelling page (browser, no server) |
| `tools/make_gated_subset.py` | random gated documents from big files → one small file |
| `keywords/russia_candidates.txt` | Wikidata candidates (cities ≥ 100k, popular people, state media, companies). Not used until you copy lines into `keywords/russia.txt` |
| `labels/seed.jsonl` | the seed labelling set, pre-filled with Claude's drafts |
| `tests/test_label.py` | 31 tests, no models |
| `cmds/labeling/*.md` | the guides |
| `corpus_olmo/` (not in git) | 2 OLMo-mix DCLM web files, 152,826 documents, + `seed_docs.jsonl` (400 random gated documents) |

## Tests

- `python -m pytest tests/test_label.py`: **31 passed**.
- Whole suite without model tests (`-m "not slow"`): **193 passed, 1 skipped**. I installed `zstandard` into
  Python 3.12 from `pkgs` (offline wheel) because the existing `.zst` tests need it.
- The label tool's JavaScript was syntax-checked with node, and its decision logic was checked against the Python
  policy on 8 cases (all equal). I could not click through it in a browser: please try it first.

## Results on real data (OLMo-mix DCLM web text)

### Gate

152,826 documents (two DCLM files from `allenai/olmo-mix-1124`): **5,613 (3.67 %) hit a keyword or marker**. The other
96 % are untouched (only place names are rewritten). 400 of the 5,613 were picked at random → `corpus_olmo/seed_docs.jsonl`.

### Seed run (80 of those documents, all 25 labels, ModernBERT, CPU)

`out_label_seed/` (not in git): 197 paragraphs, 4,925 model pairs, **50 minutes** on this CPU (~1.6 pairs/s).

| Paragraph action | count |
|---|---|
| pass (gate below 0.5) | 128 |
| keep | 41 |
| review | 27 (mostly `history_soviet`) |
| remove | 1 |

Place names rewritten: Odessa → Odesa (3), Kiev → Kyiv (2), Chernobyl → Chornobyl (1).

### Seed labels: `labels/seed.jsonl`

**182 paragraphs** (197 sampled; 15 removed later by content screening, see "Content screening" below).
All of them count as a random sample (`picked_for` contains `random`; 75 are also a label's
top score, 39 near a threshold). **Pre-filled by Claude** (4 parallel drafting passes with one written brief,
`by: claude-draft`, `status: draft`). Drafts with a doubt have a note starting `[draft]`. Draft counts:
77 of 197 paragraphs involve Russia; most of them are Tsarist / Soviet history (37 `history_soviet`); 20
politics, 8 economy, 6 science, 4 war, 4 sport; **no** culture / celebrity / cost-of-living paragraphs and only 3
narrative paragraphs (`narr_soviet_nostalgia`, one article praising the 1917 revolution). This random web sample
simply has few of the labels the policy removes: the per-label rounds must target them (`sample --label …`).

### First eval against the drafts (not decisions: the drafts are unchecked)

`python nli_label.py eval labels/seed.jsonl --include-drafts --judge-model none` (no model needed: the run's
scores are reused):

- **The gate is too strict.** At 0.5 it finds only 53 % of the paragraphs the drafts call Russia-related
  (precision 0.79). Most misses are Tsarist / Soviet history, which the wording "Russia, the Russian state or
  Russian people" scores low. Two other wordings tested (the guide: try 2–3 phrasings), at threshold 0.5:

  | Gate hypothesis | precision | recall | F1 |
  |---|---|---|---|
  | This text is about Russia, the Russian state or Russian people. (guide) | 0.79 | 0.53 | 0.64 |
  | This text is about Russia, the Soviet Union or Russian people. | 0.78 | 0.61 | 0.69 |
  | **This text mentions Russia, the Soviet Union, the Russian Empire or Russian people.** | 0.68 | **0.86** | **0.76** |

  **The policy now uses the third wording** (a gate must favour recall: what it misses never reaches any label).
  The old wording is in the label's note. To compare yourself:
  `python nli_label.py eval labels\seed.jsonl --include-drafts --judge-model none` (scores are cached).
- `history_soviet`: precision 0.63, recall 0.59 at 0.8; best-F1 threshold 0.61.
- `politics_government`, `economy_business`, `science_technology`, `war_ukraine`: recall 0.10–0.33 at 0.8: the
  model's scores for these are low on web paragraphs; thresholds will have to come down a lot (best-F1 0.07–0.21)
  once checked labels confirm it.
- Actions: agreement 125 / 197 (63.5 %); **wrongly removed ~0 tokens, missed ~623 tokens**. With these thresholds
  the policy errs on the side of keeping, mostly via the strict gate.
- `reports_or_debunks`: the drafting passes used it for any news that quotes officials, not only for narratives
  being reported or debunked. Decide which meaning you want (the hypothesis would change with it).

These numbers will move when you check the drafts. They show the method works end to end and where to look first.
(They were measured on the 197 items before the content screening below.)

### Content screening of the datasets

All datasets were screened for unwanted (explicit or crude) words: a word-list scan, then each hit read.

| File | Result |
|---|---|
| `labels/bench_synthetic_v1.jsonl` | nothing found |
| `labels/seed.jsonl` | **197 → 182 items.** 15 paragraphs removed (6 from two unsuitable web pages, 9 more containing a listed word, including crude language). In 4 items only the grey context had a listed word: the context was cleared, the item kept. Removed keys: `_meta.removed` |
| `corpus_olmo/seed_docs.jsonl` (local, not in git) | **141 of 400 pages emptied** (every page with a listed word anywhere, also in comments or side text). The lines stay (text `""`, `"removed": "content screening, 2026-11-20"`, URL dropped) so line numbers and seed keys still line up. 62 of the 182 seed paragraphs came from emptied pages: their own text passed the screening, they stay, marked `"source": {"removed": true}` |
| all other project files (test files, test corpora, keywords, code, docs) | nothing found |

The downloaded raw files `corpus_olmo/dclm/*.parquet` are not screened: they are raw OLMo-mix web data and contain
unsuitable pages like any web crawl.

## Decisions waiting for you / A's compliance team

1. **Thresholds**: all 0.8 (gate 0.5) are guesses. Set them from `eval` after the seed labels are checked.
2. **Review labels**: `literature_art`, `history_soviet`, `sport` are "review" (the guide's "Review / Policy call").
   Decide remove or keep for each.
3. **Conflicts**: a paragraph with both a remove label and a keep label → review (`"conflict"`). Alternative: remove
   or keep.
4. **Narratives vs keep subjects**: a narrative label removes the paragraph even if it is about war / politics
   ("keep if factual"). `reports_or_debunks` turns that into review for news that debunks.
5. **Place names**: historical events (Battle of Kiev), Chernobyl disaster, titles, quotes: see
   [place_names.md](../labeling/place_names.md).
6. **Candidate keywords**: review `keywords/russia_candidates.txt` (people with *granted* citizenship are marked
   CHECK; so are ambiguous city names like Perm, Engels, Pushkin).
7. **Language**: Russian-language text is not treated as Russia-related. Russian-language text is a separate
   decision in the guide.

## Next steps

1. Check the drafts in `labels/seed.jsonl` (label tool), then `eval`.
2. On a GPU machine: `run --all-labels` on a few thousand gated documents, then per-label rounds
   (`sample --label …`) until each label has 50 yes + 50 no.
3. A random round (`sample --random 300 …`) for the CRC guarantee and the weekly audit.
4. Codebook: turn the notes from labelling into rulings (label, rule, 3 yes / 3 no examples, decision).
5. SFT data (Nemotron post-training): the `messages` field needs a text field per turn. Labelling assistant turns
   only is a small addition (`--text-field` takes one string field today).
6. Speed on CPU: ~1 pair/s here. The ONNX int8 models in `models/` could be several times faster on CPU (not wired
   in yet).

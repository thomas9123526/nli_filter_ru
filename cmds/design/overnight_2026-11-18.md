# Overnight work, 2026-11-17 → 18: what changed, and how to try it

Plan steps 4 and 5 of `keyword_lexicon_plan.md` are built, tested, and checked with the real models on this PC
(CPU). Nothing is committed to git. Your keyword and hypothesis files are unchanged.

## Before you try it

1. **Restart `nli_playground.py`.** Its code changed (audit option).
2. **Restart the viewer** (`start_viewer.ps1`). The backend changed. The web pages are already built, so you don't
   need `-Rebuild`.
3. The first time you open a dataset, each result file is re-indexed (new index version), and the Keywords page
   shows "Indexing…" for a moment.

## 1. Keywords page (dataset page → **Keywords**)

One row per keyword over all result files:

- hits and lines
- % filtered and % kept
- % by rules
- lines with only this keyword
- mistakes (lines with `expect`)
- for level A: what the audit says
- flags: **mostly kept** (≥ 20 lines, ≥ 90% kept), **mostly rules**, **mistakes**, **A too broad?**,
  **A not audited**, **no hits**

Click a keyword to see its lines (filter by hit state, decision, or mistakes only). Each line opens in place.
Details are in `cmds/viewer/review_tools.md`.

## 2. Level-A audit (`--audit-strict`, Try: "audit A")

`python nli_filter.py <corpus> --audit-strict 0.05 ...` also runs 5% of the level-A lines (always the same
sample) through the rules and the models, and stores what they **would** decide. The decision stays filter.
In Try, the **audit A** checkbox audits every A line of the page; the score table then shows "audit: keep/filter".

**Real-model check (CPU, test_russia, Moscow and Kremlin made level A in a scratch copy of the keyword file):**
20 level-A lines were audited. The models would filter 18 and keep 2, and those 2 are exactly the 2 wrong lines:

| line | text | audit |
|---|---|---|
| incidental_name-003 | "Shares of Kremlin Capital Partners LLC, a hedge fund…" | keep (check 1 0.010) |
| fixed_expression-005 | "A Moscow mule is served in a copper mug…" | keep (check 1 0.250) |

The Review page's queue "Level-A audit: models would keep" listed exactly these two, and their record pages
explain it.

## 3. Review page (dataset page → **Review**) and the golden set

The Review page has five queues across all files:
- close to a threshold (unlabelled only)
- one keyword decides
- level-A audit would keep
- decided by the judge
- mistakes

▸ shows the text and explanation in place. **filter / keep** buttons label a line for the **golden set**
`golden/<dataset>.jsonl` (id, text, expect, where it came from). **The corpus is never changed.** The record
page has the same buttons, plus the audit box. The golden set is a normal test file: the Review page shows the
command to run it.

## 4. `nli_compare.py`: two runs, line by line (no models)

`python nli_compare.py out_ru_plain out_ru_kw` prints:
- accuracy, precision, recall, pairs and time of both runs
- every changed line marked **better** or **worse**, with reasons, scores, keywords and text
- what differs between the runs (settings, hypotheses, templates, keywords, lexicon)

On your two runs of 2026-11-17 it shows exactly the 2 changed lines: about-019 worse, the Moscow mule better.

## 5. `nli_replay.py`: other thresholds or fewer hypotheses from stored scores (no models)

`python nli_replay.py out_ru_plain --drop-check1 region geography --output-dir out_ru_plain_noregion` writes a
normal output folder (the viewer and `nli_compare.py` can read it). On your plain run, it showed that dropping
`region` and `geography` would fix the Moscow mule but lose about-004 (Saint Petersburg, 0.990 → 0.782), with no
model run.

Lines that depend on scores that early stop left out are marked "estimated". Run once with `--no-early-stop` for
exact replays. Details are in `cmds/testing/compare_and_replay.md`.

## 6. Smaller improvements

- **Try settings no longer keep a stale copy.** If you haven't edited the keywords or hypotheses in Try, a file
  that changed on disk is picked up by itself. If you have, a **↻ load the file** button appears next to the file
  name. (Your browser still has the old copy from before this change, so use that button once for
  `russia.txt`.)
- **Every hit now records its keyword as written in the keyword file** (`"keyword"` when the text differs in
  case), so the stats group "RUSSIA" and "Russia" together.
- **`summary.json` stores the lexicon details** (`country.lexicon_meta`: level, type, gloss, other meanings,
  exclude). For older runs, the viewer reads the keyword file instead.
- **The `--keywords-report` TSV** has level, type and level-A line columns.
- **`smoke_test.py`** now also checks replay + compare (same settings must give the same decisions), and the
  viewer's keywords, review and golden-label endpoints.

## Tests

- Filter: **175 passed**. New: `tests/test_lexicon.py` (audit, canonical keyword), `tests/test_compare.py`,
  `tests/test_replay.py`.
- Viewer: **137 passed**. New: `tests/test_review.py`, audit in `tests/test_explain_strict.py`, UI render of the
  Keywords / Review pages and the record golden label.
- `smoke_test.py` on this PC (CPU, i7-8700K, 16 GB): every step passes, including the new **replay + compare**
  step (40 lines, none changed) and the **viewer** step (keywords, review, golden label, edit + undo), except
  **"CPU, 2 workers, --mode process"**, which failed twice inside the smoke run.
  - **Cause: memory, not code.** That step starts 4 processes (2 fast + 2 judge), each with its own copy of a
    model. Run on its own, it passed, but free RAM fell to **1.6 GB of 16 GB**. Inside the smoke run, a judge
    worker died while loading. It passed in yesterday's pretest, and `nli_models.py` was not touched apart from
    the message below.
  - **Change:** when a worker dies while loading, the error now says so: "NLI worker process died while loading
    the model (… exit code …). Each process loads its own copy of the model: this is usually out of memory …
    Use fewer workers … or --mode thread." The old message was "did not start (died or timed out)".
  - **For you:** on 16 GB CPU machines, use `--mode thread` (it was faster in the smoke run anyway: 2.9 lines/s).
    The H200 and RTX 5090 machines have much more memory.

## Not done / for you to decide

- **Golden-set labels can't be edited in bulk**; one click per line. Tell me if you want keyboard shortcuts
  (f / k / ↓) on the Review page.
- **The flag thresholds are constants** in `viewer/backend/nli_viewer/results.py` (`NOISY_MIN_LINES` and the
  others). Tune them once you see real 6 TB numbers.
- **Run filter doesn't set `--audit-strict` for you.** Type it in the arguments, e.g. `--audit-strict 0.05`.
- **Adding** hypotheses can't be replayed (no scores exist for them): that needs a real run.

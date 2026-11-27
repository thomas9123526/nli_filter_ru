# 11_27_big_plan: benchmark clarity tags; Experiment page: expected vs decided, scoring without cache, draft clean-up

Planned 2026-11-27, to be built when the user says so ("do 11_27_big_plan", "I'm leaving", …). Background: the
conversation of 2026-11-27 (`cmds\conversation\2026-11-27.md`, "I have an LLM audit of the benchmark that tags each
line clear / hard / ambiguous"). The audit is saved: the table `labels\benchmark_clarity.csv` (362 rows, checked:
the 288 rows with a source file match it exactly) and the write-up `cmds\labeling\benchmark_clarity_audit.md`.

The estimate is about 3–3½ hours:
- tasks 1–4 (clarity tags): about 1–1½ h (the audit files are already in the project);
- task 5 (expected vs decided on the Experiment page): about 45 min – 1 h;
- task 6 (score again without the cache): about 30 min;
- task 7 (one automatic draft per identical draft): about 20–30 min.

**Rule for every task: real corpora have no tags.** Nothing may require `clarity`; without it every page, run and
command behaves exactly as now. The benchmark decisions are not changed (the 3 suggested fixes are the user's call).

## Tasks

### 1. The builder adds the tags (about 15 min)

`tools\build_benchmark_corpus.py` reads `labels\benchmark_clarity.csv` when it exists (`--clarity PATH`, default that
file; `--clarity none` = off) and adds to each line, matched by the source file name and line number:
- `clarity`: clear / hard / ambiguous;
- `clarity_reason`: the audit's reason.

Only when the CSV row's decision equals the source line's `decision` (and its text start matches); otherwise a warning
and no tag for that line. Rows for missing sets (contested_history, the two culture sets) are reported as "no source
file" and skipped. Text, ids, line numbers and the other fields stay as they are, so existing runs stay valid. The
summary printed at the end: tagged / not matched / skipped. Then rebuild `dataset\corpus_benchmark` and
`dataset\corpus_benchmark_russian` (same layout as now: the Russian side, `<topic>\russian_<topic>__vN.jsonl.zst`).

### 2. Nothing breaks without tags (about 10 min)

`nli_label.py` does not read these fields (check; add nothing). Tests: the builder with and without the CSV, a
mismatched row, a missing set; a label run on a corpus without tags gives the same labels file as before; the
viewer's expected panel, run page and nav on a run without tags show no clarity parts and no errors.

### 3. The viewer uses the tags (about 30–40 min)

Read `clarity` (and `clarity_reason`) with the other expected fields (`LabelRuns.expected`):
- **Expected vs result**: when any line has a tag, three scores next to the total, per the audit's recommendation:
  **clear** n / ok (%), **hard** n / ok (%), **ambiguous → review** (how many ambiguous lines the run sent to review,
  of all ambiguous). Follows the strict / quick switch.
- **The not-as-expected list** and the **run page's Expected column**: a clarity badge per line (reason on hover); a
  filter clear / hard / ambiguous on the run page (URL state like the others).
- **Experiment Prev / Next**: "stop at" options **clear**, **hard**, **ambiguous** (only when the run has tags).
- Simple-mode runs: the same scores and badges where the corpus line has a tag.

### 4. Docs and tests (about 15 min)

`cmds\labeling\benchmark_corpus.md`: the two new fields and the rebuild; `cmds\viewer\labels_pages.md`: the scores,
badges, filter and stop-at options. Backend and browser tests; the full suites.

### 5. Expected vs decided on the Experiment page (about 45 min – 1 h)

Asked 2026-11-27 ("this page should show expected vs decided at the output result"). A text that comes from a run line
(the page's own line, Prev / Next, "add a line … did not get as expected") keeps where it came from: the draft gets a
`sources` list next to `texts` (`{run, file, line}` or null for pasted text; old drafts without it still load).
`GET /api/labels/lab/base` also returns the line's expected fields (`expected_action`, `acceptable`, `note`, and
`clarity` once task 1 is done). Per text, next to "base → draft": **expected X** and **base ✓ / ✗**, **draft ✓ / ✗**,
with a strict / quick switch (labels/expected_rules.json, the same rule as the run page); a badge "fixed" when the
draft gets right what the base got wrong, "broken" for the opposite. When the text was edited after it came from the
line: "text edited" next to the expected (still shown). Saved drafts keep `sources`. Pasted texts: no expected.

### 6. Score again without the cache (about 30 min)

The instant result is the model service's in-memory score table (`CachedScorer` in nli_playground.py, kept until the
service restarts, keyed by the model names and judge band, so a cached score equals a fresh one for the same models).
On the Experiment page: a checkbox **"score again (no cache)"** next to "Run draft and base" (sends `reuse_scores:
false` and a new `fresh: true`: the base run fills the table anew, the draft then reuses those) and a **"Clear score
cache"** button (`POST /cache/clear` on the model service, through the viewer); the result line already says "N new
pairs, M reused" — add the time so a real run is visible.

### 7. One automatic draft per identical draft (about 20–30 min)

Asked 2026-11-27 ("the automatic items should be replaced if two environments are identical"). Identical = the same
draft policy and run settings (texts and the line it came from do not count). When an automatic draft is saved, an
older automatic draft identical to it is deleted (the newest stays, with its texts); when a named draft is identical,
the automatic one is not kept at all (the named one already has it). Named drafts are never deleted automatically.
The list shows "same as test1" when an automatic draft equals a named one (only until it is replaced).

# 11_27_big_plan: benchmark clarity tags; Experiment page: expected vs decided, scoring without cache, draft clean-up

Planned 2026-11-27, to be built when the user says so ("do 11_27_big_plan", "I'm leaving", …). Background: the
conversation of 2026-11-27 (`cmds\conversation\2026-11-27.md`, "I have an LLM audit of the benchmark that tags each
line clear / hard / ambiguous", and "I updated the benchmark files").

**The tags are in the benchmark files themselves** (updated by the user 2026-11-27 16:16): every line of
`dataset\benchmark\benchmark_ru_llm_*.jsonl` has `clarity` (clear / hard / ambiguous), `clarity_reason` and, in most
sets, `note`. 40 files, 440 lines: 306 clear, 72 hard, 62 ambiguous. The earlier separate audit table and write-up
(`labels\benchmark_clarity.csv`, `cmds\labeling\benchmark_clarity_audit.md`) were removed as no longer needed; they
matched the new files exactly (the 3 suggested fixes, Pink Floyd / Jamala / Chornobyl, were not applied).

The estimate is about 3½–4 hours:
- tasks 1–4 (clarity tags, new sets and fields): about 1–1½ h;
- task 5 (expected vs decided on the Experiment page): about 45 min – 1 h;
- task 6 (score again without the cache): about 30 min;
- task 7 (one automatic draft per identical draft): about 20–30 min;
- task 8 (a "Back to …" button on the Experiment page): about 30–45 min;
- task 9 (quick as the default profile): about 10 min.

**Rule for every task: real corpora have no tags.** Nothing may require `clarity`; without it every page, run and
command behaves exactly as now. The benchmark decisions are not changed.

## Tasks

### 1. The builder carries the tags and the new sets (about 20 min)

New since the first plan: sets contested_history, russian_culture and ukrainian_culture (now with files),
russian_values, ukrainian_values, negative_controls; new fields in some sets: `topic` (contested_history), `group`,
`country`, `gate_expected` (negative_controls). `tools\build_benchmark_corpus.py` today keeps only decision / label /
note, and expects `benchmark_ru_llm_<russian|ukrainian>_<topic>_vN.jsonl`. Change it:
- **Keep every source field** (`clarity`, `clarity_reason`, `note`, `topic`, `country`, `gate_expected`, and any later
  one), next to the added ones. The source's own `group` is kept as `control_group` (the builder's `group` stays the
  side).
- **Sets without a side** (`benchmark_ru_llm_contested_history_vN`, `benchmark_ru_llm_negative_controls_vN`): accepted;
  side `shared`, folder `shared\<topic>\`, case `contested_history` / `negative_controls`.
- Printed at the end: lines per clarity tag, and lines without one.
- Text, ids and line numbers of existing sets stay as they are, so existing runs stay valid.

Then rebuild `dataset\corpus_benchmark` (all sides: russian, ukrainian, shared) and `dataset\corpus_benchmark_russian`
(as now: only the `russian_*` sets, now 8 topics with culture and values, folder `<topic>\russian_<topic>__vN`).
**Open (default used unless the user says otherwise):** contested_history and negative_controls go only into the full
corpus, not into corpus_benchmark_russian.

### 2. Nothing breaks without tags (about 10 min)

`nli_label.py` does not read these fields (check; add nothing). Tests: the builder with tags in the source, a line
without them, a set without a side, a source `group`; a label run on a corpus without tags gives the same labels file
as before; the viewer's expected panel, run page and nav on a run without tags show no clarity parts and no errors.

### 3. The viewer uses the tags (about 30–40 min)

Read `clarity` (and `clarity_reason`) with the other expected fields (`LabelRuns.expected`):
- **Expected vs result**: when any line has a tag, three scores next to the total, per the audit's recommendation:
  **clear** n / ok (%), **hard** n / ok (%), **ambiguous → review** (how many ambiguous lines the run sent to review,
  of all ambiguous). Follows the strict / quick switch.
- **The not-as-expected list** and the **run page's Expected column**: a clarity badge per line (reason on hover); a
  filter clear / hard / ambiguous on the run page (URL state like the others).
- **Experiment Prev / Next**: "stop at" options **clear**, **hard**, **ambiguous** (only when the run has tags).
- Simple-mode runs: the same scores and badges where the corpus line has a tag.
- `gate_expected` (negative controls): shown next to the expected action ("gate should not open"); when the run's
  gate opened anyway, a ✗ "gate opened" (the line's reason is not `gate_negative` / no keyword).

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

### 8. A "◂ Back to …" button on the Experiment page (about 30–45 min)

Asked 2026-11-27. Not the same as the browser's Back: since Prev / Next, every step is a history entry, so the
browser's Back goes line by line (12 → 11 → 10 …). The button returns in one click to the page the Experiment was
opened from, in the view it was left in (filters, page, opened line, profile, scroll), however many lines were stepped
through. How: every "Experiment" link (run rows, Expected vs result, document page, simple run line, corpus page,
compare page) adds `back=<that page's URL>` (like the document page's "back to the run" crumb, `backHere`), and Prev /
Next carry it along. The label says where it goes: "◂ Back to the run", "◂ Back to line 12", "◂ Back to the corpus".
Without `back` (a typed or old link): to the run page of `run`, else `/label/`. Only same-site paths are accepted
(`safeBack`).

### 9. Quick as the default profile (about 10 min)

Asked 2026-11-27 ("I want quick in default when the run page opens normally"). Checked: the profile is kept in the
URL (`&profile=quick`), so the browser's Back shows quick again after it was chosen; a plain link shows the default,
`"default": "strict"` in `labels\expected_rules.json`. Change it to `"default": "quick"` (the same as Settings →
Expected-result rules → default profile). This changes the default everywhere the profile is used (run page, simple
runs, document page, Experiment); strict stays one click away and in links that name it. Update the docs that say
strict is the default.

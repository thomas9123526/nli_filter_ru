# 11_27_big_plan: benchmark clarity tags; Experiment page: expected vs decided, scoring without cache, draft clean-up

Planned 2026-11-27, to be built when the user says so ("do 11_27_big_plan", "I'm leaving", …). Background: the
conversation of 2026-11-27 (`cmds\conversation\2026-11-27.md`, "I have an LLM audit of the benchmark that tags each
line clear / hard / ambiguous", and "I updated the benchmark files").

**The tags are in the benchmark files themselves** (updated by the user 2026-11-27 16:16): every line of
`dataset\benchmark\benchmark_ru_llm_*.jsonl` has `clarity` (clear / hard / ambiguous), `clarity_reason` and, in most
sets, `note`. 40 files, 440 lines: 306 clear, 72 hard, 62 ambiguous. The earlier separate audit table and write-up
(`labels\benchmark_clarity.csv`, `cmds\labeling\benchmark_clarity_audit.md`) were removed as no longer needed; they
matched the new files exactly (the 3 suggested fixes, Pink Floyd / Jamala / Chornobyl, were not applied).

The estimate is about 6½–7 hours:
- tasks 1–4 (clarity tags, new sets and fields): about 1–1½ h;
- task 5 (expected vs decided on the Experiment page): about 45 min – 1 h;
- task 6 (score again without the cache): about 30 min;
- task 7 (one automatic draft per identical draft): about 20–30 min;
- task 8 (a "Back to …" button on the Experiment page): about 30–45 min;
- task 9 (quick as the default profile): about 10 min;
- task 10 (a blank Experiment page with its own address): about 30–45 min;
- task 11 (how the line's result comes out of its paragraphs): about 45 min – 1 h;
- task 12 (spaces checked when keyword files are saved): about 30 min;
- task 13 (`--max-removed-share`: drop a document when too much of it is cut): about 45 min – 1 h.

**The benchmark keeps growing** (said 2026-11-27): the user keeps generating new files into `dataset/benchmark\`. So
nothing may hard-code set names, line counts or field lists: the builder keeps every source field and accepts any new
set name (with or without a side); the viewer shows whatever tags and fields a line has; counts are computed when the
page or builder runs, not written into docs as fixed facts. The numbers above (40 files, 440 lines) are only the state
on 2026-11-27.

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

### 10. A blank Experiment page with its own address (about 30–45 min)

Asked 2026-11-27: "a new page like Experiment that does not load text from the datasets; I type any text; URL like
/label/try/blank; the policy like the Experiment page's; layout, buttons and functions the same".

Today `/label/lab/` without a run already starts with no text and the Russia-side policy (`policy/russia_llm_policy_v2.json`),
with every Experiment function. What is missing, and what to build:
- **Its own address `/label/lab/blank/`** (chosen by the user 2026-11-27, instead of `/label/try/blank/`: `/label/try/`
  stays the case-set page): the
  Experiment page in blank mode — the same component (`LabView`), so layout, buttons and functions stay the same and
  every later change to Experiment applies to it too.
- **A policy picker** at the top (every `policy/*.json` except the non-English file; default the Russia-side policy;
  the choice in the URL, `?policy=`). Changing it with unsaved draft changes asks first (or offers to carry the changes
  onto the new policy, as "Load a draft" does).
- **Starts blank, keeps your work**: one empty text box to type in. The draft is kept in the browser and as an automatic
  draft file like any Experiment draft; "New blank" clears texts and draft (asks first). "Load a draft" works here too
  (its texts with "+ texts").
- **Only what needs a run is hidden**: Prev / Next, "add a line the run did not get as expected", "Apply to the whole
  run", the expected vs decided badges (no expected for typed text). The crumb reads "Labelling / Experiment (blank)";
  the "◂ Back to …" button (task 8) goes to where it was opened from.
- **Links**: "Blank experiment →" on `/label/` next to "Experiment →"; the Experiment page of a run gets "Open blank →".
- Tests: the page opens empty with the default policy; typing a text and Run draft and base works; the policy picker;
  the draft survives a reload; no run-only parts shown.

### 11. How the line's result comes out of its paragraphs (about 45 min – 1 h)

Asked 2026-11-27, on `/label/lab/?run=out_label_benchmark_russian_detail&file=russian_persons__v2&line=3` and the same
line's document page: "¶1 is remove, ¶2 is keep, the final is remove, but no part shows how the final comes out; the
document page shows one paragraph at a time but no analysis of the several paragraphs together".

The rule (nli_label.py, paragraph unit): only paragraphs with a keyword / marker are checked, the others stay
untouched; each checked paragraph gets its own action; the document action is: nothing removed → review if any review,
else pass if all pass, else kept; something removed → the removed paragraphs are cut, "edited" (or "removed" when less
than `min_doc_chars` would be left). The expected check and the Experiment's "base → draft" use the strictest
paragraph action (remove > review > keep > pass). Line unit: the line's own decision.

Build a **"Whole line"** step, after the per-paragraph flow, on the document page and in the Experiment page's traces
(base and draft):
- every paragraph of the text in order (¶1, ¶2, ¶3 …), checked or not: its action, reason and the label that decided
  it (e.g. "¶1 remove · narrative · criticize_about_something 0.988"; "¶3 not checked (no keyword)"); a click selects
  it (the per-paragraph flow above follows);
- the document action with the rule that gave it ("¶1 removed, the rest kept → edited · 61 of 161 tokens removed");
- the line's result for the expected check: "strictest: remove (from ¶1)" and, when the line has an expected action,
  "expected keep → ✗"; with the decision unit "line": the line's decision and why;
- on the Experiment page also next to each text's "base → draft" a short "from ¶1" (which paragraph decided).
Also fix: in a narrow trace the score number next to the bar is cut off ("0.85…" for 0.858, the draft column on the
Experiment page): keep the number whole (smaller bar or the number on its own line).

### 12. Spaces checked when keyword files are saved (about 30 min)

Asked 2026-11-27: `keywords/russia_v3.txt` got the line `Petersburg<space><TAB>B<TAB>place<TAB>Russia` from a save on
the viewer's files page (`/label/files/`, the table's keyword box keeps what is typed). Checked: harmless today —
`nli_filter.parse_keyword_line` strips every cell, so the keyword is read as `Petersburg` and matches as before — but
the file is untidy and a stricter reader could trip on it.

On the files page (keyword lists, place-name tables, exceptions):
- **Table view:** every cell is trimmed (spaces at the start and end) when the row is written into the file, and a
  run of spaces inside a keyword becomes one ("St.  Petersburg" → "St. Petersburg"). Shown before saving: "2 cells
  trimmed".
- **Text view and the check while typing** (`/api/labels/files/check`): a warning per line with a cell that starts or
  ends with a space, or has a double space ("line 61: 'Petersburg ' ends with a space"), and a **"Trim spaces"**
  button that fixes them all. Tabs (the column separators) and comment lines are left as they are.
- **Save:** the save itself trims the same way, so a file saved from the viewer never gets these spaces again;
  the message says how many cells were trimmed.
- The existing line `Petersburg ` in russia_v3.txt: fixed by the first save with the new check (or the "Trim spaces"
  button), not by hand.
- Tests: table and text saves with leading / trailing / double spaces; comments and tabs untouched; a regex in the
  exclude column is not changed inside (only its outer spaces).

### 13. `--max-removed-share`: drop a document when too much of it is cut (about 45 min – 1 h)

Asked 2026-11-27 (conversation: "cutting vs rewriting for a training dataset", "what is max-removed-share"). Today a
document with cut paragraphs is **edited** unless fewer than `--min-doc-chars` (50) characters are left, so a document
that loses 90 % of its text but keeps 60 characters stays in the clean output as a fragment.

New `nli_label.py` setting **`--max-removed-share X`** (0 < X ≤ 1; **default off**, so existing runs and commands behave
as now): in the paragraph unit, when `tokens_removed / tokens` of a document is above X, the document action is
**removed** (reason in the row: `removed_share`, with the share) instead of **edited**; its clean line is not written.
Example with 0.5: russian_persons v2 line 3 (61 of 161 tokens cut, 38 %) stays edited; 300 of 400 cut (75 %) → removed.
- Also an option **`--drop-if-first-cut`** (off by default): drop the document when its first checked paragraph is cut
  (often the main topic).
- Wherever `--min-doc-chars` is accepted: `run`, `redecide` (so values can be tried on an existing run without the
  models) and `export`; recorded in summary.json settings; `redecide` without the option keeps the run's own value.
- Summary: how many documents went from edited to removed by this rule (also per file); the run page's counts show it.
- Viewer: both options on the Start-a-run form and in the run page's redecide panel; the document page and the
  "Whole line" step (task 11) say "removed: 75 % of the tokens would be cut (limit 50 %)".
- Line unit: not used (a line is kept or dropped whole anyway).
- Docs: `cmds\labeling\output_modes.md` / the labelling guide; tests: below / at / above the limit, off by default,
  first-paragraph option, redecide, the summary count.

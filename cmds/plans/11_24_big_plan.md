# 11_24_big_plan: everything for the Russia-side labelling in the viewer

Planned 2026-11-24. To be built while the user is away, when they say so ("do 11_24_big_plan", "I'm leaving", …).
All of it is in the viewer's Labelling area (`/label/…`), for the Russia-side policy
(`policy\russia_llm_policy_v2.json`). Already done before this plan: the policy editor (`/label/policy/`).

Estimated total: about 3 to 3½ hours of work.

## Tasks, in this order

### 1. Redecide from the run page + compare (40–50 min)

- On `/label/run/`: "Apply another policy to this run". Pick a policy (or the editor's unsaved draft) and a new output
  folder (default `dataset\<run>_redecide_<n>`). Runs `nli_label.py redecide` through the model service, no models
  loaded.
- A compare view between two runs of the same corpus: totals side by side, the paragraphs whose action changed
  (old → new, with labels and reason), and expected vs result for both when the corpus has expectations.
- Done when: a threshold change in the editor → redecide → the changed paragraphs are listed, without typing a command.

### 2. "Start a run" form + "Run this test set" (30–45 min)

- Replace the command box on `/label/` with a form: corpus (folders in `dataset\`, or a path / server address),
  policy (default the Russia-side v2), output folder, `--overwrite`, `--write-clean`, `--review-as`, judge on/off,
  topic field and mode, `--limit`. The command it builds stays visible and editable.
- "Run this test set" for `labels\russia_llm_cases_v1.json` and `labels\russia_llm_docs_v1.json`: rebuild the
  corpus from the JSON, then run (what `tools\label_test_set.py` does).
- Done when: both Russia test sets can be run and compared from the viewer alone.

### 3. Clean up old run folders (20–30 min)

- A page or panel listing the run folders in `dataset\` (from the run-folders report): in use, older, corpus missing,
  broken. Delete selected folders after a confirmation step on the page.
- Safety: only folders directly inside `dataset\`, only run folders (a `summary.json` or label/decision outputs),
  never the one in use for a corpus unless explicitly ticked, never a corpus folder.
- Done when: the unused and broken folders can be removed without a terminal.

### 4. Keyword files and place-name tables (30–45 min)

- Edit the files the policy names: `keywords\russia_v3.txt`, `keywords\ukraine.txt` (one term per line),
  `policy\place_names_ru.csv` (from → to, `#` rows switched off), `policy\place_name_exceptions_ru.txt`.
- Backup on save, refused when the file changed meanwhile (like the policy editor). Linked from the policy editor.
- Done when: a keyword or a place name can be added, switched off or removed from the viewer.

### 5. Documents test set editor (45–60 min)

- Edit `labels\russia_llm_docs_v1.json` in the viewer: documents with several paragraphs, each paragraph's expected
  action (and acceptable ones), the document's expected action, groups, notes; add, change, delete documents.
- On save: backup and rebuild `dataset\test_corpus_docs_ru` (as `tools\build_russia_llm_docs.py --corpus-only` does).
- Done when: a document can be added and labelled with expectations, and the run page's expected vs result picks it up.

## Rules while working alone

- One task at a time, in the order above; each with backend tests, a frontend build, a check of the rendered page,
  and a short update of `cmds\viewer\labels_pages.md`.
- Don't change the meaning of the Russia-side policy or the test sets' expectations; don't touch `cmds\history\`, A's
  files or `nli_filter.py`.
- Commit or push only if the user said so when leaving. Otherwise leave the work uncommitted, with a short report per
  task at the end (what was built, test results, anything left open).
- If a task turns out bigger or riskier than planned, finish the ones that fit and describe the rest instead of
  forcing it.

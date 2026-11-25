# Viewer: Labels pages (nli_label.py runs)

The viewer shows and starts `nli_label.py` runs too. Start the viewer as usual (`viewer\start_viewer.ps1`), then
click **Labelling runs (nli_label.py) →** on the home page, or open `http://127.0.0.1:8000/label/`.

| Page | What you see |
|---|---|
| **Labels** (`/label/`) | Every `nli_label.py` output folder in the project folder (found by its `summary.json`, or `progress.json` while it runs): state, documents, removed tokens, documents per action. And the **Start a run** box. |
| **Run** (`/label/run/?run=out_label_seed`) | Token composition (documents and paragraphs by action), the label table (decision, threshold, positive paragraphs and tokens). Click a label to list its documents. The document list filters by document action and by "has a paragraph that is remove / review / keep / pass". |
| **Try the policy** (`/label/try/`) | Step through 60 cases (every label yes / near miss + edge cases) and run each text through the policy with the model service: the same flow view, compared with the expected result. The **cases** list picks another case set, e.g. `labels/russia_llm_cases_v1.json` for the Russia-side project (it also shows "also fine" actions and your first decision). Guide: `cmds\labeling\cases.md`, `cmds\labeling\russia_llm.md` |
| **Document** (`/label/doc/?run=…&file=…&line=…`) | The text, each labelled paragraph coloured by its action (red remove, amber review, green keep, grey pass), keywords highlighted. Click a paragraph to see its **flow**: level 0 gate → level 1 subjects → level 2 framing → decision, every score as a bar with its threshold, "not scored" where the cascade skipped a level, and the rule that decided. |

## Starting a run from the viewer

Runs go through the model service, like "Run filter" on the dataset page:

```powershell
# once, in the project folder, in the environment with torch (no models needed for runs):
python nli_playground.py --no-models
```

(`--no-models` starts the job runner only: each run loads its own models; redecide needs none.)

The **Start a run** box on `/label/`:

- **Run a test set**: one button per test set in `labels\` that has its own corpus (`"corpus"` in the file):
  `russia_llm_cases_v1.json`, `russia_llm_docs_v1.json`. It does what `tools\label_test_set.py` does: rebuilds the
  corpus from the JSON (`dataset\test_corpus_cases_ru` / `test_corpus_docs_ru`), then runs it with the policy named in
  the file into `dataset\out_label_<file name>` (`--overwrite --write-clean`; untick **judge** for a faster run).
  When it is done: **open the run** → "Expected vs result" at the top of the run page.
- **The form**: corpus (the corpus folders in `dataset\`, or another folder / file / server address), policy
  (default the Russia-side v2), output folder (default `dataset\out_label_<corpus>_<date>_<time>`), `--limit`
  (lines per file, for a trial), topic field and mode, `--overwrite`, `--write-clean`, judge, and what happens to
  review paragraphs in the clean copy. The command it builds is shown below and can be **edited by hand** before
  **Start** ("back to the form" undoes the hand edit). It must be `nli_label.py run …` or `nli_label.py redecide …`
  with an `--output-dir`.
- The output lines follow below the box; **Stop** ends the run; **open the run →** when it is done. The run list
  refreshes by itself while a run goes (from `progress.json`). Starting works only from this PC (like every change in
  the viewer).

## Notes

- A run started on the command line shows up as well (it writes `progress.json` into its output folder). If a run
  stops without finishing, its state turns **stale** after 5 minutes without updates.
- The document page reads the text from the run's input file. If that file changed after the run (for example
  documents emptied by content screening), the page says so and shows the labels without the text.

## Exceptions and the topic field in the flow

When the policy has exceptions, the flow shows an **Exceptions** step between level 2 and the decision: every exception with its phrases or hypothesis, which one matched, and "the cascade said X; the exception decides Y". If a protected label (hate, violence) removes the paragraph, the step says the exception was blocked. Subjects answered by the corpus' topic field (`--topic-field`) carry a **topic field** chip instead of a model score. See `cmds\labeling
ussia_llm.md`.

## An nli_label.py run as a dataset's output (viewer_config.json)

A dataset's `"output"` may also be a **local** `nli_label.py` run folder. Then the corpus and its labelling results
belong together like a filter run:

```json
{
  "name": "cases_ru",
  "title": "Russia-side policy cases",
  "corpus": "../dataset/test_corpus_cases_ru",
  "output": "../out_label_ru_check",
  "editable": true
}
```

- The dataset card on the start page has a **labels** badge and opens the run's labelling pages (files, lines,
  actions, the flow of every paragraph).
- The dataset page (Browse corpus, Keywords …) shows a note with a link to the labelling run.
- A file link of the dataset (`/file/?ds=cases_ru&f=exceptions__01`) goes straight to that file on the labelling pages.
- A run folder inside the project folder keeps its folder name on the Labels pages (`out_label_ru_check`); a run
  folder elsewhere is listed under the dataset's name.
- Server outputs (FTP / SFTP / S3) are not supported for label runs yet; copy the run folder to a local disk.
- Restart the viewer after editing the config.

## Label with a policy on the corpus page

On a dataset's corpus page (`/label/corpus/?ds=…&file=…`), the panel **Label with a policy** (below **Try settings**) runs
`nli_label.py`'s policy instead of the filter. It needs the model service (`py -3.12 nli_playground.py`).

- **Label the N lines of this page**: pick a policy (remembered in this browser) and the judge on or off. Each line
  gets its result underneath it: the action (remove / review / keep / pass), the labels that were yes, an exception,
  place-name changes. **flow →** opens that line on the Try page with every score. **Nothing is saved**: reloading
  the page clears the results. The full text of each line is labelled (not the shortened text shown on the page);
  lines longer than 20,000 characters are skipped with a note.
- **Save as a labelling run**: starts `nli_label.py run` on the whole file with the same policy, into a new folder in
  the project folder (default `out_label_<dataset>_<file>`, editable; an existing non-empty folder is refused). It
  writes `*.labels.jsonl.zst`, `*.clean.jsonl.zst` and `*.rewrites.jsonl.zst`, runs in the model service, and shows
  up under **Labelling runs** with its progress. A server corpus is read with its password passed as an environment
  variable, never in the arguments. A member of a .zip / .rar cannot be saved on its own.

The **Try settings** panel above it is unchanged: that one is `nli_filter.py` (keep / filter).

## Documents test set (`/label/docs/`)

http://localhost:8000/label/docs/ ("Documents test set →" on `/label/`): edits `labels\russia_llm_docs_v1.json`, the
multi-paragraph test documents (`?file=labels/<other>.json` for another documents set).

- Left: the documents by group, each with its expected document action. **+ new document after this one**.
- Right: id, group (= the corpus subfolder), file (= `<group>/<file>.jsonl.zst`), title; then the **paragraphs**, each
  with its expected action (remove, review, keep, pass, or **none** = no keyword, not checked), the actions that are
  also fine, a note; ↑ ↓ to move, ✕ to delete, **+ paragraph after this one**. **Delete document** at the bottom.
- The document text (paragraphs joined by a blank line) and the **expected document action** follow from the
  paragraphs, as in `tools\build_russia_llm_docs.py` (a remove paragraph → edited, all removed → removed, a review →
  review, all pass → pass, no keyword → untouched, else kept).
- Checked while you edit, like the builder: unique ids and group/file pairs, valid actions, and **every paragraph must
  stay a paragraph** when the document is split: at least `min_chars` characters (200 in the Russia-side policy), no
  blank line inside. The character count turns yellow below that.
- **Save**: the old file goes to `labels\.backup\`, then `dataset\test_corpus_docs_ru` is rebuilt; run it with
  **▶ russia_llm_docs_v1.json** on `/label/` to see expected vs result. Refused when the file changed since the page
  loaded it.

## Keyword lists and place names (`/label/files/`)

http://localhost:8000/label/files/ ("Keywords & place names →" on `/label/`, and a link in the policy editor's General
section): the files a policy names: `keywords_file` (e.g. `keywords\russia_v3.txt`, `keywords\ukraine.txt`),
`place_names_file` (`policy\place_names_ru.csv`) and `place_name_exceptions_file`
(`policy\place_name_exceptions_ru.txt`). The file list marks which ones the policy uses (`?policy=` to pick
another policy; default the Russia-side v2).

- **Table**: one row per entry (keywords: keyword, level, type, gloss, other meanings, exclude; place names: from_form,
  to_form, variants, notes; exceptions: the pattern and "case-sensitive"). **on** unticked = the row is switched off
  (`#` in front, kept in the file). **+ add a row**, ✕ deletes one, a filter box. Comment lines stay as they are (edit
  them on the **Text** tab). Rows you do not touch are written back exactly as they were.
- **Text**: the whole file.
- Checked while you type with the parsers nli_label.py uses (bad level letter, broken regex, …; keywords listed twice
  are a warning). An invalid file cannot be saved.
- **Preview** (place names and exceptions): a sample text through the table as edited, with the policy's other
  place-name file, e.g. `Kyiv → Kiev` while "the Kyiv Independent" keeps its name.
- **Save**: the old file goes to `keywords\.backup\` / `policy\.backup\` (not in git); refused when the file changed
  since the page loaded it. The line endings of the file are kept. Runs and Try read the files when they start.

## Apply another policy to a run, and compare two runs

On a run page (`/label/run/?run=…`), open **▸ Apply another policy · compare runs**:

- **Redecide**: pick a policy (or "unsaved edits of …" from the policy editor's *Try these changes*), a name for the new
  run (default `<run>_rd_<date>_<time>`, created in `dataset\`), optionally the clean copy and `--review-as remove`.
  It runs `nli_label.py redecide` through the model service (`python nli_playground.py --no-models` is enough: no
  models are loaded; the stored scores are reused, seconds for the test sets). A label whose hypothesis is new or
  reworded counts as not scored (No): run the models again for those. An unsaved policy is written to
  `dataset\.policy_drafts\<new run>.json` and checked first.
- When it is done: **open the new run**, or **compare with this run**.
- **Compare with another run**: any other run, for the same corpus.

**Compare page** `/label/compare/?a=<run>&b=<run>`: documents and paragraphs per action in A and B with the difference;
**What moved** (e.g. `¶ keep → remove 8`, `doc kept → removed 8`): click one to list only those; the changed lines
with each changed paragraph before (A) and after (B): action, reason, labels, exception; links to both document pages
and to Try. ⇄ swaps A and B. Files are matched by name, lines by number, paragraphs by their position in the text.

## Edit a policy (`/label/policy/`)

http://localhost:8000/label/policy/?file=policy/russia_llm_policy_v2.json (also "Edit a policy →" on `/label/`, and
"edit policy" next to the policy on the Try page).

- **Form** tab: General (`no_subject`, `conflict`, `narrative_opens_gate`, paragraph sizes, markers, keyword files,
  place names), **Labels** by level (key, level, decision, threshold, hypothesis, softens, protected, note; add,
  rename, delete), **run_if** (tick what opens level 1 / 2), **Exceptions** (phrases, decision, priority, scope,
  skip_quoted; add, delete), **Topic field** (field, mode, topic → subjects). Renaming a label also renames it in
  run_if, softens and the topic map. Settings the form has no box for are listed under "Other settings".
- **JSON** tab: the whole file as text; applies when it is valid JSON.
- The bar at the top checks the policy with `nli_label.py`'s own rules while you type: **valid**, or the problems
  (e.g. `run_if 2: unknown label 'xyz'`, `threshold must be between 0 and 1`), plus warnings for files the policy names
  that do not exist. An invalid policy cannot be saved.
- **Save** writes the file (UTF-8, 2-space indent); the previous version goes to `policy\.backup\` (not in git). A save is
  refused when the file changed since the page loaded it (reload first). **Save as new** writes another
  `policy\<name>.json` (it must not exist yet), e.g. `russia_llm_policy_v3.json`.
- **Try these changes →** opens the Try page in a new tab with the policy as edited, **saved or not**: the policy box
  there shows "unsaved edits of …". The Try page scores every label, so `run_if` changes do not show there; use a run
  or `redecide` for those.
- Runs, Try and redecide read the file when they start: a saved change is used by the next one, no restart.

## Edit the cases on the Try page

On `/label/try/`, tick **Edit cases** (or open `/label/try/?cases=labels/russia_llm_cases_v1.json&edit=1`). Under the
case, an editor shows its fields:

| Change | How |
|---|---|
| **Update** a text | Edit it in the box (and try it), then **Store the box text in text N**. Expected action, "also fine" actions, the labels that should be yes and the note are edited right there |
| **Update** a case | id, group, title, "what it tests" (changing the id breaks links from old runs to this case) |
| **Insert a case at a place** | In the case list, click **+ insert here** at the place you want (between two cases, or at the top). A blank form opens with default settings (group of that place, expected `keep`, id filled in automatically): fill in the title, the text, expected / also fine / labels / note (and a second text if you like), then **Save (insert here)**: the case is put at that place and the file is saved at once. **Cancel** closes the form |
| **Insert a text** | **+ Text (from the box)** adds the box text to the selected case; **+ Case in "group"** / **+ Case in a new group** add a case with the box text after the selected one |
| **Remove** | **Delete text N** (not the last one) and **Delete case**, both after a confirmation |

Edits stay on the page (a badge counts them) until **Save to labels/…json**; **Discard** drops them, and leaving the
page asks first. Save:

- checks the set (unique ids, no empty text, known actions) and refuses it with the reason otherwise;
- refuses if the file was changed elsewhere since the page loaded it (reload, then edit again);
- keeps the old file in `labels\.backup\<name>.<date-time>.json`;
- rebuilds the case corpus: the set's `"corpus"` folder (`dataset/test_corpus_cases_ru` for the Russia-side set), or
  `dataset/test_corpus_cases` for the newest `cases_vN.json`. Rerun `nli_label.py run` on that folder for fresh results.
- works only from this PC, like the other save buttons.

**The JSON files are the master copy now.** `tools\build_russia_llm_cases.py` and `tools\build_cases.py` refuse to
overwrite an existing cases file; `--reset` rebuilds it from the script's lists (your edits are then lost; a `.bak`
copy is kept).

## Where runs are found

The **Labelling runs** page lists every `nli_label.py` run folder directly in the project folder **and** in
`dataset/` (a run moved there keeps working: its stored input paths are relative to the project folder). If a run
with the same name is in both, the one in the project folder is shown. **Save as a labelling run** on the corpus page
creates its folder in `dataset/`. For runs from the command line, give `--output-dir dataset/out_label_xxx` to keep
them there.

## Topics of case texts (testing `--topic-field` on the Try page)

Each case text can have a **topic**: the value a corpus' topic field would carry (see "The corpus' topic field" in
`cmds\labeling\russia_llm.md`). In **Edit cases** and in the **New case** form, the **topic** dropdown offers the
values of **`labels\topic_labels.json`** (JSON: `{"about": "...", "topics": ["History", "Politics", ...]}`), plus
"(no topic)" and **+ new topic…**, which asks for a name, adds it to that file (only from this PC) and selects it. The
file can also be edited by hand; the dropdown reads it each time the page loads.

- **Saved with the case** (`"topic": "History"` on the text) and written into the case corpus line, so
  `nli_label.py run dataset\test_corpus_cases_ru --topic-field topic --topic-mode trust …` tests the modes on the cases.
- **On the Try page**, next to **Try**: a **topic** dropdown (pre-filled with the case text's topic; change it for a
  try without saving) and a **mode** dropdown (policy default, hint, trust, off). **Try** sends both along.
- Below them, **topic → subject** says in one line what the chosen topic and mode do with this policy, e.g. with the
  Russia-side policy, `Entertainment` + trust: "culture = yes from the topic; history, politics, economy = no from the
  topic (no model); war: the model". Opened, it lists the policy's subjects and its whole `topic_map`.

**Where it is configured** (all in the policy file, e.g. `policy
ussia_llm_policy_v2.json`):

| Setting | What |
|---|---|
| `"labels"` with `"level": 1` | The subjects (`history`, `politics`, `war`, `economy`, `culture`) |
| `"topic_map"` | Which topic value stands for which subject (`"Entertainment": "culture"`); values are matched without case |
| `"topic_mode"` | The default mode (`hint`); `--topic-mode` / the Try page's mode overrides it |
| `"topic_field"` | The corpus field to read (`--topic-field` overrides it); the Try page always uses the text's topic |

What a topic never changes: a subject that is not in `topic_map` (Russia side: `war`) is decided by the model in every
mode, and the gate (level 0) and every level-2 label (opinions, hate, false claims, the guard) are always scored by the
models. An empty `topic_map`, a text without a topic, or a topic that is not in `topic_map` change nothing at all.
- A value that is not in the policy's `topic_map` changes nothing (the models decide, as without a topic).

## Expected vs result (test corpora)

When a run's corpus lines carry expected results, the labelling pages compare them with what the run did:
`expected_action` (+ `acceptable`) in the case corpora (`dataset\test_corpus_cases*`), and `expected_doc_action` +
`expected_paragraphs` in the multi-paragraph test documents (`dataset\test_corpus_docs_ru`). Runs on real data have
none, and these pages look as before.

- **Run page** (`/label/run/?run=…`): an **Expected vs result** panel at the top, e.g. "39 / 43 as expected (91 %)",
  with every line that does not match (file, line, expected, got, the case's note), each linked to its document.
  Clicking the file name opens that file's list below.
- **File list**: an **Expected** column (✓ / ✗, the expected action, what it got) and a filter **✗ not as expected /
  ✓ as expected**; "N / M in this file".
- **Document page**: above the Flow, "expected … got … ✓ / ✗" and the case's note. For a test document: the
  document action, the selected paragraph's expected vs got, and every paragraph as ¶1 keep → keep ✓ …
- Matching rules (as in `tools\compare_cases.py` / `compare_docs.py`): the "also fine" actions count; pass, untouched
  and "none" (a paragraph that was never labelled) count as the same, because all three leave the text as it is.

## The Labels panel on the run page

Click **▾ Labels** to fold the panel away (▸ opens it again); this browser remembers the choice. While it is open,
the search box filters the labels as you type: by name, hypothesis text, decision (`remove`, `review` …) or level
(`level 2`, or just `2`); "2 of 13 labels" shows how many match. Clicking a label still lists its documents below.

## A line's full text on the run page

In the documents table, **▸** at the start of a row shows that line's full text right under it (▾ hides it); the
**▸** in the header opens every row of the page shown (again: closes all). The text is loaded only when opened. The
paragraphs are coloured by their action (remove, review, keep, pass; plain = not checked), keyword hits marked; long
texts scroll in their box. Clicking a paragraph opens it on the document page (with its flow); "open the document
page →" too. `…/label/run/?run=<run>&expand=1` opens every row on arrival. Changing file, filter or page closes them.

## What the clean copy looks like (document page)

On a document page (a run → a file → a line), the **Text** panel has three views:

| View | Shows |
|---|---|
| **Labels** | The original text, paragraphs coloured by their action (as before); click a paragraph for its flow |
| **What is cut** | The original text with everything the clean copy leaves out **struck through in red**: `remove` paragraphs, and `review` paragraphs too when the run used `--review-as remove` (otherwise they stay, shaded yellow) |
| **Clean copy** | The text exactly as written to `<file>.clean.jsonl.zst` (the training data), with the rewritten place names marked (hover: Kyiv → Kiev) |

A document that was dropped (less than `--min-doc-chars` left) says so. A run made without `--write-clean` has no
clean copy; the page shows how to make one from the stored scores, without the models:

```powershell
py -3.12 nli_label.py redecide dataset\out_label_docs_ru_judge --output-dir dataset\out_label_docs_ru_clean --write-clean
```

To see a clean copy with the `review` paragraphs cut out as well:

```powershell
py -3.12 nli_label.py redecide dataset\out_label_docs_ru_judge --output-dir dataset\out_label_docs_ru_reviewcut --write-clean --review-as remove
```

(`redecide` writes a new folder; the viewer shows it as the newest run for that corpus.)

## Output modes: the schema, the non-English setting, simple runs, line unit

Added 2026-11-25. The settings themselves are described in `cmds\labeling\output_modes.md`.

| Page | What you can do |
|---|---|
| **Simple-mode output** (`/label/output/`, from the Labels page) | Edit `output\simple_schema.json`, or another schema in `output\`: the fields (name, source, order; add, delete, ↑ ↓), which lines get a row (`include`), `omit_empty`, `evidence`, and the **reason vocabulary** (add, edit, delete). There is also a JSON tab. It is checked while you type, with nli_label.py's own rules. The **Preview** builds rows from a finished detail run with the edited schema. Save keeps a backup in `output\.backup\`; "save as" makes a new schema |
| **Non-English keywords** (`/label/non-english/`) | Edit `policy\non_english.json`: scripts on or off, their Unicode ranges, adding a script, `check` / `remove` for keywords and markers, `score_when_removed`. Backup in `policy\.backup\`. The policy editor's General section has the `non_english_file` setting and a link here |
| **A simple-mode run** (`/label/run/?run=…`, marked **simple** on the Labels page) | Totals from the per-file summaries, untouched lines included. The rows of a file, filtered by decision, reason or keyword, as they were written. Click a line number to see its source text with keywords (blue) and markers (red) marked, and its stored **evidence** (when the schema had `evidence: decided` or `all`) |
| **Explain this line** (on an opened line) | Checks the line again through the model service, with the **policy recorded in the run** and the run's unit, review-as and judge band, and shows the flow trace per paragraph. The model service must be running (see Notes) |
| **A line-unit run** (`--decision-unit line`) | The run page says "decision unit: line". The document page shows the line decision, the paragraph that decided it (★, opened first), and "nothing is cut, the whole line is kept / dropped" in the "What is cut" view. The flow shows a **Non-English hit** step when a paragraph had one |

# Viewer: Labels pages (nli_label.py runs)

The viewer shows and starts `nli_label.py` runs too. Start the viewer as usual (`viewer\start_viewer.ps1`), then
click **Labelling runs (nli_label.py) →** on the home page, or open `http://127.0.0.1:8000/labels/`.

| Page | What you see |
|---|---|
| **Labels** (`/labels/`) | Every `nli_label.py` output folder in the project folder (found by its `summary.json`, or `progress.json` while it runs): state, documents, removed tokens, documents per action. And the **Start a run** box. |
| **Run** (`/labelrun/?run=out_label_seed`) | Token composition (documents and paragraphs by action), the label table (decision, threshold, positive paragraphs and tokens). Click a label to list its documents. The document list filters by document action and by "has a paragraph that is remove / review / keep / pass". |
| **Try the policy** (`/labeltry/`) | Step through 60 cases (every label yes / near miss + edge cases) and run each text through the policy with the model service: the same flow view, compared with the expected result. The **cases** list picks another case set, e.g. `labels/russia_llm_cases_v1.json` for the Russia-side project (it also shows "also fine" actions and your first decision). Guide: `cmds\labeling\cases.md`, `cmds\labeling
ussia_llm.md` |
| **Document** (`/labeldoc/?run=…&file=…&line=…`) | The text, each labelled paragraph coloured by its action (red remove, amber review, green keep, grey pass), keywords highlighted. Click a paragraph to see its **flow**: level 0 gate → level 1 subjects → level 2 framing → decision, every score as a bar with its threshold, "not scored" where the cascade skipped a level, and the rule that decided. |

## Starting a run from the viewer

Runs go through the model service, like "Run filter" on the dataset page:

```powershell
# once, in the project folder, in the environment with torch (no models needed for runs):
python nli_playground.py --no-models
```

Then in the **Start a run** box: edit the command (it must be `nli_label.py run …` or `nli_label.py redecide …` with an
`--output-dir`), pick a policy if not the default, **Start**. The output lines follow below the box; **Stop** ends
the run. The run list refreshes by itself while a run goes (from `progress.json`). Starting works only from this PC
(like every change in the viewer).

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

On a dataset's corpus page (`/corpus/?ds=…&file=…`), the panel **Label with a policy** (below **Try settings**) runs
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

## Edit the cases on the Try page

On `/labeltry/`, tick **Edit cases** (or open `/labeltry/?cases=labels/russia_llm_cases_v1.json&edit=1`). Under the
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
- **On the Try page**, a text with a topic shows `topic: History` and a **topic mode** dropdown (policy default, hint,
  trust, off). **Try** sends the topic along: with the Russia-side policy, `History` stands for the subject `history`
  (its `topic_map`), so in hint mode `history` is yes without the model and the flow marks it **topic field**.
- A value that is not in the policy's `topic_map` changes nothing (the models decide, as without a topic).

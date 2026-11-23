# Viewer: Labels pages (nli_label.py runs)

The viewer shows and starts `nli_label.py` runs too. Start the viewer as usual (`viewer\start_viewer.ps1`), then
click **Labelling runs (nli_label.py) →** on the home page, or open `http://127.0.0.1:8000/labels/`.

| Page | What you see |
|---|---|
| **Labels** (`/labels/`) | Every `nli_label.py` output folder in the project folder (found by its `summary.json`, or `progress.json` while it runs): state, documents, removed tokens, documents per action. And the **Start a run** box. |
| **Run** (`/labelrun/?run=out_label_seed`) | Token composition (documents and paragraphs by action), the label table (decision, threshold, positive paragraphs and tokens). Click a label to list its documents. The document list filters by document action and by "has a paragraph that is remove / review / keep / pass". |
| **Try the policy** (`/labeltry/`) | Step through 60 cases (every label yes / near miss + edge cases) and run each text through the policy with the model service: the same flow view, compared with the expected result. The **cases** list picks another case set, e.g. `labels/russia_llm_cases_v1.json` for the Russia-side project (it also shows "also fine" actions and your first decision). Guide: `cmds\labeling\cases.md`, `cmds\labelingussia_llm.md` |
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

When the policy has exceptions, the flow shows an **Exceptions** step between level 2 and the decision: every exception with its phrases or hypothesis, which one matched, and "the cascade said X; the exception decides Y". If a protected label (hate, violence) removes the paragraph, the step says the exception was blocked. Subjects answered by the corpus' topic field (`--topic-field`) carry a **topic field** chip instead of a model score. See `cmds\labelingussia_llm.md`.

## An nli_label.py run as a dataset's output (viewer_config.json)

A dataset's `"output"` may also be a **local** `nli_label.py` run folder. Then the corpus and its labelling results
belong together like a filter run:

```json
{
  "name": "cases_ru",
  "title": "Russia-side policy cases",
  "corpus": "../test_corpus_cases_ru",
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

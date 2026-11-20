# Viewer: Labels pages (nli_label.py runs)

The viewer shows and starts `nli_label.py` runs too. Start the viewer as usual (`viewer\start_viewer.ps1`), then
click **Labelling runs (nli_label.py) →** on the home page, or open `http://127.0.0.1:8000/labels/`.

| Page | What you see |
|---|---|
| **Labels** (`/labels/`) | Every `nli_label.py` output folder in the project folder (found by its `summary.json`, or `progress.json` while it runs): state, documents, removed tokens, documents per action. And the **Start a run** box. |
| **Run** (`/labelrun/?run=out_label_seed`) | Token composition (documents and paragraphs by action), the label table (decision, threshold, positive paragraphs and tokens). Click a label to list its documents. The document list filters by document action and by "has a paragraph that is remove / review / keep / pass". |
| **Try the policy** (`/labeltry/`) | Step through 60 cases (every label yes / near miss + edge cases) and run each text through the policy with the model service: the same flow view, compared with the expected result. Guide: `cmds\labeling\cases.md` |
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

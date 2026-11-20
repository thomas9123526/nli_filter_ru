# Hand-labelling with the label tool

The guide's most important step: **hand-label first, then measure**. Your labels tell you, per label, how often the
model is right, which threshold to use, and whether a hypothesis needs other words.

## The file: `labels\seed.jsonl`

Made by `nli_label.py sample`. First line `{"_meta": …}` (the policy's labels at sampling time), then one
paragraph per line:

| Field | Meaning |
|---|---|
| `text` | The paragraph to label (`before` / `after`: context, shown grey) |
| `hits` | Keyword / marker positions in `text` (highlighted) |
| `picked_for` | Why it was picked: `random`, `top:<label>` (high score), `near:<label>` (near the threshold), `low:<label>` |
| `model` | Scores and action of the run it came from (hidden in the tool unless you tick "show model scores") |
| `labels` | Your answers: `true` / `false` / `null` (not answered), one per policy label |
| `action` | Your action if it differs from what your labels imply (`null` = same as policy) |
| `status` | `todo` → `draft` (answered, not finished, or a draft by Claude) → `done` (checked by you) |
| `by` | `claude-draft` (pre-filled, to check) or `human` |
| `note` | Why, edge case, codebook question |

`eval` counts only `done` items. Keep the labels files in git: they are the most valuable data in the project.

## The tool: `tools\label_tool.html`

1. Open the file in **Chrome or Edge** (double-click it, or drag it into the browser).
2. **Open labels file…** → `labels\seed.jsonl`. With Chrome / Edge, **Save** writes back into the same file.
   Other browsers download a copy: replace the old file with it.
3. For each paragraph:
   - Read the highlighted paragraph. The grey context helps, but **label only the paragraph**.
   - Answer the **gate** first (`g` = Yes, `G` = No). Gate No = the keyword is incidental → action `pass`; the
     rest becomes No when you finish.
   - Answer each label Yes / No. Clicking the same answer again clears it. `n` sets every unanswered label to No
     (most labels are No for most paragraphs).
   - Check the **policy action** box. If the policy's action is wrong for this paragraph, pick **your action** and
     write why in the note. These disagreements are what the policy discussion with compliance needs.
   - **Enter** = done & next.
4. Your work is kept in the browser while you go, and saved to the file every 10 finished items and on **Save**
   (`Ctrl+S`). The page warns before closing with unsaved work.

Keep "show model scores" **off** while labelling, so the model doesn't steer your answers. Turn it on afterwards to
look at disagreements.

## Claude's drafts

`labels\seed.jsonl` comes pre-filled by Claude (`by: claude-draft`, `status: draft`) so you can go faster: check
each answer, change what is wrong, and press Enter. **Drafts are not ground truth.** Only your `done` items count in
`eval`. The filter **draft (to check)** in the tool shows the ones still to check.

## Labelling rules (start of the codebook: write your decisions in the note, then into a codebook)

- **Label what the paragraph says, not what you think the writer wanted.** "This text claims …" labels are yes only
  if the paragraph itself makes the claim.
- **Quotes and reports.** News that reports or quotes a narrative in order to criticise or debunk it:
  the narrative label is yes **and** `reports_or_debunks` is yes (→ action review). News that reports neutrally what
  an official said: the narrative label is yes only if the paragraph adopts the claim.
- **Several subjects** in one paragraph: answer each label on its own; the policy combines them.
- **Russia vs Soviet Union vs Russian language.** `history_soviet` covers the USSR and the shared history before
  1991. A text only written in Russian is not Russia-related by itself.
- **Technical text with a price or a person in it** (e.g. a Russian scientist's algorithm): `science_technology`
  yes; `celebrities` only if the text is about the person as a public figure.
- **Places.** `geography` = describes borders, rivers, distances, regions of Russia. A city name used only as a
  location ("a conference in Moscow") is not geography; usually the gate is still yes.
- **Unsure?** Leave the label empty, write the question in the note, and finish the item later. Don't guess:
  a wrong label is worse than a missing one.

Edge cases the guide says to settle early (write each ruling down): Russian scientists / inventors in a technical
context; prices inside technical text; pre-1991 / Soviet history; Russian athletes; Russian literature.

## Rounds

| Round | What | Command |
|---|---|---|
| Seed | ~200 paragraphs, all labels | `sample out_label_seed --out labels\seed.jsonl` (done; check the drafts) |
| Per label | 50 clear yes + 50 clear no **per label**, with near misses | `sample RUN --label celebrities --top 40 --near 30 --low 30 --random 0 --exclude labels\seed.jsonl --out labels\celebrities.jsonl` |
| Random check | a random sample, for the CRC guarantee and the weekly audit | `sample RUN --random 300 --top 0 --near 0 --low 0 --exclude labels\*.jsonl --out labels\random_01.jsonl` |
| Human review | every paragraph a run sent to **review**: a person decides remove / keep | `review out_label_dclm --out labels\review_dclm_01.jsonl` (see `outputs.md`) |

Run `eval` with all files together: `python nli_label.py eval labels\seed.jsonl labels\celebrities.jsonl …`.
For the per-label rounds, use a run made with `--all-labels` over many documents (on a GPU), so every label has
enough candidates.

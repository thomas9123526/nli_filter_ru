# What `nli_label.py run` writes

Per input file (`<name>` = the file name without extensions), in `--output-dir`:

| File | Content |
|---|---|
| `<name>.labels.jsonl` | **The labels as columns**: one row per input line |
| `<name>.clean.jsonl` | With `--write-clean`: the original line with removed paragraphs cut out and place names rewritten. Documents left shorter than `--min-doc-chars` (50) are dropped, and so are lines that are not JSON |
| `<name>.rewrites.jsonl` | Every place-name replacement |
| `<name>.summary.json` | The file's counts. Its presence marks the file done (a rerun skips it) |
| `summary.json` | The whole run: command, policy, settings, timing, counts, composition |

The input files are never changed.

## A row of `<name>.labels.jsonl`

```json
{"line": 12, "id": "…", "gate": true,
 "hits": [{"kw": "Moscow", "span": [340, 346]}],
 "paragraphs": [
   {"span": [300, 1120], "action": "remove", "reason": "remove_label", "labels": ["celebrities", "culture_entertainment"],
    "scores": {"involves_russia": 0.97, "culture_entertainment": 0.91, "celebrities": 0.88, "science_technology": 0.02, …},
    "tokens": 205}],
 "labels": ["celebrities", "culture_entertainment"], "tokens": 1630, "tokens_removed": 205,
 "review": false, "rewrites": 1, "action": "edited"}
```

- Untouched lines are short: `{"line": 3, "id": "…", "gate": false, "tokens": 410, "action": "untouched"}`.
- `scores` holds every label that was scored (all of them with `--all-labels`). With the cascade, a missing label was
  not needed (e.g. level 2 when politics / war / history are no).
- To build a training set from the columns instead of the clean copy (the guide's "filter on the columns"): read
  `labels.jsonl` next to the input, cut out the spans whose `action` you don't want, and rewrite names with
  `nli_names.py`.

## Human review: the `review` action and the review queue

A paragraph gets the action **review** when a `review` label is yes (`literature_art`, `history_soviet`, `sport`,
`values_mindset`), when a remove label and a keep label are both yes (`conflict`), or when a narrative is softened
by `reports_or_debunks`. It shows in `labels.jsonl` as the paragraph's `"action": "review"` and the document's
`"review": true`. The clean copy keeps review paragraphs (`--review-as remove` drops them).

To hand them to a person:

```powershell
python nli_label.py review out_label_dclm --out labels\review_dclm_01.jsonl
python nli_label.py review out_label_dclm --out labels\check_removed_01.jsonl --actions remove   # check removals
```

It writes a hand-label file with every such paragraph and its text (`picked_for` = why: `review:conflict`,
`review:review_label`, the yes labels). Open it in `tools\label_tool.html`: answer the labels, set **your action**
(remove / keep) and write why in the note. The answers become rulings for the codebook, and the file is a normal
label file for `eval`. In the viewer: Labels → run → filter **has a paragraph: review** shows the same paragraphs.

`flag` is different: `hostility_russians` is listed in `flags` for the general safety filter and never changes the
action.

## A policy change: `redecide` (no models)

The guide: "a policy change means rerunning the filter, not relabelling". Change thresholds, decisions, `run_if` or
`conflict` in a copy of the policy, then:

```powershell
python nli_label.py redecide out_label_dclm --policy policy\russia_policy_v2.json --output-dir out_label_dclm_v2 --write-clean
python nli_label.py report out_label_dclm_v2
```

It reads the input files again (for the text), takes every score from the old run's `labels.jsonl`, decides with the
new policy, and writes a normal output folder. It reports how many scores it reused and how many were **missing**
(treated as No). Scores are missing when:
- the old run used the cascade and the new policy needs a label that was skipped (e.g. you lowered the politics
  threshold, so level 2 now runs on more paragraphs). Runs made with `--all-labels` have every score;
- a hypothesis was reworded (its old scores no longer apply; the summary lists `changed`);
- keywords, markers or paragraph settings changed, so the paragraphs are not the same.

For exact results after such changes, use `run` again.

## The composition report

Printed at the end of `run`, and again with `python nli_label.py report out_label_dclm`:

```
lines 77,905   tokens (est.) 98,120,400   removed 512,330 (0.5%)   place-name rewrites 1,204

documents       docs        tokens (est.)   share of tokens
  untouched     75,140      90,512,000      92.2%
  pass             810       1,400,100       1.4%
  kept           1,300       4,010,000       4.1%
  …
labels (positive paragraphs)        decision   paragraphs   tokens (est.)
  culture_entertainment              remove           412         90,200
  …
by group        docs        tokens (est.)   removed
```

(The numbers above are an example layout, not results.) Tokens are **estimated** at ~4 characters per token, good
enough for shares and composition. Use `--group-field` to break it down by a field such as `source`.

# Output modes, decision units and the non-English setting

Added 2026-11-25 (plan `cmds\plans\11_24_output_modes.md`). Three independent settings of `nli_label.py`. None of them
changes how a paragraph is **checked**. They change what a decision applies to, what is written, and what a non-English
keyword does.

| Setting | Values | Default | Where |
|---|---|---|---|
| `--decision-unit` | `paragraph` / `line` | `paragraph` | `run`, `redecide`, `export` |
| `--output-mode` | `detail` / `simple` | `detail` | `run`, `redecide` (and `export`, always simple) |
| `non_english_file` | a config file, or no line | off | in the policy |
| `--max-removed-share X`, `--drop-if-first-cut` | 0 < X ≤ 1; a flag | off | `run`, `redecide`, `export` |

All settings are recorded in the run's `summary.json` (`settings.decision_unit`, `settings.output_mode`,
`policy.non_english`, and the whole policy as `policy_data`).

## Decision unit: paragraph or line

Paragraphs are always checked one by one. The unit decides what the result is applied to.

| | `paragraph` (default) | `line` |
|---|---|---|
| A hostile paragraph in a long article | that paragraph is cut, the rest stays | **the whole line is removed** |
| The line's decision | none (each paragraph has its own) | the **strictest** paragraph: remove > review > keep > pass |
| Document actions | untouched, pass, kept, review, edited, removed | untouched, pass, kept, review, removed (never `edited`) |
| Clean copy | text with paragraphs cut | the whole line kept, or dropped |
| `--review-as remove` | review paragraphs are cut too | a review line is dropped |

In line unit, a labels row gets three more fields:
- `decision`: the line's decision;
- `reason`: the deciding paragraph's reason;
- `decided_by`: that paragraph's index, 0-based. With a tie, the first paragraph decides.

```bash
python nli_label.py run dataset/corpus --policy policy/russia_llm_policy_v2.json --output-dir out_line --decision-unit line
python nli_label.py redecide out_label_ru_v2 --output-dir out_line2 --decision-unit line   # no models: stored scores
```

`redecide` keeps the run's unit unless `--decision-unit` says otherwise.

**Viewer:**
- The run page shows "decision unit: line".
- The document page shows the line decision on top and marks the deciding paragraph (★).
- On the document page, "What is cut" says that the whole line is kept or dropped.

## Dropping documents that lose too much: `--max-removed-share`, `--drop-if-first-cut`

Added 2026-11-27 (plan `cmds\plans\11_27_big_plan.md`, task 13). Paragraph unit only (in line unit a line is kept or
dropped whole anyway). Both are **off by default**: without them every run gives exactly the same output as before.

Without them, a document with cut paragraphs is **edited** unless fewer than `--min-doc-chars` (50) characters are left.
So a document that loses 90 % of its text but keeps 60 characters stays in the clean copy as a fragment.

| Option | An edited document becomes **removed** when … | Row fields |
|---|---|---|
| `--max-removed-share X` (0 < X ≤ 1) | `tokens_removed / tokens` is **above** X (exactly X stays edited) | `"removed_by": "removed_share"`, `"removed_share": 0.75` |
| `--drop-if-first-cut` | its first checked paragraph (the first of `paragraphs`, by position) is cut (often the main topic) | `"removed_by": "first_cut"`, `"removed_share": …` |

- The `--min-doc-chars` rule is checked first (a document removed by it has no `removed_by`); then the share, then the
  first paragraph.
- A removed document gets no clean line, as with `--min-doc-chars`.
- "Cut" means removed, and with `--review-as remove` also review.
- Example with `--max-removed-share 0.5`: 61 of 161 tokens cut (38 %) stays edited; 300 of 400 cut (75 %) → removed.
- `summary.json`: `settings.max_removed_share` (`null` = off) and `settings.drop_if_first_cut`; the stats (of the run
  and of each `<name>.summary.json`) get `removed_by`, e.g. `{"removed_share": 12, "first_cut": 3}`: how many
  documents went from edited to removed by each rule (they are counted in `docs.removed`). `report` prints it as
  "removed instead of edited".
- `redecide` and `export` (no models) take both from the run unless given: `--max-removed-share 0` (or `off`) and
  `--no-drop-if-first-cut` turn the run's values off.

```bash
python nli_label.py run dataset/corpus --policy policy/russia_llm_policy_v2.json --output-dir out_share --max-removed-share 0.5
python nli_label.py redecide out_label_ru_v2 --output-dir out_share2 --max-removed-share 0.5 --drop-if-first-cut
python nli_label.py redecide out_share2 --output-dir out_share3 --max-removed-share off   # the limit off again
```

## Output mode: detail or simple

**Detail** writes the outputs described in `outputs.md`: `.labels`, `.rewrites`, `.summary`, and `.clean` with
`--write-clean`.

**Simple** writes, per input file:
- `<name>.decisions.jsonl.zst`: one small row per line, shaped by the schema;
- `<name>.summary.json`: counts for **all** lines, untouched lines included. It also marks the file as done for resume;
- `<name>.evidence.jsonl.zst`, only if the schema asks for evidence.

```json
{"id": "myexample_7",  "ln": 7,  "src": "shard-00001", "decision": "untouched", "reason": "no_keyword"}
{"id": "myexample_10", "ln": 10, "src": "shard-00001", "decision": "remove",    "reason": "insult", "keyword_hint": {"orcs": 5, "russia": 2}}
```

- `--write-clean` is **refused** in simple mode, and the place-name rewrite is skipped because there is no clean copy.
- `redecide` and `export` need a **detail** run, because a simple run stores no scores.
- `--shard` and `run_label_shards.sh` work as usual: every input file is written by one copy.

```bash
python nli_label.py run /data/corpus --policy policy/russia_llm_policy_v2.json --output-dir /data/label_simple \
    --output-mode simple --decision-unit line                      # schema: output/simple_schema.json
python nli_label.py run ... --output-mode simple --schema output/my_schema.json
python nli_label.py export out_label_ru_v2 --output-dir out_simple --decision-unit line   # from a detail run, no models
```

`export` uses the policy recorded in the run, unless `--policy` is given. It reads the source files again, for the
`input.<field>` values and the keyword counts.

### The schema: `output\simple_schema.json`

| Key | Meaning |
|---|---|
| `file` | the decisions file's name: `decisions.jsonl.zst` → `<name>.decisions.jsonl.zst` |
| `include` | which lines get a row, by the line's strictest decision: `remove`, `review`, `keep`, `pass`, `untouched`, `error`. Untouched lines are most of a corpus; leave `untouched` out to shrink the files (the summaries still count them) |
| `omit_empty` | `true`: empty values are left out of a row (no `keyword_hint` on an untouched line) |
| `evidence` | `none` / `decided` (remove and review lines) / `all` (every checked line): their paragraphs with spans, actions, reasons, labels and scores |
| `fields` | `{"name": …, "from": …}` in the output's order. The name is yours; the sources are listed below |
| `reason_text` | the reason vocabulary: label, exception key or technical reason → your word. Exact keys are tried first, then `*` patterns in file order; a key that is not listed is written as it is |

Field sources:

| `from` | Value |
|---|---|
| `id` | the line's id field |
| `line` | the line number in the input file |
| `file` | the input file's name |
| `decision` | line unit: remove / review / keep / pass / untouched. Paragraph unit: the document action (edited, removed, kept …) |
| `level` | the line's strictest decision, in both units |
| `reason` | the deciding paragraph's technical reason (`remove_label`, `gate_negative` = every gate below its threshold, `non_english_keyword` …) |
| `reason_text` | what decided, through the vocabulary: the deciding label (`hostility_russians` → insult), the exception key, or the technical reason |
| `labels` | the line's positive labels |
| `keyword_counts` | every keyword and marker of the line, as listed and in lower case, with its count |
| `markers` | the marker terms found |
| `tokens`, `tokens_removed` | estimated tokens |
| `exception` | the deciding paragraph's exception key |
| `topic` | the corpus' topic field |
| `paragraphs` | `[[start, end, action], …]` for every checked paragraph (paragraph unit: what to cut) |
| `input.<field>` | copied from the input line, e.g. `input.url` |

A schema with an unknown source, a name used twice, or a bad `include` / `evidence` value is refused with a message,
both by the run and by the viewer.

### What a simple run can and cannot show

| Question | `evidence: none` | `evidence: decided` | detail |
|---|---|---|---|
| Totals per decision, reason, keyword and file | ✅ | ✅ | ✅ |
| Find and read lines ("all insult lines with orcs") | ✅ | ✅ | ✅ |
| Why a line was removed or reviewed | live: "Explain this line" | ✅ stored | ✅ |
| Why a line was kept (a possible miss) | live | live | ✅ |
| `redecide`, threshold tuning | ❌ | ❌ (needs a detail run) | ✅ |
| Expected vs result (a corpus with `expected_action`) | ✅ line level (needs a `line` field) | ✅ line level | ✅ also per paragraph |

**Which to use:**
- Test sets, policy tuning and samples (`--limit 20000`): **detail**.
- The big production run: **simple** with `evidence: decided`.
- Storage really tight: **simple** with `evidence: none`.

## Non-English keywords and markers

`policy\non_english.json`, used by a policy that has the line `"non_english_file": "policy/non_english.json"`. Without
that line the setting is off and nothing changes.

```json
{
  "scripts": {
    "arabic":   {"enabled": true,  "ranges": ["0600-06FF", "0750-077F", "08A0-08FF", "FB50-FDFF", "FE70-FEFF"]},
    "japanese": {"enabled": false, "ranges": ["3040-309F", "30A0-30FF"]},
    "chinese":  {"enabled": false, "ranges": ["4E00-9FFF", "3400-4DBF"]}
  },
  "keywords": "check",
  "markers": "check",
  "score_when_removed": false
}
```

- **A non-English term:** a listed keyword or marker with a letter in an **enabled** script. Cyrillic and Latin are
  never in the file, so Россия or Kyiv are checked as usual.
- **To add a script:** add its name and ranges, then enable it. No code change is needed.
- **`check`:** the normal check. The hit is still recorded per paragraph (`"non_english": [{"term", "kind",
  "script"}]`) and counted in the summary (`stats.non_english`).
- **`remove`:** a paragraph with such a hit is **removed** before the gate, with reason `non_english_keyword` or
  `non_english_marker`. No exception can lower it. In line unit, the whole line goes.
- **`score_when_removed`:**
  - `false` (default): such a paragraph is not scored, which is faster.
  - `true`: it is scored anyway, so labels and scores are stored for the flow view and `redecide`. The decision stays
    remove.
- **`redecide`** applies a changed config to a stored run. With `score_when_removed: false`, paragraphs that were
  removed without scoring have no scores, so `redecide` counts them as missing.

**Note:** the Russia-side keyword files and markers have **no Arabic terms today**, so `remove` changes nothing until
some are added (e.g. روسيا, أوكرانيا).

## In the viewer

| Page | What |
|---|---|
| `/label/output/` | The schema editor: fields (add, rename, source, order), include, omit_empty, evidence, the reason vocabulary. Checked while typing. **Live preview** of rows from a detail run. Saved with a backup in `output\.backup\` |
| `/label/non-english/` | Scripts on or off, ranges, adding a script, check / remove for keywords and markers, `score_when_removed`. Backups go to `policy\.backup\` |
| `/label/policy/` | The `non_english_file` setting, with a link to the editor |
| `/label/run/?run=<simple run>` | Totals; the lines filtered by decision, reason and keyword; open a line to see its text with keywords marked and its evidence; **Explain this line** |
| `/label/run/`, `/label/doc/` of a line-unit run | the unit, the line decision, the deciding paragraph |

**Explain this line** checks the line again through the model service. It uses the policy **recorded in the run**
(`policy_data`, not the current policy file) and the run's settings (unit, review-as, judge band). The flow trace shows
every step, including the non-English step. The model service must be running. Keyword lists are read from their
files as they are now.

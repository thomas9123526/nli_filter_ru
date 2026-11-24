# 11_24_output_modes: detail / simple output, paragraph / line decision unit, non-English hits

Planned 2026-11-24 with the user (discussion and examples: `cmds\conversation\2026-11-24.md`, from "Proposal (not
built yet)"). To be built while the user is away, when they say so. For the Russia-side policy
(`policy\russia_llm_policy_v2.json`); nothing in the checking logic changes, only what is written and what a decision
applies to.

Estimated: about 4–4½ hours (with the non-English setting).

## The two settings (independent; all four combinations allowed)

| Setting | Values | Default |
|---|---|---|
| `--output-mode` | `detail` (today's outputs) / `simple` | `detail` |
| `--decision-unit` | `paragraph` (today) / `line` | `paragraph` |

Also in `redecide` (and `export`, below), recorded in the run's `summary.json`, shown on the viewer's run page.

## Decisions (agreed)

1. **Simple mode writes one decisions file per input file** (`<name>.<file from the schema>`, default
   `<name>.decisions.jsonl.zst`) **plus `<name>.summary.json` always** (counts of all lines, untouched included; marks
   the file finished for resume). The run-wide `summary.json` stays (command, settings, the policy as used, the schema
   as used).
2. **Untouched rows are written by default**; the schema can switch them off (`include`). `omit_empty: true` by default:
   empty values are left out of a row.
3. **`--write-clean` is refused in simple mode** (clear error message). Detail mode: `--write-clean` optional as today.
4. **The reason vocabulary** (`reason_text`) maps labels, exception keys and technical reasons to words; entries can be
   added, edited and removed. Start: `hostility_*` → insult, `violence_call` → violence, `opinion_about_*` → opinion,
   `history` → history, `claim_ukraine_in_nato` → false_claim, `ambiguous_our_country` → our_country,
   `gate_negative` → not_related, `no_subject` → facts, `untouched` → no_keyword (plus the other L1 labels by name).
5. **Line unit: strictest paragraph wins**, remove > review > keep > pass. The line's reason comes from the deciding
   paragraph. Document actions: untouched, pass, kept, review, removed (never edited); the clean copy keeps or drops
   whole documents. `--review-as remove` still applies (a review line is dropped from the clean copy).
6. **Every config file can be edited in the viewer** (the schema now; the policy editor exists).
7. **`evidence`** in the schema: `none` (default) / `decided` (remove + review lines) / `all`. Writes
   `<name>.evidence.jsonl.zst`: per line its paragraphs (span, action, reason, labels, scores, exception), enough for
   the flow view, `redecide` and threshold tuning on those lines.

## The schema config: `output\simple_schema.json`

```json
{
  "about": "Simple-mode output of nli_label.py: one row per line, these fields, in this order.",
  "file": "decisions.jsonl.zst",
  "include": ["remove", "review", "keep", "pass", "untouched"],
  "omit_empty": true,
  "evidence": "none",
  "fields": [
    {"name": "id",           "from": "id"},
    {"name": "ln",           "from": "line"},
    {"name": "src",          "from": "file"},
    {"name": "decision",     "from": "decision"},
    {"name": "reason",       "from": "reason_text"},
    {"name": "keyword_hint", "from": "keyword_counts"}
  ],
  "reason_text": { "...": "see decision 4" }
}
```

- Field sources: `id`, `line`, `file`, `decision`, `reason`, `reason_text`, `labels`, `keyword_counts` (per keyword or
  marker as listed, lower-case), `markers`, `tokens`, `tokens_removed`, `exception`, `topic`, `paragraphs`
  (`[[start, end, action], …]`), `input.<field>` (copied from the input record).
- Checked like the policy: unknown source, duplicate name, bad `include` / `evidence` value → refused with a message.
- `--schema <file>` to use another schema; default `output\simple_schema.json`.

## Tasks, in this order

### 1. Decision unit (`--decision-unit line`) — ~45 min
- nli_label.py `run` and `redecide`: line decision = strictest paragraph; reason from the deciding paragraph;
  document actions and the clean copy as in decision 5; `"unit"` recorded in the rows' run summary.
- Viewer document page: the line's decision on top, the deciding paragraph marked; run page shows the unit.
- Tests: strictest rule, reason, clean copy (kept whole / dropped), redecide with the other unit on stored scores.

### 2. Non-English keywords and markers: remove, or check as usual — ~45 min

Requested and clarified 2026-11-24. Check logic, so the same in detail and simple mode and in both decision units.

**"Non-English" = Arabic letters for now.** Japanese, Chinese (and others) are added later by the user in the config
file, without code changes. Cyrillic and Latin are **not** non-English (Россия, Киев, Kyiv are checked as usual).

**A config file, editable in the viewer:** `policy\non_english.json`. The policy points to it with
`"non_english_file": "policy/non_english.json"` (no such line = the feature is off, today's behaviour).

```json
{
  "about": "Keywords / markers written in these scripts count as non-English.",
  "scripts": {
    "arabic":   {"enabled": true,  "ranges": ["0600-06FF", "0750-077F", "08A0-08FF", "FB50-FDFF", "FE70-FEFF"]},
    "japanese": {"enabled": false, "ranges": ["3040-309F", "30A0-30FF"]},
    "chinese":  {"enabled": false, "ranges": ["4E00-9FFF", "3400-4DBF"]}
  },
  "keywords": "check",
  "markers":  "check",
  "score_when_removed": false
}
```

- `scripts`: which writing systems count as non-English, as Unicode ranges (hex). Switch one on with `enabled`, or add
  a new one (name + ranges). Only **arabic** is on to start.
- `keywords` / `markers`: `"check"` (default) = the normal check; `"remove"` = a paragraph with such a hit is removed,
  reason `non_english_keyword` / `non_english_marker` (reason vocabulary e.g. → `non_english`). Like a protected
  label: exceptions never lower it. Line unit: the line is removed (strictest wins).
- `score_when_removed`: `false` (default) = such a paragraph is not scored (faster; the flow view shows only "removed:
  non-English hit"); `true` = scored anyway, so labels and scores are kept (evidence, flow view, `redecide`); the
  decision is still remove.
- A hit is judged by the **listed term** it matched (a keyword or marker with a letter in an enabled script).
- Recorded per paragraph (`"non_english": [the matched terms]`, with the script), counted in the summaries.
- **Viewer:** an editor for `policy\non_english.json` (scripts on/off, ranges, add a script, the two switches,
  `score_when_removed`; checked, backup on save), linked from the policy editor, which also gets the
  `non_english_file` setting. The flow view shows the step before the gate; the flow diagram gets it too.
- Tests: off / check / remove for keywords and markers, Arabic on and off, a newly added script, `score_when_removed`
  on and off, an exception cannot lower it, line unit, `redecide` applies a changed config on stored runs.

**Note for the user:** the Russia-side keyword files and markers have **no Arabic terms today** (checked 2026-11-24),
so `remove` changes nothing until Arabic keywords or markers are added (e.g. روسيا, أوكرانيا in
`keywords\russia_v3.txt` / `keywords\ukraine.txt`, or Arabic slurs in the markers).

### 3. Simple mode writer — ~1½ h
- `--output-mode simple`: per input file the decisions file (+ evidence file when set) + `<name>.summary.json`;
  refuses `--write-clean`; resume skips finished files; works with `--shard` / `run_label_shards.sh` (each input file
  is written by one copy, so per-file files need no joining).
- The schema file, its checks, `reason_text` matching (exact keys, then `*` patterns), `omit_empty`, `include`,
  `keyword_counts`.
- `nli_label.py export <detail run> --output-dir … [--schema …] [--decision-unit …]`: a simple-mode output from a
  detail run, no models.
- Tests: rows for every decision kind (both units), untouched on/off, omit_empty, a custom field list and names,
  evidence none / decided / all, the `--write-clean` refusal, export = run output.

### 4. Viewer — ~1–1½ h
- **Schema editor** `/label/output/` (like the policy editor): fields (add, remove, reorder, rename, source), include,
  omit_empty, evidence, the reason vocabulary (add / edit / delete entries); checked while typing; backup on save;
  **live preview** of rows built from a chosen detail run.
- **Simple run page**: totals from the summaries (untouched included), filter by decision / reason / keyword / file,
  open a line (source text with keywords highlighted, via `src` + `ln`); with evidence, the paragraph flow as on the
  document page.
- **"Explain this line"**: sends the line to the model service with the **policy recorded in the run's
  `summary.json`** (not the current file) and shows the full flow.
- Tests: API (schema check / save / preview, simple run rows and filters) and rendered pages.

### 5. Docs
- `cmds\labeling\`: a page on the two modes and the two units (when to use which: detail or `evidence: all` for
  tuning and samples; simple + `evidence: decided` for the big production run), the schema fields, examples.
- `cmds\h200\nli_label_h200.md`: the simple-mode command for the big run and the expected output size.
- `cmds\labeling\russia_policy_flow.html`: the decision unit in the document step.

## Rules while working alone

The same as `11_24_big_plan.md`: one task at a time, tests + frontend build + rendered-page check per task, no change
to the Russia-side policy's meaning or the test sets' expectations, commit / push only if the user said so when
leaving, a short report per task at the end. If both plans are to be done, ask nothing: do `11_24_big_plan` first,
then this one, unless the user said otherwise.

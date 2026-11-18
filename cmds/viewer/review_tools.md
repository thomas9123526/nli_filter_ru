# Review tools in the viewer: Keywords, Review, golden set, level-A audit

Added 2026-11-18. These pages work on any dataset with results, including the 6 TB corpus, where no line has a
label. Open a dataset page, then use the **Keywords** or **Review** button at the top.

## Keywords page (`/keywords/?ds=<dataset>`)

There is one row per keyword over every result file of the dataset.

| column | meaning |
|---|---|
| hits / lines | how often the keyword was found, and in how many lines |
| filtered / kept | the share of its lines that were filtered or kept |
| by rules | the share of its hits that a rule resolved (language menu, label, locale code, company name) |
| only this kw | lines with no other keyword. Removing the keyword would keep all of them |
| mistakes | wrong decisions among its labelled lines (`expect`) |
| A audit: keep | level A only: the share of its audited lines that the rules / models would keep |
| flags | worth a look, see below |

The flags:

- **mostly kept**: a level-B keyword with at least 20 lines, 90% or more of them kept. It mostly brings in junk.
  Add exclude patterns or other meanings, or remove it.
- **mostly rules**: 80% or more of its hits are language menus, labels or locale codes.
- **mistakes**: some of its labelled lines were decided wrongly.
- **A too broad?**: the audit says the models would keep 30% or more of its audited lines.
- **A not audited**: a level-A keyword that no run has audited yet (see below).
- **no hits**: in the keyword list but never found. This only shows with "show keywords without hits".

Click a row to see that keyword's lines. You can narrow them by hit state (not incidental, incidental, by a
rule, level A, check 1 only), by decision, or to mistakes only. Each line opens in place (▸) or on the record
page. **Copy table** copies the shown rows as tab-separated text.

The type, gloss and level come from the run's summary. Runs from before 2026-11-18 don't store them, so the
viewer reads them from the run's keyword file if it is on this machine.

On a big dataset, the first visit indexes every result file in the background ("Indexing N of M result
files…"). The numbers fill in by themselves.

## Level-A audit (`--audit-strict`)

A level-A keyword filters its lines without asking any model, so a normal run can't tell you if the word is too
broad. The audit checks that:

```powershell
python nli_filter.py <corpus> --audit-strict 0.05 --output-dir <out>
```

`--audit-strict 0.05` runs 5% of the level-A lines (a fixed sample: the same lines every run) through the rules,
check 1 and check 2 as if their A words were B. The result is stored in the decision as `"audit"`. **The decision
itself stays filter.** These audited lines cost model time, so keep the share small on big corpora.

- `summary.json` gets `"audit": {"lines": N, "would_keep": K, "would_filter": F}`.
- The **Keywords** page shows "A audit: keep" per A keyword, and the flag "A too broad?".
- The **Review** page has a queue "Level-A audit: models would keep".
- The **record** page shows a box with the audit result.
- **Try settings** has an "audit A" checkbox (Try audits every A line of the page).

## Review page (`/review/?ds=<dataset>`)

The Review page lists the lines most worth a human look, across all files. Pick a queue:

| queue | lines |
|---|---|
| Close to a threshold | unlabelled lines whose deciding score is nearest to its threshold. A small change would flip them |
| One keyword decides | filtered lines with only one keyword, closest to the threshold first |
| Level-A audit: models would keep | level-A lines the audit says the models would keep |
| Decided by the judge | lines where the judge re-scored the best check-1 pair |
| Mistakes | labelled lines decided wrongly |

▸ shows a line's text and the explanation in place. Click the file name to open the record page.

## Golden set (labels outside the corpus)

The **filter** / **keep** buttons on the Review and Keywords pages, and on every record page, label a line for the
**golden set**: `golden/<dataset>.jsonl` in the project folder. Each label copies the line's id and text, with
`expect`, `category: "review"`, an optional note and where the line came from. **The corpus is never changed:**
real corpus lines keep only `id` and `text`. Click a label again to remove it.

The golden set is a normal test file. The Review page shows the command to run it, for example:

```powershell
python nli_filter.py golden\web.jsonl --output-dir out_golden_web
```

Then compare two runs of it with `nli_compare.py` (see `cmds/testing/compare_and_replay.md`).

## API (for scripts)

- `GET /api/datasets/<ds>/keywords`: per-keyword stats
- `GET /api/datasets/<ds>/lines?kw=&kw_state=&decision=&mismatch=&labelled=&audit=&scored=&single_kw=&judged=&sort=review`:
  decisions across files
- `GET /api/datasets/<ds>/golden`, `POST /api/datasets/<ds>/golden {file, row, expect, note}`: the golden set

# Try keywords and hypotheses on the Corpus page

Added 2026-11-13. The Corpus page has a **Try settings** panel: it runs `nli_filter.py`'s decision on the lines of
the page with the keywords, hypotheses and thresholds you set there, and shows the result on every line next to
the decision of the saved filter run. The models run in a separate small program, `nli_playground.py`.

## 1. Start the model service

In the project folder, in the environment where `nli_filter.py` runs (torch + the models):

```powershell
cd D:\hkc\nli_filter2
python nli_playground.py                          # fast model + judge, device auto, http://127.0.0.1:8100
python nli_playground.py --judge-model none       # fast model only (less memory)
python nli_playground.py --device cuda:0          # a given GPU
```

It prints `nli_playground: fast modernbert, judge deberta, ... -> http://127.0.0.1:8100` when the models are
loaded. Keep the window open; `Ctrl+C` stops it. Then start the viewer as usual (another window).

The viewer finds it at `http://127.0.0.1:8100`. Another address (e.g. the GPU machine): in
`viewer\viewer_config.json`, `"playground_url": "http://192.168.170.200:8100"` (and start the service there with
`--host 0.0.0.0`).

## 2. Use the panel

Corpus page → a file → **▸ Try settings**:

| Part | What you set |
|---|---|
| Country | Russia / China (built in) or any other with its adjective |
| Model and thresholds | judge on / off, uncertain band, check-1 / check-2 thresholds, windows, early stop, rules |
| Keywords | a file from `keywords\` (or the built-in list), editable; **Save** writes `keywords\<name>.txt` |
| Hypotheses | a file from `hypotheses\` (or the built-in = `hypotheses\default.json`); add / change / remove check-1 and check-2 hypotheses; **Save** writes `hypotheses\<name>.json` |

**Run on the 20 lines of this page** → every line shows `try: filter / keep`, the reason, the best check-1 score
and `was …` = the saved run's decision (yellow when it changed). **Details** shows the highlighted text and the
check-1 / check-2 tables, as on the record page. Page through the file and run again for other lines.

The panel remembers your settings in this browser. Saving a file that exists asks first and keeps the old
version in `viewer\.viewer_edits\_project\`. Saving works only from this PC (like corpus editing).

## 3. Use the result in a real run

Hypothesis files are shared with `nli_filter.py`:

```powershell
python nli_filter.py test_corpus --hypotheses-file hypotheses\weather.json --output-dir out_weather
```

Without `--hypotheses-file`, `nli_filter.py` uses `hypotheses\<country>.json` if it exists (e.g.
`hypotheses\russia.json` for `--country Russia`), else the built-in hypotheses. Keywords work the same way
(`--keywords-file`, else `keywords\<country>.txt`). So saving your tuned set as `russia.json` / `russia.txt` makes
it the default for Russia. The run's `summary.json` records which hypothesis file was used.

File format (`hypotheses\default.json`):

```json
{
  "description": "built-in default hypotheses of nli_filter.py",
  "check1": {"topic": "This text is about {country}, a {country_adj} person, ..."},
  "check2": {"company_name": "This text mentions {country} or {country_adj} only as part of a company or brand name.",
             "language_setting": "This text mentions the {country_adj} language only as a language option or setting."}
}
```

## 4. Good to know

- A run of 20 lines takes a few seconds on a GPU (more lines with keywords = more model calls; long texts with
  many windows take longest). On CPU it is much slower.
- The decisions are exactly what `nli_filter.py` would write with the same settings (same code, same defaults).
- Nothing is written to the corpus or the output folder; only **Save** writes the keyword / hypothesis file.

## 5. Run nli_filter.py from the viewer

Dataset page → **Run filter** (next to **Browse corpus**). The page shows the arguments for
`python nli_filter.py …`, ready to edit:

- the dataset's corpus (a local path, or the server address; a password is given to the run as
  `${NLI_CORPUS_PASSWORD}` and never shown) and its output folder (`--output-dir`, must be on this PC),
- the settings of the last run (from its `summary.json`), e.g. `--judge-model none --max-windows 6`,
- `--overwrite` when the output folder already has results (else finished files are skipped).

Add what you need (`--hypotheses-file hypotheses\russia.json`, `--device cuda`, `--limit 1000` ...), click
**Start**, and the output appears live; **Stop** ends it (finished files stay done). When it is done,
**Open the results** shows the new decisions.

The run is started by `nli_playground.py` (with its Python, in the project folder), so the viewer needs no
torch. One run at a time; the full output is kept in `.playground_jobs\`. When the service is only needed for
runs, start it without loading models: `python nli_playground.py --no-models`. With models loaded, the run
loads its own copies too (more memory; on a small GPU use `--no-models` or `--judge-model none`).

On the Corpus page, a second **Run on the N lines of this page** button sits below the lines (same settings as
the Try settings panel).

## 6. Runs in progress (any nli_filter.py run)

Every `nli_filter.py` run writes a small progress file into its output folder and updates it every 60 seconds
(`--progress-every 300` for less often; the file is ~1 KB, the cost is negligible either way):
`<output>\progress\<date>-<PC>-<process>-….json` (state, files total / done / skipped, bytes read, current file,
lines/s, time left). The dataset page shows them as **Runs in progress**: one row per run (every
`run_shards.sh` / `--shard` copy has its own), a combined bar over the runs still going, and recent finished runs
(the last 24 hours). It works however the run was started: typed in a terminal, **Run filter**, `run_shards.sh`,
another PC writing to an output folder the viewer can read (also over SFTP).

| Row says | Meaning |
|---|---|
| running, 37.5 %, about 4 min left | going; the percentage counts bytes read of the files to do |
| done / failed / stopped | finished (failed: an error or unreadable files, shown on the row; stopped: Ctrl+C) |
| **no update** | said "running" but its file was not updated for 3 of its intervals (at least 2 minutes): killed, crashed, PC asleep or gone |

`"progress_stale_seconds": 120` in `viewer_config.json` sets the minimum (the run's interval x 3 counts when longer); `--no-progress-file` turns the file
off for a run. Old progress files can be deleted any time (they are only for this display).

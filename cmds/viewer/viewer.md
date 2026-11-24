# Result viewer: quick commands

Web page that shows any `nli_filter.py` decision next to its original corpus line. Full guide:
`viewer/README.md`.

## Start (Windows)

```powershell
cd D:\hkc\nli_filter2\viewer
.\start_viewer.ps1
```

Open http://127.0.0.1:8000. The first start creates `backend\.venv`, installs the packages and builds the
UI (needs internet and Node.js once). Stop with Ctrl+C.

| Option | Meaning |
|---|---|
| `.\start_viewer.ps1 -Port 8080` | other port |
| `.\start_viewer.ps1 -Public` | reachable from other machines |
| `.\start_viewer.ps1 -Config my.json` | other datasets |
| `.\start_viewer.ps1 -Rebuild` | rebuild the UI after changing it |

Linux: `cd viewer && ./start_viewer.sh` (`PORT=`, `HOST=0.0.0.0`, `CONFIG=`).

## Add a dataset

Edit `viewer\viewer_config.json`: one entry per output folder + corpus folder.

```json
{"name": "run2", "title": "Russia, full run", "corpus": "D:/data/corpus", "output": "D:/data/nli_out"}
{"name": "ftp_run", "corpus": "ftp://reader:${FTP_PASSWORD}@ftp.lan/corpus", "output": "ftp://reader:${FTP_PASSWORD}@ftp.lan/nli_out"}
{"name": "minio_run", "corpus": "minio://minio.lan:9000/corpus/cc", "output": "minio://minio.lan:9000/nli-out/run1",
 "corpus_options": {"access_key": "${MINIO_ACCESS_KEY}", "secret_key": "${MINIO_SECRET_KEY}"},
 "output_options": {"access_key": "${MINIO_ACCESS_KEY}", "secret_key": "${MINIO_SECRET_KEY}"}}
```

Restart the viewer after editing the config. New result files in an existing output folder appear by
themselves within 30 s.

## Two areas

The viewer is split by tool; every link inside an area stays in it. The header tabs show which one you are in.

| Area | Pages | For |
|---|---|---|
| `/label/…` **Labelling (Russia LLM)** | `/label/` runs, `/label/run/`, `/label/doc/`, `/label/try/`, `/label/corpus/` | `nli_label.py` with the Russia-side policy (see `labels_pages.md`) |
| `/filter/…` **Filter** | `/filter/` datasets, `/filter/dataset/`, `/filter/file/`, `/filter/record/`, `/filter/review/`, `/filter/run/`, `/filter/tune/`, `/filter/keywords/`, `/filter/corpus/` | `nli_filter.py` outputs |

- The **corpus page** exists in both areas with the same corpus: `/label/corpus/` has Edit, "Label with a policy"
  and "flow →" (Try); `/filter/corpus/` has Edit, "Try settings" and the decision links. An edit made in one shows
  in the other: it is the same file.
- The home page (`/`) lists the labelling runs first, then the filter datasets (sort and search on both).
- Old URLs (`/labelrun/?run=…`, `/dataset/?ds=…`, `/corpus/?ds=…`, …) still work: they forward to the new path with
  the same query. `/corpus/` goes to `/label/corpus/` when the dataset's output is a labelling run, else to
  `/filter/corpus/`.

## Use (Filter area)

1. **Filter** → pick a dataset.
2. **Dataset page**: totals, reasons, accuracy (test data), run settings, hypotheses, file list; "Find a
   line by id" in the top right.
3. **File page**: click Filtered / Kept / a reason / "Wrong vs expected" / "Decided by judge"; search by
   id, keyword or line number; sort by score.
4. **Record page**: verdict, highlighted text, score tables. Click a hit or a score row to locate it in the
   text. Keys: `j` next, `k` previous, `Esc` back to the list.
5. **Tune thresholds** (button on the dataset page): move the check-1 / check-2 thresholds and see which
   lines would flip and how precision / recall change, without running a model. Use the result for
   `--check1-threshold` / `--check2-threshold` in the next `nli_filter.py` run.
6. **Browse corpus** (button on the dataset page): the corpus folders, files and lines. With
   `"editable": true` on the dataset (local corpus only), the text of a line can be edited, also inside .zst
   files: see `edit_corpus.md`.

Hit colours: red = not incidental, amber = check 1 only, teal = incidental (check 2), blue = resolved by a
rule. Shaded = check-1 window, dotted underline = check-2 window.

## Terminal

```powershell
cd D:\hkc\nli_filter2\viewer\backend
.venv\Scripts\python.exe -m nli_viewer show --config ..\viewer_config.json test_corpus books/part-00/shard-00000 --line 10
.venv\Scripts\python.exe -m nli_viewer find --config ..\viewer_config.json test_corpus mixed-002
.venv\Scripts\python.exe -m nli_viewer verify --config ..\viewer_config.json test_corpus
```

Without a config: `--corpus D:\data\corpus --output D:\data\nli_out` and dataset name `default`.

## Dynamic datasets (`auto_datasets`)

With `"auto_datasets": "../dataset"` in `viewer\viewer_config.json`, the viewer looks at every run folder in
`dataset\` (folders starting with `out`) and pairs it with the corpus it was made from. The pairing comes from the run
itself (the input files recorded in its `summary.json`), not from the folder names, so `out_label_ru_v2` is paired
with `test_corpus_cases_ru` although the names differ.

- For each corpus, the **most recent** finished `nli_filter.py` run and the **most recent** finished `nli_label.py`
  run are shown as datasets, next to the ones written in the config. Their cards carry an **auto** badge; label runs
  are named `<corpus>-labels` (e.g. `test_corpus_cases_ru-labels`).
- The entries written in `"datasets"` always win: a pair that is configured already is not added twice, and a
  configured name is never reused (the dynamic one becomes `auto-<name>`). To show a particular run instead of the
  newest (e.g. `out_label_ru_v2_judge`), write it as an entry.
- A new run is picked up when the start page loads again (no restart). A run that is still going is never picked.
- Not shown automatically: runs made from a single file (`test_russia_long.jsonl`), from a server corpus
  (`sftp://…`: add those by hand), and runs whose corpus is gone.

## Which run folders are in use, which can go

```powershell
cd viewer\backend
.venv\Scripts\python.exe -m nli_viewer runs --config ..\viewer_config.json
```

It lists every run folder in `dataset\` with its status and prints `Remove-Item` lines. **Nothing is deleted by the
viewer**: copy the lines you want into PowerShell in the project folder.

| Status | Meaning | Remove? |
|---|---|---|
| in use | The most recent run of its kind for its corpus: shown by the viewer | No |
| running | `progress.json` says it is running | No |
| corpus missing | The corpus it was made from is gone | Yes (no matching corpus) |
| no summary | No `summary.json`: unfinished, stopped or broken | Yes (not valid) |
| input unknown | `summary.json` records no input | Yes |
| older run | A newer run of the same kind exists for the same corpus | Only if you no longer need it (reports in `cmds\design` cite some, e.g. v1 as a baseline) |
| single-file input / server input | Valid, but not shown as a dataset | Only if you no longer need it |

The same list as JSON: `GET /api/run-folders`.

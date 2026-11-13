# NLI result viewer

Pick any line of an `nli_filter.py` run and see its decision **next to the original corpus line**: the text
with the keyword hits and NLI windows highlighted, the hypotheses, the fast / judge / final scores, the
thresholds, the models, and a plain-language reason why it was kept or filtered. Nothing has to be
decompressed by hand. Corpus and results can be on local disk, FTP(S), SFTP or S3 / MinIO.

```
 Browser ──> Next.js UI (static files, served by the backend)
                │ JSON
                ▼
 FastAPI backend  (python -m nli_viewer serve)
   api ── results (output folder <-> corpus folder) ── explain (highlights, verdict)
             │
           lines (jump to line N of .jsonl/.gz/.zst/.zip/.rar/.parquet/.arrow; disk cache + offset index + SQLite)
             │
           storage (local | ftp:// | sftp:// | s3:// | minio://)
```

## Start

Windows:

```powershell
cd D:\hkc\nli_filter2\viewer
.\start_viewer.ps1                 # first run: creates backend\.venv, installs packages, builds the UI
.\start_viewer.ps1 -Wheels ..\pkgs\windows-py312   # first run without internet: packages from a wheel folder
```

Linux:

```bash
cd viewer && ./start_viewer.sh
```

Open http://127.0.0.1:8000. API documentation: http://127.0.0.1:8000/docs.
`-Public` (Windows) or `HOST=0.0.0.0` (Linux) makes it reachable from other machines.

Manual start (what the scripts do):

```powershell
cd viewer\backend
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
cd ..\frontend; npm install; npm run build; cd ..\backend
.venv\Scripts\python.exe -m nli_viewer serve --config ..\viewer_config.json
```

Without a config file: `python -m nli_viewer serve --corpus ../../test_corpus --output ../../out_test_corpus`.

## Configure datasets: `viewer_config.json`

A dataset = one `nli_filter.py` output folder + the corpus folder it was made from.

```json
{
  "cache_dir": ".viewer_cache",
  "cache_max_gb": 20,
  "datasets": [
    {"name": "test_corpus", "title": "Test corpus", "corpus": "../test_corpus", "output": "../out_test_corpus"},
    {"name": "ftp_run", "corpus": "ftp://reader:${FTP_PASSWORD}@ftp.lan/corpus", "output": "ftp://reader:${FTP_PASSWORD}@ftp.lan/nli_out"},
    {"name": "minio_run", "corpus": "minio://minio.lan:9000/corpus/cc", "output": "minio://minio.lan:9000/nli-out/run1",
     "corpus_options": {"access_key": "${MINIO_ACCESS_KEY}", "secret_key": "${MINIO_SECRET_KEY}"},
     "output_options": {"access_key": "${MINIO_ACCESS_KEY}", "secret_key": "${MINIO_SECRET_KEY}"}}
  ]
}
```

| Location | Write it as |
|---|---|
| Local folder | `D:\data\corpus`, `/data/corpus`, `../relative/to/config`, `file:///data/corpus` |
| FTP / FTPS | `ftp://user:password@host:21/path`, `ftps://...` (special characters in the password: URL-encode, e.g. `@` = `%40`) |
| SFTP (SSH) | `sftp://user@host:22/absolute/path` or `sftp://user@host/~/below/login/folder`; `"password"` or `"key_file"` (+ `"passphrase"`) in `*_options`; neither = SSH agent / `~/.ssh` keys. `"host_key_check"`: `warn` (default, unknown host keys accepted and logged), `strict` (host must be in `~/.ssh/known_hosts` or `"known_hosts"`), `off` |
| MinIO | `minio://host:9000/bucket/prefix` (http), `minios://...` (https), keys in `*_options` |
| S3 / other S3-compatible | `s3://bucket/prefix?region=eu-west-1`, `s3://bucket/prefix?endpoint=http://host:9000`; keys in `*_options` or `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` |

`${VAR}` is replaced by the environment variable, so passwords need not be in the file. Passwords are never
shown in the UI or the API. More examples: `viewer_config.example.json`.

**Corpus only, no results yet:** leave out `"output"`, or point it at a local folder that `nli_filter.py` will
create later. The Corpus page (browse, read, edit) works right away; the dataset page says "No filter
results yet" and shows the results by itself once the folder has them (rescanned every 30 s). A remote output
(FTP / SFTP / S3) that cannot be reached is still an error.

```json
{"name": "my_corpus", "corpus": "D:/data/my_corpus", "output": "../out_my_corpus", "editable": true}
```

How results are matched to corpus files: the output path without its suffix
(`books/part-00/shard-00000.summary.json` → `books/part-00/shard-00000`) is looked up in the same sub
folder of the corpus (`books/part-00/shard-00000.jsonl.zst`), so point `corpus` at the folder you gave to
`nli_filter.py`. If the layout differs, the file is searched by name in the whole corpus.

## Pages

| Page | What you see |
|---|---|
| Datasets | Every configured dataset; unreachable servers are marked with the reason |
| Dataset | Totals, why lines were kept or filtered, evaluation (when lines have `expect`), run settings, models, hypotheses, file list (filter by path, files with mistakes, partial, missing corpus), find a line by id |
| File | All decisions of one file: quick filters (filtered / kept / each reason / wrong vs expected / decided by the judge), search by id, keyword or line number, check-1 score range, sortable columns, paging |
| Tune thresholds | Move the check-1 / check-2 thresholds and see at once how many lines would flip, which ones, and (with `expect` labels) precision / recall / F1 before and after, plus a check-1 sweep table. Recomputed from the stored scores, no model runs. Lines that were check-1 negative never went to check 2: if a lower threshold makes them positive they are counted as filtered and marked "estimated" |
| Corpus | "Browse corpus" on the dataset page: the corpus folders and files, then any file's lines, 20 per page (go to line N); each line's id, text, a link to its decision, and **Edit** when editing is on (see below) |
| Record | Verdict and the steps behind it; the original text with hits coloured by what happened to them, check-1 windows shaded, check-2 windows underlined (hover or click a hit or score row to locate it); check-1 and check-2 tables with hypothesis, fast, judge and final score against the threshold; models; file locations; raw JSON of the line and of the decision. `j` / `k` = next / previous (within the active filters), `Esc` = back to the list |

Long texts (over 30,000 characters) are shown as the parts around the hits and windows, with the
skipped stretches marked.

## Try settings (keywords, hypotheses, models)

The Corpus page's **Try settings** panel runs `nli_filter.py`'s decision on the lines of the page with other
keywords / hypotheses / thresholds and shows each result next to the saved run's decision ("was keep" ->
changed). The models run in `nli_playground.py` (project folder, torch environment):
`python nli_playground.py` -> `http://127.0.0.1:8100` (`"playground_url"` in the config). Keyword files
(`keywords/*.txt`) and hypothesis files (`hypotheses/*.json`, also read by `nli_filter.py --hypotheses-file`)
can be edited and saved from the panel (`"project_dir"`, default `..`). Guide: `cmds/viewer/try_settings.md`.

**Run filter** (dataset page) runs `nli_filter.py` on the dataset with editable arguments (corpus, output folder, the
last run's settings, `--overwrite`) and shows the output live; the run is started by `nli_playground.py`
(`--no-models` if it is only for runs).

**Runs in progress** (dataset page): every `nli_filter.py` run, however it was started, writes
`OUTPUT/progress/<run>.json` every 60 s (`--progress-every`); the viewer shows one row per run / shard with progress, files, speed and time
left, a combined bar, and "no update" for runs that went silent (`"progress_stale_seconds"`, default 120).

## Editing corpus lines

The text field of a corpus line can be changed in the viewer, also inside `.zst` and `.gz` files. It is off
by default: turn it on per dataset in `viewer_config.json` and restart the viewer.

```json
{"name": "test_corpus_de", "corpus": "../test_corpus_de", "output": "../out_test_corpus_de", "editable": true}
```

Then use **Edit text** on a record page, or **Edit** on any line of the Corpus page (also lines without a
decision). `Ctrl+Enter` saves, `Esc` cancels.

| What | How |
|---|---|
| What can change | Only the text field (`text`, or the run's `--text-field`). The `id` and all other fields stay; the line keeps the JSON style of the file |
| Which corpora | Local, mapped-drive or UNC folders (`D:\...`, `Z:\...`, `\\server\share\...`), and FTP / SFTP / S3 / MinIO servers when the account may write there (a read-only account: the save fails, nothing changes) |
| Which files | `.jsonl` / `.json` / `.ndjson`, also `.gz` / `.zst`; members of `.zip` and `.rar` archives (choose the member on the Corpus page; the archive is rebuilt with the new member, the other members unchanged); rows of `.parquet` and `.arrow` / `.feather` tables (row n = line n; the text column is replaced; schema with its metadata, other columns, compression and row groups / record batches stay; `.arrow` in Arrow's file or stream format, e.g. Hugging Face `datasets` files). `.rar` needs WinRAR's `Rar.exe` / `UnRAR.exe` (Linux: `rar` / `unrar`, or `NLI_RAR` / `NLI_UNRAR` = their paths); without `Rar` a `.rar` is read-only. `.parquet` / `.arrow` need `pyarrow` |
| Who may edit | Only a browser on the PC the viewer runs on (`http://127.0.0.1:8000`, or the PC's own network address), also with `-Public` (other PCs see the pages read-only). `"edit_allow_remote": true` at the top of the config allows other PCs |
| How a save works | The whole file is written again, compressed like the original, to a temporary file next to it; that file is decompressed and checked; then it replaces the original in one step. A crash or power cut leaves the old file complete |
| On a server | The new file is made and checked on this PC. Just before the upload the viewer checks that the file on the server was not changed since it was read (else: conflict, nothing uploaded). Upload under a temporary name in the same folder, then renamed over the original (SFTP: one step where the server supports it, else old file aside → new file in place → old file removed; FTP the same; S3: one upload, atomic per object). The backup of the original is downloaded to this PC (`.viewer_edits`). Each save uploads the whole compressed file: save several lines together |
| Conflicts | The save sends a fingerprint (sha1) of the line as it was loaded. If the line changed in the meantime (another tab or person), the save is refused: reload and edit again |
| Backup | The first edit of a file copies the untouched original to `.viewer_edits/<dataset>/originals/<same path>`. Later edits keep that first copy. To go back completely, copy it over the corpus file |
| Log and undo | Every edit (time, file, line, id, old and new text) is appended to `.viewer_edits/<dataset>/edits.jsonl`. **Undo** in the line's edit history puts the old text back (latest change first). `python -m nli_viewer edits` lists them |
| Insert / delete | **Insert below**, **Insert at top**, **Add at end** and **Delete** on the Corpus page; new lines need an unused `id`. Later lines move by one; the log of inserts / deletes maps the decisions' line numbers to the current ones (record page: "line 12 is now line 13"; new lines marked "new"). Undo for each in "Recent changes in this file" |
| Many lines at once | On the Corpus page, **Add to pending changes** instead of Save: changes are collected (also across pages of the same file) and **Save all** writes them in one rewrite, all or nothing. The browser warns before leaving with unsaved changes |
| Time | A save rewrites the whole file. Measured with 3,000,000 lines (287 MB `.zst`, 689 MB decompressed): about 9 s for one line, 10 s for 20 lines saved together; under a second for the test corpus. zstd uses all CPU cores; level `"edit_zstd_level"` (default 3). The checked new copy goes straight into the cache, so the next page needs no decompression |
| First look at a big file | The lines show after the file is decompressed once (3.4 s for the file above); the "decision ›" links follow when the decisions table is built in the background (24 s there; "linking decisions…" meanwhile) |
| Filter results | Decisions belong to the text the run saw. A line edited after the run is marked "edited after the filter run" on its record page: verdict, highlights and scores are shown for the old text, the current text below. Rerun `nli_filter.py` on the file for decisions on the new text. `verify` counts such lines separately, not as errors |
| Don't | Edit a file while `nli_filter.py` is reading it. Windows refuses to replace an open file; the save then fails and the file stays as it was |

## Command line

The same information in a terminal (also handy over SSH):

```powershell
cd viewer\backend
.venv\Scripts\python.exe -m nli_viewer datasets  --config ..\viewer_config.json
.venv\Scripts\python.exe -m nli_viewer files     --config ..\viewer_config.json test_corpus
.venv\Scripts\python.exe -m nli_viewer decisions --config ..\viewer_config.json test_corpus books/part-00/shard-00000 --decision filter
.venv\Scripts\python.exe -m nli_viewer show      --config ..\viewer_config.json test_corpus books/part-00/shard-00000 --line 10
.venv\Scripts\python.exe -m nli_viewer find      --config ..\viewer_config.json test_corpus mixed-002
.venv\Scripts\python.exe -m nli_viewer index     --config ..\viewer_config.json      # prepare all caches in advance
.venv\Scripts\python.exe -m nli_viewer verify    --config ..\viewer_config.json test_corpus   # every decision vs its line
.venv\Scripts\python.exe -m nli_viewer check     --config ..\viewer_config.json      # can every server be reached?
.venv\Scripts\python.exe -m nli_viewer edits     --config ..\viewer_config.json test_corpus   # corpus edits made in the viewer
```

`verify` checks every decision: the original line exists, its `id` equals the decision's `id`, and every
keyword hit's character span really contains the keyword. Run it after a big filter run.

## Cache

`.zst` / `.gz` / `.zip` / `.rar` / `.parquet` / `.arrow` files and remote files have no random access, so the first look at a file
decompresses it once into `cache_dir` and builds a line index (and a SQLite table of its decisions). After
that every line opens instantly. The cache is trimmed to `cache_max_gb` (least recently used first) and
notices when a file changes (size / modification time). `python -m nli_viewer index` fills it in advance;
deleting `cache_dir` is always safe.

Measured on the development PC (i7-8700K, local disk) with one corpus file of 100,000 lines
(360 MB decompressed, 11 MB `.zst`) and its decisions:

| Action | Time |
|---|---|
| First look at the file's decisions (decompress + build the SQLite index) | 1.4 s |
| Filtered / sorted decision list, any page | 20–30 ms |
| First record of the file (decompress the 360 MB corpus file once) | 0.4 s |
| Any further record, with prev / next navigation | 10 ms |
| Threshold simulation with a 10-step sweep | 0.7 s |

Over FTP, SFTP or S3 the first look also includes the download.

## API

| Endpoint | Returns |
|---|---|
| `GET /api/datasets` | configured datasets (+ error if unreachable) |
| `GET /api/datasets/{ds}` | overview: totals, reasons, evaluation, run, models, hypotheses |
| `GET /api/datasets/{ds}/files?q=&only=mistakes\|partial\|no_corpus` | result files |
| `GET /api/datasets/{ds}/decisions?file=&decision=&reason=&q=&kw=&min_score=&max_score=&mismatch=&judged=&sort=&desc=&offset=&limit=` | decisions of one file + facets |
| `GET /api/datasets/{ds}/record?file=&line=` (or `&row=`) + the same filters | one decision, original line, explanation, prev / next |
| `GET /api/datasets/{ds}/find?id=` | the line with this id in any file |
| `GET /api/datasets/{ds}/simulate?check1=&check2=&sweep=1` | decisions recomputed with other thresholds: counts, flips, metrics, sweep |
| `GET /api/datasets/{ds}/raw?root=corpus\|output&path=&line=&count=` | raw lines of any file |
| `GET /api/datasets/{ds}/browse?root=corpus\|output&path=` | folder listing |
| `POST /api/datasets/{ds}/refresh` | rescan the output folder now (it is rescanned every 30 s anyway) |
| `GET /api/datasets/{ds}/corpus/lines?path=&start=&count=&preview=` | corpus lines: id, text, sha1, number of edits, decision row |
| `GET /api/datasets/{ds}/corpus/edit-status?path=` | can this browser edit this dataset / file, and if not, why |
| `POST /api/datasets/{ds}/corpus/edit` body `{path, line, text, sha1}` | change a line's text (needs header `X-Viewer-Edit: 1`; 409 when the line changed since it was loaded) |
| `GET /api/datasets/{ds}/corpus/edits?path=&line=` | edit log |
| `POST /api/datasets/{ds}/corpus/insert` body `{path, after, record, sha1, member}` | insert a line after line `after` (0 = top) |
| `POST /api/datasets/{ds}/corpus/delete` body `{path, line, sha1, member}` | delete a line |
| `POST /api/datasets/{ds}/corpus/edits/{edit}/undo` | undo an edit, insert or delete (same header) |

## Developing the UI

```powershell
cd viewer\backend; .venv\Scripts\python.exe -m nli_viewer serve --config ..\viewer_config.json   # API on :8000
cd viewer\frontend; npm run dev                                                                # UI on :3000, hot reload
```

`npm run dev` forwards `/api` to `NLI_VIEWER_BACKEND` (default `http://127.0.0.1:8000`). `npm run build`
writes the static UI to `frontend/out`, which the backend serves.

## Tests

```powershell
cd viewer\backend; .venv\Scripts\python.exe -m pytest      # 66 tests: storages (real FTP, SFTP + S3 servers), lines,
                                                           # results, API, editing, and the built UI in headless Chrome
.venv\Scripts\python.exe -m pytest -k "not ui"             # without the browser test (~30 s instead of ~3 min)
cd viewer\frontend; npm run typecheck; npm run build
```

## Files

| Path | Content |
|---|---|
| `backend/nli_viewer/storage.py` | Local / FTP / SFTP / S3 storage, `open_storage(uri)`: re-exports `nli_storage.py` from the project root (shared with `nli_filter.py`; copy it along when moving the viewer) |
| `backend/nli_viewer/lines.py` | `LineFile` (line N of any file), `LineCache` |
| `backend/nli_viewer/results.py` | `Dataset`, `DecisionIndex` (SQLite), file matching |
| `backend/nli_viewer/explain.py` | highlight segments, score tables, verdict text |
| `backend/nli_viewer/config.py` | config file, dataset registry |
| `backend/nli_viewer/edit.py` | `CorpusEditor`: change a line's text in a .zst / .gz / plain file safely; backup, log, undo |
| `backend/nli_viewer/api.py` | FastAPI app |
| `backend/nli_viewer/cli.py` | command line |
| `frontend/app`, `frontend/components`, `frontend/lib` | Next.js pages, UI components, API client and types |
| `viewer_config.json` | datasets of this project (test_corpus) |
| `start_viewer.ps1`, `start_viewer.sh` | one-command start |

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
           lines (jump to line N of .jsonl/.gz/.zst/.zip; disk cache + offset index + SQLite)
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
| Record | Verdict and the steps behind it; the original text with hits coloured by what happened to them, check-1 windows shaded, check-2 windows underlined (hover or click a hit or score row to locate it); check-1 and check-2 tables with hypothesis, fast, judge and final score against the threshold; models; file locations; raw JSON of the line and of the decision. `j` / `k` = next / previous (within the active filters), `Esc` = back to the list |

Long texts (over 30,000 characters) are shown as the parts around the hits and windows, with the
skipped stretches marked.

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
```

`verify` checks every decision: the original line exists, its `id` equals the decision's `id`, and every
keyword hit's character span really contains the keyword. Run it after a big filter run.

## Cache

`.zst` / `.gz` / `.zip` files and remote files have no random access, so the first look at a file
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

## Developing the UI

```powershell
cd viewer\backend; .venv\Scripts\python.exe -m nli_viewer serve --config ..\viewer_config.json   # API on :8000
cd viewer\frontend; npm run dev                                                                # UI on :3000, hot reload
```

`npm run dev` forwards `/api` to `NLI_VIEWER_BACKEND` (default `http://127.0.0.1:8000`). `npm run build`
writes the static UI to `frontend/out`, which the backend serves.

## Tests

```powershell
cd viewer\backend; .venv\Scripts\python.exe -m pytest      # 52 tests: storages (real FTP, SFTP + S3 servers), lines,
                                                           # results, API, and the built UI in headless Chrome
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
| `backend/nli_viewer/api.py` | FastAPI app |
| `backend/nli_viewer/cli.py` | command line |
| `frontend/app`, `frontend/components`, `frontend/lib` | Next.js pages, UI components, API client and types |
| `viewer_config.json` | datasets of this project (test_corpus) |
| `start_viewer.ps1`, `start_viewer.sh` | one-command start |

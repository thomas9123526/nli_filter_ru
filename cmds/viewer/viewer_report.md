# Result viewer: overnight report (2026-11-10)

A web UI (Next.js) with a Python backend (FastAPI) to pick any line of an `nli_filter.py` run and see its
decision next to the original corpus line. Nothing is decompressed by hand. Works with local disk, FTP and
S3/MinIO; every part is a separate, reusable module.

## Start

```powershell
cd D:\hkc\nli_filter2\viewer
.\start_viewer.ps1        # first start: creates the venv, installs packages, builds the UI
```

Open http://127.0.0.1:8000 (API docs: http://127.0.0.1:8000/docs).
The `dataset/test_corpus` / `dataset/out_test_corpus` pair is already configured in `viewer\viewer_config.json`.

## Pages

| Page | What it shows |
|---|---|
| Datasets | Each configured pair of output folder + corpus folder; an unreachable server is marked with the reason |
| Dataset | Totals, why lines were kept / filtered, accuracy (when lines have `expect`), models, thresholds, hypotheses, file list, search by line id |
| File | All decisions of one file; one-click filters (filtered, kept, each reason, wrong vs expected, decided by the judge), search, score range, sorting, paging |
| Record | Verdict + steps; original text with hits coloured, check-1 windows shaded, check-2 windows underlined; score tables (hypothesis, fast / judge / final vs threshold; click a row to jump to it); raw JSON. Keys: `j` next, `k` previous, `Esc` back |
| Tune thresholds | Move check-1 / check-2 thresholds and see which lines flip and how precision / recall change. Recomputed from stored scores, no model runs |

## Command line

```powershell
cd viewer\backend
.venv\Scripts\python.exe -m nli_viewer show   --config ..\viewer_config.json test_corpus books/part-00/shard-00000 --line 10
.venv\Scripts\python.exe -m nli_viewer find   --config ..\viewer_config.json test_corpus mixed-002
.venv\Scripts\python.exe -m nli_viewer verify --config ..\viewer_config.json test_corpus
```

Other commands: `datasets`, `files`, `decisions`, `index`, `check`. `verify` checks that every decision's
line exists, the ids match, and every hit's characters really contain its keyword.

## Tests

| What | Result |
|---|---|
| Viewer tests (storages with real local FTP + S3 servers, file formats, API, UI in headless Chrome) | 45 pass |
| New tests for `nli_filter.py` / `nli_models.py` (one loads ModernBERT for real) | 59 pass |
| `verify` on `dataset/out_test_corpus`, read from local disk, FTP and S3 | 568 / 568 consistent each |
| Scale: 100,000-line file | first open 1.4 s, then 10 ms per record |

## Fixed along the way

- `nli_filter.py`: a check-2 window cut from a long sentence lost the sentence's last words (found by the
  new tests).
- Viewer: record lookups 100x faster, index build 7x faster.
- Viewer: rewritten output files are picked up instead of showing old results.
- Long texts open scrolled to the part that decided the result.

## Notes

- `dataset/out_test_corpus` was regenerated: the earlier `--limit 60` run covered only 3 of 20 files. It now holds
  full results for all 20 files with the default ModernBERT + DeBERTa cascade
  (accuracy 0.930, precision 1.000, recall 0.851).
- S3 was tested with a local stand-in (moto), not a real MinIO server; FTPS was not tested.
- Thresholds on `dataset/test_corpus`: check 1 at 0.7 changes nothing; at 0.6 it adds 8 filtered lines, all the
  same false positive ("A Moscow mule is served...").
- Nothing is committed. Changes: `.gitignore`, `nli_filter.py`, `tests/`, `viewer/`, `cmds/`.

## More

- `viewer\README.md`: full guide (config, storage URIs, API, cache)
- `viewer\PLAN.md`: plan and status
- `cmds\viewer\viewer.md`, `cmds\testing\tests.md`: commands

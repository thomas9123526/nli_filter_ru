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

## Use

1. **Datasets** → pick one.
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

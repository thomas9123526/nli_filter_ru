# Running the tests

## nli_filter.py and nli_models.py

From the project folder, with the torch venv active (see `cmds/setup/00_setup.ps1`):

```powershell
cd D:\hkc\nli_filter2
python -m pytest tests                 # 59 tests, ~15 s on CPU
python -m pytest tests -m "not slow"   # without the test that loads ModernBERT
```

| File | Covers |
|---|---|
| `tests/test_nli_filter.py` | keyword matching (both engines, word boundaries, CJK, exclusions), the trie regex, the cheap rules, windows, every decision reason, judge band, runner outputs (`.jsonl/.gz/.zip/.zst`, split files), threads, resume and `--limit` partial files, `--shard` summaries, `--report`, CLI errors |
| `tests/test_nli_models.py` | model registry, devices, batch planning, readers (every format, blank / bad lines), atomic writers; slow: ModernBERT scores and `NLIPool` thread mode |
| `tests/test_remote_input.py` | corpus input from local FTP / SFTP / S3 test servers: results identical to local input, folders / one file / `*` and `**` patterns, streaming reader, resume downloads only missing files, retry and failed downloads, passwords hidden, password from an environment variable |

Most tests use a fake scorer instead of the models, so they run anywhere. `.zst` tests need `zstandard`
(skipped otherwise); the slow test needs `models/ModernBERT-large-zeroshot-v2.0`.

`tests/test_remote_input.py` needs the test servers (`pyftpdlib`, `paramiko`, `moto`, `boto3`) and is skipped
without them. They are in the viewer's venv, which can run the project tests too (no torch needed):

```powershell
cd D:\hkc\nli_filter2
viewer\backend\.venv\Scripts\python.exe -m pytest tests -m "not slow"   # 67 tests incl. 13 server tests
```

## Viewer

```powershell
cd D:\hkc\nli_filter2\viewer\backend
.venv\Scripts\python.exe -m pytest              # 52 tests incl. local FTP / SFTP / S3 servers and the UI in headless Chrome
.venv\Scripts\python.exe -m pytest -k "not ui"  # without the browser test (~30 s)
cd ..\frontend; npm run typecheck; npm run build
```

## Data checks

```powershell
cd D:\hkc\nli_filter2\viewer\backend
.venv\Scripts\python.exe -m nli_viewer verify --config ..\viewer_config.json test_corpus
```

`verify` opens every decision of a run next to its corpus line: the line exists, the ids match, and every
keyword hit's character span contains the keyword. Run it after a large filter run.

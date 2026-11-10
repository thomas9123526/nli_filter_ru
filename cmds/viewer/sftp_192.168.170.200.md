# Filter and view test_corpus on the SFTP server 192.168.170.200

| | |
|---|---|
| Server | `sftp://192.168.170.200` (port 22), user `download` |
| Corpus | `/mnt/disk1/HKC_123/nli_filter2/test_corpus` |
| Results | written to the PC: `D:\hkc\sftp_run\out_test_corpus` |

The password is not written here: it goes into the `SFTP_PASSWORD` environment variable (step 2), and the
commands read it from there.

`nli_filter.py` reads the corpus straight from the server (each file is downloaded while the previous one
is filtered, then deleted) and writes the results locally. The viewer reads the corpus over SFTP and the
results from the PC. General guide: `cmds\setup\remote_corpus.md`.

## 1. Install paramiko in the filter venv (once)

```powershell
cd D:\hkc\nli_filter2
D:\hkc\nli_country_filter\.venv\Scripts\Activate.ps1
pip install --no-index --find-links D:\hkc\nli_filter2\pkgs\rtx5090-windows-py310 paramiko
```

## 2. Filter the corpus from the server

```powershell
$env:SFTP_PASSWORD = "PASSWORD"
python .\nli_filter.py 'sftp://download:${SFTP_PASSWORD}@192.168.170.200/mnt/disk1/HKC_123/nli_filter2/test_corpus' --device cpu --write-split --output-dir D:\hkc\sftp_run\out_test_corpus
```

- Single quotes, so PowerShell passes `${SFTP_PASSWORD}` on; `nli_filter.py` fills it in.
- `test_corpus` is the Russia test corpus; Russia is the default, so no `--country` is needed.
- The default models (ModernBERT + DeBERTa judge) take several minutes on CPU; add `--judge-model none` for a
  quicker run.
- The first log line says how many files were found; the summary at the end should show 20 files.
- A warning about the server's host key on the first connection is normal (the PC has not seen this server
  before).
- If a download fails three times the file is marked `failed` and the run goes on; run the same command
  again and only the missing files are downloaded.

## 3. Viewer config

Add to the `"datasets"` list in `viewer\viewer_config.json` (comma after the previous entry's `}`):

```json
    {
      "name": "sftp_test_corpus",
      "title": "Test corpus on SFTP (192.168.170.200)",
      "corpus": "sftp://download@192.168.170.200/mnt/disk1/HKC_123/nli_filter2/test_corpus",
      "output": "D:/hkc/sftp_run/out_test_corpus",
      "corpus_options": {"password": "${SFTP_PASSWORD}"}
    }
```

## 4. Check, then start the viewer (same PowerShell window as step 2)

```powershell
cd D:\hkc\nli_filter2\viewer\backend
.venv\Scripts\python.exe -m nli_viewer check  --config ..\viewer_config.json
.venv\Scripts\python.exe -m nli_viewer verify --config ..\viewer_config.json sftp_test_corpus
cd ..
.\start_viewer.ps1
```

1. `check`: `sftp_test_corpus` is listed as reachable.
2. `verify`: every line is read over SFTP; all should be consistent.
3. Open http://127.0.0.1:8000 and pick "Test corpus on SFTP".

## Alternative: copy with rclone first

For very long runs a local copy is the most robust; see `cmds\setup\remote_corpus.md` ("Alternative: copy
(or mount) with rclone"), with `user=download`.

## If nli_filter2 is installed on the server itself

Filter there with local paths, then use the server folder as both `corpus` and `output` in the viewer:

```bash
ssh download@192.168.170.200
cd /mnt/disk1/HKC_123/nli_filter2
python nli_filter.py test_corpus --write-split --output-dir out_test_corpus
```

(`download` needs write access to that folder for this.)

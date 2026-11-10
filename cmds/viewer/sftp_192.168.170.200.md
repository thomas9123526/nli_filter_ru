# Filter and view test_corpus on the SFTP server 192.168.170.200

| | |
|---|---|
| Server | `sftp://192.168.170.200` (port 22), user `root` |
| Corpus | `/mnt/disk1/HKC_123/nli_filter2/test_corpus` |
| Output | `/mnt/disk1/HKC_123/nli_filter2/out_test_corpus` |

The password is not written here: replace `PASSWORD` below, or keep it in the `SFTP_PASSWORD` environment
variable.

`nli_filter.py` reads local files only, so the corpus is copied to the PC with rclone, filtered, and the
results uploaded. The viewer then reads both over SFTP. General guide: `cmds\setup\remote_corpus.md`.

## 1. Install rclone (once)

Download `rclone-...-windows-amd64.zip` from https://rclone.org/downloads/ and unzip `rclone.exe` to
`D:\hkc\tools`. Then:

```powershell
$env:Path += ";D:\hkc\tools"
rclone config create hkc sftp host=192.168.170.200 user=root pass=PASSWORD
rclone lsd hkc:/mnt/disk1/HKC_123/nli_filter2          # should list test_corpus and out_test_corpus
```

## 2. Copy the corpus, filter it, upload the results

`D:\hkc\sftp_run` keeps this run apart from the local `test_corpus` / `out_test_corpus`.

```powershell
rclone copy hkc:/mnt/disk1/HKC_123/nli_filter2/test_corpus D:\hkc\sftp_run\test_corpus --progress

cd D:\hkc\nli_filter2
D:\hkc\nli_country_filter\.venv\Scripts\Activate.ps1
python .\nli_filter.py D:\hkc\sftp_run\test_corpus --device cpu --write-split --output-dir D:\hkc\sftp_run\out_test_corpus

rclone ls   hkc:/mnt/disk1/HKC_123/nli_filter2/out_test_corpus      # what is already there
rclone copy D:\hkc\sftp_run\out_test_corpus hkc:/mnt/disk1/HKC_123/nli_filter2/out_test_corpus --progress
```

- `test_corpus` is the Russia test corpus; Russia is the default, so no `--country` is needed.
- The default models (ModernBERT + DeBERTa judge) take several minutes on CPU; add `--judge-model none`
  for a quicker run.
- `rclone copy` **replaces** files that already exist in the server's `out_test_corpus`.

## 3. Viewer config

Add to the `"datasets"` list in `viewer\viewer_config.json` (comma after the previous entry's `}`):

```json
    {
      "name": "sftp_test_corpus",
      "title": "Test corpus on SFTP (192.168.170.200)",
      "corpus": "sftp://root@192.168.170.200/mnt/disk1/HKC_123/nli_filter2/test_corpus",
      "output": "sftp://root@192.168.170.200/mnt/disk1/HKC_123/nli_filter2/out_test_corpus",
      "corpus_options": {"password": "${SFTP_PASSWORD}"},
      "output_options": {"password": "${SFTP_PASSWORD}"}
    }
```

## 4. Check, then start the viewer (same PowerShell window)

```powershell
$env:SFTP_PASSWORD = "PASSWORD"
cd D:\hkc\nli_filter2\viewer\backend
.venv\Scripts\python.exe -m nli_viewer check  --config ..\viewer_config.json
.venv\Scripts\python.exe -m nli_viewer verify --config ..\viewer_config.json sftp_test_corpus
cd ..
.\start_viewer.ps1
```

1. `check`: `sftp_test_corpus` is listed as reachable.
2. `verify`: every line is read over SFTP; all should be consistent.
3. Open http://127.0.0.1:8000 and pick "Test corpus on SFTP".

## If nli_filter2 is installed on the server itself

Skip both `rclone copy` commands and filter there:

```bash
ssh root@192.168.170.200
cd /mnt/disk1/HKC_123/nli_filter2
python nli_filter.py test_corpus --write-split --output-dir out_test_corpus
```

Then steps 3 and 4 on the PC.

## Security

This is the root login. For the viewer (read-only) a separate read-only user on the server is safer.

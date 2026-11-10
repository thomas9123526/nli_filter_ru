# Run nli_filter.py on test_corpus from the SFTP server

| | |
|---|---|
| Source | `sftp://192.168.170.200/mnt/disk1/HKC_123/nli_filter2/test_corpus`, user `download` |
| Results | `D:\hkc\sftp_run\out_test_corpus` (on this PC) |

The password is not written here: replace `PASSWORD` below.

## 1. Install paramiko in the filter venv (once, from the wheels in pkgs)

```powershell
cd D:\hkc\nli_filter2
D:\hkc\nli_country_filter\.venv\Scripts\Activate.ps1
pip install --no-index --find-links D:\hkc\nli_filter2\pkgs\rtx5090-windows-py310 paramiko
```

`rtx5090-windows-py310` = the wheels for this PC's Python 3.10.

## 2. Run the filter

```powershell
$env:SFTP_PASSWORD = "PASSWORD"
python .\nli_filter.py 'sftp://download:${SFTP_PASSWORD}@192.168.170.200/mnt/disk1/HKC_123/nli_filter2/test_corpus' --device cpu --write-split --output-dir D:\hkc\sftp_run\out_test_corpus
```

- **Single quotes:** they keep PowerShell from replacing `${SFTP_PASSWORD}` itself; `nli_filter.py` fills
  it in. The password can also go straight into the URL: `'sftp://download:PASSWORD@192.168.170.200/...'`.
- **Country:** none given, so the default, Russia (`test_corpus` is the Russia test corpus).
- **Quicker run:** add `--judge-model none` to use only ModernBERT.
- **Host-key warning:** a warning about the server's key on the first connection is normal.
- **Result:** the summary at the end should show 20 files.

## How the files are read

One file at a time is downloaded to `D:\hkc\sftp_run\out_test_corpus\.download`, filtered, and deleted,
while the next file downloads. Failed downloads are retried 3 times (`--retries`); a file that still fails
is marked `failed` and the run goes on. Running the same command again skips finished files.

## Next: view the result

Viewer config and start: `cmds\viewer\sftp_192.168.170.200.md` (steps 3 and 4). General guide for server
input: `cmds\setup\remote_corpus.md`.

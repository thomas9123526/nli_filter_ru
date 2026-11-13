# Moving nli_filter2 to a new machine (torch + CUDA already installed)

Copying `nli_filter2` with `pkgs` is enough; nothing from `D:\hkc\nli_country_filter` is needed. No code
refers to that folder; only the docs mention it, as the path of the current venv.

## Checked (2026-11-10)

For each of the four `pkgs` folders, pip was given only that folder plus the packages a torch environment
normally has, without internet (`--no-index`). All four resolve completely (47 packages each, including SFTP
and S3 support).

## What to copy

| What | Size | Note |
|---|---|---|
| `nli_filter2\` (code, `cmds`, `tests`) | small | |
| `nli_filter2\models\` | 11 GB | **in `.gitignore`**: a git clone does not include it, copy the folder itself |
| `nli_filter2\pkgs\<the folder for that machine>` | about 50 MB | must match the new machine (below); the other folders and the rclone zips only if you use them |

| `pkgs` folder | Machine |
|---|---|
| `rtx5090-windows-py310` | Windows, Python 3.10 |
| `windows-py312` | Windows, Python 3.12 |
| `rtx5090-ubuntu-py310` | Ubuntu, Python 3.10 |
| `h200-ubuntu-py312` | Ubuntu, Python 3.12 |

## On the new machine

```powershell
python pkgs\check_missing.py          # shows what is really missing in that environment
pip install --no-index --find-links pkgs\<machine folder> transformers==5.20.2 orjson pyahocorasick zstandard sentencepiece protobuf paramiko
python .\nli_models.py --check modernbert    # loads a model on the new machine: the real test
```

Add `boto3` to the `pip install` line only if you read from S3 or MinIO. Linux: `pkgs/<machine folder>` with
forward slashes.

## Conditions

1. **The machine must already have** torch with CUDA, plus `numpy`, `filelock`, `fsspec`, `jinja2`,
   `markupsafe`, `networkx`, `sympy`, `mpmath`, `typing_extensions` and `setuptools`. A normal torch install
   brings all of these. If `check_missing.py` lists any of them, pip stops with "No matching distribution
   found": that wheel then has to come from another source, because these are not in `pkgs`.
2. **A very old torch** might not suit transformers 5.20.2; `nli_models.py --check modernbert` shows that
   straight away.
3. **The viewer** (and its tests) has its own venv; its wheels are in the same `pkgs\<machine>` folders since
   2026-11-13 (list: VIEWER section at the end of `pkgs\whl_files_need.txt`). First start offline:
   `.\start_viewer.ps1 -Wheels ..\pkgs\<machine folder>`, or by hand in `viewer\backend`:
   `python -m venv .venv` then `.venv\Scripts\python -m pip install --no-index --find-links ..\..\pkgs\<machine folder> -r requirements.txt`.
   Checked 2026-11-13: fresh Python 3.10 and 3.12 venvs installed only from `pkgs` pass all 52 viewer tests and
   the 13 server-input tests. Keep the project path short on Windows (see `cmds\viewer\move_viewer.md`).
   Moving the viewer: `cmds\viewer\move_viewer.md`.

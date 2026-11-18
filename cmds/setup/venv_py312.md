# A `.venv` for this project on Windows + Python 3.12 (offline, from `pkgs`)

How to create a venv in the project folder and install everything from the wheels in `pkgs`, without internet.
Run every command in PowerShell from the project folder:

```powershell
cd D:\hkc\nli_filter2
```

Wheels used (this PC: Windows, Python 3.12):

| Folder | What it gives |
|---|---|
| `pkgs\windows-py312` | transformers, tokenizers, safetensors, sentencepiece, protobuf, pyarrow, zstandard, orjson, pyahocorasick, pytest, ... |
| `pkgs\p2000-windows-torch-cu126` | torch 2.11.0+cu126 and numpy (not in `windows-py312`) |

The cu126 torch wheel also runs on a PC without an NVIDIA GPU (CPU only).

## 1. Create and activate the venv

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks the activation script, allow local scripts once and activate again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## 2. Install offline from the wheels

```powershell
python -m pip install --no-index --find-links pkgs\windows-py312 --find-links pkgs\p2000-windows-torch-cu126 torch numpy transformers tokenizers safetensors sentencepiece protobuf pyarrow zstandard orjson pyahocorasick tqdm pyyaml regex truststore pytest
```

`--no-index` means pip never goes online: a missing wheel gives a clear error instead of a download.

### Is it really offline?

Yes. The install commands here only use the two `pkgs` folders:

- `--no-index` turns off PyPI and every other index, including an `index-url` / `extra-index-url` set in
  `pip.ini` or in environment variables.
- `--find-links pkgs\...` makes the local folders the only place pip looks for wheels.
- A missing wheel stops pip with `No matching distribution found for X`, and nothing is installed. pip never falls
  back to the internet.

`--find-links` adds to any `find-links` already in your pip configuration rather than replacing it. Check that
none of them is a web address:

```powershell
python -m pip config list
```

If no `find-links` line is printed, only `pkgs` is used.

To see what would be installed and from where, without changing anything, add `--dry-run`:

```powershell
python -m pip install --dry-run --no-index --find-links pkgs\windows-py312 --find-links pkgs\p2000-windows-torch-cu126 torch numpy transformers tokenizers safetensors sentencepiece protobuf pyarrow zstandard orjson pyahocorasick tqdm pyyaml regex truststore pytest
```

### Only pytest

To add just pytest (e.g. to a venv that already has torch and transformers):

```powershell
python -m pip install --no-index --find-links pkgs\windows-py312 pytest
python -m pytest --version
```

Its dependencies (iniconfig, pluggy, packaging, colorama) are in `pkgs\windows-py312` too.

### Everything in one command (project + viewer + tests)

There is no install script in the project; this one command installs everything this PC needs (filter, models,
tests, SFTP / S3 corpus input, and the viewer with its tests):

```powershell
python -m pip install --no-index --find-links pkgs\windows-py312 --find-links pkgs\p2000-windows-torch-cu126 torch numpy transformers tokenizers safetensors sentencepiece protobuf pyarrow zstandard orjson pyahocorasick tqdm pyyaml regex truststore pytest paramiko boto3 -r viewer\backend\requirements.txt
```

Leave out `paramiko boto3 -r viewer\backend\requirements.txt` when the viewer and server corpora are not needed.

Do not install every `.whl` file in the folder (`pip install pkgs\windows-py312\*.whl`): the folder holds two
versions of some packages (e.g. `annotated_doc` 0.0.5 and 0.0.6) and pip stops with a conflict. Naming the
packages lets pip pick the right versions.

Other files about installing (not for this PC as they are):

| File | What it is |
|---|---|
| `cmds\setup\00_setup.ps1` | Reference commands to copy (starts with `return`); points to the old venv in `D:\hkc\nli_country_filter` |
| `pkgs\whl_files_need.txt` | Which wheels to copy to a machine that already has torch: a copy list, not a pip requirements file |
| `cmds\setup\offline_wheels.md`, `cmds\setup\wheels_check.md` | Install commands for the Python 3.10 (RTX 5090) wheel folders |

Check the active Python and torch after installing:

```powershell
python -c "import sys, torch; print(sys.executable, torch.__version__)"
```

Expect `...\nli_filter2\.venv\Scripts\python.exe 2.11.0+cu126`.

## 3. Check nothing is missing

```powershell
python pkgs\check_missing.py
```

## 4. Run the tests

```powershell
python -m pytest tests -m "not slow" -q     # fast tests, no model needed
python -m pytest tests -q                   # + slow tests (load the real models in .\models)
python smoke_test.py --lines 20             # short end-to-end check
```

More on the test suites: `cmds\testing\tests.md`.

## Optional: corpus on a server (SFTP / S3)

Only needed when `nli_filter.py` reads its input from a server. Local files and `ftp://` / `ftps://` need nothing
extra. Every wheel is in `pkgs\windows-py312`. Run with `.venv` activated:

```powershell
# sftp:// only (paramiko, bcrypt, cryptography, invoke, pynacl, cffi, pycparser)
python -m pip install --no-index --find-links pkgs\windows-py312 paramiko

# s3:// / minio:// only (boto3, botocore, jmespath, s3transfer, python-dateutil, six, urllib3)
python -m pip install --no-index --find-links pkgs\windows-py312 boto3

# both
python -m pip install --no-index --find-links pkgs\windows-py312 paramiko boto3
```

`tests\test_remote_input.py` is skipped unless `pyftpdlib`, `paramiko`, `moto` and `boto3` are all installed.
`moto[server]` also brings flask and werkzeug for its local S3 server. To run that test:

```powershell
python -m pip install --no-index --find-links pkgs\windows-py312 paramiko boto3 pyftpdlib "moto[server]"
python -m pytest tests\test_remote_input.py -v
```

More on server corpora: `cmds\setup\remote_corpus.md`.

## Optional: the result viewer's own venv

The viewer (`viewer\backend`) has its own venv and needs no torch:

```powershell
cd viewer\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --no-index --find-links ..\..\pkgs\windows-py312 -r requirements.txt
```

## Note: git

`.gitignore` only ignores `viewer/backend/.venv/`. Add a line `.venv/` to `.gitignore` so the project's venv is not committed.

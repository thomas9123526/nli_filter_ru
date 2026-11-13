# Are the wheels in `pkgs` enough for another computer?

Yes, for a computer that already has **torch >= 2.6** (with CUDA) in Python 3.10 or 3.12, e.g. an Anaconda env.

Checked 2026-11-13 by resolving every requirement offline with `uv pip compile --no-index --find-links
pkgs\<folder>`, for the folder's own OS and Python, with the torch packages (torch, numpy, filelock, fsspec,
...) taken as already installed.

| Folder | For | Filter scripts | sftp / S3 | Viewer + its tests | All in one env |
|---|---|---|---|---|---|
| `rtx5090-windows-py310` | Windows, Python 3.10 | OK | OK | OK | OK |
| `windows-py312` | Windows, Python 3.12 | OK | OK | OK | OK |
| `rtx5090-ubuntu-py310` | Ubuntu, Python 3.10 | OK | OK | OK | OK |
| `h200-ubuntu-py312` | Ubuntu, Python 3.12 | OK | OK | OK | OK |

- "Filter scripts" = `transformers==5.20.2 orjson pyahocorasick zstandard sentencepiece protobuf pyarrow`.
- "sftp / S3" = `paramiko boto3`.
- "Viewer + its tests" = `viewer\backend\requirements.txt`.
- The names rtx5090 / h200 do not matter: none of these wheels depend on the GPU.
- `p2000-windows-torch-cu126` holds only torch and its packages; not needed when torch is installed.

## What the existing environment must have

- **torch >= 2.6**: `transformers 5.20.2` refuses older ones. Check:
  `python -c "import torch; print(torch.__version__)"`
- **numpy, filelock, fsspec**: come with every torch install; they are not in the folders.

## Not covered

- Python 3.11 / 3.13, macOS, ARM Linux.
- Linux older than Ubuntu 20.04 (pyarrow needs glibc 2.28).
- Not wheels: the `models` folder, and `viewer\frontend\out` (the built web pages; copy it if the other
  computer has no Node.js).

## Install into the conda env

Windows, Python 3.10 (change the folder for the other cases):

```powershell
conda activate <env>
python -m pip install --no-index --find-links pkgs\rtx5090-windows-py310 transformers==5.20.2 orjson pyahocorasick zstandard sentencepiece protobuf pyarrow paramiko boto3 -r viewer\backend\requirements.txt
python pkgs\check_missing.py
```

pip upgrades a few packages conda installed (`typing_extensions` to 4.16, `packaging`, `pyyaml`, ...): normal.
Only the resolution was checked, not a real install on another machine; `check_missing.py` confirms it.

See also `offline_wheels.md`, `new_machine.md`, `pycharm.md`.

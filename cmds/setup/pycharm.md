# PyCharm: `nli_viewer` imports shown as errors

## Problem

Opening the project in PyCharm, the files in `viewer\backend\tests` show errors at `nli_viewer.api`,
`nli_viewer.config`, etc.

## Why

`nli_viewer` is this project's own code in `viewer\backend\nli_viewer`, not a package, so no wheel in
`pkgs` provides it. PyCharm looks in the project root (`nli_filter2`) and in the interpreter's installed
packages; `nli_viewer` is one level lower, so it is not found.

## Fix

In the Project panel: right-click `viewer\backend` -> **Mark Directory as -> Sources Root** (the folder
turns blue). Imports resolve, and running / debugging tests from PyCharm finds `nli_viewer` too.

If `fastapi`, `uvicorn`, `httpx` etc. are still red, the viewer packages are not installed in the conda env
yet. Install them from the wheel folder for the machine (see `offline_wheels.md`):

```powershell
python -m pip install --no-index --find-links pkgs\<wheel folder> -r viewer\backend\requirements.txt
```

## Effect on the `nli_filter.py` run configuration

None in practice. With **Add source roots to PYTHONPATH** (on by default), `viewer\backend` is added to the
import path of every run configuration, but:
- the script's own folder (project root) is searched first, so `nli_filter.py`, `nli_models.py`,
  `nli_storage.py` load as before;
- `viewer\backend` adds only the package `nli_viewer`, which `nli_filter.py` never imports;
- working directory, arguments, interpreter and environment variables are unchanged.

To keep it exactly as before: untick **Add source roots to PYTHONPATH** in the `nli_filter.py` run
configuration, and leave it ticked for the tests.

## Without PyCharm

Run the viewer tests from `viewer\backend` with `python -m pytest` (the `-m` form adds the current folder to
the path; plain `pytest` does not).

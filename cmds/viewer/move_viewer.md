# Moving the viewer to another computer

Notes from 2026-11-10. The viewer works on another computer as long as you leave out its Python environment
(`viewer\backend\.venv`) when you copy it.

## Why a straight copy fails

`viewer\backend\.venv` is tied to the Python install of the PC that made it (here
`C:\Users\ThinkVision\AppData\Local\Programs\Python\Python312`). On another PC, `start_viewer.ps1` sees
`.venv\Scripts\python.exe` and assumes the environment is ready. That `python.exe` then fails with an error like
"No Python at C:\Users\ThinkVision\...".

## What to copy

| Copy? | Folder | Size | Why |
|---|---|---|---|
| Yes | `viewer\` without the three below | small | The program and `viewer_config.json` |
| Yes | `nli_storage.py` and `nli_formats.py` (project root) | small | The viewer's file access (local / FTP / SFTP / S3) and file formats (.rar / .parquet). Keep them in the folder above `viewer\`, as in the project |
| Yes | `viewer\frontend\out` | 1 MB | The built web pages. With it, the new PC doesn't need Node.js. |
| No | `viewer\backend\.venv` | 324 MB | Only works on the PC that made it. The script makes a new one on first start. |
| No | `viewer\frontend\node_modules` | 351 MB | Only needed to rebuild the web pages |
| Optional | `viewer\.viewer_cache` | 1.5 MB | Safe to leave out; it gets rebuilt |
| Optional | `viewer\.viewer_edits` | small | Only if you edited corpus text in the viewer: backups of the original files and the edit log (needed for Undo) |
| Yes | The corpus and output folders | as large as they are | Keep them in the same place relative to `viewer\` (for example `test_corpus_de` and `out_test_corpus_de` next to `viewer`), or edit the paths in `viewer_config.json` |

`viewer\frontend\out` is in `.gitignore`, so a git clone does not include it: copy it by hand.

## What the new PC needs

- Windows 10 or 11 with Python 3.10+ from python.org, so the `py` launcher is installed.
- The backend packages: from the internet on the first start, or offline from `pkgs` (since 2026-11-13 the
  viewer's wheels, also those for its tests, are in each `pkgs\<machine>` folder):
  `.\start_viewer.ps1 -Wheels ..\pkgs\windows-py312` (Linux: `WHEELS=../pkgs/h200-ubuntu-py312 ./start_viewer.sh`).
  Pick the folder for the PC's Windows/Linux and Python version; list: end of `pkgs\whl_files_need.txt`.
- A short project path, e.g. `D:\nli_filter2`: a test package (cfn-lint, part of moto) has very long file
  names, and a deep path hits Windows' 260-character limit ("No such file or directory ... cfnlint"). The
  start script then removes the half-made `.venv` and says so; or enable long paths
  (https://pip.pypa.io/warnings/enable-long-paths).
- The script-blocking fix from `cmds\viewer\check_results.md` if Windows won't run `.ps1` files.

## Start on the new PC

```powershell
cd <project folder>\viewer
.\start_viewer.ps1
```

If `.venv` was copied by mistake, delete `viewer\backend\.venv` on the new PC and run `.\start_viewer.ps1` again.

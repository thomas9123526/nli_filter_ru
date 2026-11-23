# `py -3.12`, `python` and a venv: which Python runs the project

## What `py -3.12` is

`py` is the **Python launcher for Windows** (`py.exe`). The installer from python.org puts it into `C:\Windows\`. It
does not contain Python itself; it finds the installed Pythons and starts the one you ask for:

```powershell
py -0            # list the installed Pythons
py -3.12 x.py    # run x.py with Python 3.12
py x.py          # run it with the newest installed Python
```

On the development PC, `py -0` shows:

```
 -V:3.12 *   Python 3.12 (64-bit)
 -V:3.10     Python 3.10 (64-bit)
```

## Why the commands in some notes use `py -3.12`

That PC has two Pythons, and plain `python` starts **3.10**, which has no `pytest` (hence `No module named pytest`).
The packages the project needs (pytest, torch, transformers, zstandard) are installed in **3.12**. `py -3.12` picks
the right one without changing PATH. It is a shortcut for that PC, not the project's standard way.

## Does it work on another computer?

| Computer | `py -3.12` works? | Use instead |
|---|---|---|
| Windows, Python 3.12 from python.org | yes | – |
| Windows without Python 3.12 | no ("No suitable Python runtime found") | install 3.12, or `py -3.10` if the packages are in that one |
| Windows, Python from the Microsoft Store or Anaconda | usually no `py` launcher | `python` |
| **Linux / Ubuntu (the H200 machine)** | **no**: `py` does not exist there | `python3`, or the venv's `python` |

So it is not a general solution: a Windows convenience that depends on what is installed.

## What works everywhere: a virtual environment (venv)

A venv is created once with the right Python. After activating it, plain `python` is always that Python with the
project's packages, on every machine. This is why the notes in `cmds\` mostly write `python …`.

```powershell
# Windows, once (in D:\hkc\nli_filter2): see cmds\setup\venv_py312.md for the offline install
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install --no-index --find-links pkgs\windows-py312 ...     # the package list in venv_py312.md

# every time after that
.venv\Scripts\Activate.ps1
python nli_label.py run ...
python -m pytest tests
```

```bash
# Linux / the H200 machine: see cmds/h200/linux_h200.md
source /path/to/venv/bin/activate
python nli_label.py run ...
```

Without activating, call the venv's Python directly: `.venv\Scripts\python.exe nli_label.py …` (Windows) or
`/path/to/venv/bin/python nli_label.py …` (Linux).

## Quick check: which Python runs, and does it have the packages?

```powershell
python -c "import sys; print(sys.executable, sys.version)"
python pkgs\check_missing.py        # lists missing packages (prints "(nothing missing)" when all are there)
```

## Related

- `cmds\setup\venv_py312.md`: create `.venv` with Python 3.12 and install offline from `pkgs\`
- `cmds\h200\linux_h200.md`: the environment on the H200 machine
- `cmds\setup\offline_wheels.md`, `cmds\setup\wheels_check.md`: which wheels each machine needs

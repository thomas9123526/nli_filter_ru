# Setup: run these once per terminal (PowerShell), from D:\hkc\nli_filter2.
# Reference file: copy the command you need. The `return` below stops the file if it is run as a whole.
return

cd D:\hkc\nli_filter2

# Allow local scripts so the venv can be activated (once per user account; no admin needed)
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
# ...or only for this terminal
Set-ExecutionPolicy -Scope Process Bypass

# Activate the venv with torch + transformers (prompt then starts with "(.venv)")
D:\hkc\nli_country_filter\.venv\Scripts\Activate.ps1
# cmd.exe instead of PowerShell
#   D:\hkc\nli_country_filter\.venv\Scripts\activate.bat

# Check that the right Python is active (expect ...\.venv\Scripts\python.exe 2.11.0+cu128)
python -c "import sys, torch; print(sys.executable, torch.__version__)"

# Needed for .zst input/output
python -m pip install zstandard

# Without activating: call the venv Python by its full path, e.g.
D:\hkc\nli_country_filter\.venv\Scripts\python.exe .\nli_filter.py --device cpu --chunk-lines 16

# Help for every option
python .\nli_filter.py --help
python .\nli_models.py --help

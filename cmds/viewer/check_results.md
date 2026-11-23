# Check a filter result in the viewer, and running the viewer on Windows

Notes from 2026-11-10. Run commands from `D:\hkc\nli_filter2` unless a `cd` says otherwise.
These notes come from reading the script and the docs; the viewer was not started for them.

## 1. Check a filter result

1. **Run the filter**, for example:
   ```powershell
   python .\nli_filter.py dataset/test_corpus_de --country Germany --country-adj German --judge-model none --device cpu --output-dir dataset/out_test_corpus_de
   ```
2. **Add the run to `viewer\viewer_config.json`.** Each entry pairs a corpus folder with the output folder made
   from it (paths are relative to the config file). The config already pairs `dataset/test_corpus_de` with
   `dataset/out_test_corpus_de`. For a new run, add an entry inside `"datasets"` (comma after the previous `}`):
   ```json
   {"name": "de_run2", "title": "Germany, run 2", "corpus": "../my_corpus", "output": "../out_my_run"}
   ```
   Restart the viewer after editing the config.
3. **Start the viewer** and open http://127.0.0.1:8000:
   ```powershell
   cd D:\hkc\nli_filter2\viewer
   .\start_viewer.ps1
   ```
4. **What to look at:**
   - **Dataset page:** totals, reasons, and accuracy. Accuracy only appears for test data made by
     `make_test_corpus.py`, because those lines carry the expected answer.
   - **"Wrong vs expected":** the lines where the filter disagreed with the expected answer. Read these first.
   - **"Decided by judge":** the uncertain lines that the second model decided.
   - **Record page:** the original text with keyword hits highlighted and the model scores.
     `j` / `k` = next / previous, `Esc` = back to the list.
   - **Tune thresholds:** move the check-1 and check-2 thresholds and see which lines would flip, without
     rerunning the models. Use the values you settle on as `--check1-threshold` / `--check2-threshold` in the
     next `nli_filter.py` run.
5. **Integrity check from the terminal:** every decision should match its original line, and every keyword
   position should really hold the keyword:
   ```powershell
   cd D:\hkc\nli_filter2\viewer\backend
   .venv\Scripts\python.exe -m nli_viewer verify --config ..\viewer_config.json test_corpus
   ```
   Use the dataset's `name` from the config in place of `test_corpus`.

More: `cmds\testing\germany_test.md` (step by step), `cmds\viewer\viewer.md`, `viewer\README.md`.

## 2. Does `start_viewer.ps1` work on a normal Windows PC?

**Windows 10 and 11: yes.** The script only uses PowerShell 5.1 features, which are built into both.
Windows 7/8: no, because the viewer needs Python 3.10+ and Python 3.10 does not support Windows 7.

On a fresh Windows 10/11 machine you may hit these:

| Problem | Why | Fix |
|---|---|---|
| "running scripts is disabled on this system" | Windows 10/11 block `.ps1` scripts by default | `powershell -ExecutionPolicy Bypass -File .\start_viewer.ps1`, or once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| Script copied from a zip or download still blocked | Windows marks downloaded files | `Unblock-File .\start_viewer.ps1` |
| `py` not found | The script calls the `py` launcher. The python.org installer includes it; Microsoft Store Python and conda do not. | Install Python 3.10+ from python.org, or give the Python to use: `.\start_viewer.ps1 -Python C:\path\to\python.exe` (first run only; delete `viewer\backend\.venv` to switch) |
| First start needs internet | It installs fastapi, uvicorn and the other backend packages with pip. `viewer\backend\requirements.txt` also lists test-only packages (pytest, moto). | Run the first start on a machine with internet, or prepare an offline wheel folder like the one for the filter (`cmds\setup\offline_wheels.md`) |
| Web pages missing ("npm not found") | `viewer\frontend\out` is in `.gitignore`, so a git clone does not include it, and building it needs Node.js | Copy `viewer\frontend\out` from a PC where it is already built |
| First start failed partway | If pip fails, the script carries on, and the next start skips the install because `backend\.venv` already exists | Delete `viewer\backend\.venv` and run the script again |
| `-Public` | Windows Firewall asks to allow Python | Allow it on private networks |

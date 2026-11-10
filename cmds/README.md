# cmds: commands and notes

| Folder | File | What it is |
|---|---|---|
| `setup/` | `00_setup.ps1` | Create the venv, install packages, execution-policy fix |
| | `01_nli_models.ps1` | `nli_models.py` commands (list, check, score) |
| | `02_nli_filter.ps1` | `nli_filter.py` commands |
| | `windows.md` | Summary of the three scripts above |
| `h200/` | `linux_h200.md` | Running on the 8 x H200 Ubuntu machine (`run_shards.sh`) |
| | `h200_readiness.md` | Review of the scripts for multi-GPU runs |
| `testing/` | `test_corpus.md` | Make and filter `test_corpus` (`make_test_corpus.py`) |
| | `tests.md` | Run the pytest suites |
| `viewer/` | `viewer.md` | Start and use the result viewer |
| | `viewer_report.md` | Overnight report: what the viewer does, tests, fixes |
| `explain/` | `models.md` | Which model runs when (fast, judge, bge-m3) |
| | `long_texts.md` | How long texts are cut into windows |
| | `chunk_lines.md` | What `--chunk-lines` means |

Run every command from the project folder `D:\hkc\nli_filter2`, not from `cmds`.

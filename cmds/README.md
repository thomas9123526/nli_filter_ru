# cmds: commands and notes

| Folder | File | What it is |
|---|---|---|
| `setup/` | `00_setup.ps1` | Create the venv, install packages, execution-policy fix |
| | `01_nli_models.ps1` | `nli_models.py` commands (list, check, score) |
| | `02_nli_filter.ps1` | `nli_filter.py` commands |
| | `windows.md` | Summary of the three scripts above |
| | `single_model.md` | Use one model on its own (filter without the judge, or score text directly) |
| | `country_hypotheses.md` | Change or add countries, keywords, hypotheses, language names, labels |
| | `snapshot_changes.md` | Remember the project's files; later copy only the changed ones (folder tree kept, no git) |
| | `p2000.md` | The P2000 machine: driver, offline install with `pkgs\p2000-windows-torch-cu126`, running with fp32 |
| | `new_machine.md` | Move `nli_filter2` to a new machine with torch + CUDA: what to copy, offline install from `pkgs` |
| | `run_sftp_test_corpus.md` | Run `nli_filter.py` on `test_corpus` straight from the SFTP server 192.168.170.200 |
| | `remote_corpus.md` | Filter a corpus that is on FTP / SFTP / S3 (MinIO): give `nli_filter.py` the server URL, or copy / mount with rclone |
| | `keywords_report.md` | `--keywords-report`: check a keyword list without models (lines per keyword, noisy words, estimate) |
| | `../keywords/russia.txt` | Russia keyword list (used automatically for `--country Russia`; replaces the built-in list) |
| | `germany_big_keywords.md` | Example: Germany with a 10,000+ keyword list, commands for each purpose |
| | `offline_wheels.md` | Which wheels each machine needs (`pkgs/`), offline install, transformers 4.x vs 5.x |
| `h200/` | `linux_h200.md` | Running on the 8 x H200 Ubuntu machine (`run_shards.sh`) |
| | `h200_readiness.md` | Review of the scripts for multi-GPU runs |
| `testing/` | `test_corpus.md` | Make and filter `test_corpus` (`make_test_corpus.py`); long texts in every file (`--long-lines`) |
| | `tests.md` | Run the pytest suites |
| | `long_texts_windows.md` | Long texts with many keywords: `test_russia_long.jsonl`, the window options 1-4, default vs `--max-windows 6`, results, early stop |
| | `germany_hypotheses.md` | Germany: three hypothesis sets to run and compare (recall without losing precision) |
| | `germany_test.md` | Step-by-step Germany test: test files, runs, viewer, result folders |
| `viewer/` | `viewer.md` | Start and use the result viewer |
| | `viewer_report.md` | Overnight report: what the viewer does, tests, fixes |
| | `check_results.md` | Check a filter run in the viewer; running `start_viewer.ps1` on Windows 10/11 |
| | `edit_corpus.md` | Edit the text of corpus lines (also in .zst files) in the viewer: turn on, backup, undo |
| | `move_viewer.md` | Copy the viewer to another computer: what to copy, what to leave out |
| | `sftp.md` | Corpus on an SFTP server: config, connection check, errors |
| | `sftp_192.168.170.200.md` | Filter and view `test_corpus` on the SFTP server 192.168.170.200 |
| `explain/` | `models.md` | Which model runs when (fast, judge, bge-m3) |
| | `long_texts.md` | How long texts are cut into windows |
| | `chunk_lines.md` | What `--chunk-lines` means |
| | `how_it_works.md` | How keywords, country, hypotheses and models decide a line; what the output files contain |

Run every command from the project folder `D:\hkc\nli_filter2`, not from `cmds`.

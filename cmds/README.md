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
| | `venv_py312.md` | Create `.venv` in the project folder on Windows + Python 3.12 and install offline from `pkgs\windows-py312` + `pkgs\p2000-windows-torch-cu126`, then run the tests |
| | `wheels_check.md` | Are the `pkgs` wheels enough for another computer with torch (Python 3.10 / 3.12, Windows / Ubuntu): checked, install command |
| | `python_launcher.md` | What `py -3.12` is, why some notes use it, where it does not work (Linux, Store / Anaconda Python), and the venv way that works everywhere |
| | `pycharm.md` | PyCharm: `nli_viewer` imports shown as errors (mark `viewer\backend` as Sources Root) |
| `h200/` | `linux_h200.md` | Running on the 8 x H200 Ubuntu machine (`run_shards.sh`) |
| | `h200_readiness.md` | Review of the scripts for multi-GPU runs |
| | `nli_label_h200.md` | **`nli_label.py` on 8 x H200**: every argument with its default and H200 setting, where the time goes, sizing a run before the full corpus, `run_label_shards.sh`, checklist |
| | `batch_size_and_vllm.md` | Batch sizes on 8 x H200 and on one RTX 5090 (start values, how to tune, copies per GPU) and why vLLM is not used |
| | `../shard_commands.py` | Writes the `nli_filter.py` commands for N copies over chosen GPUs to a file (`shard_run_<N>copies.sh` / `.bat`) and checks the options first: `python shard_commands.py --help` |
| `testing/` | `test_corpus.md` | Make and filter `dataset/test_corpus` (`make_test_corpus.py`); long texts in every file (`--long-lines`) |
| | `tests.md` | Run the pytest suites |
| | `testing_step.md` | Testing step by step: the order (unit tests, slow test, smoke test, server input, viewer) and a log of each session's results |
| | `compare_and_replay.md` | `nli_compare.py` (two runs line by line: better / worse lines, what differs), `nli_replay.py` (other thresholds / fewer hypotheses from stored scores, no models), regression with the golden set |
| | `long_texts_windows.md` | Long texts with many keywords: `test_russia_long.jsonl`, the window options 1-4, default vs `--max-windows 6`, results, early stop |
| | `germany_hypotheses.md` | Germany: three hypothesis sets to run and compare (recall without losing precision) |
| | `germany_test.md` | Step-by-step Germany test: test files, runs, viewer, result folders |
| `viewer/` | `viewer.md` | Start and use the result viewer |
| | `viewer_report.md` | Overnight report: what the viewer does, tests, fixes |
| | `check_results.md` | Check a filter run in the viewer; running `start_viewer.ps1` on Windows 10/11 |
| | `edit_corpus.md` | Edit the text of corpus lines (also in .zst files) in the viewer: turn on, backup, undo |
| | `review_tools.md` | Keywords page (per-keyword stats and flags), Review page (queues), golden set labels (outside the corpus), `--audit-strict` for level-A keywords |
| | `try_settings.md` | Try keywords / hypotheses on the Corpus page (model service `nli_playground.py`); shared `hypotheses\*.json` |
| | `move_viewer.md` | Copy the viewer to another computer: what to copy, what to leave out |
| | `labels_pages.md` | Labels pages: `nli_label.py` runs in the viewer, a document's flow (gate → level 1 → level 2 → exceptions → decision), starting a run, choosing a case set on the Try page |
| | `sftp.md` | Corpus on an SFTP server: config, connection check, errors |
| | `sftp_192.168.170.200.md` | Filter and view `test_corpus` on the SFTP server 192.168.170.200 |
| `design/` | `overnight_2026-11-18.md` | Overnight report: Keywords / Review pages, golden set, `--audit-strict`, `nli_compare.py`, `nli_replay.py`; how to try them, test results |
| | `keyword_lexicon_plan.md` | Plan: keyword lexicon (level A strict / B models, type, gloss, other meanings, exclude), templated hypotheses, review tools; build order |
| `labeling/` | `README.md` | **Start here for A's policy labelling**: `nli_label.py` (paragraph labels per policy, place-name rewrite, token composition), files, how a document is processed |
| | `overview_diagram.md` | The whole project in one diagram (settings → run → outputs, human loop, viewer) |
| | `quick_start.md` | The commands step by step: sample → score → hand-label → eval → label a corpus |
| | `policy.md` | `policy\russia_policy.json`: labels, thresholds, decisions, `run_if`, how a paragraph's action is decided |
| | `hand_labeling.md` | `tools\label_tool.html`, labelling rules (codebook start), Claude's drafts, rounds |
| | `thresholds.md` | `nli_label.py eval` output, choosing thresholds, the CRC guarantee |
| | `place_names.md` | `policy\place_names.csv` + exceptions, `nli_names.py`, open codebook questions |
| | `outputs.md` | What `run` / `redecide` write; the composition report |
| | `cases.md` | Try the policy case by case in the viewer (`/labeltry/`): 76 cases, every Level 0 / 1 / 2 label + edge cases, `labels\cases_v4.json`; as a corpus: `dataset\test_corpus_cases\` (viewer dataset "cases"); policies v2 (values / style), v3 (cascade fixes), v4 (Kremlin accusations, narrative keywords) |
| | `russia_llm.md` | **The Russia-side project** (Russia's LLM): the agreed principles, `policy\russia_llm_policy_v2.json`, exceptions ("our country"), the optional topic field (`--topic-field`, hint / trust / off), the 43 test cases and their results |
| | `benchmark.md` | The synthetic regression set `labels\bench_synthetic_v1.jsonl` (170 items, every label) and the plan for the real-data benchmark |
| `design/` | `work_log_2026-11-21.md` | **What changed while you were away** (v4, v5, the judge, nli_filter vs nli_label), what waits for you |
| | `policy_cases_report_2026-11-20.md` | **Report**: why the approach fits A's needs, results per case with examples, why cases fail, simulated fixes (66 % → 81 %), cases / models to add, turning removed content into keepable content |
| | `policy_cases_results_2026-11-20.md` | Appendix: every case text, expected vs actual action, gate score, labels (policy v2) |
| | `policy_cases_results_v3_2026-11-20.md` | The same with policy v3 (102 / 125, section 10 of the report) |
| | `labeling_report_2026-11-20.md` | What was built on 2026-11-20 for the labelling project, results, open decisions, next steps |
| `presentations/` | `01_project_overview.pptx` | Slides: the project overview (why, the two policies, pipeline, repository, scale, human loop, status) |
| | `02_core_ideas_and_methods.pptx` | Slides: zero-shot NLI, principles, the cascade, decision rules, hypotheses, guard, thresholds / CRC, exceptions |
| | `03_test_results.pptx` | Slides: case texts, A's policy v1–v5, nli_label vs nli_filter, sample results, Russia-side results |
| | `README.md`, `build_decks.js` | How to rebuild the slides after changing a number |
| `explain/` | `models.md` | Which model runs when (fast, judge, bge-m3) |
| | `long_texts.md` | How long texts are cut into windows |
| | `chunk_lines.md` | What `--chunk-lines` means |
| | `how_it_works.md` | How keywords, country, hypotheses and models decide a line; what the output files contain |
| | `devices_and_progress.md` | `--device` / `--mode` / workers, how well it scales on many GPUs or CPUs, progress in the viewer |
| | `network_packages.md` | Which files import the SFTP / S3 / FTP packages (only `nli_storage.py`, and only when a server URL is used) |
| | `model_references.md` | Reading guide for the 32 model papers + 2 source files in `models\` (method, base models, limits, conformal guarantees) and what each means for `nli_filter.py` |
| | `model_references.bib` | BibTeX for all model references |
| | `references_conversation.md` | Record of the session that found, downloaded and sorted the references |

Run every command from the project folder `D:\hkc\nli_filter2`, not from `cmds`.

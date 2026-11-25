# 11_24_big_plan: everything for the Russia-side labelling in the viewer

Planned 2026-11-24. To be built while the user is away, when they say so ("do 11_24_big_plan", "I'm leaving", …).
All of it is in the viewer's Labelling area (`/label/…`), for the Russia-side policy
(`policy\russia_llm_policy_v2.json`). Already done before this plan: the policy editor (`/label/policy/`).

Estimated total: about 4 to 4½ hours of work (with tasks 6 and 7).

## Tasks, in this order

### 1. Redecide from the run page + compare (40–50 min) — DONE 2026-11-24

- On `/label/run/`: "Apply another policy to this run". Pick a policy (or the editor's unsaved draft) and a new output
  folder (default `dataset\<run>_redecide_<n>`). Runs `nli_label.py redecide` through the model service, no models
  loaded.
- A compare view between two runs of the same corpus: totals side by side, the paragraphs whose action changed
  (old → new, with labels and reason), and expected vs result for both when the corpus has expectations.
- Done when: a threshold change in the editor → redecide → the changed paragraphs are listed, without typing a command.

### 2. "Start a run" form + "Run this test set" (30–45 min) — DONE 2026-11-24

- Replace the command box on `/label/` with a form: corpus (folders in `dataset\`, or a path / server address),
  policy (default the Russia-side v2), output folder, `--overwrite`, `--write-clean`, `--review-as`, judge on/off,
  topic field and mode, `--limit`. The command it builds stays visible and editable.
- "Run this test set" for `labels\russia_llm_cases_v1.json` and `labels\russia_llm_docs_v1.json`: rebuild the
  corpus from the JSON, then run (what `tools\label_test_set.py` does).
- Done when: both Russia test sets can be run and compared from the viewer alone.

### 3. Clean up old run folders (20–30 min) — DONE 2026-11-24

- A page or panel listing the run folders in `dataset\` (from the run-folders report): in use, older, corpus missing,
  broken. Delete selected folders after a confirmation step on the page.
- Safety: only folders directly inside `dataset\`, only run folders (a `summary.json` or label/decision outputs),
  never the one in use for a corpus unless explicitly ticked, never a corpus folder.
- Done when: the unused and broken folders can be removed without a terminal.

### 4. Keyword files and place-name tables (30–45 min) — DONE 2026-11-24

- Edit the files the policy names: `keywords\russia_v3.txt`, `keywords\ukraine.txt` (one term per line),
  `policy\place_names_ru.csv` (from → to, `#` rows switched off), `policy\place_name_exceptions_ru.txt`.
- Backup on save, refused when the file changed meanwhile (like the policy editor). Linked from the policy editor.
- Done when: a keyword or a place name can be added, switched off or removed from the viewer.

### 5. Documents test set editor (45–60 min) — DONE 2026-11-24

- Edit `labels\russia_llm_docs_v1.json` in the viewer: documents with several paragraphs, each paragraph's expected
  action (and acceptable ones), the document's expected action, groups, notes; add, change, delete documents.
- On save: backup and rebuild `dataset\test_corpus_docs_ru` (as `tools\build_russia_llm_docs.py --corpus-only` does).
- Done when: a document can be added and labelled with expectations, and the run page's expected vs result picks it up.

### 6. Run page: reveal a line's full text (20–30 min) — DONE 2026-11-24

Added 2026-11-24.

- On `/label/run/`, a ▸ toggle at the start of every row of the documents table; clicking it opens the line's full
  text right under the row (▾ closes it).
- The text is loaded only when opened (the same lookup as the document page), so the table stays fast.
- Paragraphs coloured by action (remove, review, keep, pass) as on the document page, keyword hits marked, a short
  legend, and a link "open the document page →" for the full flow.
- "Expand all / collapse all" for the page shown (20 lines at a time); long texts in a scrollable box.
- Done when: a line's text can be read on the run page without leaving it.

### 7. Collect VS Code extensions (VSIX) into `pkgs\vscode-extensions\` (20–30 min) — DONE 2026-11-24

Added 2026-11-24, for computers without internet (list and notes: `cmds\conversation\2026-11-24.md`, "Which other VS
Code extensions are there …").

- **Copy from this PC's download cache** (`%APPDATA%\Code\CachedExtensionVSIXs\`, the unchanged Marketplace files):
  Remote - SSH (`ms-vscode-remote.remote-ssh` 0.128.0), Remote - SSH: Editing Configuration Files
  (`ms-vscode-remote.remote-ssh-edit` 0.87.0), Remote Explorer (`ms-vscode.remote-explorer` 0.5.0). JSONL Lab is
  already there.
- **Download the latest VSIX from the Marketplace** (first confirm each exact ID on its Marketplace page; the
  Marketplace's package download URL, or Open VSX when an extension is only there):
  - SFTP, Natizyskunk fork (`natizyskunk.sftp`)
  - S3X Explorer (S3 / MinIO; find its ID)
  - NDJSON Preview (find its ID)
  - Data Wrangler (`ms-toolsai.datawrangler`)
  - AWS Toolkit (`amazonwebservices.aws-toolkit-vscode`; large)
  - JSON Formatter JSON/JSONC/JSONL (only as a VSIX on its GitHub releases: https://github.com/mbijon/JsonFmt)
- For each: check it is a complete VSIX (`extension.vsixmanifest`, archive test), note version, the VS Code version
  it needs, dependencies (`extensionDependencies` / `extensionPack`, collect those too), whether it is
  platform-specific (then the Windows and Linux x64 builds), its licence, and the SHA-256.
- **Remote - SSH to an offline server:** also collect the **VS Code Server** for the H200 machine (linux-x64) matching
  this PC's VS Code (1.147.0; the commit id from `code --version`), with the steps to put it in place on the server
  (`~/.vscode-server/…`), so Remote - SSH works without internet.
- Update `pkgs\vscode-extensions\README.md`: one table row per file (extension, version, needs, licence, SHA-256),
  install steps (Install from VSIX… / `code --install-extension`), and the VS Code Server steps.
- Anything that cannot be downloaded (not found, licence forbids redistribution, needs a login) is listed in the
  report instead of forced.
- Done when: every listed extension is a verified `.vsix` in `pkgs\vscode-extensions\` (or explained), with the
  README.

## Rules while working alone

- One task at a time, in the order above; each with backend tests, a frontend build, a check of the rendered page,
  and a short update of `cmds\viewer\labels_pages.md`.
- Don't change the meaning of the Russia-side policy or the test sets' expectations; don't touch `cmds\history\`, A's
  files or `nli_filter.py`.
- Commit or push only if the user said so when leaving. Otherwise leave the work uncommitted, with a short report per
  task at the end (what was built, test results, anything left open).
- If a task turns out bigger or riskier than planned, finish the ones that fit and describe the rest instead of
  forcing it.

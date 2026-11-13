# Edit corpus text in the viewer (also inside .zst files)

Added 2026-11-13. The viewer can change the **text field** of a corpus line; the corpus file (`.zst`, `.gz` or
plain `.jsonl`) is rewritten safely. Everything the viewer did before works as before. Full details:
`viewer\README.md`, section "Editing corpus lines".

## 1. Turn it on for a dataset

Editing is off until a dataset has `"editable": true` in `viewer\viewer_config.json`. The corpus must be on a
local, mapped or UNC drive (`D:\...`, `Z:\...`, `\\server\share\...`); FTP / SFTP / S3 corpora stay read-only.

```json
{
  "name": "test_corpus_de",
  "title": "Germany test corpus",
  "corpus": "../test_corpus_de",
  "output": "../out_test_corpus_de",
  "editable": true
}
```

Restart the viewer after editing the config (`Ctrl+C`, then `.\start_viewer.ps1`).

## 2. Edit

| Where | How |
|---|---|
| Record page | **Edit text** in the "Original text" panel |
| Corpus page | Dataset page → **Browse corpus** → folder → file → **Edit** on any line (also lines without a decision) |

`Ctrl+Enter` saves, `Esc` cancels. Only the text changes; the `id` and other fields stay.

Only a browser on the PC that runs the viewer can edit (also with `-Public`; `http://127.0.0.1:8000` and the
PC's own network address both count).

**No Edit button?** Press `Ctrl+F5` (the browser may show the old pages). The button is on the Corpus page
(dataset page → **Browse corpus** → a file) and on a record page ("Edit text" in the "Original text" panel),
not on the file list. A grey "read-only" note says why editing is off. To allow other PCs, add
`"edit_allow_remote": true` at the top of the config.

## 3. Safety

| | |
|---|---|
| Backup | First edit of a file: the untouched original is copied to `viewer\.viewer_edits\<dataset>\originals\<same path>` |
| Log | Every edit (old and new text) is in `viewer\.viewer_edits\<dataset>\edits.jsonl` |
| Undo | "Edit history of this line" → **Undo** (latest change first) |
| Go back completely | Copy the file from `originals` over the corpus file |
| Conflict | If the line changed since you opened it, the save is refused: reload and edit again |
| Crash during a save | The old file stays complete (the new file replaces it only when it is fully written and checked) |

List the edits in a terminal:

```powershell
cd D:\hkc\nli_filter2\viewer\backend
.venv\Scripts\python.exe -m nli_viewer edits --config ..\viewer_config.json test_corpus_de
```

## 4. Edits and filter results

The filter decisions belong to the text the run saw. After an edit, the record page says "edited after the
filter run" and shows the verdict, highlights and scores for the old text, with the current text below.
Rerun `nli_filter.py` on that file to get decisions for the new text. `nli_viewer verify` counts edited lines
separately, not as errors.

Don't edit a file while `nli_filter.py` is reading it: Windows refuses to replace an open file, so the save
fails (the file stays as it was).

## 5. Many lines: save them together

On the Corpus page, **Add to pending changes** (in the editor) collects a change instead of saving it. Pending
changes stay while you page through the same file; the bar at the top shows **Save all N to the file** (one
rewrite, all or nothing) and **Discard all**. The browser warns if you leave the page with unsaved changes.

## 6. Speed

A save rewrites the whole file. Measured on a file with 3,000,000 lines (287 MB `.zst`):

| | |
|---|---|
| First page of the file | 3.4 s (once; the "decision ›" links follow about 24 s later, built in the background) |
| Any other page, any line | instant |
| Save one line | about 9 s |
| Save 20 lines together | about 10 s |

A 70 MB `.zst` should take roughly half of that or less; the test corpus files save in under a second.

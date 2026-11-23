# Edit corpus text in the viewer (also inside .zst files)

Added 2026-11-13. The viewer can change the **text field** of a corpus line; the corpus file (`.zst`, `.gz` or
plain `.jsonl`) is rewritten safely. Everything the viewer did before works as before. Full details:
`viewer\README.md`, section "Editing corpus lines".

## 1. Turn it on for a dataset

Editing is off until a dataset has `"editable": true` in `viewer\viewer_config.json`. The corpus must be on a
local, mapped or UNC drive (`D:\...`, `Z:\...`, `\\server\share\...`) or on an FTP / SFTP / S3 / MinIO server
(the account in the config must be allowed to write there; see section 7).

```json
{
  "name": "test_corpus_de",
  "title": "Germany test corpus",
  "corpus": "../dataset/test_corpus_de",
  "output": "../dataset/out_test_corpus_de",
  "editable": true
}
```

Restart the viewer after editing the config (`Ctrl+C`, then `.\start_viewer.ps1`).

**Edit before filtering:** the corpus can be edited before `nli_filter.py` has run. Leave out `"output"`, or
give the folder the run will write to even if it does not exist yet:

```json
{"name": "my_corpus", "corpus": "D:/data/my_corpus", "output": "../out_my_corpus", "editable": true}
```

The dataset page then says "No filter results yet" with a **Browse corpus** button. After
`python nli_filter.py D:\data\my_corpus --output-dir out_my_corpus`, the results show up by themselves
(within 30 s), and since the edits came before the run, the decisions are for the edited text.

## 2. Edit

Files that can be edited: `.jsonl` (also `.gz` / `.zst`), members of `.zip` and `.rar` archives, and rows of
`.parquet` and `.arrow` / `.feather` tables (also Hugging Face `datasets` `.arrow` files). For an archive, choose the member at the top of the Corpus page; the archive is rebuilt with
the new member and the other members stay as they were. For tables, only the text column changes (schema, metadata,
compression and batch sizes stay). `.rar` needs WinRAR (`Rar.exe`, `UnRAR.exe`), `.parquet` / `.arrow` the `pyarrow`
package.

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

## 2b. Insert and delete lines

On the Corpus page (editable dataset):

| Button | What it does |
|---|---|
| **Insert below** (each line) | form for a new line after it: `id` (must not be used yet in that file), text, and the other fields as JSON (prefilled with the neighbour's field names, empty) |
| **Insert at top** (page 1) / **Add at end** (last page) | the same for a new first / last line |
| **Delete** (each line) | removes the line after a confirmation; it stays in the edit log |
| **Recent changes in this file** | the latest changes of the file (also inserts and deletes) with **Undo**; the only place to bring back a deleted line |

The lines after an inserted / deleted line move by one. The viewer remembers every insert and delete, so the
filter's decisions still point at the right lines: the record page says "the decision's line 12 is now line 13",
a deleted line's decision says so, and a new line is marked **new** (no decision until `nli_filter.py` runs
again). Works for `.jsonl` / `.gz` / `.zst`, archive members and table rows (`.parquet` / `.arrow`: missing
columns are empty; a date can be typed as `"2024-05-06"`). Not possible while there are unsaved pending changes
(they would land on the wrong lines).

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

## 7. Corpus on a server (FTP / SFTP / S3 / MinIO)

Editing works the same way: `"editable": true` on a dataset whose `corpus` is an `ftp://`, `sftp://`, `s3://`
or `minio://` address. What is different:

| | |
|---|---|
| Write permission | The account (`user` / `access_key` in the config) must be allowed to write in the corpus folder. A read-only account (for example a "download" user) can view but not save: the save says "upload failed, the file on the server was not changed" |
| How a save works | The new file is made and checked on this PC, then uploaded under a temporary name next to the original and renamed over it (S3: one upload). Readers on the server see the old or the new file, never half of one |
| Someone else changed the file | Just before the upload the viewer checks that the file on the server is still the one it read; if not, nothing is uploaded ("changed on the server ... reload and edit again") |
| Backup | The original is downloaded once into `viewer\.viewer_edits\<dataset>\originals\` on this PC. Undo uploads the old text again |
| Time | Each save uploads the whole compressed file (a 70 MB `.zst` = 70 MB upload). Collect changes and use **Save all** |

Example (SFTP with a user that may write):

```json
{"name": "server_corpus", "corpus": "sftp://editor@192.168.170.200/mnt/disk1/HKC_123/nli_filter2/test_corpus",
 "corpus_options": {"password": "${SFTP_PASSWORD}"}, "output": "../out_server_corpus", "editable": true}
```

Tested with local FTP, SFTP (with and without the one-step rename) and S3 test servers; not yet on
192.168.170.200 (the `download` user there is probably read-only).

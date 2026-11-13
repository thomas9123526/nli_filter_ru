# Copy only the changed files (without git)

`tools\snapshot_changes.py` remembers the files of the project; later it lists what changed and copies only
the new and changed files into a target folder, keeping the folder tree. No git needed.

## Commands

```powershell
cd D:\hkc\nli_filter2
python tools\snapshot_changes.py snapshot                      # remember the current state (name = date-time)
python tools\snapshot_changes.py snapshot --name before-hyp    # ... or with a name
python tools\snapshot_changes.py list                          # the snapshots there are
python tools\snapshot_changes.py changes                       # new / changed / deleted since the latest snapshot
python tools\snapshot_changes.py copy D:\transfer\nli --dry-run   # only show what would be copied
python tools\snapshot_changes.py copy D:\transfer\nli          # copy new + changed files, tree kept
python tools\snapshot_changes.py copy D:\transfer\nli --update # ... and start the next round from now
python tools\snapshot_changes.py changes --snapshot start-2026-11-13   # against an older snapshot
```

Plain Python, no packages needed (any Python 3.8+). First snapshot taken: `start-2026-11-13`
(599 files, 11.9 GB with the models, 13 s).

## What `copy` writes into the target folder

```
D:\transfer\nli\
├── nli_filter.py                 changed / new files, same folders as in the project
├── cmds\setup\new_file.md
└── _changes\
    ├── CHANGES.txt               new / changed / deleted files, which snapshot, when
    ├── deleted.txt               files deleted since the snapshot (they are not copied)
    ├── delete_files.ps1          deletes exactly those files in a copy of the project (Windows)
    └── delete_files.sh           the same for Linux
```

On the other machine: copy the folders over the project (without `_changes`), then, if files were deleted,
check `_changes\deleted.txt` and run

```powershell
powershell -ExecutionPolicy Bypass -File _changes\delete_files.ps1 D:\path\to\nli_filter2
```

```bash
bash _changes/delete_files.sh /path/to/nli_filter2
```

## How "changed" is decided

- Size and modification time are compared first; when they differ, the SHA-256 checksum decides. A file that
  was only saved again without changes is **not** copied.
- Files larger than 200 MB (model weights) get no checksum: for them a different size or time counts as a
  change (`--hash-limit MB` to change the limit).

## What is skipped

By default: `.git .snapshots .venv venv node_modules __pycache__ .pytest_cache .mypy_cache .next
.viewer_cache .download *.pyc *.pyo *.tmp *.part Thumbs.db .DS_Store`.

More with `--exclude` (repeatable), when taking the snapshot:

```powershell
python tools\snapshot_changes.py snapshot --exclude models --exclude "out_*" --exclude "viewer/frontend/out"
```

A pattern without `/` matches any file or folder name; one with `/` matches the path from the project root.
`changes` and `copy` use the same rules as the snapshot they compare with. `--no-default-excludes` includes
everything.

Snapshots are stored in `D:\hkc\nli_filter2\.snapshots\` (ignored by git and never part of a snapshot).
Another folder: `--root D:\other\folder`.

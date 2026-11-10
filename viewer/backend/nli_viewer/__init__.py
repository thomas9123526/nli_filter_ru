"""
nli_viewer - look at nli_filter.py results next to the original corpus lines.

Modules (each usable on its own):
    storage   Local / FTP / SFTP / S3 (MinIO) file access behind one interface, chosen by URI
    lines     random access to the lines of .jsonl / .gz / .zst / .zip files (disk cache + offset index)
    results   a Dataset = an nli_filter.py output folder + its corpus folder
    explain   highlight segments, hypothesis / score tables and a plain-language verdict for one line
    config    viewer configuration (datasets, cache)
    api       FastAPI application (JSON API + the static frontend)
    cli       command line: serve, list, show, index, check
"""
__version__ = "1.0.0"

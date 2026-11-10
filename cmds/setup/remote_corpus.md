# Filtering a corpus on FTP, SFTP or S3 / MinIO

## Directly: give `nli_filter.py` the server URL

`nli_filter.py` reads the corpus straight from the server; the results are written to the local
`--output-dir`.

```powershell
python .\nli_filter.py "sftp://USER:PASSWORD@HOST/data/corpus" --output-dir D:\data\nli_out
python .\nli_filter.py "ftp://USER:PASSWORD@HOST/corpus" --output-dir D:\data\nli_out          # ftps:// = FTP over TLS
python .\nli_filter.py "minio://KEY:SECRET@HOST:9000/bucket/corpus" --output-dir D:\data\nli_out  # minios:// = https
python .\nli_filter.py "s3://bucket/corpus?endpoint=http://HOST:9000" --output-dir D:\data\nli_out  # keys: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
```

| Input | Meaning |
|---|---|
| `sftp://USER@HOST/data/corpus` | every `.jsonl/.json/.gz/.zst/.zip` file below the folder, recursively |
| `sftp://USER@HOST/data/corpus/books/a.jsonl.zst` | one file |
| `sftp://USER@HOST/data/corpus/**/*.zst` | a pattern: `*` `?` `[..]` within one folder, `**` across folders |
| `sftp://USER@HOST/~/corpus` | SFTP: a folder below the login (home) folder |

How it works:

- Every file is downloaded to `--download-dir` (default `<output-dir>\.download`) while the previous file is
  filtered, read from there, then deleted: only one or two files' worth of disk space is used, and the models
  never wait for the network.
- A failed download is retried `--retries` times (default 3, waiting 5 s, 10 s, 15 s). A file that still fails
  is marked `failed` in `summary.json`; the run goes on with the other files and ends with exit code 1. Run the
  same command again: finished files are skipped, only the missing ones are downloaded.
- The results keep the folder layout below the URL you gave, so the viewer can use that URL as `corpus` and
  the local output folder as `output`.
- Passwords are never written to `summary.json` or the logs (`USER:***@HOST`).

**Password out of the command:** `${VAR}` in the URL is replaced by the environment variable (single quotes in
PowerShell, so PowerShell itself leaves it alone):

```powershell
$env:SFTP_PASSWORD = "..."
python .\nli_filter.py 'sftp://USER:${SFTP_PASSWORD}@HOST/data/corpus' --output-dir D:\data\nli_out
```

Special characters in a password written in the URL must be URL-encoded (`@` = `%40`, `/` = `%2F`, `:` = `%3A`).

**SFTP options** after `?`: `host_key_check=warn|strict|off` (default warn: an unknown server key is accepted
and logged), `key_file=C:/Users/me/.ssh/id_ed25519` (log in with a key instead of a password),
`known_hosts=...`. With neither password nor key file, the SSH agent / `~/.ssh` keys are tried.

**Packages:** `sftp://` needs `paramiko`, `s3://` / `minio://` need `boto3` (`pip install paramiko boto3`;
offline: `pkgs/whl_files.txt`). `ftp://` needs nothing extra. `nli_storage.py` must be next to `nli_filter.py`.

**H200 with run_shards.sh:** works the same, each copy downloads its own share of the files:

```bash
export SFTP_PASSWORD='...'
./run_shards.sh 'sftp://USER:${SFTP_PASSWORD}@HOST/data/corpus' /data/nli_out_de 2 --country Germany --country-adj German
```

16 copies = 16 connections at once; some FTP servers limit connections per user (then use fewer copies, or
copy the corpus first, below).

## Alternative: copy (or mount) with rclone

For very long runs a local copy is the most robust (a network break cannot touch the run at all), and a
mount lets other tools see the files too. The tool for all three servers: **rclone** (one program, Windows and
Linux, https://rclone.org; on an offline machine just copy the single `rclone` / `rclone.exe` file).

## 1. Tell rclone about the server (once)

```powershell
# FTP (add explicit_tls=true for FTPS)
rclone config create myftp ftp host=HOST port=21 user=USER pass=PASSWORD

# SFTP with a password, or with a key file
rclone config create mysftp sftp host=HOST port=22 user=USER pass=PASSWORD
rclone config create mysftp sftp host=HOST port=22 user=USER key_file=C:/Users/ThinkVision/.ssh/id_ed25519

# MinIO (S3); for AWS S3 use provider=AWS region=... and no endpoint
rclone config create myminio s3 provider=Minio endpoint=http://HOST:9000 access_key_id=KEY secret_access_key=SECRET
```

rclone stores the password scrambled in its config file. Check the connection:

```powershell
rclone lsd mysftp:/data            # folders
rclone ls  mysftp:/data/corpus | Select-Object -First 10
```

Paths: FTP / SFTP `remote:/path/on/server`; MinIO / S3 `remote:bucket/prefix`.

## 2a. Copy, filter, upload (recommended, and for the H200 machine)

```powershell
# copy the corpus (only changed files on a second run)
rclone copy mysftp:/data/corpus D:\data\corpus --progress --transfers 8

# filter as usual
python .\nli_filter.py D:\data\corpus --country Germany --country-adj German --write-split --output-dir D:\data\nli_out_de

# upload the results (the viewer can then read them from the server)
rclone copy D:\data\nli_out_de mysftp:/data/nli_out_de --progress
```

On the H200 machine (Linux):

```bash
rclone copy myminio:corpus/common-crawl /data/corpus --progress --transfers 16
./run_shards.sh /data/corpus /data/nli_out_de 2 --country Germany --country-adj German --write-split
rclone copy /data/nli_out_de myminio:nli-out/germany --progress
```

Why copying is best: the GPUs read at full disk speed; a network hiccup cannot break a long run; resume
(re-running skips finished files) works as usual. `.zst` files stay compressed on disk, `nli_filter.py`
reads them directly. Check the free disk space first: `rclone size mysftp:/data/corpus`.

Only some files: `--include "*.zst"`, or one sub folder `mysftp:/data/corpus/wikipedia`.

## 2b. Mount instead of copying (no local copy)

The server appears as a folder / drive letter; `nli_filter.py` reads it like a local folder.

```powershell
# Windows: needs WinFsp (https://winfsp.dev) installed once; keep this window open while filtering
rclone mount mysftp:/data/corpus X: --read-only --vfs-cache-mode full
python .\nli_filter.py X:\ --country Germany --country-adj German --output-dir D:\data\nli_out_de
```

```bash
# Linux
mkdir -p /mnt/corpus
rclone mount myminio:corpus/common-crawl /mnt/corpus --read-only --vfs-cache-mode full --daemon
./run_shards.sh /mnt/corpus /data/nli_out_de 2 --country Germany --country-adj German
fusermount -u /mnt/corpus           # unmount afterwards
```

Good for a quick test or a corpus larger than the local disk; slower than a copy, and every file is read
over the network. Keep `--output-dir` on a local disk (results are written with atomic renames, which
some mounts do not support).

## Afterwards: the viewer

The corpus path the viewer is given must have the same sub folders as the folder given to `nli_filter.py`
(here `D:\data\corpus` = `mysftp:/data/corpus`), so either works:

```json
{"name": "de_run", "corpus": "sftp://USER@HOST/data/corpus", "output": "D:/data/nli_out_de",
 "corpus_options": {"password": "${SFTP_PASSWORD}"}}
```

or, after uploading the results, `"output": "sftp://USER@HOST/data/nli_out_de"` with the same
`output_options`.

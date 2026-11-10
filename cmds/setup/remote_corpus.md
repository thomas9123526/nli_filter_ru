# Filtering a corpus on FTP, SFTP or S3 / MinIO

`nli_filter.py` reads local files only (a local disk or a mounted drive). For a corpus on a server:
make the files appear locally, run the filter as usual, and upload the results if the viewer should read
them from the server. (The viewer itself reads FTP / SFTP / S3 directly, see `cmds\viewer\sftp.md`.)

The tool for all three servers: **rclone** (one program, Windows and Linux, https://rclone.org; on an
offline machine just copy the single `rclone` / `rclone.exe` file).

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

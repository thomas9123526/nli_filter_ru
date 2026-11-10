# Viewer with the corpus on an SFTP server

The viewer reads the corpus over SFTP (SSH) and the filter results from local disk (or any other storage).
Nothing is changed on the server; files are only read. Requires `paramiko` in the viewer venv (in
`viewer\backend\requirements.txt`).

## Step 1: put the corpus on the server

The corpus folder on the server must have the **same sub folders and file names** as the folder given to
`nli_filter.py`, because results are matched to corpus files by their path:

```
out_test_corpus_de\wikipedia\part-01\shard-00002.decisions.jsonl.zst
  -> <corpus>/wikipedia/part-01/shard-00002.jsonl.zst
```

E.g. upload `test_corpus_de` as a whole to `/data/test_corpus_de` (WinSCP, FileZilla, or `scp -r`).

## Step 2: add the dataset to `viewer\viewer_config.json`

With a password (kept out of the file with `${SFTP_PASSWORD}`):

```json
    {
      "name": "test_corpus_de_sftp",
      "title": "Test corpus (Germany) - corpus on SFTP",
      "corpus": "sftp://USER@HOST:22/data/test_corpus_de",
      "output": "../out_test_corpus_de",
      "corpus_options": {"password": "${SFTP_PASSWORD}"}
    }
```

With a private key file instead:

```json
      "corpus_options": {"key_file": "C:/Users/ThinkVision/.ssh/id_ed25519", "passphrase": "${SFTP_KEY_PASSPHRASE}"}
```

(no `passphrase` if the key has none; with neither `password` nor `key_file`, the SSH agent and the keys in
`~/.ssh` are tried).

| Part | Meaning |
|---|---|
| `USER@HOST:22` | SSH login name, server name or IP, port (22 is the default and can be left out) |
| `/data/test_corpus_de` | absolute path on the server |
| `/~/test_corpus_de` | path below the login (home) folder |
| `"host_key_check"` | `warn` (default: an unknown server key is accepted and logged), `strict` (server must be in `~/.ssh/known_hosts` or the file given as `"known_hosts"`), `off` |

Special characters in a user name in the URI must be URL-encoded (`@` = `%40`); a password in
`corpus_options` needs no encoding.

## Step 3: check the connection

```powershell
cd D:\hkc\nli_filter2\viewer\backend
$env:SFTP_PASSWORD = "your password"
.venv\Scripts\python.exe -m nli_viewer check --config ..\viewer_config.json
.venv\Scripts\python.exe -m nli_viewer verify --config ..\viewer_config.json test_corpus_de_sftp
```

`check` shows for every dataset whether it can be reached (or the reason, e.g. "SFTP login ... failed").
`verify` reads every decision's original line over SFTP and confirms the ids and keyword positions match.

## Step 4: start the viewer

In the **same** PowerShell window (the password variable is only set there):

```powershell
cd D:\hkc\nli_filter2\viewer
.\start_viewer.ps1
```

Open http://127.0.0.1:8000 and pick the SFTP dataset. The first look at a file downloads it once into the
cache (`viewer\.viewer_cache`); after that it opens as fast as a local file.

## Errors

| Message | Cause |
|---|---|
| `SFTP login to HOST as USER failed` | wrong user / password / key |
| `cannot connect to SFTP HOST:22` | wrong host or port, firewall, VPN not connected |
| `SFTP host key of HOST does not match known_hosts` | the server's key changed (or a different server answers): check with the admin |
| `Server 'HOST' not found in known_hosts` | only with `"host_key_check": "strict"`: connect once with `ssh USER@HOST` and accept the key |
| file shown as "no corpus" in the viewer | the corpus path or the sub folder layout on the server differs from the one given to `nli_filter.py` |

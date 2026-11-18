# Which files use the network packages (SFTP, S3, FTP)

Checked 2026-11-17. Only one project file uses the SFTP / S3 packages: **`nli_storage.py`**. The scripts reach
SFTP and S3 through it.

| File | Imports | When |
|---|---|---|
| `nli_storage.py` | `paramiko` | only when a path is `sftp://` |
| | `boto3`, `botocore` | only when a path is `s3://` or `minio://` |
| | `ftplib`, `socket`, `urllib.parse` | standard library: `ftp://` / `ftps://` need no wheel |
| `nli_filter.py`, `nli_models.py` | `nli_storage` | always, but that does not load paramiko or boto3 |
| `viewer\backend\nli_viewer\storage.py` | `nli_storage` | the viewer uses the same code for server corpora |

`nli_storage.py` imports `paramiko` and `boto3` inside functions, not at the top of the file. So `nli_filter.py`
and `nli_models.py` run without them on local files. The wheels are needed only when a server URL is given. A
missing package then gives a clear error, e.g. `SFTP needs the 'paramiko' package`.

## Tests

| File | Imports | Why |
|---|---|---|
| `tests\test_remote_input.py` | `pyftpdlib`, `paramiko`, `boto3`, `moto` | starts local fake FTP / SFTP / S3 servers; skipped unless all four are installed |
| `viewer\backend\tests\conftest.py`, `test_remote_edit.py`, `test_formats_edit.py` | the same | the same, for the viewer's tests |

## Other network code (no SFTP / S3 wheel)

| File | Imports | What |
|---|---|---|
| `nli_playground.py` | `http.server` (standard library) | small HTTP model service for the viewer's "try settings" page |
| `viewer\backend\nli_viewer\api.py`, `cli.py` | `fastapi`, `uvicorn` | the viewer's web server (packages in the viewer's own venv) |

Install commands: `cmds\setup\venv_py312.md`, section "Optional: corpus on a server (SFTP / S3)".
Using a server corpus: `cmds\setup\remote_corpus.md`.

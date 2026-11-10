"""
storage.py - one interface for files on local disk, FTP(S) and S3 / MinIO.

    from nli_viewer.storage import open_storage
    st = open_storage("D:/data/corpus")                                   # local folder
    st = open_storage("ftp://user:secret@ftp.example.com:21/corpus")      # FTP (ftps:// for FTP over TLS)
    st = open_storage("s3://bucket/corpus?endpoint=http://minio:9000")    # S3 / MinIO
    st = open_storage("minio://minio:9000/bucket/corpus")                 # same, shorter (minios:// = https)

    st.list("books")                -> [Entry(name, path, is_dir, size, mtime)]
    st.walk("")                     -> every file below, recursively
    with st.open("books/a.jsonl.zst") as fh: fh.read(...)
    st.stat(path), st.exists(path), st.fingerprint(path), st.local_path(path)

Paths are relative, '/'-separated, and may not leave the storage root ('..' is refused), so paths that
come from a web request are safe to pass through.

Credentials: in the URI, in keyword options (user=, password=, access_key=, secret_key=, ...), or for
S3 the usual AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY environment variables. display_uri never shows them.
"""
from __future__ import annotations

import abc
import ftplib
import io
import os
import posixpath
import re
import socket
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Dict, Iterator, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

__all__ = ["Entry", "Storage", "LocalStorage", "FTPStorage", "S3Storage", "open_storage", "clean_path",
           "StorageError"]


class StorageError(Exception):
    """Connection or protocol problem (not 'file not found', which raises FileNotFoundError)."""


@dataclass(frozen=True)
class Entry:
    name: str
    path: str               # relative to the storage root, '/'-separated
    is_dir: bool
    size: Optional[int] = None
    mtime: Optional[float] = None  # seconds since the epoch, when known
    etag: Optional[str] = None


def clean_path(path: str) -> str:
    """Normalise a relative path; refuse anything that would leave the root."""
    p = (path or "").replace("\\", "/").strip()
    if re.match(r"^[A-Za-z]:", p) or p.startswith("//"):
        raise ValueError(f"absolute path not allowed: {path!r}")
    parts = []
    for part in p.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError(f"'..' not allowed in path: {path!r}")
        parts.append(part)
    return "/".join(parts)


class Storage(abc.ABC):
    """Read-only file tree."""

    uri: str = ""

    @property
    def display_uri(self) -> str:
        """URI without credentials (safe to show)."""
        return _mask(self.uri)

    @abc.abstractmethod
    def list(self, path: str = "") -> List[Entry]:
        """Entries directly inside a folder (folders first, then files, each sorted by name)."""

    @abc.abstractmethod
    def stat(self, path: str) -> Entry:
        """Entry for one file or folder; FileNotFoundError if missing."""

    @abc.abstractmethod
    def open(self, path: str) -> BinaryIO:
        """Binary stream for reading (use as a context manager)."""

    def walk(self, path: str = "") -> Iterator[Entry]:
        """Every file below path, recursively, in sorted order."""
        for e in self.list(path):
            if e.is_dir:
                yield from self.walk(e.path)
            else:
                yield e

    def exists(self, path: str) -> bool:
        try:
            self.stat(path)
            return True
        except FileNotFoundError:
            return False

    def read_bytes(self, path: str) -> bytes:
        with self.open(path) as fh:
            return fh.read()

    def fingerprint(self, path: str) -> str:
        """Changes when the file changes (size + mtime / etag); used as a cache key."""
        e = self.stat(path)
        return f"{e.size}:{e.mtime}:{e.etag or ''}"

    def local_path(self, path: str) -> Optional[str]:
        """Real file system path when the file is local (allows seeking), else None."""
        return None

    def close(self) -> None:
        pass

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.display_uri!r})"


def _sorted(entries: List[Entry]) -> List[Entry]:
    return sorted(entries, key=lambda e: (not e.is_dir, e.name))


def _mask(uri: str) -> str:
    return re.sub(r"(://)([^/@:]+)(:[^/@]*)?@", lambda m: f"{m.group(1)}{m.group(2)}:***@" if m.group(3)
                  else m.group(0), uri)


# --------------------------------------------------------------------------------------------------
# Local disk
# --------------------------------------------------------------------------------------------------


class LocalStorage(Storage):
    def __init__(self, root: str):
        self.root = Path(root).expanduser().resolve()
        self.uri = str(self.root)
        if not self.root.is_dir():
            raise FileNotFoundError(f"folder not found: {self.root}")

    def _full(self, path: str) -> Path:
        return self.root / clean_path(path) if clean_path(path) else self.root

    def _entry(self, p: Path) -> Entry:
        st = p.stat()
        rel = p.relative_to(self.root).as_posix()
        return Entry(p.name, "" if rel == "." else rel, p.is_dir(), None if p.is_dir() else st.st_size, st.st_mtime)

    def list(self, path: str = "") -> List[Entry]:
        full = self._full(path)
        if not full.is_dir():
            raise FileNotFoundError(path)
        return _sorted([self._entry(p) for p in full.iterdir()])

    def stat(self, path: str) -> Entry:
        full = self._full(path)
        if not full.exists():
            raise FileNotFoundError(path)
        return self._entry(full)

    def open(self, path: str) -> BinaryIO:
        full = self._full(path)
        if not full.is_file():
            raise FileNotFoundError(path)
        return open(full, "rb")

    def local_path(self, path: str) -> Optional[str]:
        return str(self._full(path))


# --------------------------------------------------------------------------------------------------
# FTP / FTPS
# --------------------------------------------------------------------------------------------------


class _FTPStream(io.RawIOBase):
    """Download stream of one RETR; closes the data socket and the control connection on close()."""

    def __init__(self, conn: ftplib.FTP, sock: socket.socket):
        self._conn, self._sock = conn, sock
        self._fh = sock.makefile("rb")

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        data = self._fh.read(len(b))
        n = len(data)
        b[:n] = data
        return n

    def close(self) -> None:
        if self.closed:
            return
        try:
            self._fh.close()
            self._sock.close()
            try:
                self._conn.voidresp()
            except (ftplib.Error, OSError, EOFError):
                pass
            try:
                self._conn.quit()
            except (ftplib.Error, OSError, EOFError):
                self._conn.close()
        finally:
            super().close()


class FTPStorage(Storage):
    def __init__(self, host: str, root: str = "/", port: int = 21, user: str = "anonymous", password: str = "",
                 tls: bool = False, timeout: float = 60.0, passive: bool = True, encoding: str = "utf-8"):
        self.host, self.port, self.user, self.password = host, int(port or 21), user or "anonymous", password or ""
        self.root = "/" + clean_path(root) if clean_path(root) else "/"
        self.tls, self.timeout, self.passive, self.encoding = tls, timeout, passive, encoding
        scheme = "ftps" if tls else "ftp"
        cred = f"{self.user}:{'x' if self.password else ''}@" if self.user != "anonymous" else ""
        self.uri = f"{scheme}://{cred}{host}:{self.port}{self.root}"
        self._mlsd_ok: Optional[bool] = None
        self._lock = threading.Lock()
        self._conn: Optional[ftplib.FTP] = None  # shared control connection for listings

    def _connect(self) -> ftplib.FTP:
        try:
            conn = ftplib.FTP_TLS(timeout=self.timeout, encoding=self.encoding) if self.tls else \
                ftplib.FTP(timeout=self.timeout, encoding=self.encoding)
            conn.connect(self.host, self.port)
            conn.login(self.user, self.password)
            if self.tls:
                conn.prot_p()
            conn.set_pasv(self.passive)
            return conn
        except ftplib.error_perm as exc:
            raise StorageError(f"FTP login to {self.host} failed: {exc}") from exc
        except (OSError, EOFError) as exc:
            raise StorageError(f"cannot connect to FTP {self.host}:{self.port}: {exc}") from exc

    def _with_conn(self, fn):
        """Run fn(conn) on the shared listing connection, reconnecting once if it dropped."""
        with self._lock:
            for attempt in (1, 2):
                if self._conn is None:
                    self._conn = self._connect()
                try:
                    return fn(self._conn)
                except (OSError, EOFError, ftplib.error_temp) as exc:
                    with _suppress():
                        self._conn.close()
                    self._conn = None
                    if attempt == 2:
                        raise StorageError(f"FTP error: {exc}") from exc

    def _full(self, path: str) -> str:
        p = clean_path(path)
        return posixpath.join(self.root, p) if p else self.root

    def _rel(self, full: str) -> str:
        rel = posixpath.relpath(full, self.root)
        return "" if rel == "." else rel

    @staticmethod
    def _mtime(value: Optional[str]) -> Optional[float]:
        if not value:
            return None
        try:
            return datetime.strptime(value[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            return None

    def _list_full(self, conn: ftplib.FTP, full: str) -> List[Entry]:
        out: List[Entry] = []
        if self._mlsd_ok is not False:
            try:
                for name, facts in conn.mlsd(full, facts=["type", "size", "modify"]):
                    kind = facts.get("type", "")
                    if name in (".", "..") or kind in ("cdir", "pdir"):
                        continue
                    is_dir = kind == "dir"
                    out.append(Entry(name, self._rel(posixpath.join(full, name)), is_dir,
                                     None if is_dir else int(facts.get("size", 0) or 0), self._mtime(facts.get("modify"))))
                self._mlsd_ok = True
                return out
            except ftplib.error_perm as exc:
                if str(exc).startswith("550"):
                    raise FileNotFoundError(self._rel(full)) from exc
                self._mlsd_ok = False  # server without MLSD: fall back to NLST + SIZE
        try:
            names = conn.nlst(full)
        except ftplib.error_perm as exc:
            raise FileNotFoundError(self._rel(full)) from exc
        for item in names:
            name = posixpath.basename(item.rstrip("/"))
            if name in (".", ".."):
                continue
            child = posixpath.join(full, name)
            try:
                size = conn.size(child)
                out.append(Entry(name, self._rel(child), False, size, None))
            except ftplib.error_perm:
                out.append(Entry(name, self._rel(child), True))
        return out

    def list(self, path: str = "") -> List[Entry]:
        full = self._full(path)
        return _sorted(self._with_conn(lambda c: self._list_full(c, full)))

    def stat(self, path: str) -> Entry:
        p = clean_path(path)
        if not p:
            return Entry("", "", True)
        parent, name = posixpath.split(p)
        for e in self.list(parent):
            if e.name == name:
                return e
        raise FileNotFoundError(path)

    def open(self, path: str) -> BinaryIO:
        e = self.stat(path)
        if e.is_dir:
            raise FileNotFoundError(f"{path} is a folder")
        conn = self._connect()  # a data transfer needs its own control connection
        try:
            conn.voidcmd("TYPE I")
            sock = conn.transfercmd("RETR " + self._full(path))
        except ftplib.error_perm as exc:
            conn.close()
            raise FileNotFoundError(path) from exc
        return io.BufferedReader(_FTPStream(conn, sock), buffer_size=1 << 20)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                with _suppress():
                    self._conn.quit()
                self._conn = None


class _suppress:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return True


# --------------------------------------------------------------------------------------------------
# S3 / MinIO
# --------------------------------------------------------------------------------------------------


class S3Storage(Storage):
    def __init__(self, bucket: str, prefix: str = "", endpoint_url: Optional[str] = None,
                 access_key: Optional[str] = None, secret_key: Optional[str] = None,
                 session_token: Optional[str] = None, region: Optional[str] = None, verify: bool = True,
                 client: Any = None):
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:  # pragma: no cover
            raise StorageError("S3 / MinIO needs the 'boto3' package (pip install boto3)") from exc
        self.bucket = bucket
        self.prefix = clean_path(prefix)
        self.endpoint_url = endpoint_url
        q = f"?endpoint={endpoint_url}" if endpoint_url else ""
        self.uri = f"s3://{bucket}/{self.prefix}{q}"
        self.client = client or boto3.client(
            "s3", endpoint_url=endpoint_url, aws_access_key_id=access_key, aws_secret_access_key=secret_key,
            aws_session_token=session_token, region_name=region or os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
            verify=verify, config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                                         retries={"max_attempts": 5, "mode": "standard"}))

    def _key(self, path: str) -> str:
        p = clean_path(path)
        return "/".join(x for x in (self.prefix, p) if x)

    def _rel(self, key: str) -> str:
        key = key.rstrip("/")
        if self.prefix:
            key = key[len(self.prefix):].lstrip("/")
        return key

    def _call(self, fn, **kwargs):
        from botocore.exceptions import BotoCoreError, ClientError
        try:
            return fn(**kwargs)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404", "NotFound"):
                raise FileNotFoundError(kwargs.get("Key") or kwargs.get("Prefix")) from exc
            if code == "NoSuchBucket":
                raise StorageError(f"bucket '{self.bucket}' does not exist") from exc
            raise StorageError(f"S3 error {code}: {exc}") from exc
        except BotoCoreError as exc:
            raise StorageError(f"S3 connection error: {exc}") from exc

    def list(self, path: str = "") -> List[Entry]:
        base = self._key(path)
        prefix = base + "/" if base else ""
        out: List[Entry] = []
        token = None
        while True:
            kw = {"Bucket": self.bucket, "Prefix": prefix, "Delimiter": "/"}
            if token:
                kw["ContinuationToken"] = token
            resp = self._call(self.client.list_objects_v2, **kw)
            for cp in resp.get("CommonPrefixes", []):
                rel = self._rel(cp["Prefix"])
                out.append(Entry(posixpath.basename(rel), rel, True))
            for obj in resp.get("Contents", []):
                if obj["Key"].endswith("/"):
                    continue  # folder marker object
                rel = self._rel(obj["Key"])
                out.append(Entry(posixpath.basename(rel), rel, False, obj["Size"], obj["LastModified"].timestamp(),
                                 obj.get("ETag", "").strip('"')))
            if not resp.get("IsTruncated"):
                break
            token = resp.get("NextContinuationToken")
        if not out and path and clean_path(path):
            if not self.exists(path):
                raise FileNotFoundError(path)
        return _sorted(out)

    def walk(self, path: str = "") -> Iterator[Entry]:
        base = self._key(path)
        prefix = base + "/" if base else ""
        token = None
        entries = []
        while True:
            kw = {"Bucket": self.bucket, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            resp = self._call(self.client.list_objects_v2, **kw)
            for obj in resp.get("Contents", []):
                if not obj["Key"].endswith("/"):
                    rel = self._rel(obj["Key"])
                    entries.append(Entry(posixpath.basename(rel), rel, False, obj["Size"],
                                         obj["LastModified"].timestamp(), obj.get("ETag", "").strip('"')))
            if not resp.get("IsTruncated"):
                break
            token = resp.get("NextContinuationToken")
        yield from sorted(entries, key=lambda e: e.path)

    def stat(self, path: str) -> Entry:
        p = clean_path(path)
        if not p and not self.prefix:
            return Entry("", "", True)
        key = self._key(path)
        try:
            h = self._call(self.client.head_object, Bucket=self.bucket, Key=key)
            return Entry(posixpath.basename(p), p, False, h["ContentLength"], h["LastModified"].timestamp(),
                         h.get("ETag", "").strip('"'))
        except FileNotFoundError:
            resp = self._call(self.client.list_objects_v2, Bucket=self.bucket, Prefix=key + "/", MaxKeys=1)
            if resp.get("KeyCount", 0) or resp.get("Contents") or resp.get("CommonPrefixes"):
                return Entry(posixpath.basename(p), p, True)
            raise

    def open(self, path: str) -> BinaryIO:
        resp = self._call(self.client.get_object, Bucket=self.bucket, Key=self._key(path))
        return io.BufferedReader(_BodyStream(resp["Body"]), buffer_size=1 << 20)


class _BodyStream(io.RawIOBase):
    def __init__(self, body):
        self._body = body

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        data = self._body.read(len(b))
        n = len(data)
        b[:n] = data
        return n

    def close(self) -> None:
        if not self.closed:
            with _suppress():
                self._body.close()
        super().close()


# --------------------------------------------------------------------------------------------------
# URI -> Storage
# --------------------------------------------------------------------------------------------------


def open_storage(uri: str, base_dir: Optional[str] = None, **options: Any) -> Storage:
    """
    Storage for a URI or a local path. Relative local paths are resolved against base_dir.
    options override / add to what the URI says (user, password, access_key, secret_key, region,
    endpoint_url, tls, timeout, verify ...).
    """
    uri = os.path.expandvars(str(uri).strip())
    if re.match(r"^[A-Za-z]:[\\/]", uri) or "://" not in uri:  # plain path (Windows or POSIX)
        p = Path(uri)
        if not p.is_absolute() and base_dir:
            p = Path(base_dir) / p
        return LocalStorage(str(p))
    u = urlparse(uri)
    scheme = u.scheme.lower()
    query = {k: v[-1] for k, v in parse_qs(u.query).items()}
    if scheme == "file":
        path = unquote(u.path)
        if re.match(r"^/[A-Za-z]:", path):
            path = path[1:]
        if u.netloc and u.netloc not in ("", "localhost"):
            path = f"//{u.netloc}{path}"  # UNC share
        return LocalStorage(path)
    if scheme in ("ftp", "ftps"):
        return FTPStorage(
            host=u.hostname or "", root=unquote(u.path or "/"), port=u.port or 21,
            user=options.get("user") or (unquote(u.username) if u.username else "anonymous"),
            password=options.get("password") or (unquote(u.password) if u.password else ""),
            tls=options.get("tls", scheme == "ftps"), timeout=float(options.get("timeout", 60)),
            passive=options.get("passive", True))
    if scheme in ("s3", "minio", "minios"):
        if scheme == "s3":
            bucket, prefix = u.netloc, u.path.lstrip("/")
            endpoint = options.get("endpoint_url") or query.get("endpoint") or os.environ.get("S3_ENDPOINT_URL")
        else:
            parts = u.path.lstrip("/").split("/", 1)
            bucket, prefix = parts[0], parts[1] if len(parts) > 1 else ""
            endpoint = options.get("endpoint_url") or f"{'https' if scheme == 'minios' else 'http'}://{u.hostname}" \
                                                      f"{':' + str(u.port) if u.port else ''}"
        if not bucket:
            raise ValueError(f"no bucket in {uri!r}")
        access = options.get("access_key") or (unquote(u.username) if scheme != "s3" and u.username else None)
        secret = options.get("secret_key") or (unquote(u.password) if scheme != "s3" and u.password else None)
        return S3Storage(bucket, prefix, endpoint_url=endpoint, access_key=access, secret_key=secret,
                         session_token=options.get("session_token"), region=options.get("region") or query.get("region"),
                         verify=str(options.get("verify", query.get("verify", "true"))).lower() not in ("0", "false", "no"))
    raise ValueError(f"unsupported storage URI {uri!r} (use a path, file://, ftp://, ftps://, s3://, minio://)")

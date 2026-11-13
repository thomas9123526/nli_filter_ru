"""
nli_storage.py - one interface for files on local disk, FTP(S), SFTP and S3 / MinIO.

Used by nli_filter.py / nli_models.py (corpus input from a server) and by the result viewer
(viewer/backend/nli_viewer/storage.py re-exports this module).

    from nli_storage import open_storage
    st = open_storage("D:/data/corpus")                                   # local folder
    st = open_storage("ftp://user:secret@ftp.example.com:21/corpus")      # FTP (ftps:// for FTP over TLS)
    st = open_storage("sftp://user@ssh.example.com:22/data/corpus", password="secret")  # SFTP (or key_file=)
    st = open_storage("s3://bucket/corpus?endpoint=http://minio:9000")    # S3 / MinIO
    st = open_storage("minio://minio:9000/bucket/corpus")                 # same, shorter (minios:// = https)

    st.list("books")                -> [Entry(name, path, is_dir, size, mtime)]
    st.walk("")                     -> every file below, recursively
    with st.open("books/a.jsonl.zst") as fh: fh.read(...)
    st.stat(path), st.exists(path), st.fingerprint(path), st.local_path(path)

    expand_remote("sftp://u:p@host/data/corpus")      -> [RemoteFile, ...]  (folder, one file, or a * pattern)
    download(remote_file, "local.jsonl.zst", retries=3)

Paths are relative, '/'-separated, and may not leave the storage root ('..' is refused), so paths that
come from a web request are safe to pass through.

Credentials: in the URI, in keyword options (user=, password=, access_key=, secret_key=, ...), or for
S3 the usual AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY environment variables. ${VAR} / $VAR in a URI is
replaced by the environment variable. display_uri / mask_uri never show passwords.

Optional packages: paramiko (sftp://), boto3 (s3:// minio://). FTP needs nothing extra.
"""
from __future__ import annotations

import abc
import ftplib
import io
import os
import logging
import posixpath
import re
import shutil
import socket
import threading
import uuid
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Dict, Iterator, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

__all__ = ["Entry", "Storage", "LocalStorage", "FTPStorage", "SFTPStorage", "S3Storage", "open_storage", "clean_path",
           "StorageError", "RemoteFile", "REMOTE_SCHEMES", "is_remote", "expand_remote", "download", "mask_uri"]

log = logging.getLogger("nli_storage")


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
    """File tree: reading for every storage; replace_file() (whole-file upload) where `writable` is True."""

    uri: str = ""
    writable: bool = False  # replace_file() is implemented (used by the viewer's corpus editing)

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

    def replace_file(self, path: str, local_file: str) -> None:
        """
        Replace the existing file `path` with the content of local_file, so that readers see either the old or the
        new file, never a half-written one: upload under a temporary name next to it, then rename it over the
        original (S3: one PUT, which is atomic per object). Raises StorageError (e.g. no write permission).
        """
        raise StorageError(f"{type(self).__name__} cannot write files")

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.display_uri!r})"


def _upload_name(full: str) -> str:
    """Temporary name next to the target: same folder, hidden, unique."""
    folder, name = posixpath.split(full)
    return posixpath.join(folder, f".{name}.upload-{os.getpid()}-{uuid.uuid4().hex[:8]}")


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

    writable = True

    def replace_file(self, path: str, local_file: str) -> None:
        full = self._full(path)
        tmp = full.with_name(f".{full.name}.upload-{os.getpid()}-{uuid.uuid4().hex[:8]}")
        try:
            shutil.copyfile(local_file, tmp)
            os.replace(tmp, full)
        except PermissionError as exc:
            raise StorageError(f"cannot replace {path}: no permission or the file is open in another program "
                               f"({exc})") from exc
        finally:
            with _suppress():
                tmp.unlink()


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

    writable = True

    def replace_file(self, path: str, local_file: str) -> None:
        full = self._full(path)
        tmp = _upload_name(full)
        conn = self._connect()  # own control connection for the transfer
        try:
            try:
                with open(local_file, "rb") as fh:
                    conn.storbinary("STOR " + tmp, fh, blocksize=1 << 20)
            except ftplib.error_perm as exc:
                raise StorageError(f"FTP upload to {posixpath.dirname(full)} refused (no write permission?): "
                                   f"{exc}") from exc
            try:
                conn.rename(tmp, full)  # most servers replace the target in one step
            except ftplib.error_perm:
                # servers that refuse to rename over an existing file: move the old one aside first
                old = _upload_name(full) + ".old"
                try:
                    conn.rename(full, old)
                except ftplib.error_perm as exc:
                    raise StorageError(f"FTP server refuses to replace {path}: {exc}") from exc
                try:
                    conn.rename(tmp, full)
                except ftplib.error_perm as exc:
                    with _suppress():
                        conn.rename(old, full)  # put the original back
                    raise StorageError(f"FTP server refuses to replace {path}: {exc}") from exc
                with _suppress():
                    conn.delete(old)
            tmp = None
        except (OSError, EOFError, ftplib.error_temp) as exc:
            raise StorageError(f"FTP upload of {path} failed: {exc}") from exc
        finally:
            if tmp is not None:
                with _suppress():
                    conn.delete(tmp)
            with _suppress():
                conn.quit()

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
# SFTP (SSH)
# --------------------------------------------------------------------------------------------------


class _SFTPStream(io.RawIOBase):
    """Read stream of one remote file; closes the file and its SFTP channel on close()."""

    def __init__(self, sftp, fh):
        self._sftp, self._fh = sftp, fh

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        data = self._fh.read(len(b))
        n = len(data)
        b[:n] = data
        return n

    def close(self) -> None:
        if not self.closed:
            with _suppress():
                self._fh.close()
            with _suppress():
                self._sftp.close()
        super().close()


class SFTPStorage(Storage):
    """
    Files on an SSH server (SFTP). Log in with a password, a private key file, or the keys of the local
    SSH agent / ~/.ssh when neither is given.

    host_key_check: 'warn' (default: unknown host keys are accepted and logged), 'strict' (the host must be
    in known_hosts / ~/.ssh/known_hosts) or 'off' (accept silently).
    """

    def __init__(self, host: str, root: str = "", port: int = 22, user: Optional[str] = None,
                 password: Optional[str] = None, key_file: Optional[str] = None, passphrase: Optional[str] = None,
                 known_hosts: Optional[str] = None, host_key_check: str = "warn", timeout: float = 60.0):
        try:
            import paramiko  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise StorageError("SFTP needs the 'paramiko' package (pip install paramiko)") from exc
        if host_key_check not in ("warn", "strict", "off"):
            raise ValueError("host_key_check must be warn, strict or off")
        self.host, self.port, self.user = host, int(port or 22), user or None
        self.password, self.key_file, self.passphrase = password or None, key_file or None, passphrase or None
        self.known_hosts, self.host_key_check, self.timeout = known_hosts, host_key_check, timeout
        # "/data/corpus" = absolute path; "" or "~" = login folder; "~/corpus" = below the login folder
        r = (root or "").replace("\\", "/")
        if r in ("", "/~", "~"):
            self.root = "."
        elif r.startswith(("/~/", "~/")):
            self.root = clean_path(r.split("~/", 1)[1]) or "."
        else:
            self.root = "/" + clean_path(r) if clean_path(r) else "/"
        cred = f"{self.user}{':x' if self.password else ''}@" if self.user else ""
        shown = self.root if self.root.startswith("/") else "/~/" + ("" if self.root == "." else self.root)
        self.uri = f"sftp://{cred}{host}:{self.port}{shown}"
        self._lock = threading.Lock()
        self._ssh = None
        self._sftp = None  # shared SFTP channel for listings

    # -- connection --------------------------------------------------------------------------------

    def _connect(self):
        import paramiko
        ssh = paramiko.SSHClient()
        with _suppress():
            ssh.load_system_host_keys()
        if self.known_hosts:
            try:
                ssh.load_host_keys(os.path.expanduser(self.known_hosts))
            except OSError as exc:
                raise StorageError(f"cannot read known_hosts file {self.known_hosts}: {exc}") from exc
        ssh.set_missing_host_key_policy({"warn": paramiko.WarningPolicy, "strict": paramiko.RejectPolicy,
                                         "off": paramiko.AutoAddPolicy}[self.host_key_check]())
        explicit = bool(self.password or self.key_file)
        try:
            ssh.connect(self.host, port=self.port, username=self.user, password=self.password,
                        key_filename=os.path.expanduser(self.key_file) if self.key_file else None,
                        passphrase=self.passphrase, timeout=self.timeout, banner_timeout=self.timeout,
                        auth_timeout=self.timeout, allow_agent=not explicit, look_for_keys=not explicit)
            ssh.get_transport().set_keepalive(30)
            return ssh
        except paramiko.AuthenticationException as exc:
            ssh.close()
            raise StorageError(f"SFTP login to {self.host} as {self.user or '(default user)'} failed: {exc}") from exc
        except paramiko.BadHostKeyException as exc:
            ssh.close()
            raise StorageError(f"SFTP host key of {self.host} does not match known_hosts: {exc}") from exc
        except (paramiko.SSHException, OSError, EOFError) as exc:
            ssh.close()
            raise StorageError(f"cannot connect to SFTP {self.host}:{self.port}: {exc}") from exc

    def _alive(self) -> bool:
        t = self._ssh.get_transport() if self._ssh is not None else None
        return bool(t and t.is_active())

    def _ensure(self):
        """Connected SSH client (call with the lock held)."""
        if not self._alive():
            self._drop()
            self._ssh = self._connect()
        return self._ssh

    def _drop(self) -> None:
        for obj in (self._sftp, self._ssh):
            if obj is not None:
                with _suppress():
                    obj.close()
        self._sftp = self._ssh = None

    def _with_sftp(self, fn):
        """Run fn(sftp) on the shared channel, reconnecting once if the connection dropped."""
        import paramiko
        with self._lock:
            for attempt in (1, 2):
                try:
                    ssh = self._ensure()
                    if self._sftp is None:
                        self._sftp = ssh.open_sftp()
                    return fn(self._sftp)
                except (FileNotFoundError, StorageError):
                    raise
                except PermissionError as exc:
                    raise StorageError(f"SFTP permission denied: {exc}") from exc
                except (paramiko.SSHException, EOFError, OSError) as exc:
                    self._drop()
                    if attempt == 2:
                        raise StorageError(f"SFTP error: {exc}") from exc

    # -- paths -------------------------------------------------------------------------------------

    def _full(self, path: str) -> str:
        p = clean_path(path)
        return posixpath.join(self.root, p) if p else self.root

    @staticmethod
    def _missing(exc: OSError, path: str) -> None:
        """Re-raise 'no such file' as FileNotFoundError(path); other errors unchanged."""
        if isinstance(exc, FileNotFoundError) or getattr(exc, "errno", None) == 2:
            raise FileNotFoundError(path) from exc
        raise exc

    def _stat_full(self, sftp, full: str, rel: str):
        try:
            return sftp.stat(full)  # follows symbolic links
        except OSError as exc:
            self._missing(exc, rel)

    # -- Storage -----------------------------------------------------------------------------------

    def list(self, path: str = "") -> List[Entry]:
        import stat as st_mod
        rel_dir = clean_path(path)
        full = self._full(path)

        def run(sftp):
            try:
                attrs = sftp.listdir_attr(full)
            except OSError as exc:
                self._missing(exc, rel_dir)
            out = []
            for a in attrs:
                if a.filename in (".", ".."):
                    continue
                rel = posixpath.join(rel_dir, a.filename) if rel_dir else a.filename
                if a.st_mode is not None and st_mod.S_ISLNK(a.st_mode):
                    try:
                        a = sftp.stat(posixpath.join(full, a.filename))
                    except OSError:
                        continue  # broken link
                is_dir = bool(a.st_mode is not None and st_mod.S_ISDIR(a.st_mode))
                out.append(Entry(posixpath.basename(rel), rel, is_dir, None if is_dir else a.st_size,
                                 float(a.st_mtime) if a.st_mtime is not None else None))
            return out

        return _sorted(self._with_sftp(run))

    def stat(self, path: str) -> Entry:
        import stat as st_mod
        p = clean_path(path)
        a = self._with_sftp(lambda sftp: self._stat_full(sftp, self._full(p), p))
        is_dir = bool(a.st_mode is not None and st_mod.S_ISDIR(a.st_mode))
        return Entry(posixpath.basename(p), p, is_dir, None if is_dir else a.st_size,
                     float(a.st_mtime) if a.st_mtime is not None else None)

    def open(self, path: str) -> BinaryIO:
        e = self.stat(path)
        if e.is_dir:
            raise FileNotFoundError(f"{path} is a folder")
        with self._lock:
            sftp = self._ensure().open_sftp()  # a transfer gets its own channel on the same connection
        try:
            fh = sftp.open(self._full(path), "rb")
            fh.prefetch(e.size)  # pipelined reads: much faster than one request per block
        except OSError as exc:
            sftp.close()
            self._missing(exc, clean_path(path))
        return io.BufferedReader(_SFTPStream(sftp, fh), buffer_size=1 << 20)

    writable = True

    def replace_file(self, path: str, local_file: str) -> None:
        full = self._full(path)
        tmp = _upload_name(full)
        with self._lock:
            sftp = self._ensure().open_sftp()  # own channel for the transfer
        try:
            try:
                sftp.put(local_file, tmp, confirm=True)  # confirm: compares the size after the upload
            except PermissionError as exc:
                raise StorageError(f"SFTP upload to {posixpath.dirname(full)} refused (no write permission): "
                                   f"{exc}") from exc
            try:
                sftp.posix_rename(tmp, full)  # OpenSSH: replaces the target in one step
            except OSError:
                # server without posix-rename: move the old file aside, put the new one in place, remove the old
                old = _upload_name(full) + ".old"
                try:
                    sftp.rename(full, old)
                except OSError as exc:
                    raise StorageError(f"SFTP server refuses to replace {path}: {exc}") from exc
                try:
                    sftp.rename(tmp, full)
                except OSError as exc:
                    with _suppress():
                        sftp.rename(old, full)
                    raise StorageError(f"SFTP server refuses to replace {path}: {exc}") from exc
                with _suppress():
                    sftp.remove(old)
            tmp = None
        except StorageError:
            raise
        except (OSError, EOFError) as exc:
            raise StorageError(f"SFTP upload of {path} failed: {exc}") from exc
        finally:
            if tmp is not None:
                with _suppress():
                    sftp.remove(tmp)
            with _suppress():
                sftp.close()

    def close(self) -> None:
        with self._lock:
            self._drop()


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

    writable = True

    def replace_file(self, path: str, local_file: str) -> None:
        # one PUT (multipart for big files): readers see the old object until the new one is complete
        from boto3.exceptions import S3UploadFailedError
        try:
            self._call(self.client.upload_file, Filename=local_file, Bucket=self.bucket, Key=self._key(path))
        except S3UploadFailedError as exc:
            raise StorageError(f"S3 upload of {path} failed (no write permission?): {exc}") from exc


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
    if scheme == "sftp":
        key_file = options.get("key_file") or query.get("key_file")
        if key_file and base_dir and not os.path.isabs(os.path.expanduser(key_file)):
            key_file = os.path.normpath(os.path.join(base_dir, key_file))
        return SFTPStorage(
            host=u.hostname or "", root=unquote(u.path or ""), port=u.port or 22,
            user=options.get("user") or (unquote(u.username) if u.username else None),
            password=options.get("password") or (unquote(u.password) if u.password else None),
            key_file=key_file, passphrase=options.get("passphrase"),
            known_hosts=options.get("known_hosts") or query.get("known_hosts"),
            host_key_check=options.get("host_key_check") or query.get("host_key_check") or "warn",
            timeout=float(options.get("timeout", 60)))
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
    raise ValueError(f"unsupported storage URI {uri!r} (use a path, file://, ftp://, ftps://, sftp://, s3://, minio://)")


def mask_uri(text: str) -> str:
    """Hide the password of every URI in a text (user:secret@host -> user:***@host)."""
    return _mask(str(text))


# --------------------------------------------------------------------------------------------------
# Corpus input from a server (nli_filter.py / nli_models.py)
# --------------------------------------------------------------------------------------------------

REMOTE_SCHEMES = ("ftp", "ftps", "sftp", "s3", "minio", "minios")
_GLOB_CHARS = re.compile(r"[*?\[]")


def is_remote(item: Any) -> bool:
    """True for ftp:// ftps:// sftp:// s3:// minio:// minios:// (not for local paths or file://)."""
    m = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*)://", str(item))
    return bool(m) and m.group(1).lower() in REMOTE_SCHEMES


def _join_uri(uri: str, path: str) -> str:
    """URI of a file below a storage URI, without the ?query (so the text still ends in .jsonl.zst etc.)."""
    return uri.partition("?")[0].rstrip("/") + "/" + path


class RemoteFile(str):
    """
    A file on a server. Its text is the URL without password and ?options (safe to print and to store, and it
    ends with the file name, so suffix checks such as .endswith(".zst") work); .storage is the open Storage
    (shared by all files of one input), .path the path below the storage root, .size the size in bytes (when
    the server listed it).
    """

    storage: Storage
    path: str
    size: Optional[int]

    def __new__(cls, storage: Storage, path: str, size: Optional[int] = None) -> "RemoteFile":
        obj = str.__new__(cls, _join_uri(storage.display_uri, path))
        obj.storage, obj.path, obj.size = storage, path, size
        return obj

    def open(self) -> BinaryIO:
        return self.storage.open(self.path)

    @property
    def layout_key(self) -> str:
        """'/'-path that is unique across servers: /<scheme>_<host>/<root>/<path>."""
        u = urlparse(self.storage.display_uri)
        host = f"{u.scheme}_{u.hostname or ''}" + (f"_{u.port}" if u.port else "")
        return posixpath.join("/", host, u.path.lstrip("/"), self.path)


def _glob_regex(pattern: str) -> "re.Pattern[str]":
    """Glob over '/'-paths: * and ? stay inside one folder, ** spans folders, [..] as usual."""
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            j = pattern.find("]", i + 1)
            if j < 0:
                out.append(re.escape(c))
                i += 1
            else:
                body = pattern[i + 1:j]
                out.append("[" + ("^" + body[1:] if body.startswith("!") else body) + "]")
                i = j + 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("".join(out) + r"\Z")


def expand_remote(uri: str, supported=lambda name: True, **options: Any) -> List[RemoteFile]:
    """
    Files behind a server URL, sorted by path:
      a folder        -> every supported file below it (recursively)
      one file        -> that file (the last part has a supported suffix and is not a folder)
      a glob pattern  -> matching files; * ? [..] inside one folder, ** across folders
                         (e.g. sftp://host/data/corpus/**/*.zst)
    FileNotFoundError when nothing is there.
    """
    uri = os.path.expandvars(str(uri).strip())
    base, q, query = uri.partition("?")
    query = q + query
    m = re.match(r"^([^:/]+://[^/]*)(/.*)?$", base)
    if not m:
        raise ValueError(f"not a server URL: {mask_uri(uri)}")
    head, path = m.group(1), m.group(2) or ""
    parts = path.split("/")
    star = next((i for i, part in enumerate(parts) if _GLOB_CHARS.search(part)), None)
    if star is not None:
        st = open_storage(head + "/".join(parts[:star]) + query, **options)
        rx = _glob_regex("/".join(parts[star:]))
        files = [e for e in st.walk("") if rx.match(e.path)]
        if not files:
            raise FileNotFoundError(f"no files match {mask_uri(uri)}")
    else:
        files, st = [], None
        name = parts[-1]
        if name and supported(name):
            st = open_storage(head + "/".join(parts[:-1]) + query, **options)
            try:
                e = st.stat(name)
            except FileNotFoundError:
                raise FileNotFoundError(mask_uri(uri)) from None
            if not e.is_dir:
                files = [e]
            else:
                st.close()
                st = None
        if st is None:
            st = open_storage(head + path + query, **options)
            try:
                files = [e for e in st.walk("") if supported(e.name)]
            except FileNotFoundError:
                raise FileNotFoundError(mask_uri(uri)) from None
    return [RemoteFile(st, e.path, e.size) for e in sorted(files, key=lambda e: e.path)]


def download(rf: RemoteFile, dest: str, retries: int = 3, wait: float = 5.0) -> int:
    """
    Copy a remote file to dest (written as dest + '.part', renamed when complete). Network errors and short
    downloads are retried `retries` times (waiting wait, 2 x wait, ... seconds). Returns the number of bytes.
    """
    tmp = dest + ".part"
    attempt = 0
    while True:
        attempt += 1
        try:
            with rf.open() as src, open(tmp, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            got = os.path.getsize(tmp)
            if rf.size is not None and got != rf.size:
                raise StorageError(f"incomplete download ({got} of {rf.size} bytes)")
            os.replace(tmp, dest)
            return got
        except FileNotFoundError:
            with _suppress():
                os.remove(tmp)
            raise
        except Exception as exc:  # network errors come as OSError, EOFError, paramiko / botocore errors ...
            with _suppress():
                os.remove(tmp)
            if attempt > retries:
                raise StorageError(f"download of {rf} failed after {attempt} attempt(s): {exc}") from exc
            log.warning("download of %s failed (%s); retry %d of %d in %.0fs", rf, exc, attempt, retries, wait * attempt)
            time.sleep(wait * attempt)

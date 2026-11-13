"""Editing corpus lines on FTP / SFTP / S3 servers: safe upload, backup, undo, conflicts, read-only accounts."""
import gzip
import json
import os
import socket
import threading
from pathlib import Path

import pytest
import zstandard

from conftest import build_tree
from nli_viewer.config import DatasetConfig, DatasetRegistry, ViewerConfig
from nli_viewer.edit import EditConflict, EditError


def _port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _content(name: str, data: bytes) -> bytes:
    if name.endswith(".zst"):
        return zstandard.ZstdDecompressor().stream_reader(data).read()
    if name.endswith(".gz"):
        return gzip.decompress(data)
    return data


@pytest.fixture()
def tree(tmp_path):
    return build_tree(tmp_path / "tree")


# ---- servers ---------------------------------------------------------------------------------------------------

@pytest.fixture()
def ftp(tree):
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer
    auth = DummyAuthorizer()
    auth.add_user("writer", "pw", str(tree), perm="elradfmw")
    auth.add_user("reader", "pw", str(tree), perm="elr")
    handler = type("H", (FTPHandler,), {"authorizer": auth})
    port = _port()
    server = FTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, kwargs={"timeout": 0.2}, daemon=True).start()
    yield port
    server.close_all()


def _sftp_server(root: str, with_posix_rename: bool):
    import paramiko
    from paramiko import SFTP_OK, SFTPAttributes, SFTPHandle, SFTPServer, SFTPServerInterface

    class Auth(paramiko.ServerInterface):
        def check_auth_password(self, username, password):
            return paramiko.AUTH_SUCCESSFUL if password == "pw" else paramiko.AUTH_FAILED

        def get_allowed_auths(self, username):
            return "password"

        def check_channel_request(self, kind, chanid):
            return paramiko.OPEN_SUCCEEDED

    class Handle(SFTPHandle):
        def stat(self):
            return SFTPAttributes.from_stat(os.fstat((self.readfile or self.writefile).fileno()))

    class Files(SFTPServerInterface):
        def _real(self, path):
            return root + self.canonicalize(path)

        def list_folder(self, path):
            try:
                out = []
                for name in os.listdir(self._real(path)):
                    a = SFTPAttributes.from_stat(os.stat(os.path.join(self._real(path), name)))
                    a.filename = name
                    out.append(a)
                return out
            except OSError as e:
                return SFTPServer.convert_errno(e.errno)

        def stat(self, path):
            try:
                return SFTPAttributes.from_stat(os.stat(self._real(path)))
            except OSError as e:
                return SFTPServer.convert_errno(e.errno)

        lstat = stat

        def open(self, path, flags, attr):
            write = flags & (os.O_WRONLY | os.O_RDWR)
            try:
                f = open(self._real(path), "wb" if write else "rb")
            except OSError as e:
                return SFTPServer.convert_errno(e.errno)
            h = Handle(flags)
            h.filename = path
            if write:
                h.writefile = f
            else:
                h.readfile = f
            return h

        def remove(self, path):
            try:
                os.remove(self._real(path))
                return SFTP_OK
            except OSError as e:
                return SFTPServer.convert_errno(e.errno)

        def rename(self, old, new):  # SFTP rename: refuses an existing target (like many servers)
            try:
                if os.path.exists(self._real(new)):
                    return SFTPServer.convert_errno(17)
                os.rename(self._real(old), self._real(new))
                return SFTP_OK
            except OSError as e:
                return SFTPServer.convert_errno(e.errno)

        if with_posix_rename:
            def posix_rename(self, old, new):  # OpenSSH extension: replaces the target
                try:
                    os.replace(self._real(old), self._real(new))
                    return SFTP_OK
                except OSError as e:
                    return SFTPServer.convert_errno(e.errno)

    key = paramiko.RSAKey.generate(2048)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(20)
    sock.settimeout(0.3)
    stop = threading.Event()
    transports = []

    def serve():
        while not stop.is_set():
            try:
                conn, _ = sock.accept()
            except OSError:
                continue
            t = paramiko.Transport(conn)
            t.add_server_key(key)
            t.set_subsystem_handler("sftp", SFTPServer, Files)
            try:
                t.start_server(server=Auth())
            except (paramiko.SSHException, EOFError, OSError):
                continue
            transports.append(t)

    threading.Thread(target=serve, daemon=True).start()

    def close():
        stop.set()
        for t in transports:
            t.close()
        sock.close()
    return sock.getsockname()[1], close


@pytest.fixture(params=[True, False], ids=["posix-rename", "plain-rename"])
def sftp(tree, request):
    port, close = _sftp_server(str(tree).replace("\\", "/"), with_posix_rename=request.param)
    yield port
    close()


@pytest.fixture()
def s3(tree):
    import boto3
    from moto.server import ThreadedMotoServer
    port = _port()
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=port)
    server.start()
    endpoint = f"http://127.0.0.1:{port}"
    c = boto3.client("s3", endpoint_url=endpoint, region_name="us-east-1", aws_access_key_id="test",
                     aws_secret_access_key="test")
    c.create_bucket(Bucket="nli")
    for p in (tree / "corpus").rglob("*"):
        if p.is_file():
            c.upload_file(str(p), "nli", "corpus/" + p.relative_to(tree / "corpus").as_posix())
    yield endpoint
    server.stop()


def _dataset(tree, tmp_path, corpus, **opts):
    cfg = ViewerConfig(datasets=[DatasetConfig(name="r", corpus=corpus, output=str(tree / "out"), editable=True,
                                               corpus_options=opts)],
                       cache_dir=str(tmp_path / "cache"), edits_dir=str(tmp_path / "edits"), base_dir=str(tmp_path))
    return DatasetRegistry(cfg).get("r")


def _server_lines(ds, rel):
    with ds.corpus.open(rel) as fh:
        return _content(rel, fh.read()).splitlines()


def _check_edit_and_undo(ds, tmp_path, rel):
    before = _server_lines(ds, rel)
    assert ds.edit_problem(rel) is None
    sha = ds.editor.read_line(rel, 2)["sha1"]
    out = ds.editor.edit_texts(rel, [{"line": 2, "text": "edited on the server", "sha1": sha},
                                     {"line": 4, "text": "and this line too"}])
    assert out["changed"] == 2
    after = _server_lines(ds, rel)
    assert json.loads(after[1])["text"] == "edited on the server" and json.loads(after[3])["text"] == "and this line too"
    assert [a for i, a in enumerate(after) if i not in (1, 3)] == [b for i, b in enumerate(before) if i not in (1, 3)]
    # the viewer reads the new file (its cache was filled from the checked copy)
    assert ds.corpus_lines(rel, 1, 5)["lines"][1]["text"] == "edited on the server"
    # backup of the server's original on this PC
    orig = tmp_path / "edits" / "r" / "originals" / rel
    assert _content(rel, orig.read_bytes()).splitlines() == before
    # no temporary upload files left on the server
    folder = rel.rsplit("/", 1)[0]
    assert not [e.name for e in ds.corpus.list(folder) if ".upload-" in e.name]
    for e in reversed(ds.editor.history(rel)):
        ds.editor.undo(e["edit"])
    assert _server_lines(ds, rel) == before


@pytest.mark.parametrize("rel", ["a/x.jsonl.zst", "a/y.jsonl.gz", "b/z.jsonl"])
def test_ftp(tree, tmp_path, ftp, rel):
    ds = _dataset(tree, tmp_path, f"ftp://writer:pw@127.0.0.1:{ftp}/corpus")
    _check_edit_and_undo(ds, tmp_path, rel)


@pytest.mark.parametrize("rel", ["a/x.jsonl.zst", "b/z.jsonl"])
def test_sftp(tree, tmp_path, sftp, rel):
    ds = _dataset(tree, tmp_path, f"sftp://writer@127.0.0.1:{sftp}/corpus", password="pw", host_key_check="off")
    _check_edit_and_undo(ds, tmp_path, rel)


@pytest.mark.parametrize("rel", ["a/x.jsonl.zst", "b/z.jsonl"])
def test_s3(tree, tmp_path, s3, rel):
    ds = _dataset(tree, tmp_path, f"s3://nli/corpus?endpoint={s3}", access_key="test", secret_key="test")
    _check_edit_and_undo(ds, tmp_path, rel)


def test_read_only_account_changes_nothing(tree, tmp_path, ftp):
    ds = _dataset(tree, tmp_path, f"ftp://reader:pw@127.0.0.1:{ftp}/corpus")
    rel = "a/x.jsonl.zst"
    before = (tree / "corpus" / rel).read_bytes()
    with pytest.raises(EditError, match="upload failed"):
        ds.editor.edit_text(rel, 1, "not allowed")
    assert (tree / "corpus" / rel).read_bytes() == before
    assert ds.editor.history() == []  # nothing logged
    assert not [p.name for p in (tree / "corpus" / "a").iterdir() if ".upload-" in p.name]


def test_file_changed_on_server_between_read_and_save(tree, tmp_path, ftp, monkeypatch):
    ds = _dataset(tree, tmp_path, f"ftp://writer:pw@127.0.0.1:{ftp}/corpus")
    rel = "a/x.jsonl.zst"
    ds.editor.read_line(rel, 1)
    before = (tree / "corpus" / rel).read_bytes()
    real = ds.corpus.fingerprint
    calls = {"n": 0}

    def fingerprint(path):  # the second look (just before the upload) sees another file
        calls["n"] += 1
        return real(path) + ("-changed" if calls["n"] >= 2 else "")
    monkeypatch.setattr(ds.corpus, "fingerprint", fingerprint)
    with pytest.raises(EditConflict, match="changed on the server"):
        ds.editor.edit_text(rel, 1, "too late")
    assert (tree / "corpus" / rel).read_bytes() == before

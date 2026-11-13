"""
Corpus input from a server (ftp:// sftp:// s3://) for nli_filter.py / nli_models.py.

Needs the test servers' packages (pyftpdlib, paramiko, moto, boto3); they are in the viewer's venv:
    viewer\\backend\\.venv\\Scripts\\python.exe -m pytest tests\\test_remote_input.py
Without them the tests are skipped.
"""
import functools
import json
import os
import socket
import threading

import pytest

pytest.importorskip("pyftpdlib")
pytest.importorskip("paramiko")
pytest.importorskip("moto")
pytest.importorskip("boto3")

import nli_filter as nf  # noqa: E402
import nli_storage  # noqa: E402
from conftest import FakePool  # noqa: E402
from nli_models import JsonlSource, expand_inputs  # noqa: E402
from test_nli_filter import read_lines, run, write_inputs  # noqa: E402

NAMES = ["a", "sub/b", "sub/c"]


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def tree(tmp_path_factory):
    root = tmp_path_factory.mktemp("srv")
    write_inputs(root / "corpus")
    return root


@pytest.fixture(scope="module")
def ftp_url(tree):
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer
    auth = DummyAuthorizer()
    auth.add_user("reader", "s3cret", str(tree), perm="elr")
    server = FTPServer(("127.0.0.1", _free_port()), type("H", (FTPHandler,), {"authorizer": auth}))
    threading.Thread(target=server.serve_forever, kwargs={"timeout": 0.5}, daemon=True).start()
    yield f"ftp://reader:s3cret@127.0.0.1:{server.address[1]}/corpus"
    server.close_all()


@pytest.fixture(scope="module")
def sftp_url(tree):
    import paramiko
    from paramiko import SFTPAttributes, SFTPHandle, SFTPServer, SFTPServerInterface
    root = str(tree)

    class Auth(paramiko.ServerInterface):
        def check_auth_password(self, username, password):
            return paramiko.AUTH_SUCCESSFUL if (username, password) == ("reader", "s3cret") else paramiko.AUTH_FAILED

        def get_allowed_auths(self, username):
            return "password"

        def check_channel_request(self, kind, chanid):
            return paramiko.OPEN_SUCCEEDED

    class Handle(SFTPHandle):
        def stat(self):
            return SFTPAttributes.from_stat(os.fstat(self.readfile.fileno()))

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
            try:
                f = open(self._real(path), "rb")
            except OSError as e:
                return SFTPServer.convert_errno(e.errno)
            h = Handle(flags)
            h.filename, h.readfile = path, f
            return h

    key = paramiko.RSAKey.generate(2048)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(20)
    sock.settimeout(0.5)
    stop, transports = threading.Event(), []

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
    yield f"sftp://reader:s3cret@127.0.0.1:{sock.getsockname()[1]}/corpus?host_key_check=off"
    stop.set()
    for t in transports:
        t.close()
    sock.close()


@pytest.fixture(scope="module")
def s3_url(tree):
    import boto3
    from moto.server import ThreadedMotoServer
    port = _free_port()
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=port)
    server.start()
    endpoint = f"http://127.0.0.1:{port}"
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    s3 = boto3.client("s3", endpoint_url=endpoint, region_name="us-east-1")
    s3.create_bucket(Bucket="nli")
    for p in tree.rglob("*"):
        if p.is_file():
            s3.upload_file(str(p), "nli", "data/" + p.relative_to(tree).as_posix())
    yield f"s3://nli/data/corpus?endpoint={endpoint}"
    server.stop()


@pytest.fixture(params=["ftp", "sftp", "s3"])
def url(request, ftp_url, sftp_url, s3_url):
    return {"ftp": ftp_url, "sftp": sftp_url, "s3": s3_url}[request.param]


def with_path(url, path):
    base, q, query = url.partition("?")
    return f"{base}/{path}" + (q + query if q else "")


def names_in(out):
    return sorted(str(p.relative_to(out)).replace("\\", "/")[: -len(".summary.json")]
                  for p in out.rglob("*.summary.json"))


# ---------------------------------------------------------------- tests


def test_same_result_as_local(url, tree, tmp_path):
    local = run(expand_inputs([str(tree / "corpus")]), tmp_path / "local")
    files = expand_inputs([url])
    assert all(isinstance(f, nli_storage.RemoteFile) for f in files)
    assert "s3cret" not in "".join(files)  # the file names never carry the password
    remote = run(files, tmp_path / "remote")
    expected = names_in(tmp_path / "local")
    assert names_in(tmp_path / "remote") == expected and set(NAMES) <= set(expected)
    for name in expected:
        for kind in ("decisions", "kept", "filtered"):
            a = (tmp_path / "local" / f"{name}.{kind}.jsonl").read_bytes()
            b = (tmp_path / "remote" / f"{name}.{kind}.jsonl").read_bytes()
            assert a == b, (name, kind)
    assert remote.total.lines == local.total.lines and remote.failed == 0
    assert not (tmp_path / "remote" / ".download").exists()  # downloaded copies are removed


def test_one_file_and_patterns(url, tmp_path):
    assert [f.path for f in expand_inputs([with_path(url, "a.jsonl")])] == ["a.jsonl"]
    assert [f.path for f in expand_inputs([with_path(url, "**/*.gz")])] == ["sub/b.jsonl.gz"]
    # paths count from the folder before the pattern (as for a local pattern)
    assert [f.path for f in expand_inputs([with_path(url, "sub/*")])] == ["b.jsonl.gz", "c.zip"]
    assert [f.path for f in expand_inputs([with_path(url, "*/*.zip")])] == ["sub/c.zip"]
    run(expand_inputs([with_path(url, "**/*.zip")]), tmp_path / "out")
    assert names_in(tmp_path / "out") == ["sub/c"]
    with pytest.raises(FileNotFoundError):
        expand_inputs([with_path(url, "nope.jsonl")])
    with pytest.raises(FileNotFoundError):
        expand_inputs([with_path(url, "*.nothing")])


def test_streaming_reader_matches_local(url, tree):
    """nli_models.JsonlSource reads a RemoteFile straight from the server (a .zip via a temporary file)."""
    for rf in expand_inputs([url]):
        local = tree / "corpus" / rf.path
        got = [(r.line, r.raw, r.error) for r in JsonlSource(rf).records()]
        want = [(r.line, r.raw, r.error) for r in JsonlSource(local).records()]
        assert got == want, rf.path


def test_resume_downloads_only_missing_files(sftp_url, tmp_path, monkeypatch):
    files = expand_inputs([sftp_url])
    run(files, tmp_path / "out")
    fetched = []
    real = nf.download
    monkeypatch.setattr(nf, "download", lambda rf, dest, **kw: fetched.append(rf.path) or real(rf, dest, **kw))
    r = run(expand_inputs([sftp_url]), tmp_path / "out")
    assert fetched == [] and all(f["status"] == "skipped (already done)" for f in r.files)
    (tmp_path / "out" / "sub" / "b.summary.json").unlink()
    r = run(expand_inputs([sftp_url]), tmp_path / "out")
    assert fetched == ["sub/b.jsonl.gz"]


def test_download_retry_and_failure(ftp_url, tmp_path, monkeypatch):
    monkeypatch.setattr(nf, "download", functools.partial(nli_storage.download, wait=0))
    files = expand_inputs([ftp_url])
    storage = files[0].storage
    real_open = storage.open
    calls = {}

    def flaky(path):
        calls[path] = calls.get(path, 0) + 1
        if path == "a.jsonl" and calls[path] == 1:
            raise nli_storage.StorageError("connection reset")  # fails once, then works
        if path == "sub/b.jsonl.gz":
            raise nli_storage.StorageError("connection reset")  # always fails
        return real_open(path)

    monkeypatch.setattr(storage, "open", flaky)
    r = run(files, tmp_path / "out", retries=2)
    status = {str(f["input"]).split("/corpus/")[-1]: f["status"] for f in r.files}
    assert status["a.jsonl"] == "done" and calls["a.jsonl"] == 2
    assert status["sub/b.jsonl.gz"].startswith("failed:") and calls["sub/b.jsonl.gz"] == 3
    assert status["sub/c.zip"] == "done" and r.failed == 1
    assert not (tmp_path / "out" / "sub" / "b.summary.json").exists()  # retried by the next run
    assert not list((tmp_path / "out").rglob("*.part"))


def test_cli_hides_password_and_reports_failures(sftp_url, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(nf, "NLIPool", lambda name, **kw: FakePool(name))
    out = tmp_path / "out"
    assert nf.main([sftp_url, "--output-dir", str(out), "--judge-model", "none"]) == 0
    text = (out / "summary.json").read_text(encoding="utf-8")
    assert "s3cret" not in text and "reader:***@" in text
    assert "s3cret" not in capsys.readouterr().out
    summ = json.loads(text)
    assert summ["stats"]["lines"] > 0 and all(f["status"] == "done" for f in summ["files"])
    # a folder that is not there
    assert nf.main([with_path(sftp_url, "missing"), "--output-dir", str(tmp_path / "o2")]) == 2
    err = capsys.readouterr().err
    assert "input not found" in err and "s3cret" not in err
    # wrong password
    bad = sftp_url.replace("s3cret", "wrong")
    assert nf.main([bad, "--output-dir", str(tmp_path / "o3")]) == 2
    err = capsys.readouterr().err
    assert "login" in err and "wrong" not in err


def test_keywords_report_from_server(url, tree, tmp_path, capsys):
    """--keywords-report streams the files from the server: same counts as for the local copy."""
    assert nf.main([str(tree / "corpus"), "--keywords-report", "--output-dir", str(tmp_path / "local")]) == 0
    assert nf.main([url, "--keywords-report", "--output-dir", str(tmp_path / "remote")]) == 0
    a = json.loads((tmp_path / "local" / "keywords_report.json").read_text(encoding="utf-8"))
    b = json.loads((tmp_path / "remote" / "keywords_report.json").read_text(encoding="utf-8"))
    for k in ("lines", "lines_with_keyword", "lines_rules_only", "lines_to_models", "estimate"):
        assert a[k] == b[k], k
    assert "s3cret" not in (tmp_path / "remote" / "keywords_report.json").read_text(encoding="utf-8")
    assert "s3cret" not in capsys.readouterr().out


def test_password_from_environment(sftp_url, monkeypatch):
    monkeypatch.setenv("NLI_TEST_PW", "s3cret")
    files = expand_inputs([sftp_url.replace("s3cret", "${NLI_TEST_PW}")])
    assert len(files) >= 3 and "s3cret" not in "".join(files)

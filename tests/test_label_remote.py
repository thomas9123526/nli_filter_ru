"""
nli_label.py with corpus input from a server (ftp:// sftp:// s3://): same labels as for the local copy, passwords
never written or printed, ${VAR} addresses reopened by sample / review / redecide, download failures skipped,
--shard. Uses the test servers of test_remote_input.py; run with the viewer's venv (it has their packages):
    viewer\\backend\\.venv\\Scripts\\python.exe -m pytest tests\\test_label_remote.py
"""
import json

import pytest

pytest.importorskip("pyftpdlib")
pytest.importorskip("paramiko")
pytest.importorskip("moto")
pytest.importorskip("boto3")

import nli_filter as nf  # noqa: E402
import nli_label  # noqa: E402
import nli_storage  # noqa: E402
from test_label import FakeScorer, small_policy  # noqa: E402
from test_remote_input import ftp_url, s3_url, sftp_url, tree, url  # noqa: E402,F401  (fixtures)


@pytest.fixture()
def policy_file(tmp_path):
    p = tmp_path / "policy.json"
    p.write_text(json.dumps(small_policy().data), encoding="utf-8")
    return str(p)


@pytest.fixture()
def fake_models(monkeypatch):
    monkeypatch.setattr(nli_label, "build_scorer", lambda args: (FakeScorer(), None, None))


def _all_text(folder):
    """Every output's text, .jsonl.zst decompressed (a password inside a compressed file must be found too)."""
    from nli_models import open_text
    out = []
    for p in folder.rglob("*"):
        if p.is_file() and (p.suffix in (".json", ".jsonl") or p.name.endswith(".jsonl.zst")):
            with open_text(p) as fh:
                out.append(fh.read())
    return "\n".join(out)


def _actions(folder):
    """{file: [doc actions]} from <name>.labels.jsonl or .labels.jsonl.zst (the default)."""
    from nli_models import open_text
    res = {}
    for p in sorted(list(folder.glob("*.labels.jsonl")) + list(folder.glob("*.labels.jsonl.zst"))):
        with open_text(p) as fh:
            res[p.name.split(".labels.")[0]] = [json.loads(x)["action"] for x in fh.read().splitlines() if x.strip()]
    return res


def test_same_labels_as_local_and_no_password(url, tree, tmp_path, policy_file, fake_models, capsys):
    local, remote = tmp_path / "local", tmp_path / "remote"
    assert nli_label.main(["run", str(tree / "corpus"), "--output-dir", str(local), "--policy", policy_file]) == 0
    assert nli_label.main(["run", url, "--output-dir", str(remote), "--policy", policy_file, "--write-clean"]) == 0
    assert _actions(local) == _actions(remote) and _actions(remote)
    assert "s3cret" not in _all_text(remote)
    assert "s3cret" not in capsys.readouterr().out
    summ = json.loads((remote / "summary.json").read_text(encoding="utf-8"))
    assert all(f["status"] == "done" for f in summ["files"]) and summ["files_failed"] == 0
    assert not list(remote.rglob("*.part")) and not list((remote / ".download").glob("*.*"))  # downloads removed


def test_literal_password_is_not_stored_so_no_reopen(sftp_url, tmp_path, policy_file, fake_models, capsys):
    out = tmp_path / "out"
    assert nli_label.main(["run", sftp_url, "--output-dir", str(out), "--policy", policy_file]) == 0
    assert "s3cret" not in _all_text(out) and "reader:***@" in (out / "summary.json").read_text(encoding="utf-8")
    assert not any("reopen" in json.loads(p.read_text(encoding="utf-8")) for p in out.glob("*.summary.json")
                   if not p.name.startswith("summary"))
    rc = nli_label.main(["sample", str(out), "--out", str(tmp_path / "s.jsonl"), "--policy", policy_file])
    err = capsys.readouterr().err
    assert rc == 2 and "environment variable" in err and "s3cret" not in err


def test_password_from_environment_reopens(sftp_url, tmp_path, policy_file, fake_models, monkeypatch, capsys):
    monkeypatch.setenv("NLI_CORPUS_PASSWORD", "s3cret")
    typed = sftp_url.replace("s3cret", "${NLI_CORPUS_PASSWORD}")
    out = tmp_path / "out"
    assert nli_label.main(["run", typed, "--output-dir", str(out), "--policy", policy_file]) == 0
    text = _all_text(out)
    assert "s3cret" not in text and "${NLI_CORPUS_PASSWORD}" in text
    s = tmp_path / "s.jsonl"
    assert nli_label.main(["sample", str(out), "--out", str(s), "--policy", policy_file, "--random", "3"]) == 0
    _, items = nli_label.read_labels_file(str(s))
    assert items and all(it["text"] for it in items) and "s3cret" not in s.read_text(encoding="utf-8")
    assert nli_label.main(["redecide", str(out), "--output-dir", str(tmp_path / "re"), "--policy", policy_file]) == 0
    assert _actions(tmp_path / "re") == _actions(out)
    assert "s3cret" not in capsys.readouterr().out


def test_download_failure_skips_the_file(ftp_url, tmp_path, policy_file, fake_models, monkeypatch):
    real = nli_storage.download

    def flaky(rf, dest, **kw):
        if rf.path == "sub/b.jsonl.gz":
            raise nli_storage.StorageError("connection reset")
        return real(rf, dest, **kw)

    monkeypatch.setattr(nf, "download", flaky)
    out = tmp_path / "out"
    assert nli_label.main(["run", ftp_url, "--output-dir", str(out), "--policy", policy_file, "--retries", "0"]) == 0
    summ = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    status = {f["name"]: f["status"] for f in summ["files"]}
    assert status["b"].startswith("failed:") and summ["files_failed"] == 1
    assert status["a"] == "done" and not (out / "b.summary.json").exists()  # retried by the next run
    monkeypatch.setattr(nf, "download", real)
    assert nli_label.main(["run", ftp_url, "--output-dir", str(out), "--policy", policy_file]) == 0
    status = {f["name"]: f["status"] for f in json.loads((out / "summary.json").read_text(encoding="utf-8"))["files"]}
    assert status["b"] == "done" and status["a"] == "skipped (done)"


def test_shards_cover_every_file_once(sftp_url, tmp_path, policy_file, fake_models):
    out = tmp_path / "out"
    for k in range(2):
        assert nli_label.main(["run", sftp_url, "--output-dir", str(out), "--policy", policy_file,
                               "--shard", f"{k}/2"]) == 0
    one = json.loads((out / "summary.shard0of2.json").read_text(encoding="utf-8"))
    two = json.loads((out / "summary.shard1of2.json").read_text(encoding="utf-8"))
    names = [f["name"] for f in one["files"]] + [f["name"] for f in two["files"]]
    assert sorted(names) == sorted(set(names)) and len(names) >= 3        # every file exactly once
    full = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    # each shard's summary merges every file finished so far: the last shard's (and summary.json) is complete
    assert full["stats"]["lines"] == two["stats"]["lines"] > one["stats"]["lines"] > 0
    assert nli_label.main(["run", sftp_url, "--output-dir", str(out), "--policy", policy_file,
                           "--shard", "2/2"]) == 2

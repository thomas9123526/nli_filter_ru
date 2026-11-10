import json

import pytest

from nli_viewer.lines import LineCache, LineFile
from nli_viewer.storage import FTPStorage, LocalStorage, S3Storage, clean_path, open_storage


def storages(tree, ftp_server, s3_server):
    return {
        "local": open_storage(str(tree)),
        "ftp": open_storage(ftp_server + "/"),
        "s3": open_storage(f"s3://nli/data?endpoint={s3_server}", access_key="test", secret_key="test"),
    }


@pytest.mark.parametrize("kind", ["local", "ftp", "s3"])
def test_list_walk_stat_open(kind, tree, ftp_server, s3_server):
    st = storages(tree, ftp_server, s3_server)[kind]
    names = [e.name for e in st.list("")]
    assert names[:2] == ["corpus", "out"]
    files = [e.path for e in st.walk("corpus")]
    assert files == ["corpus/a/x.jsonl.zst", "corpus/a/y.jsonl.gz", "corpus/b/z.jsonl", "corpus/c/w.zip"]
    e = st.stat("corpus/b/z.jsonl")
    assert not e.is_dir and e.size == (tree / "corpus/b/z.jsonl").stat().st_size
    assert st.stat("corpus/a").is_dir
    assert st.read_bytes("corpus/b/z.jsonl") == (tree / "corpus/b/z.jsonl").read_bytes()
    with pytest.raises(FileNotFoundError):
        st.stat("corpus/nope.jsonl")
    with pytest.raises(FileNotFoundError):
        st.open("corpus/nope.jsonl")
    st.close()


@pytest.mark.parametrize("kind", ["local", "ftp", "s3"])
@pytest.mark.parametrize("rel", ["a/x.jsonl.zst", "a/y.jsonl.gz", "b/z.jsonl", "c/w.zip"])
def test_line_access_every_format(kind, rel, tree, ftp_server, s3_server, tmp_path):
    st = storages(tree, ftp_server, s3_server)[kind]
    lf = LineFile(st, "corpus/" + rel, member="w1.jsonl" if rel.endswith(".zip") else None,
                  cache=LineCache(str(tmp_path / "cache")))
    assert len(lf) == 5
    assert json.loads(lf.line(1))["text"].startswith("Russia is")
    assert json.loads(lf.line(5))["text"] == ""
    assert [json.loads(b)["id"][-1] for b in lf.lines(2, 3)] == ["2", "3", "4"]
    assert not lf.line(4).endswith(b"\r")
    with pytest.raises(IndexError):
        lf.line(6)
    # second object reuses the cache (no rebuild)
    lf2 = LineFile(st, "corpus/" + rel, member="w1.jsonl" if rel.endswith(".zip") else None,
                   cache=LineCache(str(tmp_path / "cache")))
    assert lf2.line(3) == lf.line(3)


def test_line_numbering_matches_python(tmp_path):
    data = b'{"a":1}\n\n{"a":3}\r\n{"a":4}'  # blank line, CRLF, no final newline
    (tmp_path / "f.jsonl").write_bytes(data)
    lf = LineFile(LocalStorage(str(tmp_path)), "f.jsonl", cache=LineCache(str(tmp_path / "c")))
    with open(tmp_path / "f.jsonl", "rb") as fh:
        expected = [ln.rstrip(b"\r\n") for ln in fh]
    assert len(lf) == len(expected) == 4
    assert [lf.line(i) for i in range(1, 5)] == expected
    (tmp_path / "e.jsonl").write_bytes(b"")
    assert len(LineFile(LocalStorage(str(tmp_path)), "e.jsonl", cache=LineCache(str(tmp_path / "c")))) == 0


def test_cache_invalidated_when_file_changes(tmp_path):
    p = tmp_path / "f.jsonl"
    p.write_bytes(b"1\n2\n")
    st = LocalStorage(str(tmp_path))
    cache = LineCache(str(tmp_path / "c"))
    assert len(LineFile(st, "f.jsonl", cache=cache)) == 2
    import os, time
    p.write_bytes(b"1\n2\n3\n")
    os.utime(p, (time.time() + 5, time.time() + 5))
    assert len(LineFile(st, "f.jsonl", cache=cache)) == 3


def test_cache_trim(tmp_path):
    st = LocalStorage(str(tmp_path))
    for i in range(5):
        (tmp_path / f"f{i}.jsonl.gz").write_bytes(__import__("gzip").compress(b"x" * 5000 + b"\n"))
    cache = LineCache(str(tmp_path / "c"), max_bytes=12000)
    for i in range(5):
        assert len(LineFile(st, f"f{i}.jsonl.gz", cache=cache)) == 1
    assert cache.usage() <= 12000 + 6000  # newest entry is always kept


@pytest.mark.parametrize("bad", ["../x", "a/../../b", "C:/Windows", "//server/share", "a/../.."])
def test_clean_path_refuses_escapes(bad):
    with pytest.raises(ValueError):
        clean_path(bad)


def test_clean_path_normalises():
    assert clean_path("/a//b/./c/") == "a/b/c"
    assert clean_path("a\\b") == "a/b"


def test_open_storage_uris(tmp_path):
    assert isinstance(open_storage(str(tmp_path)), LocalStorage)
    assert isinstance(open_storage(tmp_path.as_uri()), LocalStorage)
    f = open_storage("ftp://u:p%40ss@host.example:2121/data/x")
    assert isinstance(f, FTPStorage) and f.port == 2121 and f.password == "p@ss" and f.root == "/data/x"
    assert "p@ss" not in f.display_uri
    s = open_storage("minio://key:secret@minio.lan:9000/bucket/pre/fix")
    assert isinstance(s, S3Storage) and s.bucket == "bucket" and s.prefix == "pre/fix"
    assert s.endpoint_url == "http://minio.lan:9000" and "secret" not in s.display_uri
    with pytest.raises(ValueError):
        open_storage("gopher://x/y")


def test_wrong_ftp_password(tree, ftp_server):
    from nli_viewer.storage import StorageError
    bad = ftp_server.replace("s3cret", "wrong")
    with pytest.raises(StorageError):
        open_storage(bad + "/").list("")

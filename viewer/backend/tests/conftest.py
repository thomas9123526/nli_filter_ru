"""Shared fixtures: a tiny corpus + nli_filter-style output folder, and FTP / S3 servers serving them."""
from __future__ import annotations

import gzip
import io
import json
import os
import socket
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest
import zstandard

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TEXTS = [
    ("a-1", "Russia is the largest country in the world by area.", "filter"),
    ("a-2", "Preheat the oven to 200 degrees.", "keep"),
    ("a-3", "Available languages: English, German, Russian.", "keep"),
    ("a-4", "Russian River Brewing Company sponsored the lecture. The speaker discussed Russia's crisis.", "filter"),
    ("a-5", "", "keep"),
]


def _lines(prefix: str):
    return [json.dumps({"id": f"{prefix}{i}", "text": t, "expect": e}) for i, (_, t, e) in enumerate(TEXTS, 1)]


def _decision(n: int, rec_id: str, text: str, expect: str, source: str = None):
    d = {"line": n, "decision": "keep", "reason": "no_keyword", "id": rec_id, "expect": expect}
    if source:
        d = {"source": source, **d}
    if not text:
        d["reason"] = "no_text"
        return d
    i = text.find("Russia")
    if i < 0:
        return d
    end = i + (7 if text[i:i + 7] == "Russian" else 6)
    hits = [{"kw": text[i:end], "span": [i, end]}]
    if "languages" in text:
        hits[0]["rule"] = "language_menu"
        d.update(reason="rules_incidental", hits=hits)
        return d
    c1 = {"score": 0.97, "positive": True, "hyp": "topic", "window": [0, len(text)],
          "pairs": [{"window": [0, len(text)], "hyp": "topic", "fast": 0.9, "judge": 0.97, "score": 0.97}]}
    hits[0]["check2"] = {"window": [0, len(text)], "hyp": "company_name", "fast": 0.1, "judge": None, "score": 0.1,
                         "incidental": False}
    d.update(decision="filter", reason="about_country", check1=c1, hits=hits)
    return d


RUN = {
    "country": {"name": "Russia", "adj": "Russian"},
    "hypotheses": {"check1": {"topic": "This text is about Russia."},
                   "check2": {"company_name": "This text mentions Russia only as part of a company name."}},
    "settings": {"check1_threshold": 0.8, "check2_threshold": 0.8, "uncertain_band": [0.6, 0.95],
                 "text_field": "text", "id_field": "id", "expect_field": "expect", "write_split": False},
    "models": {"fast": {"model": "modernbert", "mode": "single", "devices": ["cpu"], "dtype": "float32"},
               "judge": {"model": "deberta"}},
    "timing": {"load_seconds": 1, "run_seconds": 2, "lines_per_second": 1, "fast_pairs": 4, "judge_pairs": 1,
               "pairs_per_second": 2},
    "files": [], "stats": {"lines": 0}, "finished": "2026-11-09 10:00:00",
}


def _summary(decisions, input_name, outputs):
    st = {"lines": len(decisions), "decisions": {}, "reasons": {}, "rules": {}, "hits": 0, "check1_windows": 0,
          "check2_hits": 0}
    conf = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    for d in decisions:
        st["decisions"][d["decision"]] = st["decisions"].get(d["decision"], 0) + 1
        st["reasons"][d["reason"]] = st["reasons"].get(d["reason"], 0) + 1
        cell = {("filter", "filter"): "tp", ("keep", "filter"): "fp", ("keep", "keep"): "tn",
                ("filter", "keep"): "fn"}[(d["expect"], d["decision"])]
        conf[cell] += 1
    st["eval"] = {"confusion": conf, "metrics": {"accuracy": (conf["tp"] + conf["tn"]) / len(decisions),
                                                 "fp": conf["fp"], "fn": conf["fn"]}, "by_group": {}}
    return {"input": input_name, "complete": True, "seconds": 1.0, "stats": st, "outputs": outputs}


def build_tree(root: Path) -> Path:
    corpus, out = root / "corpus", root / "out"
    files = {  # key -> (corpus relative path, writer)
        "a/x": "a/x.jsonl.zst",
        "a/y": "a/y.jsonl.gz",
        "b/z": "b/z.jsonl",
        "c/w": "c/w.zip",
    }
    for key, rel in files.items():
        prefix = key.replace("/", "") + "-"
        lines = _lines(prefix)
        p = corpus / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        data = ("\n".join(lines) + "\n").encode()
        if rel.endswith(".zst"):
            p.write_bytes(zstandard.ZstdCompressor().compress(data))
        elif rel.endswith(".gz"):
            p.write_bytes(gzip.compress(data))
        elif rel.endswith(".zip"):
            with zipfile.ZipFile(p, "w") as z:
                z.writestr("w1.jsonl", data)
        else:  # plain, CRLF line endings, no newline at the end
            p.write_bytes("\r\n".join(lines).encode())
        source = "w1.jsonl" if rel.endswith(".zip") else None
        decs = [_decision(n, f"{prefix}{n}", t, e, source) for n, (_, t, e) in enumerate(TEXTS, 1)]
        o = out / key
        o.parent.mkdir(parents=True, exist_ok=True)
        dec_name = f"{o.name}.decisions.jsonl" + (".zst" if rel.endswith(".zst") else "")
        dec_data = ("\n".join(json.dumps(d) for d in decs) + "\n").encode()
        (o.parent / dec_name).write_bytes(zstandard.ZstdCompressor().compress(dec_data)
                                          if dec_name.endswith(".zst") else dec_data)
        summ = _summary(decs, f"corpus\\{rel.replace('/', os.sep)}", {"decisions": f"/elsewhere/{dec_name}"})
        (o.parent / f"{o.name}.summary.json").write_text(json.dumps(summ))
    run = dict(RUN, files=[{"input": f"corpus/{rel}", "status": "done"} for rel in files.values()])
    (out / "summary.json").write_text(json.dumps(run))
    return root


@pytest.fixture(scope="session")
def tree(tmp_path_factory) -> Path:
    return build_tree(tmp_path_factory.mktemp("tree"))


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session")
def ftp_server(tree):
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer
    auth = DummyAuthorizer()
    auth.add_user("reader", "s3cret", str(tree), perm="elr")
    handler = type("H", (FTPHandler,), {"authorizer": auth})
    port = _free_port()
    server = FTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=server.serve_forever, kwargs={"timeout": 0.5}, daemon=True)
    t.start()
    yield f"ftp://reader:s3cret@127.0.0.1:{port}"
    server.close_all()


@pytest.fixture(scope="session")
def s3_server(tree):
    from moto.server import ThreadedMotoServer
    import boto3
    port = _free_port()
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=port)
    server.start()
    endpoint = f"http://127.0.0.1:{port}"
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    s3 = boto3.client("s3", endpoint_url=endpoint, region_name="us-east-1", aws_access_key_id="test",
                      aws_secret_access_key="test")
    s3.create_bucket(Bucket="nli")
    for p in tree.rglob("*"):
        if p.is_file():
            s3.upload_file(str(p), "nli", "data/" + p.relative_to(tree).as_posix())
    yield endpoint
    server.stop()

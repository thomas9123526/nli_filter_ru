"""translate.py: fallback between OpenAI-compatible providers, language check, cache, <think> stripping, alignment,
no key leaks. Uses small fake OpenAI-compatible servers (threaded http.server on free ports)."""
from __future__ import annotations

import json
import logging
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nli_viewer import translate
from nli_viewer.config import ViewerConfig
from nli_viewer.translate import language_check, split_pieces, strip_think, clean_answer

KEY = "sk-very-secret-test-key-123"
ZH = "这是一段中文翻译。"
RU = "Это перевод на русский язык."


class FakeServer:
    """mode: ok (answers in the asked language) | http500 | empty | wrong (always Russian) | wrong_once |
    think (wraps the answer in <think>) | echo (returns the user text tagged with the target)."""

    def __init__(self, mode: str = "ok", model: str = "fake-model"):
        self.mode, self.model = mode, model
        self.requests = []
        self.calls = 0
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                raw = json.dumps(obj, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path.endswith("/models"):
                    self._send(200, {"object": "list", "data": [{"id": outer.model, "object": "model"}]})
                else:
                    self._send(404, {"error": "no"})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append({"headers": dict(self.headers), "body": body})
                outer.calls += 1
                if outer.mode == "http500":
                    return self._send(500, {"error": "model crashed"})
                user = body["messages"][-1]["content"]
                zh = "Chinese" in user or "中文" in user
                ans = ZH if zh else RU
                if outer.mode == "empty":
                    ans = ""
                elif outer.mode == "wrong":
                    ans = RU if zh else "This is English, not Russian at all."
                elif outer.mode == "wrong_once" and outer.calls == 1:
                    ans = RU if zh else "English answer"
                elif outer.mode == "think":
                    ans = f"<think>let me think about it\nhmm</think>\n{ans}"
                elif outer.mode == "echo":
                    text = user.split("\n\n", 1)[1]
                    ans = f"[{'zh' if zh else 'ru'}] {text}"
                    ans = ans.replace("[zh]", "中文翻译").replace("[ru]", "русский перевод текста")
                self._send(200, {"choices": [{"message": {"role": "assistant", "content": ans}}]})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def servers():
    made = []

    def make(mode="ok", model="fake-model"):
        s = FakeServer(mode, model)
        made.append(s)
        return s
    yield make
    for s in made:
        s.close()


def _client(tmp_path: Path, providers, **extra) -> TestClient:
    cfg = ViewerConfig(datasets=[], base_dir=str(tmp_path))
    cfg.translate = {"targets": ["zh", "ru"], "providers": providers, **extra}
    app = FastAPI()
    translate.install(app, cfg)
    return TestClient(app)


def _prov(name, url, **kw):
    return {"name": name, "kind": "openai", "base_url": url, "model": f"{name}-model", "timeout": 5, **kw}


# ------------------------------------------------------------------ fallback

def test_first_ok(tmp_path, servers):
    a, b = servers(), servers()
    c = _client(tmp_path, [_prov("qwen", a.url), _prov("hunyuan", b.url, prompt="hunyuan")])
    r = c.post("/api/translate", json={"texts": ["Hello."], "target": "zh"}).json()
    assert r["ok"] and r["failed"] == 0
    x = r["results"][0]
    assert x["translation"] == ZH and x["provider"] == "qwen" and x["fallback"] is False and not x["cached"]
    assert x["model"] == "qwen-model" and x["errors"] == []
    assert b.calls == 0


@pytest.mark.parametrize("mode", ["down", "http500", "empty"])
def test_first_fails_fallback_answers(tmp_path, servers, mode):
    b = servers()
    a_url = f"http://127.0.0.1:{_closed_port()}/v1" if mode == "down" else servers(mode).url
    c = _client(tmp_path, [_prov("qwen", a_url), _prov("hunyuan", b.url, prompt="hunyuan")])
    r = c.post("/api/translate", json={"texts": ["Hello."], "target": "ru"}).json()
    x = r["results"][0]
    assert r["ok"] and x["translation"] == RU and x["provider"] == "hunyuan" and x["fallback"] is True
    assert x["errors"][0]["provider"] == "qwen"
    assert {"down": "cannot connect", "http500": "HTTP 500", "empty": "empty answer"}[mode] in x["errors"][0]["error"]


def test_unreachable_provider_skipped_for_a_while(tmp_path, servers):
    b = servers()
    c = _client(tmp_path, [_prov("qwen", f"http://127.0.0.1:{_closed_port()}/v1"), _prov("hunyuan", b.url)])
    c.post("/api/translate", json={"texts": ["One."], "target": "ru"})
    x = c.post("/api/translate", json={"texts": ["Two."], "target": "ru"}).json()["results"][0]
    assert x["provider"] == "hunyuan" and x["errors"][0]["error"].startswith("skipped: unreachable")


def test_both_fail_clear_error(tmp_path, servers):
    a = servers("http500")
    c = _client(tmp_path, [_prov("qwen", a.url), _prov("hunyuan", f"http://127.0.0.1:{_closed_port()}/v1")])
    resp = c.post("/api/translate", json={"texts": ["Hello.", "World."], "target": "zh"})
    assert resp.status_code == 200
    r = resp.json()
    assert r["ok"] is False and r["failed"] == 2 and "2 of 2 not translated" in r["error"]
    x = r["results"][0]
    assert x["ok"] is False and x["translation"] is None
    assert [e["provider"] for e in x["errors"]] == ["qwen", "hunyuan"]
    assert "qwen: HTTP 500" in x["error"] and "hunyuan: cannot connect" in x["error"]


def test_forced_provider_no_fallback(tmp_path, servers):
    a, b = servers("http500"), servers()
    c = _client(tmp_path, [_prov("qwen", a.url), _prov("hunyuan", b.url)])
    x = c.post("/api/translate", json={"texts": ["Hi."], "target": "zh", "provider": "qwen"}).json()["results"][0]
    assert x["ok"] is False and b.calls == 0
    x = c.post("/api/translate", json={"texts": ["Hi."], "target": "zh", "provider": "hunyuan"}).json()["results"][0]
    assert x["provider"] == "hunyuan" and x["fallback"] is False
    assert c.post("/api/translate", json={"texts": ["Hi."], "target": "zh", "provider": "nope"}).status_code == 400


def test_disabled_provider_skipped(tmp_path, servers):
    a, b = servers(), servers()
    c = _client(tmp_path, [_prov("qwen", a.url, enabled=False), _prov("hunyuan", b.url)])
    x = c.post("/api/translate", json={"texts": ["Hi."], "target": "zh"}).json()["results"][0]
    assert x["provider"] == "hunyuan" and a.calls == 0


# ------------------------------------------------------------------ language check

def test_wrong_language_retried_then_ok(tmp_path, servers):
    a, b = servers("wrong_once"), servers()
    c = _client(tmp_path, [_prov("qwen", a.url), _prov("hunyuan", b.url)])
    x = c.post("/api/translate", json={"texts": ["Shchi is a soup."], "target": "zh"}).json()["results"][0]
    assert x["provider"] == "qwen" and x["translation"] == ZH and a.calls == 2 and b.calls == 0
    assert "retried" in x["notes"][0]
    strict = a.requests[1]["body"]
    assert len(strict["messages"]) == 4 and strict["messages"][2]["role"] == "assistant"   # one-shot example


def test_wrong_language_twice_goes_to_next(tmp_path, servers):
    a, b = servers("wrong"), servers()
    c = _client(tmp_path, [_prov("qwen", a.url), _prov("hunyuan", b.url)])
    for target, want in (("zh", ZH), ("ru", RU)):
        x = c.post("/api/translate", json={"texts": [f"Text {target}."], "target": target}).json()["results"][0]
        assert x["provider"] == "hunyuan" and x["fallback"] and x["translation"] == want
        assert "wrong language" in x["errors"][0]["error"]
    assert a.calls == 4


# made-up Hangul syllables built from code points (no real words), for the "ko" script check
HANGUL = " ".join("".join(chr(0xAC00 + 588 * i + 28 * j) for j in range(3)) for i in range(5)) + "."


@pytest.mark.parametrize("text,target,ok", [
    (ZH, "zh", True),
    (RU, "ru", True),
    (RU, "zh", False),
    (ZH, "ru", False),
    ("This is English only, nothing translated.", "zh", False),
    ("This is English only, nothing translated.", "ru", False),
    ("斯特罗甘诺夫牛肉（Beef Stroganoff）首次出现在1871年Elena Molokhovets的食谱中。", "zh", True),
    ("Бефстроганов (Beef Stroganoff) впервые появился в 1871 году в книге Elena Molokhovets.", "ru", True),
    ("Щи — суп. 这是中文。", "zh", False),        # half / half
    ("1871 — 2026, 42%!", "zh", True),            # nothing to judge
    ("Moscow", "zh", True),                        # a single name: too short to judge
    ("Москва", "zh", False),                       # too short, but another script only
    ("こんにちは、これは日本語です。", "zh", False),  # kana
    (HANGUL, "ko", True),
    ("This is English only, nothing translated.", "ko", False),
    (ZH, "ko", False),
    (RU, "ko", False),
])
def test_language_check(text, target, ok):
    assert language_check(text, target)["ok"] is ok, language_check(text, target)


# ------------------------------------------------------------------ prompts

def test_prompts_and_sampling(tmp_path, servers):
    a, b = servers(), servers()
    c = _client(tmp_path, [_prov("qwen", a.url, no_think=True), _prov("hunyuan", b.url, prompt="hunyuan")])
    c.post("/api/translate", json={"texts": ["Hello."], "target": "zh", "provider": "qwen"})
    q = a.requests[0]["body"]
    assert q["chat_template_kwargs"] == {"enable_thinking": False}
    assert q["messages"][0]["role"] == "system"
    assert q["messages"][-1]["content"].startswith("Translate the following text into Chinese (简体中文).")
    assert "/no_think" not in q["messages"][-1]["content"]
    c.post("/api/translate", json={"texts": ["Hello."], "target": "zh", "provider": "hunyuan"})
    c.post("/api/translate", json={"texts": ["Hello."], "target": "ru", "provider": "hunyuan"})
    h_zh, h_ru = b.requests[0]["body"], b.requests[1]["body"]
    assert h_zh["messages"] == [{"role": "user", "content": "把下面的文本翻译成中文，不要额外解释。\n\nHello."}]
    assert h_ru["messages"][0]["content"] == \
        "Translate the following segment into Russian, without additional explanation.\n\nHello."
    assert (h_zh["top_k"], h_zh["top_p"], h_zh["repetition_penalty"], h_zh["temperature"]) == (20, 0.6, 1.05, 0.7)
    assert "chat_template_kwargs" not in h_zh


def test_no_think_tag_option(tmp_path, servers):
    a = servers()
    c = _client(tmp_path, [_prov("qwen", a.url, no_think=True, no_think_tag=True)])
    c.post("/api/translate", json={"texts": ["Hello."], "target": "ru"})
    assert "/no_think" in a.requests[0]["body"]["messages"][-1]["content"]


def test_think_stripped(tmp_path, servers):
    a = servers("think")
    c = _client(tmp_path, [_prov("qwen", a.url)])
    x = c.post("/api/translate", json={"texts": ["Hello."], "target": "ru"}).json()["results"][0]
    assert x["translation"] == RU


def test_strip_think_variants():
    assert strip_think("<think>a</think>B") == "B"
    assert strip_think("<THINK>a\nb</THINK>\n\nB <think>x</think>C") == "B C"
    assert strip_think("reasoning only</think>Answer") == "Answer"
    assert strip_think("Answer<think>never closed") == "Answer"
    assert clean_answer("Assistant: 你好") == "你好"
    assert clean_answer("<think></think>\nTranslation: Привет") == "Привет"


# ------------------------------------------------------------------ cache

def test_cache(tmp_path, servers):
    a = servers()
    c = _client(tmp_path, [_prov("qwen", a.url)])
    body = {"texts": ["Cache me."], "target": "zh"}
    x1 = c.post("/api/translate", json=body).json()["results"][0]
    x2 = c.post("/api/translate", json=body).json()["results"][0]
    assert not x1["cached"] and x2["cached"] and x2["translation"] == x1["translation"] and a.calls == 1
    files = list((tmp_path / ".viewer_cache" / "translate").rglob("*.json"))
    assert len(files) == 1 and json.loads(files[0].read_text("utf-8"))["provider"] == "qwen"
    x3 = c.post("/api/translate", json={**body, "nocache": True}).json()["results"][0]
    assert not x3["cached"] and a.calls == 2
    c.post("/api/translate", json={"texts": ["Cache me."], "target": "ru"})   # other target: not cached
    assert a.calls == 3


def test_cache_used_while_provider_down(tmp_path, servers):
    a, b = servers(), servers()
    c = _client(tmp_path, [_prov("qwen", a.url), _prov("hunyuan", b.url)])
    c.post("/api/translate", json={"texts": ["Old text."], "target": "zh"})
    a.close()
    x = c.post("/api/translate", json={"texts": ["Old text."], "target": "zh"}).json()["results"][0]
    assert x["provider"] == "qwen" and x["cached"]


def test_cache_key_includes_model(tmp_path, servers):
    a = servers()
    c1 = _client(tmp_path, [_prov("qwen", a.url, model="m1")])
    c1.post("/api/translate", json={"texts": ["Same."], "target": "zh"})
    c2 = _client(tmp_path, [_prov("qwen", a.url, model="m2")])
    x = c2.post("/api/translate", json={"texts": ["Same."], "target": "zh"}).json()["results"][0]
    assert not x["cached"] and a.calls == 2


# ------------------------------------------------------------------ paragraphs

def test_split_pieces_roundtrip():
    texts = ["One.", "\n\nA.\n\nB.\n", "A.\n \n\nB.\r\n\r\nC.", "  lead\n\n\n\ntrail  \n", "", "\n\n",
             "Line 1\nLine 2\n\nPara 2"]
    for t in texts:
        assert "".join(p + s for p, s in split_pieces(t)) == t
    assert [p for p, _ in split_pieces("A.\n\nB.\n\n\nC.") if p] == ["A.", "B.", "C."]
    assert [p for p, _ in split_pieces("Line 1\nLine 2\n\nP2") if p] == ["Line 1\nLine 2", "P2"]


def test_split_long_paragraph():
    long = " ".join(f"Sentence number {i} is here." for i in range(200))
    pieces = split_pieces(long, max_chars=500)
    assert len(pieces) > 5 and all(len(p) <= 500 for p, _ in pieces)
    assert "".join(p + s for p, s in pieces) == long
    no_breaks = "x" * 1200
    assert "".join(p + s for p, s in split_pieces(no_breaks, 500)) == no_breaks


def test_paragraph_alignment(tmp_path, servers):
    a = servers("echo")
    c = _client(tmp_path, [_prov("qwen", a.url)])
    text = "First paragraph.\n\nSecond one.\n\n\nThird.\n"
    x = c.post("/api/translate", json={"texts": [text], "target": "zh"}).json()["results"][0]
    assert x["pieces"] == 3 and a.calls == 3
    assert x["translation"] == "中文翻译 First paragraph.\n\n中文翻译 Second one.\n\n\n中文翻译 Third.\n"
    # "paragraphs": each item as one piece, results in the same order
    r = c.post("/api/translate", json={"paragraphs": ["P1", "P2\n\nstill P2", "", "P4"], "target": "ru"}).json()
    assert [x["translation"] for x in r["results"]] == ["русский перевод текста P1", "русский перевод текста P2\n\nstill P2", "", "русский перевод текста P4"]
    assert [x["index"] for x in r["results"]] == [0, 1, 2, 3]


# ------------------------------------------------------------------ keys

def test_key_sent_but_never_shown(tmp_path, servers, monkeypatch, caplog):
    monkeypatch.setenv("TEST_TRANSLATE_KEY", KEY)
    a, bad = servers(), servers("http500")
    caplog.set_level(logging.DEBUG)
    c = _client(tmp_path, [_prov("bad", bad.url, api_key_env="TEST_TRANSLATE_KEY"),
                           _prov("qwen", a.url, api_key_env="TEST_TRANSLATE_KEY")])
    texts = [c.post("/api/translate", json={"texts": ["Hi."], "target": "zh"}).text,
             c.get("/api/translate/settings").text,
             c.post("/api/translate/test", json={}).text]
    assert a.requests[0]["headers"]["Authorization"] == f"Bearer {KEY}"
    for t in texts:
        assert KEY not in t
    assert KEY not in caplog.text
    s = c.get("/api/translate/settings").json()
    assert s["providers"][0]["has_key"] is True and s["providers"][0]["api_key_env"] == "TEST_TRANSLATE_KEY"
    for p in s["providers"]:
        assert set(p) >= {"name", "kind", "base_url", "model", "enabled", "has_key"}


def test_no_key_no_header(tmp_path, servers, monkeypatch):
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    a = servers()
    c = _client(tmp_path, [_prov("qwen", a.url, api_key_env="QWEN_API_KEY")])
    c.post("/api/translate", json={"texts": ["Hi."], "target": "zh"})
    assert "Authorization" not in a.requests[0]["headers"]


def test_key_in_config_rejected(tmp_path, servers):
    with pytest.raises(ValueError):
        translate.parse_settings({"providers": [{"name": "q", "base_url": "http://x/v1", "model": "m",
                                                 "api_key": KEY}]})


# ------------------------------------------------------------------ settings / test / errors

def test_settings_and_test_endpoint(tmp_path, servers):
    a = servers(model="qwen-model")
    c = _client(tmp_path, [_prov("qwen", a.url), _prov("hunyuan", f"http://127.0.0.1:{_closed_port()}/v1"),
                           {"name": "local", "kind": "local", "model": "Hunyuan-MT-7B", "enabled": False}])
    s = c.get("/api/translate/settings").json()
    assert s["configured"] and [t["code"] for t in s["targets"]] == ["zh", "ru"]
    assert s["providers"][2]["base_url"] == "http://127.0.0.1:8001/v1" and s["providers"][2]["prompt"] == "hunyuan"
    r = c.post("/api/translate/test", json={}).json()
    q, h = r["providers"][0], r["providers"][1]
    assert q["reachable"] and q["models"] == ["qwen-model"] and q["model_served"]
    assert [x["target"] for x in q["samples"]] == ["zh", "ru"] and all(x["ok"] for x in q["samples"])
    assert q["samples"][0]["language"]["ok"] and "seconds" in q["samples"][0]
    assert h["reachable"] is False and h["samples"] == [] and h["error"]
    one = c.post("/api/translate/test", json={"provider": "qwen", "targets": ["ru"], "text": "Hi."}).json()
    assert len(one["providers"]) == 1 and one["text"] == "Hi."


def test_test_endpoint_reports_retry(tmp_path, servers):
    a = servers("wrong_once")
    c = _client(tmp_path, [_prov("qwen", a.url)])
    s = c.post("/api/translate/test", json={"targets": ["zh"]}).json()["providers"][0]["samples"][0]
    assert s["ok"] is False and s["retry"]["ok"] is True and "fixed" in s["error"]


def test_bad_requests(tmp_path, servers):
    a = servers()
    c = _client(tmp_path, [_prov("qwen", a.url)], targets=["zh"])
    assert c.post("/api/translate", json={"texts": ["x"], "target": "de"}).status_code == 400
    assert c.post("/api/translate", json={"texts": ["x"], "target": "ru"}).status_code == 400   # not in targets
    assert c.post("/api/translate", json={"target": "zh"}).status_code == 400
    assert c.post("/api/translate", json={"texts": ["x"], "paragraphs": ["y"], "target": "zh"}).status_code == 400


def test_not_configured(tmp_path):
    app = FastAPI()
    translate.install(app, ViewerConfig(datasets=[], base_dir=str(tmp_path)))
    c = TestClient(app)
    assert c.get("/api/translate/settings").json()["configured"] is False
    assert c.post("/api/translate", json={"texts": ["x"], "target": "zh"}).status_code == 503


def test_block_read_from_config_file(tmp_path, servers):
    """Without config.py keeping the block, it is read from viewer_config.json next to base_dir (and re-read)."""
    a = servers()
    f = tmp_path / "viewer_config.json"
    f.write_text('{\n  // comment\n  "datasets": [],\n  "translate": {"providers": [' +
                 json.dumps(_prov("qwen", a.url)) + "]}\n}", "utf-8")
    app = FastAPI()
    translate.install(app, ViewerConfig(datasets=[], base_dir=str(tmp_path)))
    c = TestClient(app)
    assert c.get("/api/translate/settings").json()["providers"][0]["name"] == "qwen"
    x = c.post("/api/translate", json={"texts": ["Hi."], "target": "zh"}).json()["results"][0]
    assert x["ok"] and x["provider"] == "qwen"
    import os
    import time
    f.write_text('{"datasets": [], "translate": {"providers": [' + json.dumps(_prov("other", a.url)) + "]}}", "utf-8")
    os.utime(f, (time.time() + 5, time.time() + 5))
    assert c.get("/api/translate/settings").json()["providers"][0]["name"] == "other"


# ------------------------------------------------------------------ editing the providers from the settings page

def _file_client(tmp_path, servers):
    a, b = servers(), servers()
    f = tmp_path / "viewer_config.json"
    f.write_text('{\n  // datasets\n  "datasets": [],\n  // translate buttons\n  "translate": {\n    "targets": ["zh", "ru"],\n'
                 '    "providers": [\n      // the first one\n      ' + json.dumps(_prov("qwen", a.url, api_key_env="QWEN_X")) +
                 ',\n      ' + json.dumps(_prov("hunyuan", b.url, prompt="hunyuan")) + '\n    ]\n  },\n  "after": 1\n}\n',
                 "utf-8")
    app = FastAPI()
    translate.install(app, ViewerConfig(datasets=[], base_dir=str(tmp_path)))
    return TestClient(app), f, a, b


def test_save_reorders_and_edits(tmp_path, servers):
    c, f, a, b = _file_client(tmp_path, servers)
    s = c.get("/api/translate/settings").json()
    assert s["editable"] and s["mtime"]
    r = c.post("/api/translate/settings/save", json={"mtime": s["mtime"], "providers": [
        {"name": "hunyuan", "timeout": 30},
        {"name": "qwen", "enabled": False, "base_url": "http://10.0.0.9:8000/v1/", "model": "qwen-x"}]})
    assert r.status_code == 200, r.text
    assert [p["name"] for p in r.json()["providers"]] == ["hunyuan", "qwen"]
    text = f.read_text("utf-8")
    assert "// datasets" in text and "// translate buttons" in text and '"after": 1' in text   # outside the block kept
    from nli_viewer.config import _strip_comments
    blk = json.loads(_strip_comments(text))["translate"]
    assert blk["targets"] == ["zh", "ru"]
    q = blk["providers"][1]
    assert q["base_url"] == "http://10.0.0.9:8000/v1" and q["model"] == "qwen-x" and q["enabled"] is False
    assert q["api_key_env"] == "QWEN_X" and blk["providers"][0]["timeout"] == 30 and blk["providers"][0]["prompt"] == "hunyuan"
    assert list((tmp_path / ".backup").glob("viewer_config.json.*"))
    # used at once: qwen is off, so hunyuan answers; the settings page shows the new order
    x = c.post("/api/translate", json={"texts": ["Hi."], "target": "zh"}).json()["results"][0]
    assert x["ok"] and x["provider"] == "hunyuan" and not x["fallback"]
    s2 = c.get("/api/translate/settings").json()
    assert [p["name"] for p in s2["providers"]] == ["hunyuan", "qwen"] and s2["providers"][1]["enabled"] is False
    # back on: "enabled" is left out again
    c.post("/api/translate/settings/save", json={"mtime": s2["mtime"], "providers": [{"name": "qwen", "enabled": True}, {"name": "hunyuan"}]})
    blk = json.loads(_strip_comments(f.read_text("utf-8")))["translate"]
    assert [p["name"] for p in blk["providers"]] == ["qwen", "hunyuan"] and "enabled" not in blk["providers"][0]


def test_save_refusals(tmp_path, servers):
    c, f, a, b = _file_client(tmp_path, servers)
    s = c.get("/api/translate/settings").json()
    before = f.read_text("utf-8")
    bad = [
        [{"name": "qwen"}],                                                   # one missing
        [{"name": "qwen"}, {"name": "qwen"}],                                 # twice
        [{"name": "qwen"}, {"name": "hunyuan"}, {"name": "new"}],            # unknown
        [{"name": "qwen", "base_url": "ftp://x"}, {"name": "hunyuan"}],
        [{"name": "qwen", "model": "  "}, {"name": "hunyuan"}],
        [{"name": "qwen", "timeout": 0}, {"name": "hunyuan"}],
    ]
    for provs in bad:
        r = c.post("/api/translate/settings/save", json={"mtime": s["mtime"], "providers": provs})
        assert r.status_code == 400, (provs, r.text)
    assert f.read_text("utf-8") == before
    # changed on disk since loaded
    r = c.post("/api/translate/settings/save", json={"mtime": str(int(s["mtime"]) - 1), "providers": [{"name": "hunyuan"}, {"name": "qwen"}]})
    assert r.status_code == 409 and f.read_text("utf-8") == before


def test_save_not_editable_without_file(tmp_path, servers):
    a = servers()
    c = _client(tmp_path, [_prov("qwen", a.url)])
    assert c.get("/api/translate/settings").json()["editable"] is False
    assert c.post("/api/translate/settings/save", json={"providers": [{"name": "qwen"}]}).status_code == 409


def test_save_real_config_shape(tmp_path):
    """The project's viewer_config.json: the block is found, rewritten, and the rest of the file is byte-identical."""
    from nli_viewer.translate import find_value_span, format_block, edited_block
    from nli_viewer.config import _strip_comments
    text = (Path(__file__).resolve().parents[2] / "viewer_config.json").read_text("utf-8")
    a, b, ind = find_value_span(text, "translate")
    blk = json.loads(_strip_comments(text))["translate"]
    new = edited_block(blk, [{"name": p["name"]} for p in reversed(blk["providers"])])
    out = text[:a] + format_block(new, ind) + text[b:]
    assert out[:a] == text[:a] and out[a + len(format_block(new, ind)):] == text[b:]
    data = json.loads(_strip_comments(out))
    assert [p["name"] for p in data["translate"]["providers"]] == [p["name"] for p in reversed(blk["providers"])]
    assert {k: v for k, v in data.items() if k != "translate"} == {k: v for k, v in json.loads(_strip_comments(text)).items() if k != "translate"}


def test_test_button_with_unsaved_values(tmp_path, servers):
    """The settings page's Test with a URL / model typed but not saved: that server is tried, nothing is written."""
    a, b = servers(), servers()
    c = _client(tmp_path, [_prov("qwen", "http://127.0.0.1:9/v1")])
    r = c.post("/api/translate/test", json={"provider": "qwen", "targets": ["zh"],
                                            "override": {"base_url": b.url + "/", "model": "fake-model"}}).json()
    p = r["providers"][0]
    assert p["reachable"] and p["base_url"] == b.url and p["model"] == "fake-model" and p["model_served"]
    assert c.get("/api/translate/settings").json()["providers"][0]["base_url"] == "http://127.0.0.1:9/v1"
    assert c.post("/api/translate/test", json={"provider": "qwen", "override": {"base_url": "nope"}}).status_code == 400

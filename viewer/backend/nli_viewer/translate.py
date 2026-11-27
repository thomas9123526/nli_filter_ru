"""
translate.py - translate texts shown in the viewer (for reading only: labels always come from the original text).

Settings: a "translate" block in viewer_config.json (see cmds/viewer/translate.md):

    "translate": {
      "targets": ["zh", "ru"],
      "providers": [
        {"name": "qwen", "kind": "openai", "base_url": "http://192.168.170.108:8000/v1", "model": "qwen3-4b",
         "api_key_env": "QWEN_API_KEY", "timeout": 60, "no_think": true},
        {"name": "hunyuan", "kind": "openai", "base_url": "http://127.0.0.1:8001/v1", "model": "Hunyuan-MT-7B",
         "prompt": "hunyuan", "timeout": 120}
      ]
    }

Providers are tried in order. A provider fails on: no connection, timeout, HTTP error, empty answer, or an answer in
the wrong language (checked by script; one retry with a stricter prompt first). Every provider speaks the
OpenAI-compatible /v1/chat/completions; "kind": "local" is the same protocol, served by tools/serve_translate_local.py.

The API key is read from the environment variable named by "api_key_env" (none set: no Authorization header). It is
never stored, logged or returned.

Long texts are split on blank lines (and very long paragraphs on line / sentence ends), translated piece by piece and
joined back with the same breaks. Each piece is cached in <cache_dir>/translate/, keyed by (text, target, provider,
model, prompt version).

Endpoints (wired by install(app, cfg)):
    POST /api/translate            {"texts": [...]} or {"paragraphs": [...]}, "target": "zh"|"ru",
                                   optional "provider" (force one, no fallback), "nocache"
    GET  /api/translate/settings   the providers (no keys) and targets; "editable" + "mtime" for the save below
    POST /api/translate/settings/save  order, on / off, base_url, model, timeout of the providers: rewrites only the
                                   "translate" block of viewer_config.json (old file to .backup/), refused when the
                                   file changed since it was loaded; used at once (the file is re-read on change)
    POST /api/translate/test       per provider: reachable, served models, a sample translation + language check
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel

log = logging.getLogger("nli_viewer.translate")

router = APIRouter(tags=["translate"])

PROMPT_VERSION = "1"            # part of the cache key: change when the prompts change
MAX_ITEMS = 500                 # texts / paragraphs per request
MAX_CHARS = 400_000             # characters per request
SAMPLE_TEXT = ("Shchi, a cabbage soup often made with sauerkraut, has been eaten for so long that an old saying "
               "calls 'shchi and kasha' the people's everyday food.")

# code -> (English name, own name, Hunyuan-MT target name)
LANGUAGES: Dict[str, Tuple[str, str, str]] = {
    "zh": ("Chinese", "简体中文", "中文"),
    "ru": ("Russian", "русский язык", "Russian"),
    "ko": ("Korean", "Korean", "Korean"),
}


# --------------------------------------------------------------------------------------------- settings

@dataclass
class Provider:
    name: str
    kind: str = "openai"            # openai | local (both: OpenAI-compatible HTTP)
    base_url: str = ""
    model: str = ""
    api_key_env: Optional[str] = None
    timeout: float = 60.0
    no_think: bool = False          # Qwen3: chat_template_kwargs.enable_thinking=false
    no_think_tag: bool = False      # also append "/no_think" to the message (made qwen3-4b prefix "Assistant:")
    prompt: str = "generic"         # generic | hunyuan
    enabled: bool = True
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    max_chars: int = 3000           # longer paragraphs are split on line / sentence ends

    def api_key(self) -> Optional[str]:
        return os.environ.get(self.api_key_env) or None if self.api_key_env else None

    def public(self) -> Dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "base_url": self.base_url, "model": self.model,
                "timeout": self.timeout, "no_think": self.no_think, "no_think_tag": self.no_think_tag,
                "prompt": self.prompt, "enabled": self.enabled,
                "api_key_env": self.api_key_env, "has_key": bool(self.api_key())}


@dataclass
class Settings:
    targets: List[str] = field(default_factory=lambda: ["zh", "ru"])
    providers: List[Provider] = field(default_factory=list)
    concurrency: int = 4
    down_seconds: float = 30.0      # a provider that could not be reached is skipped for this long
    configured: bool = False
    source: str = ""


def parse_settings(block: Optional[Dict[str, Any]], source: str = "") -> Settings:
    if not block:
        return Settings(source=source)
    s = Settings(configured=True, source=source)
    targets = block.get("targets") or ["zh", "ru"]
    bad = [t for t in targets if t not in LANGUAGES]
    if bad:
        raise ValueError(f"translate.targets: unknown {bad} (known: {sorted(LANGUAGES)})")
    s.targets = list(targets)
    s.concurrency = max(1, int(block.get("concurrency", 4)))
    s.down_seconds = float(block.get("down_seconds", 30))
    names = set()
    for p in block.get("providers") or []:
        kind = p.get("kind", "openai")
        if kind not in ("openai", "local"):
            raise ValueError(f"translate provider {p.get('name')}: kind must be openai or local, not {kind}")
        if "api_key" in p:
            raise ValueError("translate providers take the key from an environment variable: use \"api_key_env\"")
        d = {k: v for k, v in p.items() if k in Provider.__dataclass_fields__}
        if kind == "local":
            d.setdefault("base_url", "http://127.0.0.1:8001/v1")
            d.setdefault("prompt", "hunyuan")
            d.setdefault("timeout", 180)
        if not d.get("name") or not d.get("base_url") or not d.get("model"):
            raise ValueError(f"translate provider needs name, base_url and model: {p.get('name')}")
        if d["name"] in names:
            raise ValueError(f"translate: duplicate provider name {d['name']}")
        names.add(d["name"])
        prov = Provider(**d)
        prov.base_url = prov.base_url.rstrip("/")
        prov.timeout = float(prov.timeout)
        s.providers.append(prov)
    return s


def _config_file(cfg: Any) -> Optional[Path]:
    """The viewer_config.json the viewer was started with (best guess when the config does not record it)."""
    for cand in (getattr(cfg, "config_path", None), os.environ.get("NLI_VIEWER_CONFIG")):
        if cand:
            return Path(cand).resolve()
    p = Path(getattr(cfg, "base_dir", ".")) / "viewer_config.json"
    return p.resolve() if p.is_file() else None


def _read_block(path: Path) -> Optional[Dict[str, Any]]:
    from .config import _expand, _strip_comments
    data = _expand(json.loads(_strip_comments(path.read_text("utf-8"))))
    return data.get("translate")


# --------------------------------------------------------------------------------------------- text helpers

_THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)


def strip_think(text: str) -> str:
    """Remove <think>…</think> blocks; an unclosed <think> means the whole rest is reasoning, a lone </think> means
    everything before it was."""
    text = _THINK_RE.sub("", text or "")
    low = text.lower()
    if "</think>" in low:
        text = text[low.rfind("</think>") + len("</think>"):]
    elif "<think>" in low:
        text = text[:low.find("<think>")]
    return text.strip()


def split_pieces(text: str, max_chars: int = 3000) -> List[Tuple[str, str]]:
    """[(piece, separator_after)], joined back as ''.join(p + s). Blank-line breaks first; a paragraph longer than
    max_chars is split further on line ends, then sentence ends. Leading whitespace is kept as an empty piece."""
    out: List[Tuple[str, str]] = []
    lead = re.match(r"\s*", text).group(0)
    if lead:
        out.append(("", lead))
    parts = re.split(r"(\n[ \t\r]*\n\s*)", text[len(lead):])
    for i in range(0, len(parts), 2):
        para, sep = parts[i], parts[i + 1] if i + 1 < len(parts) else ""
        if not para:
            if sep:
                out.append(("", sep))
            continue
        trail = re.search(r"\s*$", para).group(0)
        body = para[:len(para) - len(trail)] if trail else para
        subs = _split_long(body, max_chars)
        subs[-1] = (subs[-1][0], subs[-1][1] + trail + sep)
        out.extend(subs)
    return out


def _split_long(body: str, max_chars: int) -> List[Tuple[str, str]]:
    if len(body) <= max_chars:
        return [(body, "")]
    for pattern in (r"(\n)", r"(?<=[.!?。！？…])(\s+)"):
        parts = re.split(pattern, body)
        if len(parts) > 1:
            pieces: List[Tuple[str, str]] = []
            cur, cur_sep = "", ""
            for i in range(0, len(parts), 2):
                seg, sep = parts[i], parts[i + 1] if i + 1 < len(parts) else ""
                if cur and len(cur) + len(cur_sep) + len(seg) > max_chars:
                    pieces.append((cur, cur_sep))
                    cur, cur_sep = seg, sep
                else:
                    cur, cur_sep = (cur + cur_sep + seg if cur else seg), sep
            pieces.append((cur, cur_sep))
            out: List[Tuple[str, str]] = []
            for p, s in pieces:
                sub = _split_long(p, max_chars) if len(p) > max_chars and pattern == r"(\n)" else [(p, "")]
                sub[-1] = (sub[-1][0], sub[-1][1] + s)
                out.extend(sub)
            return out
    # one huge "sentence": hard cut
    return [(body[i:i + max_chars], "") for i in range(0, len(body), max_chars)]


def _script(ch: str) -> str:
    o = ord(ch)
    if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0xF900 <= o <= 0xFAFF or 0x20000 <= o <= 0x2FA1F:
        return "cjk"
    if 0x3040 <= o <= 0x30FF:
        return "kana"
    if 0xAC00 <= o <= 0xD7AF:
        return "hangul"
    if 0x0400 <= o <= 0x052F:
        return "cyrillic"
    if ch.isascii() or 0x00C0 <= o <= 0x024F:
        return "latin"
    return "other"


def language_check(text: str, target: str) -> Dict[str, Any]:
    """Is text written in the target language? By script: zh -> mostly CJK, ru -> mostly Cyrillic,
    ko -> mostly Hangul.
    Digits / punctuation are ignored. Units: one CJK character = 1, one word of an alphabetic script = 1.
    Latin words (names, abbreviations) are ignored as long as the target script is at least 50% of all units;
    other scripts (Cyrillic in a Chinese answer, CJK in a Russian one) must stay below 20% of the non-Latin units.
    Very short answers (< 3 units) pass unless another script dominates."""
    want = {"zh": "cjk", "ru": "cyrillic", "ko": "hangul"}[target]
    units: Dict[str, int] = {}
    prev = None
    for ch in text or "":
        if not unicodedata.category(ch).startswith("L"):
            prev = None
            continue
        sc = _script(ch)
        if sc == "cjk" or sc != prev:   # a new word (or a CJK character)
            units[sc] = units.get(sc, 0) + 1
        prev = sc
    total = sum(units.values())
    tgt = units.get(want, 0)
    latin = units.get("latin", 0)
    non_latin = total - latin
    share = tgt / total if total else 0.0
    share_non_latin = tgt / non_latin if non_latin else 0.0
    if total < 3:
        ok = tgt >= non_latin - tgt
    else:
        ok = share >= 0.5 and share_non_latin >= 0.8
    main = max(units, key=units.get) if units else None
    return {"ok": bool(ok), "target_share": round(share, 3), "target_share_non_latin": round(share_non_latin, 3),
            "main_script": main, "units": units}


# --------------------------------------------------------------------------------------------- prompts

def build_messages(p: Provider, text: str, target: str, strict: bool = False) -> List[Dict[str, str]]:
    en, own, hy = LANGUAGES[target]
    if p.prompt == "hunyuan":
        # model card template; the model has no default system prompt
        if target == "zh":
            msg = f"把下面的文本翻译成{hy}，不要额外解释。\n\n{text}"
        else:
            msg = f"Translate the following segment into {hy}, without additional explanation.\n\n{text}"
        return [{"role": "user", "content": msg}]
    lang = en if own == en else f"{en} ({own})"
    system = (f"You are a professional translator. Translate the user's text into {lang}. Keep names, "
              f"numbers, line breaks and paragraph breaks. Output only the translation.")
    head = f"Translate the following text into {lang}. Output only the translation."
    if p.no_think and p.no_think_tag:
        head += " /no_think"
    msgs = [{"role": "system", "content": system}]
    if strict:
        msgs[0]["content"] += f" The answer must be written in {en} only, never in another language."
    if strict and target in EXAMPLES:
        # the retry: one worked example in the target language. On qwen3-4b the plain prompt answered a text about
        # Russian food in Russian when asked for Chinese (4 of 8 tries); with the example: 0 of 8.
        msgs += [{"role": "user", "content": f"{head}\n\n{EXAMPLE_SOURCE}"},
                 {"role": "assistant", "content": EXAMPLES[target]}]
    msgs.append({"role": "user", "content": f"{head}\n\n{text}"})
    return msgs


EXAMPLE_SOURCE = "Borscht is a beet soup that is popular in Moscow."
EXAMPLES = {"zh": "罗宋汤是一种在莫斯科很受欢迎的甜菜汤。", "ru": "Борщ — свекольный суп, который популярен в Москве."}

_LABEL_RE = re.compile(r"^\s*(assistant|translation|译文|翻译|перевод)\s*[:：]\s*", re.I)


def clean_answer(text: str) -> str:
    """Remove <think> blocks and a leading "Assistant:" / "Translation:" label (qwen3-4b adds one at times)."""
    return _LABEL_RE.sub("", strip_think(text)).strip()


def request_body(p: Provider, messages: List[Dict[str, str]], text: str, strict: bool) -> Dict[str, Any]:
    body: Dict[str, Any] = {"model": p.model, "messages": messages, "stream": False,
                            "max_tokens": p.max_tokens or max(256, min(8192, len(text) * 3))}
    if p.prompt == "hunyuan":
        # model card / generation_config.json: top_k 20, top_p 0.6, repetition_penalty 1.05, temperature 0.7
        body.update({"top_k": 20, "top_p": 0.6, "repetition_penalty": 1.05,
                     "temperature": p.temperature if p.temperature is not None else 0.7})
        if strict:
            body["temperature"] = min(body["temperature"], 0.3)
    else:
        body.update({"temperature": p.temperature if p.temperature is not None else 0.2, "top_p": 0.8})
        if strict:
            body["temperature"] = 0.0
    if p.no_think:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    return body


# --------------------------------------------------------------------------------------------- saving the block

def find_value_span(text: str, key: str) -> Optional[Tuple[int, int, str]]:
    """(start, end, indent) of the value of a top-level "key" in a JSON-with-// comments text: text[start:end] is the
    whole {...} value, indent the leading whitespace of the key's line. None when there is no such object key."""
    depth = 0
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == chr(92) else 1
            word = text[i + 1:j]
            k = j + 1
            if depth == 1 and word == key:
                m = k
                while m < n and text[m] in " \t\r\n":
                    m += 1
                if m < n and text[m] == ":":
                    m += 1
                    while m < n and text[m] in " \t\r\n":
                        m += 1
                    if m < n and text[m] == "{":
                        end = _match_brace(text, m)
                        line_start = text.rfind("\n", 0, i) + 1
                        indent = re.match(r"[ \t]*", text[line_start:]).group(0)
                        return (m, end, indent) if end else None
            i = k
            continue
        if ch == "/" and text.startswith("//", i):
            nl = text.find("\n", i)
            i = n if nl < 0 else nl
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        i += 1
    return None


def _match_brace(text: str, start: int) -> Optional[int]:
    depth, i, n = 0, start, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == chr(92) else 1
            i = j + 1
            continue
        if ch == "/" and text.startswith("//", i):
            nl = text.find("\n", i)
            i = n if nl < 0 else nl
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def format_block(block: Dict[str, Any], indent: str) -> str:
    """The "translate" value as written back: one line per setting, one line per provider."""
    inner = indent + "  "
    lines = ["{"]
    keys = [k for k in block if k != "providers"] + (["providers"] if "providers" in block else [])
    for n, k in enumerate(keys):
        comma = "," if n < len(keys) - 1 else ""
        if k == "providers":
            provs = block["providers"]
            lines.append(f'{inner}"providers": [')
            for m, p in enumerate(provs):
                pc = "," if m < len(provs) - 1 else ""
                lines.append(f"{inner}  {json.dumps(p, ensure_ascii=False)}{pc}")
            lines.append(f"{inner}]{comma}")
        else:
            lines.append(f"{inner}{json.dumps(k)}: {json.dumps(block[k], ensure_ascii=False)}{comma}")
    lines.append(indent + "}")
    return "\n".join(lines)


EDITABLE = ("enabled", "base_url", "model", "timeout")


def edited_block(block: Dict[str, Any], edits: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The block with the providers in the order of `edits` (every provider exactly once, by name) and their
    enabled / base_url / model / timeout replaced; every other field stays as it was."""
    old = {p.get("name"): p for p in block.get("providers") or []}
    names = [e.get("name") for e in edits]
    if sorted(map(str, names)) != sorted(map(str, old)) or len(set(names)) != len(names):
        raise ValueError(f"give every provider exactly once: have {sorted(old)}, got {names}")
    provs = []
    for e in edits:
        p = dict(old[e["name"]])
        for k in EDITABLE:
            if k not in e or e[k] is None:
                continue
            v = e[k]
            if k == "enabled":
                v = bool(v)
                if v:
                    p.pop("enabled", None)      # on = the default: leave it out
                    continue
            elif k == "timeout":
                v = float(v)
                if not 1 <= v <= 3600:
                    raise ValueError(f"{e['name']}: timeout must be 1 to 3600 seconds")
                v = int(v) if v == int(v) else v
            else:
                v = str(v).strip()
                if not v:
                    raise ValueError(f"{e['name']}: {k} is empty")
                if k == "base_url":
                    if not re.match(r"^https?://[^\s/]+", v):
                        raise ValueError(f"{e['name']}: base_url must start with http:// or https://")
                    v = v.rstrip("/")
            p[k] = v
        provs.append(p)
    out = dict(block)
    out["providers"] = provs
    return out


# --------------------------------------------------------------------------------------------- the service

class ProviderError(Exception):
    def __init__(self, message: str, unreachable: bool = False):
        super().__init__(message)
        self.unreachable = unreachable


class Translator:
    def __init__(self, cfg: Any = None, settings: Optional[Settings] = None, cache_dir: Optional[str] = None):
        self._file: Optional[Path] = None
        self._mtime: Optional[float] = None
        self._settings = settings
        if settings is None:
            block = getattr(cfg, "translate", None)
            if block is not None:       # config.py keeps the block
                self._settings = parse_settings(block, "viewer_config.json")
            else:                       # read it from the config file, again whenever the file changes
                self._file = _config_file(cfg)
                self._settings = Settings(source=str(self._file or ""))
        if cache_dir is None:
            base = Path(getattr(cfg, "base_dir", ".") or ".")
            c = Path(getattr(cfg, "cache_dir", ".viewer_cache") or ".viewer_cache")
            cache_dir = str((c if c.is_absolute() else base / c) / "translate")
        self.cache_dir = Path(cache_dir)
        self._down: Dict[str, Tuple[float, str]] = {}
        self._lock = threading.Lock()

    @property
    def settings(self) -> Settings:
        if self._file is not None:
            try:
                mtime = self._file.stat().st_mtime
            except OSError:
                return self._settings
            if mtime != self._mtime:
                self._settings = parse_settings(_read_block(self._file), str(self._file))
                self._mtime = mtime
        return self._settings

    @property
    def editable(self) -> bool:
        return self._file is not None and self._file.is_file()

    def file_mtime(self) -> Optional[str]:
        """The config file's change time in ns, as a string (a JavaScript number would round it)."""
        try:
            return str(self._file.stat().st_mtime_ns) if self._file else None
        except OSError:
            return None

    def save(self, edits: List[Dict[str, Any]], mtime: Optional[str]) -> Dict[str, Any]:
        """Write the edited providers into the config file's "translate" block (see edited_block)."""
        if not self.editable:
            raise HTTPException(409, "these settings do not come from a viewer_config.json file: edit them where "
                                     "the viewer was configured")
        f = self._file
        with self._lock:
            if mtime is not None and self.file_mtime() != mtime:
                raise HTTPException(409, f"{f.name} changed since this page loaded it: reload the page and try again")
            from .config import _strip_comments
            text = f.read_text("utf-8")
            block = json.loads(_strip_comments(text)).get("translate")
            span = find_value_span(text, "translate")
            if not isinstance(block, dict) or span is None:
                raise HTTPException(409, f'no "translate" block found in {f.name}')
            try:
                new = edited_block(block, edits)
                parse_settings(new, str(f))          # the same checks as on loading
            except ValueError as exc:
                raise HTTPException(400, str(exc))
            start, end, indent = span
            out = text[:start] + format_block(new, indent) + text[end:]
            json.loads(_strip_comments(out))         # still a valid config
            bdir = f.parent / ".backup"
            bdir.mkdir(exist_ok=True)
            backup = bdir / f"{f.name}.{time.strftime('%Y%m%d-%H%M%S')}"
            backup.write_bytes(f.read_bytes())
            tmp = f.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(out, "utf-8", newline="")
            os.replace(tmp, f)
            self._mtime = None                      # re-read at the next use
            self._down.clear()
        return {"saved": str(f), "backup": str(backup), "mtime": self.file_mtime()}

    def provider(self, name: str) -> Provider:
        for p in self.settings.providers:
            if p.name == name:
                return p
        raise HTTPException(400, f"unknown translate provider '{name}'")

    # ---- cache
    def _key(self, text: str, target: str, p: Provider) -> str:
        raw = json.dumps([text, target, p.name, p.model, p.prompt, PROMPT_VERSION], ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> Optional[str]:
        f = self.cache_dir / key[:2] / f"{key}.json"
        try:
            return json.loads(f.read_text("utf-8"))["translation"]
        except (OSError, ValueError, KeyError):
            return None

    def _cache_put(self, key: str, text: str, target: str, p: Provider, translation: str) -> None:
        f = self.cache_dir / key[:2] / f"{key}.json"
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps({"target": target, "provider": p.name, "model": p.model, "source": text,
                                       "translation": translation, "time": time.time()}, ensure_ascii=False),
                           "utf-8")
            os.replace(tmp, f)
        except OSError as exc:
            log.warning("translate cache write failed: %s", exc)

    # ---- one HTTP call
    def _mask(self, p: Provider, msg: str) -> str:
        key = p.api_key()
        return msg.replace(key, "***") if key else msg

    def chat(self, p: Provider, messages: List[Dict[str, str]], text: str, strict: bool = False) -> str:
        headers = {"Content-Type": "application/json"}
        key = p.api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        body = request_body(p, messages, text, strict)
        try:
            with httpx.Client(timeout=httpx.Timeout(p.timeout, connect=min(10.0, p.timeout))) as c:
                r = c.post(f"{p.base_url}/chat/completions", json=body, headers=headers)
        except httpx.TimeoutException:
            raise ProviderError(f"timeout after {p.timeout:g}s", unreachable=True)
        except httpx.HTTPError as exc:
            raise ProviderError(self._mask(p, f"cannot connect to {p.base_url}: {type(exc).__name__}: {exc}"),
                                unreachable=True)
        if r.status_code != 200:
            detail = r.text[:300].replace("\n", " ")
            raise ProviderError(self._mask(p, f"HTTP {r.status_code}: {detail}"))
        try:
            data = r.json()
            content = data["choices"][0]["message"].get("content") or ""
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError(f"not an OpenAI chat completion answer: {r.text[:200]!r}")
        content = clean_answer(content)
        if not content:
            raise ProviderError("empty answer")
        return content

    def translate_piece(self, p: Provider, text: str, target: str) -> Tuple[str, List[str]]:
        """One piece with one provider; wrong language -> one strict retry. Returns (translation, notes)."""
        out = self.chat(p, build_messages(p, text, target), text)
        chk = language_check(out, target)
        if chk["ok"]:
            return out, []
        note = f"answer not in {LANGUAGES[target][0]} (main script {chk['main_script']}), retried with a stricter prompt"
        out2 = self.chat(p, build_messages(p, text, target, strict=True), text, strict=True)
        chk2 = language_check(out2, target)
        if chk2["ok"]:
            return out2, [note]
        raise ProviderError(f"answered in the wrong language twice (wanted {LANGUAGES[target][0]}, got script "
                            f"{chk2['main_script']}): {out2[:80]!r}")

    # ---- a whole text with fallback
    def translate_text(self, text: str, target: str, split: bool = True, force: Optional[str] = None,
                       nocache: bool = False) -> Dict[str, Any]:
        st = self.settings
        t0 = time.time()
        providers = [self.provider(force)] if force else [p for p in st.providers if p.enabled]
        res: Dict[str, Any] = {"ok": False, "translation": None, "provider": None, "model": None, "fallback": False,
                               "cached": False, "pieces": 0, "seconds": 0.0, "errors": [], "notes": []}
        if not text.strip():
            res.update(ok=True, translation=text, cached=True)
            return res
        pieces = split_pieces(text, min(p.max_chars for p in providers) if providers else 3000) if split \
            else [(text, "")]
        res["pieces"] = sum(1 for piece, _ in pieces if piece.strip())
        for idx, p in enumerate(providers):
            keys = [self._key(piece, target, p) if piece.strip() else None for piece, _ in pieces]
            got = [None if k is None or nocache else self._cache_get(k) for k in keys]
            missing = [i for i, (k, g) in enumerate(zip(keys, got)) if k is not None and g is None]
            if missing and not force:
                with self._lock:
                    down = self._down.get(p.name)
                if down and time.time() - down[0] < st.down_seconds:
                    res["errors"].append({"provider": p.name, "model": p.model,
                                          "error": f"skipped: unreachable {time.time() - down[0]:.0f}s ago ({down[1]})"})
                    continue
            try:
                notes: List[str] = []
                for i in missing:
                    piece = pieces[i][0]
                    lead = re.match(r"\s*", piece).group(0)
                    trail = re.search(r"\s*$", piece).group(0)
                    out, n = self.translate_piece(p, piece.strip(), target)
                    got[i] = lead + out + trail
                    notes += n
                    self._cache_put(keys[i], piece, target, p, got[i])
            except ProviderError as exc:
                if exc.unreachable:
                    with self._lock:
                        self._down[p.name] = (time.time(), str(exc))
                log.info("translate: provider %s failed: %s", p.name, exc)
                res["errors"].append({"provider": p.name, "model": p.model, "error": str(exc)})
                continue
            with self._lock:
                self._down.pop(p.name, None)
            res.update(ok=True, provider=p.name, model=p.model, fallback=idx > 0, cached=not missing,
                       translation="".join((g if k is not None else piece) + sep
                                           for (piece, sep), k, g in zip(pieces, keys, got)),
                       notes=notes)
            break
        if not res["ok"]:
            if not providers:
                res["errors"].append({"provider": None, "model": None, "error": "no translate provider enabled"})
            res["error"] = "no provider could translate: " + "; ".join(
                f"{e['provider']}: {e['error']}" for e in res["errors"])
        res["seconds"] = round(time.time() - t0, 3)
        return res

    def translate_many(self, items: List[str], target: str, split: bool, force: Optional[str],
                       nocache: bool) -> List[Dict[str, Any]]:
        n = max(1, min(self.settings.concurrency, len(items)))
        with ThreadPoolExecutor(max_workers=n) as pool:
            return list(pool.map(lambda t: self.translate_text(t, target, split, force, nocache), items))

    # ---- settings test
    def models(self, p: Provider) -> Dict[str, Any]:
        headers = {}
        key = p.api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        t0 = time.time()
        try:
            with httpx.Client(timeout=min(10.0, p.timeout)) as c:
                r = c.get(f"{p.base_url}/models", headers=headers)
            if r.status_code != 200:
                return {"reachable": True, "models": [], "error": self._mask(p, f"HTTP {r.status_code}: {r.text[:200]}"),
                        "seconds": round(time.time() - t0, 3)}
            ids = [m.get("id") for m in r.json().get("data", []) if isinstance(m, dict)]
            return {"reachable": True, "models": ids, "error": None, "seconds": round(time.time() - t0, 3)}
        except (httpx.HTTPError, ValueError) as exc:
            return {"reachable": False, "models": [], "error": self._mask(p, f"{type(exc).__name__}: {exc}"),
                    "seconds": round(time.time() - t0, 3)}

    def test(self, names: Optional[List[str]], targets: List[str], text: str,
             override: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        provs = [self.provider(n) for n in names] if names else list(self.settings.providers)
        if override and len(provs) == 1:
            # unsaved values from the settings page (base_url / model / timeout), checked like a save would
            import dataclasses
            name = provs[0].name
            try:
                e = edited_block({"providers": [provs[0].public()]},
                                 [{"name": name, **{k: override.get(k) for k in ("base_url", "model", "timeout")}}])
            except ValueError as exc:
                raise HTTPException(400, str(exc))
            p = e["providers"][0]
            provs = [dataclasses.replace(provs[0], base_url=p["base_url"], model=p["model"], timeout=float(p["timeout"]))]

        def one(p: Provider) -> Dict[str, Any]:
            row = {"name": p.name, "model": p.model, "base_url": p.base_url, "enabled": p.enabled, **self.models(p)}
            row["model_served"] = p.model in row["models"]
            row["samples"] = []
            if not row["reachable"]:
                return row
            for t in targets:
                t0 = time.time()
                s: Dict[str, Any] = {"target": t, "ok": False, "translation": None, "error": None}
                try:
                    out = self.chat(p, build_messages(p, text, t), text)
                    s["translation"] = out
                    s["language"] = language_check(out, t)
                    s["ok"] = s["language"]["ok"]
                    if not s["ok"]:
                        s["error"] = f"answer not in {LANGUAGES[t][0]}"
                        out2 = self.chat(p, build_messages(p, text, t, strict=True), text, strict=True)
                        s["retry"] = {"translation": out2, "language": language_check(out2, t)}
                        s["retry"]["ok"] = s["retry"]["language"]["ok"]
                        if s["retry"]["ok"]:
                            s["error"] += "; the stricter retry prompt fixed it"
                except ProviderError as exc:
                    s["error"] = str(exc)
                s["seconds"] = round(time.time() - t0, 3)
                row["samples"].append(s)
            return row

        with ThreadPoolExecutor(max_workers=max(1, len(provs))) as pool:
            return list(pool.map(one, provs))


# --------------------------------------------------------------------------------------------- HTTP API

class TranslateRequest(BaseModel):
    texts: Optional[List[str]] = None
    paragraphs: Optional[List[str]] = None
    target: str
    provider: Optional[str] = None
    nocache: bool = False


class TranslateSaveRequest(BaseModel):
    providers: List[Dict[str, Any]]
    mtime: Optional[str] = None


class TranslateTestRequest(BaseModel):
    provider: Optional[str] = None
    override: Optional[Dict[str, Any]] = None     # unsaved base_url / model / timeout for this one provider
    targets: Optional[List[str]] = None
    text: Optional[str] = None


def _translator(request: Request) -> Translator:
    tr = getattr(request.app.state, "translator", None)
    if tr is None:
        raise HTTPException(503, "translation is not wired into this viewer (translate.install)")
    return tr


def _check_target(tr: Translator, target: str) -> None:
    if target not in LANGUAGES:
        raise HTTPException(400, f"unknown target '{target}' (known: {', '.join(LANGUAGES)})")
    if target not in tr.settings.targets:
        raise HTTPException(400, f"target '{target}' is not in translate.targets")


@router.post("/api/translate")
def api_translate(body: TranslateRequest, request: Request):
    tr = _translator(request)
    st = tr.settings
    if not st.configured or not st.providers:
        raise HTTPException(503, 'translation is not set up: add a "translate" block with providers to '
                                 'viewer_config.json (see cmds/viewer/translate.md)')
    _check_target(tr, body.target)
    if (body.texts is None) == (body.paragraphs is None):
        raise HTTPException(400, "give either texts or paragraphs")
    items = body.texts if body.texts is not None else body.paragraphs
    if len(items) > MAX_ITEMS or sum(len(t) for t in items) > MAX_CHARS:
        raise HTTPException(413, f"at most {MAX_ITEMS} items and {MAX_CHARS} characters per request")
    if body.provider:
        tr.provider(body.provider)
    results = tr.translate_many(items, body.target, split=body.texts is not None, force=body.provider,
                                nocache=body.nocache)
    for i, r in enumerate(results):
        r["index"] = i
    failed = [r for r in results if not r["ok"]]
    return {"target": body.target, "ok": not failed, "failed": len(failed),
            "error": (f"{len(failed)} of {len(results)} not translated: {failed[0]['error']}" if failed else None),
            "results": results}


@router.get("/api/translate/settings")
def api_translate_settings(request: Request):
    tr = _translator(request)
    st = tr.settings
    return {"configured": st.configured, "source": st.source,
            "targets": [{"code": t, "name": LANGUAGES[t][0], "label": LANGUAGES[t][1]} for t in st.targets],
            "providers": [p.public() for p in st.providers], "cache_dir": str(tr.cache_dir),
            "concurrency": st.concurrency, "down_seconds": st.down_seconds,
            "editable": tr.editable, "mtime": tr.file_mtime()}


@router.post("/api/translate/settings/save")
def api_translate_settings_save(body: TranslateSaveRequest, request: Request):
    tr = _translator(request)
    r = tr.save(body.providers, body.mtime)
    st = tr.settings
    r["providers"] = [p.public() for p in st.providers]
    return r


@router.post("/api/translate/test")
def api_translate_test(body: TranslateTestRequest, request: Request):
    tr = _translator(request)
    targets = body.targets or tr.settings.targets
    for t in targets:
        _check_target(tr, t)
    text = (body.text or "").strip() or SAMPLE_TEXT
    return {"text": text, "providers": tr.test([body.provider] if body.provider else None, targets, text,
                                               body.override if body.provider else None)}


def install(app: FastAPI, cfg: Any) -> Translator:
    """Wire translation into the viewer app: app.state.translator + the /api/translate routes."""
    tr = Translator(cfg)
    app.state.translator = tr
    app.include_router(router)
    return tr

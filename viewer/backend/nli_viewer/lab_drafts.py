"""
lab_drafts.py - the Experiment page's drafts, kept as files so they can be loaded again from another page:
dataset/lab_drafts/<id>.json (dataset/ is git-ignored). Two kinds:

- automatic ("auto": true): the page saves its draft by itself a moment after every change, one file per page visit
  (id auto-<time>-<random>); only the newest MAX_AUTO are kept;
- named ("auto": false): "Save draft as…", id = the name; never removed automatically, replaced only on request.

A draft file:
    {"id": "...", "name": "ukraine_gate_try" | null, "auto": true, "saved": "2026-11-27 10:12:03", "saved_ts": 1795...,
     "summary": "added label ukraine; threshold of politics: 0.8 → 0.7",
     "base": {"run": "...", "file": "...", "line": 5, "para": 0, "policy_path": "policy/....json", "policy_data": {...},
              "settings": {...}},
     "policy": {...}, "settings": {...}, "texts": ["...", ...]}

Nothing here touches policy/: a draft becomes a policy only through the page's "Save as new" / "Replace".
"""
from __future__ import annotations

import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

MAX_AUTO = 50
MAX_BYTES = 5_000_000
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


def drafts_dir(project: Path) -> Path:
    return Path(project) / "dataset" / "lab_drafts"


def new_auto_id() -> str:
    return f"auto-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"


def _path(project: Path, draft_id: str) -> Path:
    if not ID_RE.match(draft_id or ""):
        raise HTTPException(400, "a draft name is 1-80 letters, digits, _ . - (starting with a letter or digit)")
    return drafts_dir(project) / f"{draft_id}.json"


def _read(p: Path) -> Optional[Dict[str, Any]]:
    try:
        d = json.loads(p.read_text("utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def listing(project: Path) -> List[Dict[str, Any]]:
    """Every draft, newest first, without the big parts (policy, texts)."""
    out = []
    for p in drafts_dir(project).glob("*.json"):
        d = _read(p)
        if not d:
            continue
        base = d.get("base") or {}
        pol = d.get("policy") or {}
        texts = d.get("texts") or []
        out.append({"id": p.stem, "name": d.get("name"), "auto": bool(d.get("auto")), "saved": d.get("saved"),
                    "saved_ts": d.get("saved_ts") or p.stat().st_mtime, "summary": d.get("summary") or "",
                    "run": base.get("run"), "file": base.get("file"), "line": base.get("line"),
                    "policy_path": base.get("policy_path"), "labels": len(pol.get("labels") or {}),
                    "texts": len(texts), "first_text": (texts[0][:140] if texts and isinstance(texts[0], str) else "")})
    out.sort(key=lambda x: x["saved_ts"], reverse=True)
    return out


def get(project: Path, draft_id: str) -> Dict[str, Any]:
    p = _path(project, draft_id)
    d = _read(p) if p.is_file() else None
    if d is None:
        raise HTTPException(404, f"no draft {draft_id}")
    d["id"] = draft_id
    return d


def save(project: Path, body: Dict[str, Any]) -> Dict[str, Any]:
    """body: {id?, name?, auto, overwrite?, summary, base, policy, settings, texts}. Auto: id from the page (or a new
    one). Named: id = name; an existing named draft is replaced only with overwrite; never over an automatic one."""
    auto = bool(body.get("auto"))
    if not isinstance(body.get("policy"), dict) or not isinstance(body.get("policy", {}).get("labels"), dict):
        raise HTTPException(400, "policy with labels is needed")
    texts = body.get("texts") or []
    if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
        raise HTTPException(400, "texts must be a list of strings")
    if auto:
        draft_id = body.get("id") or new_auto_id()
        if not str(draft_id).startswith("auto-"):
            raise HTTPException(400, "an automatic draft id starts with auto-")
        name = None
    else:
        name = (body.get("name") or "").strip()
        if name.startswith("auto-"):
            raise HTTPException(400, "a name cannot start with auto-")
        draft_id = name
    p = _path(project, draft_id)
    if not auto and p.is_file() and not body.get("overwrite"):
        raise HTTPException(409, f"a draft named {name} exists already")
    now = time.time()
    rec = {"id": draft_id, "name": name, "auto": auto, "saved": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
           "saved_ts": now, "summary": str(body.get("summary") or "")[:2000], "base": body.get("base") or {},
           "policy": body["policy"], "settings": body.get("settings") or {}, "texts": texts,
           "sources": body.get("sources") if isinstance(body.get("sources"), list) else []}
    raw = json.dumps(rec, ensure_ascii=False, indent=1)
    if len(raw.encode("utf-8")) > MAX_BYTES:
        raise HTTPException(413, "this draft is too big to keep (over 5 MB): remove some texts")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(raw, "utf-8")
    os.replace(tmp, p)
    removed = prune(project) if auto else []
    same = drop_duplicates(project, draft_id, rec) if auto else {"replaced": [], "same_as": None}
    return {"id": draft_id, "saved": rec["saved"], "auto": auto, "pruned": removed, **same}


def _env(d: Dict[str, Any]) -> str:
    """What makes two drafts the same: the draft policy and the run settings (not the texts or the line)."""
    return json.dumps([d.get("policy"), d.get("settings")], sort_keys=True, ensure_ascii=False)


def drop_duplicates(project: Path, draft_id: str, rec: Dict[str, Any]) -> Dict[str, Any]:
    """After an automatic save: older automatic drafts identical to it are deleted (the newest stays, with its texts);
    when a named draft is identical, this automatic one is deleted instead (the named one already keeps it). Named
    drafts are never deleted here."""
    env = _env(rec)
    replaced, same_as = [], None
    for p in drafts_dir(project).glob("*.json"):
        if p.stem == draft_id:
            continue
        d = _read(p)
        if not d or _env(d) != env:
            continue
        if d.get("auto"):
            try:
                p.unlink()
                replaced.append(p.stem)
            except OSError:
                pass
        elif same_as is None:
            same_as = p.stem
    if same_as:
        try:
            (drafts_dir(project) / f"{draft_id}.json").unlink()
        except OSError:
            pass
    return {"replaced": replaced, "same_as": same_as}


def prune(project: Path, keep: Optional[int] = None) -> List[str]:
    keep = MAX_AUTO if keep is None else keep
    autos = [x for x in listing(project) if x["auto"]]
    gone = []
    for x in autos[keep:]:
        try:
            (drafts_dir(project) / f"{x['id']}.json").unlink()
            gone.append(x["id"])
        except OSError:
            pass
    return gone


def delete(project: Path, draft_id: str) -> Dict[str, Any]:
    p = _path(project, draft_id)
    if not p.is_file():
        raise HTTPException(404, f"no draft {draft_id}")
    p.unlink()
    return {"deleted": draft_id}

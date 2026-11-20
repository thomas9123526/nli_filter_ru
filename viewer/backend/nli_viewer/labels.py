"""
labels.py - the viewer's Labels pages: nli_label.py runs (policy labels per paragraph).

A label run is a folder with summary.json (written by nli_label.py run / redecide, it has a "policy" key) and
<name>.labels.jsonl per input file, or a progress.json while the run is going. Folders are found in the project
folder (one level deep). Nothing here imports torch: the source text is read with nli_models.JsonlSource.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

__all__ = ["LabelRuns"]

ACTIONS = ("untouched", "pass", "kept", "review", "edited", "removed", "error")


def _read_json(p: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class LabelRuns:
    def __init__(self, project: Path, stale_seconds: float = 300.0):
        self.project = Path(project)
        self.stale = stale_seconds
        if str(self.project) not in sys.path:
            sys.path.insert(0, str(self.project))

    # ---- finding runs ------------------------------------------------------------------------------
    def _is_run(self, d: Path) -> bool:
        s = d / "summary.json"
        if s.is_file():
            data = _read_json(s) or {}
            return "policy" in data
        p = _read_json(d / "progress.json") or {}
        return str(p.get("command", "")).startswith("nli_label.py")

    def folder(self, name: str) -> Path:
        if not name or "/" in name or "\\" in name or name.startswith("."):
            raise ValueError(f"bad run name '{name}'")
        d = self.project / name
        if not d.is_dir() or not self._is_run(d):
            raise KeyError(f"no nli_label.py run '{name}' in {self.project}")
        return d

    def progress(self, d: Path) -> Optional[Dict[str, Any]]:
        p = _read_json(d / "progress.json")
        if not p:
            return None
        if p.get("state") == "running":
            try:
                age = time.time() - (d / "progress.json").stat().st_mtime
            except OSError:
                age = 0
            if age > self.stale:
                p["state"] = "stale"
                p["note"] = f"no update for {int(age)} s: the run was probably stopped"
        return p

    def list(self) -> Dict[str, Any]:
        runs = []
        for d in sorted(self.project.iterdir()):
            if not d.is_dir() or d.name.startswith(".") or d.name in ("viewer", "models", "pkgs", "node_modules"):
                continue
            try:
                if not self._is_run(d):
                    continue
            except OSError:
                continue
            s = _read_json(d / "summary.json") or {}
            st = s.get("stats") or {}
            runs.append({"name": d.name, "finished": s.get("finished"), "command": s.get("command"),
                         "policy": (s.get("policy") or {}).get("path"), "lines": st.get("lines"),
                         "tokens": st.get("tokens"), "tokens_removed": st.get("tokens_removed"),
                         "docs": st.get("docs") or {}, "redecided": bool(s.get("redecide")),
                         "progress": self.progress(d)})
        runs.sort(key=lambda r: (r["progress"] or {}).get("updated") or r["finished"] or "", reverse=True)
        return {"project": str(self.project), "runs": runs}

    # ---- one run -----------------------------------------------------------------------------------
    def run(self, name: str) -> Dict[str, Any]:
        d = self.folder(name)
        s = _read_json(d / "summary.json") or {}
        files = []
        for sp in sorted(d.glob("*.summary.json")):
            fs = _read_json(sp) or {}
            files.append({"name": fs.get("name") or sp.name[:-len(".summary.json")], "input": fs.get("input"),
                          "lines": (fs.get("stats") or {}).get("lines"), "docs": (fs.get("stats") or {}).get("docs"),
                          "seconds": fs.get("seconds")})
        return {"name": name, "summary": s, "files": files, "progress": self.progress(d)}

    def _rows(self, d: Path, file: str) -> Iterator[Dict[str, Any]]:
        p = d / f"{file}.labels.jsonl"
        if not p.is_file():
            raise KeyError(f"no labels file for '{file}'")
        with open(p, encoding="utf-8") as fh:
            for raw in fh:
                if raw.strip():
                    yield json.loads(raw)

    def docs(self, name: str, file: str, action: Optional[str] = None, label: Optional[str] = None,
             para_action: Optional[str] = None, gated: bool = True, offset: int = 0, limit: int = 50) -> Dict[str, Any]:
        d = self.folder(name)
        counts: Dict[str, int] = {}
        out, total = [], 0
        for r in self._rows(d, file):
            if gated and not r.get("gate"):
                continue
            counts[r.get("action", "?")] = counts.get(r.get("action", "?"), 0) + 1
            if action and r.get("action") != action:
                continue
            paras = r.get("paragraphs") or []
            if label and label not in (r.get("labels") or []):
                continue
            if para_action and not any(p.get("action") == para_action for p in paras):
                continue
            total += 1
            if offset <= total - 1 < offset + limit:
                pa: Dict[str, int] = {}
                for p in paras:
                    pa[p["action"]] = pa.get(p["action"], 0) + 1
                out.append({"line": r.get("line"), "id": r.get("id"), "action": r.get("action"),
                            "labels": r.get("labels") or [], "flags": r.get("flags") or [],
                            "tokens": r.get("tokens"), "tokens_removed": r.get("tokens_removed"),
                            "paragraphs": pa, "rewrites": r.get("rewrites", 0),
                            "keywords": sorted({h["kw"] for h in r.get("hits") or [] if not h.get("rule")})[:8]})
        return {"rows": out, "total": total, "counts": counts, "offset": offset, "limit": limit}

    def doc(self, name: str, file: str, line: int) -> Dict[str, Any]:
        d = self.folder(name)
        row = next((r for r in self._rows(d, file) if r.get("line") == line), None)
        if row is None:
            raise KeyError(f"line {line} not in {file}")
        s = _read_json(d / "summary.json") or {}
        fs = _read_json(d / f"{file}.summary.json") or {}
        text, problem = None, None
        src = fs.get("input")
        tf = (s.get("settings") or {}).get("text_field") or "text"
        if src:
            path = Path(src) if Path(src).is_absolute() else self.project / src
            try:
                from nli_models import JsonlSource  # project module; no torch at import
                for rec in JsonlSource(str(path)).records():
                    if rec.line == line:
                        t = rec.get(tf)
                        text = t if isinstance(t, str) else None
                        break
            except Exception as exc:  # noqa: BLE001 - shown on the page
                problem = f"cannot read {src}: {exc}"
        if text == "" and row.get("paragraphs"):
            problem = "the source document is empty now (removed after the run, e.g. by content screening)"
            text = None
        elif text is not None and row.get("paragraphs"):
            s_end = max(p["span"][1] for p in row["paragraphs"])
            if s_end > len(text):
                problem = "the source text changed since the run (spans do not fit): the text is not shown"
                text = None
        pol = s.get("policy") or {}
        return {"name": name, "file": file, "input": src, "row": row, "text": text, "problem": problem,
                "policy": {"labels": pol.get("labels") or {}, "run_if": pol.get("run_if") or {},
                           "conflict": pol.get("conflict")},
                "settings": s.get("settings") or {}}

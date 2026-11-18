"""
playground.py - the Corpus page's "Try settings" panel: run nli_filter.py's decision on the lines shown, with any
keywords and hypotheses, through the model service nli_playground.py (which has torch and the models; the viewer
does not). Also lists and saves the shared files hypotheses/*.json and keywords/*.txt of the project.

viewer_config.json (defaults): "playground_url": "http://127.0.0.1:8100", "project_dir": ".." (the folder with
nli_filter.py, hypotheses/ and keywords/; relative to the config file).
"""
from __future__ import annotations

import json
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from .explain import explain
from .storage import clean_path

import nli_hypotheses  # noqa: E402  (project root, put on sys.path by .storage)

__all__ = ["Playground", "PlaygroundError"]


class PlaygroundError(Exception):
    """The model service cannot be reached or refused the request: HTTP 502 / 400."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


class Playground:
    def __init__(self, url: str, project_dir: str, backups_dir: str, timeout: float = 600.0):
        self.url = url.rstrip("/")
        self.project = Path(project_dir).resolve()
        self.backups = Path(backups_dir)
        self.timeout = timeout

    # ---- model service ----------------------------------------------------------------------------

    def _call(self, path: str, body: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method="POST" if data else "GET",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read()).get("detail")
            except ValueError:
                detail = str(exc)
            raise PlaygroundError(f"model service: {detail}", exc.code if exc.code in (400, 404, 409) else 502) from None
        except (urllib.error.URLError, OSError) as exc:
            raise PlaygroundError(f"the model service at {self.url} is not running ({exc}); start it with: "
                                  f"python nli_playground.py") from None

    def status(self) -> Dict[str, Any]:
        try:
            return {"url": self.url, "running": True, **self._call("/health", timeout=3)}
        except PlaygroundError as exc:
            return {"url": self.url, "running": False, "error": str(exc),
                    "start": f"cd {self.project}; python nli_playground.py"}

    def info(self) -> Dict[str, Any]:
        """nli_filter.py facts from the service (countries, option arities); {} when it is not running."""
        try:
            return self._call("/info", timeout=3)
        except PlaygroundError:
            return {}

    # ---- nli_filter.py runs (started by the service, in its torch environment) -------------------

    def start_job(self, args: List[str], env: Dict[str, str], label: str) -> Dict[str, Any]:
        return self._call("/jobs", {"args": args, "env": env, "label": label}, timeout=30)

    def job(self, jid: str) -> Dict[str, Any]:
        return self._call(f"/jobs/{jid}", timeout=10)

    def jobs(self) -> Dict[str, Any]:
        return self._call("/jobs", timeout=10)

    def stop_job(self, jid: str) -> Dict[str, Any]:
        return self._call(f"/jobs/{jid}/stop", {}, timeout=10)

    # ---- shared files ----------------------------------------------------------------------------

    @property
    def hyp_dir(self) -> Path:
        return self.project / "hypotheses"

    @property
    def kw_dir(self) -> Path:
        return self.project / "keywords"

    def resources(self) -> Dict[str, Any]:
        kws = []
        for p in sorted(self.kw_dir.glob("*.txt")) if self.kw_dir.is_dir() else []:
            text = p.read_text(encoding="utf-8", errors="replace")
            kws.append({"name": p.stem, "file": p.name, "text": text, "count": len(_keywords(text))})
        return {"project_dir": str(self.project), "hypotheses": nli_hypotheses.list_files(self.hyp_dir),
                "builtin_hypotheses": nli_hypotheses.DEFAULT, "keywords": kws}

    def _save(self, folder: Path, name: str, suffix: str, text: str, overwrite: bool) -> Dict[str, Any]:
        if not nli_hypotheses.NAME_RE.fullmatch(name or ""):
            raise ValueError("file name: letters, digits, _ . - only (max 80)")
        folder.mkdir(parents=True, exist_ok=True)
        p = folder / f"{name}{suffix}"
        backup = None
        if p.exists():
            if not overwrite:
                raise ValueError(f"{p.name} exists already (choose another name, or overwrite)")
            b = self.backups / folder.name / f"{name}.{time.strftime('%Y%m%d-%H%M%S')}{suffix}"
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, b)
            backup = str(b)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(text, encoding="utf-8", newline="\n")
        tmp.replace(p)
        return {"file": str(p), "backup": backup}

    def save_hypotheses(self, name: str, data: Dict[str, Any], overwrite: bool = False) -> Dict[str, Any]:
        return self._save(self.hyp_dir, name, ".json", nli_hypotheses.dump(data), overwrite)

    def save_keywords(self, name: str, text: str, overwrite: bool = False) -> Dict[str, Any]:
        if not _keywords(text):
            raise ValueError("the keyword list is empty")
        return self._save(self.kw_dir, name, ".txt", text if text.endswith("\n") else text + "\n", overwrite)

    # ---- running ---------------------------------------------------------------------------------

    def run(self, ds, path: str, member: Optional[str], lines: List[int], settings: Dict[str, Any]) -> Dict[str, Any]:
        """Decisions for these corpus lines with these settings, explained like the record page."""
        path = clean_path(path)
        if not lines:
            raise ValueError("no lines")
        lf = ds._line_file(ds.corpus, path, member or None)
        items = []
        for n in lines:
            items.append({"line": int(n), "raw": lf.line(int(n)).decode("utf-8", "replace")})
        req = dict(settings)
        if isinstance(req.get("keywords"), str):  # every line, so the service's errors give the right line numbers
            req["keywords"] = req["keywords"].splitlines()
        latest = max(ds.runs(), key=lambda r: r.get("finished", ""), default={})
        st = latest.get("settings") or {}
        req.setdefault("text_field", ds._text_field or st.get("text_field") or "text")
        req.setdefault("id_field", ds._id_field or st.get("id_field") or "id")
        req["lines"] = items
        out = self._call("/filter", req)
        run = {"hypotheses": out["hypotheses"], "settings": out["settings"], "models": out["models"]}
        previous = _previous(ds, path, member, lines)
        previous_pending = previous is None
        previous = previous or {}
        results = []
        for item, dec in zip(items, out["decisions"]):
            text = None
            try:
                obj = json.loads(item["raw"])
                t = obj.get(req["text_field"]) if isinstance(obj, dict) else None
                text = t if isinstance(t, str) else None
            except ValueError:
                pass
            ex = explain(text, dec, run, max_chars=30000)
            results.append({"line": item["line"], "decision": dec, "explanation": ex,
                            "previous": previous.get(item["line"])})
        return {"results": results, "seconds": out["seconds"], "pairs": out["pairs"], "keywords": out["keywords"],
                "country": out["country"], "hypotheses": out["hypotheses"], "models": out["models"],
                "settings": out["settings"], "previous_pending": previous_pending}


def _keywords(text: str) -> List[str]:
    """Keyword file text -> keywords (same rules as nli_filter.load_keywords: '#' comments, blank lines; the
    keyword is the first tab-separated column of a lexicon line)."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s.split("	", 1)[0].strip())
    return [k for k in out if k]


def _previous(ds, path: str, member: Optional[str], lines: List[int]) -> Optional[Dict[int, Dict[str, Any]]]:
    """The saved run's decision of these lines (when the file has results), for comparison."""
    fr = next((f for f in ds.files() if f.corpus_path == path), None)
    if fr is None or not fr.decisions_path:
        return {}
    idx = ds.decisions(fr.key)
    if not idx.ready():  # big file: build the table in the background; the next run can compare
        idx.build_in_background()
        return None
    from .edit import map_back
    ops = ds.editor.structural_ops(path, member, ds._decisions_time(fr)) if ds.editor is not None else []
    out = {}
    for n in lines:
        old = map_back(n, ops) if ops else n
        row = idx.find_row(old, member) if old is not None else None
        if row is None:
            continue
        dec = json.loads(ds._line_file(ds.output, fr.decisions_path).line(row))
        out[n] = {"decision": dec.get("decision"), "reason": dec.get("reason"), "row": row,
                  "check1": (dec.get("check1") or {}).get("score")}
    return out

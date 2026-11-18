"""
Golden set: lines labelled in the viewer (review queue / record page), kept OUTSIDE the corpus.

One JSONL file per dataset, golden/<dataset>.jsonl in the project folder. Each line is a ready test line for
nli_filter.py (id, text, expect, category) plus where it came from:

    {"id": "...", "text": "...", "expect": "filter", "category": "review", "note": "",
     "source": {"dataset": "web", "file": "cc/part-00/shard-00001", "line": 1234, "id": "..."},
     "labelled": "2026-11-18 09:30:00"}

The real corpus keeps only id + text; labels never go into it. Run the golden set like any test file:
    python nli_filter.py golden\\web.jsonl --output-dir out_golden_web
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = ["GoldenStore"]

_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


class GoldenStore:
    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self._lock = threading.Lock()

    def path(self, dataset: str) -> Path:
        if not _NAME_RE.match(dataset):
            raise ValueError(f"dataset name '{dataset}' cannot be a file name")
        return self.folder / f"{dataset}.jsonl"

    @staticmethod
    def key(file: str, line: int) -> str:
        return f"{file}#{line}"

    def load(self, dataset: str) -> Dict[str, Dict[str, Any]]:
        p = self.path(dataset)
        out: Dict[str, Dict[str, Any]] = {}
        if not p.is_file():
            return out
        for raw in p.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            src = d.get("source") or {}
            if src.get("file") is not None and src.get("line") is not None:
                out[self.key(src["file"], int(src["line"]))] = d
        return out

    def summary(self, dataset: str) -> Dict[str, Any]:
        items = self.load(dataset)
        counts: Dict[str, int] = {}
        for d in items.values():
            counts[d.get("expect", "")] = counts.get(d.get("expect", ""), 0) + 1
        return {"path": str(self.path(dataset)), "count": len(items), "expect": counts,
                "labels": {k: d.get("expect") for k, d in items.items()}}

    def set(self, dataset: str, file: str, line: int, text: str, expect: Optional[str], rid: Any = None,
            note: str = "", category: str = "review") -> Dict[str, Any]:
        """Add / replace / (expect None or '') remove the label of one line; rewrites the file atomically."""
        if expect not in (None, "", "filter", "keep"):
            raise ValueError("expect must be 'filter' or 'keep' (or empty to remove the label)")
        with self._lock:
            items = self.load(dataset)
            k = self.key(file, int(line))
            entry = None
            if expect:
                entry = {"id": str(rid) if rid not in (None, "") else f"{dataset}:{file}:{line}", "text": text,
                         "expect": expect, "category": category, "note": note,
                         "source": {"dataset": dataset, "file": file, "line": int(line),
                                    **({"id": rid} if rid not in (None, "") else {})},
                         "labelled": time.strftime("%Y-%m-%d %H:%M:%S")}
                items[k] = entry
            else:
                items.pop(k, None)
            self._write(dataset, list(items.values()))
        return {"key": k, "entry": entry, "count": len(items)}

    def _write(self, dataset: str, rows: List[Dict[str, Any]]) -> None:
        p = self.path(dataset)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".jsonl.tmp")
        rows.sort(key=lambda d: (d["source"]["file"], d["source"]["line"]))
        tmp.write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in rows), encoding="utf-8")
        os.replace(tmp, p)

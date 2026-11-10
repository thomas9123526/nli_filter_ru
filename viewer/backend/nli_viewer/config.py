"""
config.py - viewer configuration: which datasets (corpus + output pairs) to show, and the cache.

viewer_config.json:
{
  "cache_dir": ".viewer_cache",          // relative to this file
  "cache_max_gb": 20,
  "cors_origins": ["http://localhost:3000"],
  "datasets": [
    {"name": "test", "title": "Test corpus (Russia)",
     "corpus": "../test_corpus", "output": "../out_test_corpus"},
    {"name": "s3run", "corpus": "minio://minio:9000/corpus", "output": "minio://minio:9000/nli-out",
     "corpus_options": {"access_key": "${MINIO_USER}", "secret_key": "${MINIO_PASSWORD}"},
     "output_options": {"access_key": "${MINIO_USER}", "secret_key": "${MINIO_PASSWORD}"}},
    {"name": "ftprun", "corpus": "ftp://reader:${FTP_PASSWORD}@ftp.lan/corpus", "output": "ftp://reader:${FTP_PASSWORD}@ftp.lan/out"}
  ]
}

${VAR} is replaced with the environment variable VAR, so passwords need not be written in the file.
Comments (// ...) are allowed.
"""
from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .lines import LineCache
from .results import Dataset
from .storage import open_storage

__all__ = ["DatasetConfig", "ViewerConfig", "load_config", "quick_config", "DatasetRegistry"]


@dataclass
class DatasetConfig:
    name: str
    corpus: str
    output: str
    title: Optional[str] = None
    description: str = ""
    corpus_options: Dict[str, Any] = field(default_factory=dict)
    output_options: Dict[str, Any] = field(default_factory=dict)
    text_field: Optional[str] = None
    id_field: Optional[str] = None
    refresh_seconds: float = 30.0   # how often the output folder is rescanned for new / changed results


@dataclass
class ViewerConfig:
    datasets: List[DatasetConfig]
    cache_dir: str = ".viewer_cache"
    cache_max_gb: float = 20.0
    cors_origins: List[str] = field(default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"])
    base_dir: str = "."
    frontend_dir: Optional[str] = None


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def _strip_comments(text: str) -> str:
    out = []
    for line in text.splitlines():
        in_str = False
        for i, ch in enumerate(line):
            if ch == '"' and (i == 0 or line[i - 1] != "\\"):
                in_str = not in_str
            if not in_str and line.startswith("//", i):
                line = line[:i]
                break
        out.append(line)
    return "\n".join(out)


def load_config(path: str) -> ViewerConfig:
    p = Path(path).resolve()
    data = _expand(json.loads(_strip_comments(p.read_text("utf-8"))))
    names = set()
    datasets = []
    for d in data.get("datasets", []):
        if not d.get("name") or not d.get("corpus") or not d.get("output"):
            raise ValueError(f"{p}: every dataset needs name, corpus and output: {d}")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", d["name"]):
            raise ValueError(f"{p}: dataset name '{d['name']}' may use only letters, digits, _ . -")
        if d["name"] in names:
            raise ValueError(f"{p}: duplicate dataset name '{d['name']}'")
        names.add(d["name"])
        datasets.append(DatasetConfig(**{k: v for k, v in d.items() if k in DatasetConfig.__dataclass_fields__}))
    if not datasets:
        raise ValueError(f"{p}: no datasets")
    cfg = ViewerConfig(datasets=datasets, base_dir=str(p.parent))
    for k in ("cache_dir", "cache_max_gb", "cors_origins", "frontend_dir"):
        if k in data:
            setattr(cfg, k, data[k])
    return cfg


def quick_config(corpus: str, output: str, name: str = "default", title: Optional[str] = None) -> ViewerConfig:
    """Config for a single dataset given on the command line."""
    return ViewerConfig(datasets=[DatasetConfig(name=name, corpus=corpus, output=output, title=title)],
                        base_dir=os.getcwd())


class DatasetRegistry:
    """Opens datasets lazily (a remote server that is down does not stop the others) and remembers errors."""

    def __init__(self, cfg: ViewerConfig):
        self.cfg = cfg
        cache_dir = Path(cfg.cache_dir)
        if not cache_dir.is_absolute():
            cache_dir = Path(cfg.base_dir) / cache_dir
        self.cache = LineCache(str(cache_dir), max_bytes=float(cfg.cache_max_gb) * 1e9)
        self._configs = {d.name: d for d in cfg.datasets}
        self._open: Dict[str, Dataset] = {}
        self._errors: Dict[str, str] = {}
        self._lock = threading.Lock()

    def names(self) -> List[str]:
        return list(self._configs)

    def config(self, name: str) -> DatasetConfig:
        if name not in self._configs:
            raise KeyError(f"unknown dataset '{name}'")
        return self._configs[name]

    def get(self, name: str) -> Dataset:
        c = self.config(name)
        with self._lock:
            if name in self._open:
                return self._open[name]
            try:
                corpus = open_storage(c.corpus, self.cfg.base_dir, **c.corpus_options)
                output = open_storage(c.output, self.cfg.base_dir, **c.output_options)
            except Exception as exc:
                self._errors[name] = str(exc)
                raise
            ds = Dataset(c.name, corpus, output, self.cache, c.title, c.description, c.text_field, c.id_field,
                         refresh_seconds=float(c.refresh_seconds))
            self._open[name] = ds
            self._errors.pop(name, None)
            return ds

    def describe(self, probe_seconds: float = 5.0) -> List[Dict[str, Any]]:
        """Every dataset with its (masked) locations; error set when its storage cannot be reached.
        Remote storages are probed in parallel; a probe that takes longer than probe_seconds is reported as slow."""
        import concurrent.futures as cf

        def probe(name: str) -> Optional[str]:
            ds = self.get(name)
            ds.output.list("")
            return None

        out = []
        # not a `with` block: leaving it would wait for a probe that hangs
        pool = cf.ThreadPoolExecutor(max_workers=max(1, min(8, len(self._configs))))
        try:
            futures = {name: pool.submit(probe, name) for name in self._configs}
            cf.wait(futures.values(), timeout=probe_seconds)
            for name, c in self._configs.items():
                row = {"name": name, "title": c.title or name, "description": c.description,
                       "corpus": _mask(c.corpus), "output": _mask(c.output), "error": None}
                fut = futures[name]
                if not fut.done():
                    row["error"] = f"no answer within {probe_seconds:.0f}s (server slow or unreachable)"
                elif fut.exception() is not None:
                    row["error"] = str(fut.exception())
                if name in self._open:
                    ds = self._open[name]
                    row["corpus"], row["output"] = ds.corpus.display_uri, ds.output.display_uri
                out.append(row)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return out

    def close(self) -> None:
        for ds in self._open.values():
            ds.corpus.close()
            ds.output.close()


def _mask(uri: str) -> str:
    return re.sub(r"(://[^/@:]+):[^/@]*@", r"\1:***@", uri)

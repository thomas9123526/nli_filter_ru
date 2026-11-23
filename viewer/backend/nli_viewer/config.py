"""
config.py - viewer configuration: which datasets (corpus + output pairs) to show, and the cache.

viewer_config.json:
{
  "cache_dir": ".viewer_cache",          // relative to this file
  "cache_max_gb": 20,
  "cors_origins": ["http://localhost:3000"],
  "datasets": [
    {"name": "test", "title": "Test corpus (Russia)",
     "corpus": "../dataset/test_corpus", "output": "../dataset/out_test_corpus",
     "editable": true},                   // allow editing the text of corpus lines (local corpus only)
    {"name": "s3run", "corpus": "minio://minio:9000/corpus", "output": "minio://minio:9000/nli-out",
     "corpus_options": {"access_key": "${MINIO_USER}", "secret_key": "${MINIO_PASSWORD}"},
     "output_options": {"access_key": "${MINIO_USER}", "secret_key": "${MINIO_PASSWORD}"}},
    {"name": "ftprun", "corpus": "ftp://reader:${FTP_PASSWORD}@ftp.lan/corpus", "output": "ftp://reader:${FTP_PASSWORD}@ftp.lan/out"}
  ]
}

Editing (see edit.py): "editable": true on a dataset whose corpus is on a local / mapped drive. Optional top level
keys: "edits_dir" (backups of the original files + edit log, default ".viewer_edits"), "edit_zstd_level" (3),
"edit_allow_remote" (false: only a browser on the viewer's own PC may edit, also when started with -Public).

"output" may be left out, or be a local folder that does not exist yet (corpus only, e.g. to browse or edit it
before running nli_filter.py): the viewer shows "no filter results yet" and picks the folder up once it appears.

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
from typing import Any, BinaryIO, Dict, List, Optional

from .lines import LineCache
from .results import Dataset
from .storage import Entry, LocalStorage, Storage, clean_path, open_storage

__all__ = ["DatasetConfig", "ViewerConfig", "load_config", "quick_config", "DatasetRegistry"]


@dataclass
class DatasetConfig:
    name: str
    corpus: str
    output: str = ""                # "" = no filter results (yet): corpus only
    title: Optional[str] = None
    description: str = ""
    corpus_options: Dict[str, Any] = field(default_factory=dict)
    output_options: Dict[str, Any] = field(default_factory=dict)
    text_field: Optional[str] = None
    id_field: Optional[str] = None
    refresh_seconds: float = 30.0   # how often the output folder is rescanned for new / changed results
    editable: bool = False          # corpus lines' text may be edited in the viewer (local corpus only)


@dataclass
class ViewerConfig:
    datasets: List[DatasetConfig]
    cache_dir: str = ".viewer_cache"
    cache_max_gb: float = 20.0
    cors_origins: List[str] = field(default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"])
    base_dir: str = "."
    frontend_dir: Optional[str] = None
    edits_dir: str = ".viewer_edits"    # original copies of edited files + edit log, per dataset
    edit_zstd_level: int = 3
    edit_allow_remote: bool = False     # False: only requests from this PC (127.0.0.1 / ::1) may edit
    playground_url: str = "http://127.0.0.1:8100"  # nli_playground.py (models) for the "Try settings" panel
    project_dir: str = ".."             # folder with nli_filter.py, hypotheses/, keywords/ (relative to the config)
    progress_stale_seconds: float = 120.0  # a running nli_filter.py whose progress file is older: "no update"
    auto_datasets: Optional[str] = None  # a folder (e.g. "../dataset"): its run folders become datasets (discover.py)


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
        if not d.get("name") or not d.get("corpus"):
            raise ValueError(f"{p}: every dataset needs name and corpus (output is optional): {d}")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", d["name"]):
            raise ValueError(f"{p}: dataset name '{d['name']}' may use only letters, digits, _ . -")
        if d["name"] in names:
            raise ValueError(f"{p}: duplicate dataset name '{d['name']}'")
        names.add(d["name"])
        datasets.append(DatasetConfig(**{k: v for k, v in d.items() if k in DatasetConfig.__dataclass_fields__}))
    if not datasets and not data.get("auto_datasets"):
        raise ValueError(f"{p}: no datasets")
    cfg = ViewerConfig(datasets=datasets, base_dir=str(p.parent))
    for k in ("cache_dir", "cache_max_gb", "cors_origins", "frontend_dir", "edits_dir", "edit_zstd_level",
              "edit_allow_remote", "playground_url", "project_dir", "progress_stale_seconds", "auto_datasets"):
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
        edits_dir = Path(cfg.edits_dir)
        self.edits_dir = edits_dir if edits_dir.is_absolute() else Path(cfg.base_dir) / edits_dir
        self._configs = {d.name: d for d in cfg.datasets}
        self._auto: set = set()  # names added by set_auto (dynamic datasets)
        self._open: Dict[str, Dataset] = {}
        self._errors: Dict[str, str] = {}
        self._lock = threading.Lock()

    def names(self) -> List[str]:
        return list(self._configs)

    def is_auto(self, name: str) -> bool:
        return name in self._auto

    def configured_pairs(self) -> Dict[str, tuple]:
        """{name: (corpus, output)} of the datasets from the config file (local paths resolved)."""
        out = {}
        for n, c in self._configs.items():
            if n in self._auto:
                continue

            def res(v: str) -> str:
                if not v or "://" in v:
                    return v or ""
                p = Path(v)
                return str((p if p.is_absolute() else Path(self.cfg.base_dir) / p).resolve())
            out[n] = (res(c.corpus), res(c.output))
        return out

    def set_auto(self, entries: List[Dict[str, Any]]) -> None:
        """Replace the dynamic datasets; one whose output changed (a newer run) is opened again."""
        with self._lock:
            new = {e["name"]: e for e in entries}
            for name in list(self._auto):
                old = self._configs.get(name)
                if name not in new or (old is not None and old.output != new[name]["output"]):
                    ds = self._open.pop(name, None)
                    if ds is not None:
                        ds.corpus.close()
                        ds.output.close()
                    if name not in new:
                        self._configs.pop(name, None)
                        self._auto.discard(name)
            for name, e in new.items():
                self._configs[name] = DatasetConfig(name=name, corpus=e["corpus"], output=e["output"],
                                                    title=e.get("title"), description=e.get("description") or "")
                self._auto.add(name)

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
                output = _open_output(c.output, self.cfg.base_dir, c.output_options)
            except Exception as exc:
                self._errors[name] = str(exc)
                raise
            ds = Dataset(c.name, corpus, output, self.cache, c.title, c.description, c.text_field, c.id_field,
                         refresh_seconds=float(c.refresh_seconds))
            if c.editable:
                from .edit import CorpusEditor
                ds.editor = CorpusEditor(ds, str(self.edits_dir), zstd_level=int(self.cfg.edit_zstd_level))
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
                       "corpus": _mask(c.corpus), "output": _mask(c.output), "error": None,
                       "editable": bool(c.editable), "auto": name in self._auto}
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


class PendingOutput(Storage):
    """
    Output location without results yet: no "output" in the config, or a local folder that does not exist yet.
    Looks like an empty folder; a local folder is used as soon as it appears (nli_filter.py creates it).
    """

    def __init__(self, path: Optional[str]):
        self.path = Path(path).expanduser().resolve() if path else None
        self.uri = str(self.path) if self.path else "(none)"
        self._real: Optional[LocalStorage] = None

    @property
    def ready(self) -> bool:
        return self._get() is not None

    def _get(self) -> Optional[LocalStorage]:
        if self._real is None and self.path is not None and self.path.is_dir():
            self._real = LocalStorage(str(self.path))
        return self._real

    @property
    def display_uri(self) -> str:
        if self.path is None:
            return "(no output folder configured)"
        return self.uri if self.ready else f"{self.uri} (not created yet)"

    def list(self, path: str = "") -> List[Entry]:
        real = self._get()
        if real is not None:
            return real.list(path)
        if clean_path(path):
            raise FileNotFoundError(path)
        return []

    def stat(self, path: str) -> Entry:
        real = self._get()
        if real is None:
            raise FileNotFoundError(path)
        return real.stat(path)

    def open(self, path: str) -> BinaryIO:
        real = self._get()
        if real is None:
            raise FileNotFoundError(path)
        return real.open(path)

    def local_path(self, path: str) -> Optional[str]:
        real = self._get()
        return real.local_path(path) if real is not None else None


def _open_output(uri: str, base_dir: str, options: Dict[str, Any]) -> Storage:
    """The output storage; a missing / not yet created local folder gives an empty PendingOutput."""
    if not uri:
        return PendingOutput(None)
    try:
        return open_storage(uri, base_dir, **options)
    except FileNotFoundError:
        if re.match(r"^[A-Za-z]:[\\/]", uri) or "://" not in uri or uri.lower().startswith("file:"):
            p = Path(uri[7:] if uri.lower().startswith("file://") else uri)
            return PendingOutput(str(p if p.is_absolute() else Path(base_dir) / p))
        raise


def _mask(uri: str) -> str:
    return re.sub(r"(://[^/@:]+):[^/@]*@", r"\1:***@", uri)

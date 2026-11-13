"""
results.py - an nli_filter.py output folder together with the corpus it was made from.

    from nli_viewer.results import Dataset
    ds = Dataset("test", corpus_storage, output_storage, cache)
    ds.overview()                         # totals, reasons, evaluation, run settings, models
    ds.files()                            # one FileResult per input file that has results
    ds.decisions("books/part-00/shard-00000").query(decision="filter", limit=20)
    ds.record("books/part-00/shard-00000", line=12)   # decision + original line + explanation

A file key is the output path of a file's results without the suffix: output
"books/part-00/shard-00000.summary.json" -> key "books/part-00/shard-00000". The corpus file is found in
the same sub folder of the corpus by its name without .jsonl/.zst/... (or by the name in the summary).
"""
from __future__ import annotations

import contextlib
import os
import shutil
import hashlib
import json
import posixpath
import sqlite3
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .explain import explain
from .lines import LineCache, LineFile, archive_members
from .storage import Entry, Storage, clean_path

import nli_formats  # noqa: E402  (project root, put on sys.path by .storage)

__all__ = ["Dataset", "FileResult", "DecisionIndex", "stem", "REASONS"]

_SUFFIXES = nli_formats.INPUT_SUFFIXES  # .jsonl .json .ndjson .gz .zst .zstd .zip .rar .parquet
REASONS = ["blank", "bad_json", "no_text", "no_keyword", "rules_incidental", "check1_negative",
           "check2_incidental", "about_country"]
_RUN_PREFIX = "summary"


def stem(name: str) -> str:
    """'shard-00000.jsonl.zst' -> 'shard-00000' (same rule nli_filter.py uses for output names)."""
    changed = True
    while changed:
        changed = False
        for suf in _SUFFIXES:
            if name.lower().endswith(suf) and len(name) > len(suf):
                name, changed = name[: -len(suf)], True
    return name


def _loads(data: bytes) -> Any:
    try:
        import orjson
        return orjson.loads(data)
    except ImportError:  # pragma: no cover
        return json.loads(data)


# --------------------------------------------------------------------------------------------------
# Decisions index (SQLite per decisions file)
# --------------------------------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE d (
  row INTEGER PRIMARY KEY,   -- line number inside the decisions file
  line INTEGER,              -- line number in the corpus file (or zip member)
  source TEXT,               -- zip member, else NULL
  id TEXT,
  decision TEXT,
  reason TEXT,
  c1 REAL,                   -- best check-1 score (NULL if check 1 did not run)
  judged INTEGER,            -- 1 if the judge decided the best check-1 pair
  hits INTEGER,
  kws TEXT,                  -- keywords hit, '|'-joined
  rules TEXT,                -- rules that resolved hits, '|'-joined
  c2 REAL,                   -- lowest check-2 score among hits that went to check 2
  expect TEXT,
  ok INTEGER                 -- 1/0 when expect is filter/keep, else NULL
);
"""
_INDEXES = """
CREATE INDEX ix_line ON d(line);
CREATE INDEX ix_id ON d(id);
CREATE INDEX ix_reason ON d(reason);
"""

_SORTS = {"row": "row", "line": "line", "score": "c1", "check1": "c1", "check2": "c2", "hits": "hits", "id": "id"}


class _Conn:
    """Thin wrapper so `con.close()` in the query code keeps the shared per-thread connection open."""

    def __init__(self, con: sqlite3.Connection):
        self._con = con

    def execute(self, *args):
        return self._con.execute(*args)

    def close(self) -> None:
        pass


class DecisionIndex:
    """SQLite table over one decisions file: filter, sort and page through decisions quickly."""

    def __init__(self, decisions: LineFile, cache: LineCache):
        self.decisions = decisions
        self.cache = cache
        self._db: Optional[str] = None
        self._lock = threading.Lock()
        self._local = threading.local()
        self._bg: Optional[threading.Thread] = None
        self.error: Optional[str] = None  # last background build error

    def ready(self) -> bool:
        """True when the SQLite table exists already (no build needed); cheap: one stat, no decompression."""
        if self._db:
            return True
        st, path = self.decisions.storage, self.decisions.path
        key = self.cache.key("decision-index-v1", st.uri, path, st.fingerprint(path))
        db = self.cache.dir(key) / "decisions.sqlite"
        if db.exists():
            with self._lock:
                self._db = self._db or str(db)
            return True
        return False

    def build_in_background(self) -> None:
        """Start building the table in a thread (no-op when it is ready or already being built)."""
        with self._lock:
            if self._db or (self._bg is not None and self._bg.is_alive()):
                return

            def run():
                try:
                    self._ensure()
                    self.error = None
                except Exception as exc:  # noqa: BLE001 - reported to the caller via .error
                    self.error = str(exc)

            self._bg = threading.Thread(target=run, name="decision-index", daemon=True)
            self._bg.start()

    def _ensure(self) -> str:
        if self._db:
            return self._db
        with self._lock:
            if self._db:
                return self._db
            st, path = self.decisions.storage, self.decisions.path
            key = self.cache.key("decision-index-v1", st.uri, path, st.fingerprint(path))
            d = self.cache.dir(key)
            db = d / "decisions.sqlite"
            with self.cache.lock(key):
                if not db.exists():
                    d.mkdir(parents=True, exist_ok=True)
                    self._build(str(db) + ".tmp")
                    Path(str(db) + ".tmp").replace(db)
            self.cache.touch(key)
            self._db = str(db)
            return self._db

    def _build(self, db: str) -> None:
        Path(db).unlink(missing_ok=True)
        con = sqlite3.connect(db, isolation_level=None)
        try:
            # a rebuildable cache written to a temporary file: no journal, no fsync (was ~75 % of the build time)
            con.execute("PRAGMA journal_mode=OFF")
            con.execute("PRAGMA synchronous=OFF")
            con.execute("BEGIN")
            con.execute(_SCHEMA)
            batch = []
            for row, raw in self.decisions.iter_lines():
                try:
                    d = _loads(raw)
                except ValueError:
                    continue
                batch.append(self._row(row, d))
                if len(batch) >= 5000:
                    con.executemany("INSERT INTO d VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
                    batch = []
            if batch:
                con.executemany("INSERT INTO d VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
            for stmt in _INDEXES.strip().splitlines():
                con.execute(stmt)
            con.execute("COMMIT")
        finally:
            con.close()

    @staticmethod
    def _row(row: int, d: Dict[str, Any]) -> Tuple:
        hits = d.get("hits") or []
        c1 = d.get("check1") or {}
        judged = None
        if c1:
            best = next((p for p in c1.get("pairs", []) if p.get("score") == c1.get("score")), None)
            judged = int(bool(best and best.get("judge") is not None))
        c2s = [h["check2"]["score"] for h in hits if h.get("check2")]
        expect = d.get("expect")
        ok = None
        if isinstance(expect, str) and expect.lower() in ("filter", "keep"):
            ok = int(expect.lower() == d.get("decision"))
        return (row, d.get("line"), d.get("source"), None if d.get("id") is None else str(d.get("id")),
                d.get("decision"), d.get("reason"), c1.get("score"), judged, len(hits),
                "|".join(sorted({h.get("kw", "") for h in hits})) or None,
                "|".join(sorted({h["rule"] for h in hits if h.get("rule")})) or None,
                min(c2s) if c2s else None, None if expect is None else str(expect), ok)

    def _connect(self) -> "_Conn":
        """Read-only connection, one per thread and index (opening one per query is slow on Windows)."""
        db = self._ensure()
        con = getattr(self._local, "con", None)
        if con is None:
            con = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True, check_same_thread=False)
            con.row_factory = sqlite3.Row
            self._local.con = con
        return _Conn(con)

    @staticmethod
    def _where(decision=None, reason=None, q=None, kw=None, rule=None, min_score=None, max_score=None,
               mismatch=False, judged=None) -> Tuple[str, List[Any]]:
        cond, args = [], []
        if decision:
            cond.append("decision = ?"); args.append(decision)
        if reason:
            reasons = [r for r in str(reason).split(",") if r]
            cond.append(f"reason IN ({','.join('?' * len(reasons))})"); args += reasons
        if q:
            if str(q).isdigit():
                cond.append("(line = ? OR id LIKE ?)"); args += [int(q), f"%{q}%"]
            else:
                cond.append("(id LIKE ? OR kws LIKE ?)"); args += [f"%{q}%", f"%{q}%"]
        if kw:
            cond.append("('|' || kws || '|') LIKE ?"); args.append(f"%|{kw}|%")
        if rule:
            cond.append("rules LIKE ?"); args.append(f"%{rule}%")
        if min_score is not None:
            cond.append("c1 >= ?"); args.append(float(min_score))
        if max_score is not None:
            cond.append("c1 <= ?"); args.append(float(max_score))
        if mismatch:
            cond.append("ok = 0")
        if judged is not None:
            cond.append("judged = ?"); args.append(int(bool(judged)))
        return (" WHERE " + " AND ".join(cond)) if cond else "", args

    def query(self, offset: int = 0, limit: int = 50, sort: str = "row", desc: bool = False,
              **filters: Any) -> Dict[str, Any]:
        where, args = self._where(**filters)
        col = _SORTS.get(sort, "row")
        order = f"{col} {'DESC' if desc else 'ASC'}" + ("" if col == "row" else ", row")
        con = self._connect()
        try:
            total = con.execute(f"SELECT COUNT(*) FROM d{where}", args).fetchone()[0]
            rows = con.execute(f"SELECT * FROM d{where} ORDER BY {order} LIMIT ? OFFSET ?",
                               args + [int(limit), int(offset)]).fetchall()
        finally:
            con.close()
        return {"total": total, "offset": offset, "limit": limit, "rows": [self._out(r) for r in rows]}

    @staticmethod
    def _out(r: sqlite3.Row) -> Dict[str, Any]:
        d = dict(r)
        d["kws"] = d["kws"].split("|") if d["kws"] else []
        d["rules"] = d["rules"].split("|") if d["rules"] else []
        d["judged"] = None if d["judged"] is None else bool(d["judged"])
        d["ok"] = None if d["ok"] is None else bool(d["ok"])
        return d

    def facets(self) -> Dict[str, Any]:
        con = self._connect()
        try:
            dec = {r[0]: r[1] for r in con.execute("SELECT decision, COUNT(*) FROM d GROUP BY decision")}
            rea = {r[0]: r[1] for r in con.execute("SELECT reason, COUNT(*) FROM d GROUP BY reason")}
            mism = con.execute("SELECT COUNT(*) FROM d WHERE ok = 0").fetchone()[0]
            labelled = con.execute("SELECT COUNT(*) FROM d WHERE ok IS NOT NULL").fetchone()[0]
            judged = con.execute("SELECT COUNT(*) FROM d WHERE judged = 1").fetchone()[0]
            total = con.execute("SELECT COUNT(*) FROM d").fetchone()[0]
            kws: Dict[str, int] = {}
            for (k,) in con.execute("SELECT kws FROM d WHERE kws IS NOT NULL"):
                for w in k.split("|"):
                    kws[w] = kws.get(w, 0) + 1
        finally:
            con.close()
        return {"total": total, "decisions": dec, "reasons": {k: rea[k] for k in REASONS if k in rea},
                "labelled": labelled, "mismatches": mism, "judged": judged,
                "keywords": dict(sorted(kws.items(), key=lambda kv: -kv[1])[:30])}

    def score_rows(self) -> List[Tuple[int, int, Optional[str], str, str, Optional[float], Optional[float], Optional[str]]]:
        """(row, line, id, decision, reason, c1, c2, expect) for every decision, for threshold simulation."""
        con = self._connect()
        try:
            return [tuple(r) for r in con.execute(
                "SELECT row, line, id, decision, reason, c1, c2, expect FROM d ORDER BY row")]
        finally:
            con.close()

    def find_row(self, line: int, source: Optional[str] = None) -> Optional[int]:
        con = self._connect()
        try:
            if source:
                r = con.execute("SELECT row FROM d WHERE line = ? AND source = ? LIMIT 1", (line, source)).fetchone()
            else:
                r = con.execute("SELECT row FROM d WHERE line = ? ORDER BY row LIMIT 1", (line,)).fetchone()
        finally:
            con.close()
        return r[0] if r else None

    def find_id(self, value: str, limit: int = 20) -> List[Dict[str, Any]]:
        con = self._connect()
        try:
            rows = con.execute("SELECT * FROM d WHERE id = ? ORDER BY row LIMIT ?", (value, limit)).fetchall()
        finally:
            con.close()
        return [self._out(r) for r in rows]

    def neighbours(self, row: int, **filters: Any) -> Dict[str, Optional[int]]:
        """Previous / next row overall and within the filters; position inside the filtered list."""
        where, args = self._where(**filters)
        joiner = " AND " if where else " WHERE "
        con = self._connect()
        try:
            def one(sql, a):
                r = con.execute(sql, a).fetchone()
                return r[0] if r else None
            out = {
                "prev": one("SELECT MAX(row) FROM d WHERE row < ?", [row]),
                "next": one("SELECT MIN(row) FROM d WHERE row > ?", [row]),
                "prev_match": one(f"SELECT MAX(row) FROM d{where}{joiner}row < ?", args + [row]),
                "next_match": one(f"SELECT MIN(row) FROM d{where}{joiner}row > ?", args + [row]),
                "position": one(f"SELECT COUNT(*) FROM d{where}{joiner}row <= ?", args + [row]),
                "matches": one(f"SELECT COUNT(*) FROM d{where}", args),
            }
        finally:
            con.close()
        return out


# --------------------------------------------------------------------------------------------------
# Dataset
# --------------------------------------------------------------------------------------------------


@dataclass
class FileResult:
    key: str                         # e.g. "books/part-00/shard-00000"
    summary_path: str                # in the output storage
    summary: Dict[str, Any]
    decisions_path: Optional[str] = None
    kept_path: Optional[str] = None
    filtered_path: Optional[str] = None
    corpus_path: Optional[str] = None  # in the corpus storage (None = not found)

    def row(self) -> Dict[str, Any]:
        st = self.summary.get("stats", {})
        dec = st.get("decisions", {})
        ev = (st.get("eval") or {}).get("metrics")
        return {"key": self.key, "input": posixpath.basename(str(self.summary.get("input", "")).replace("\\", "/")),
                "corpus_path": self.corpus_path, "decisions_path": self.decisions_path,
                "complete": self.summary.get("complete", True), "lines": st.get("lines", 0),
                "filtered": dec.get("filter", 0), "kept": dec.get("keep", 0), "reasons": st.get("reasons", {}),
                "seconds": self.summary.get("seconds"), "accuracy": ev.get("accuracy") if ev else None,
                "mistakes": (ev["fp"] + ev["fn"]) if ev else None}


class Dataset:
    """Results (output storage) + corpus (corpus storage) of one nli_filter.py run."""

    def __init__(self, name: str, corpus: Storage, output: Storage, cache: LineCache, title: Optional[str] = None,
                 description: str = "", text_field: Optional[str] = None, id_field: Optional[str] = None,
                 refresh_seconds: float = 30.0):
        self.name, self.corpus, self.output, self.cache = name, corpus, output, cache
        self.title = title or name
        self.description = description
        self._text_field, self._id_field = text_field, id_field
        self.refresh_seconds = refresh_seconds
        self._lock = threading.Lock()
        self._files: Optional[Dict[str, FileResult]] = None
        self._runs: List[Dict[str, Any]] = []
        self._loaded_at = 0.0
        self._corpus_map: Optional[Dict[str, str]] = None
        self._indexes: "OrderedDict[str, DecisionIndex]" = OrderedDict()
        self._line_files: "OrderedDict[Tuple[str, str, Optional[str]], LineFile]" = OrderedDict()
        self._fps: Dict[str, Tuple] = {}
        self.editor = None  # CorpusEditor when the dataset is editable (set by DatasetRegistry)
        self._members: Dict[str, Tuple[str, List[str]]] = {}  # archive path -> (fingerprint, member names)

    # ---- loading --------------------------------------------------------------------------------

    def refresh(self, force: bool = False) -> None:
        with self._lock:
            if not force and self._files is not None and time.time() - self._loaded_at < self.refresh_seconds:
                return
            files: Dict[str, FileResult] = {}
            runs: List[Dict[str, Any]] = []
            outputs: Dict[str, List[Entry]] = {}
            fps: Dict[str, Tuple] = {}
            for e in self.output.walk(""):
                outputs.setdefault(posixpath.dirname(e.path), []).append(e)
                fps[e.path] = (e.size, e.mtime, e.etag)
            # output files rewritten since the last scan (e.g. nli_filter.py --overwrite): forget their indexes
            for path, fp in self._fps.items():
                if fps.get(path) != fp:
                    self._indexes.pop(path, None)
                    self._line_files.pop((self.output.uri, path, None), None)
            self._fps = fps
            for folder, entries in outputs.items():
                names = {e.name for e in entries}
                for e in entries:
                    if not e.name.endswith(".summary.json"):
                        if folder == "" and e.name.startswith(_RUN_PREFIX) and e.name.endswith(".json"):
                            runs.append(self._read_json(e.path) | {"_file": e.name})
                        continue
                    if folder == "" and e.name.startswith(_RUN_PREFIX + "."):
                        continue  # run summary, not a per-file one
                    key = e.path[: -len(".summary.json")]
                    summary = self._read_json(e.path)
                    base = posixpath.basename(key)

                    def pick(kind: str) -> Optional[str]:
                        out_name = posixpath.basename(str((summary.get("outputs") or {}).get(kind) or "")
                                                      .replace("\\", "/"))
                        if out_name and out_name in names:
                            return posixpath.join(folder, out_name) if folder else out_name
                        for n in sorted(names):
                            if n.startswith(f"{base}.{kind}.jsonl"):
                                return posixpath.join(folder, n) if folder else n
                        return None

                    files[key] = FileResult(key, e.path, summary, pick("decisions"), pick("kept"), pick("filtered"))
            for fr in files.values():
                fr.corpus_path = self._find_corpus(fr)
            self._files, self._runs, self._loaded_at = files, runs, time.time()

    def _read_json(self, path: str) -> Dict[str, Any]:
        try:
            return json.loads(self.output.read_bytes(path).decode("utf-8"))
        except (ValueError, FileNotFoundError):
            return {}

    def _find_corpus(self, fr: FileResult) -> Optional[str]:
        folder, base = posixpath.split(fr.key)
        wanted = posixpath.basename(str(fr.summary.get("input", "")).replace("\\", "/"))
        try:
            entries = [e for e in self.corpus.list(folder) if not e.is_dir]
        except FileNotFoundError:
            entries = []
        cands = [e for e in entries if stem(e.name) == base]
        exact = [e for e in cands if e.name == wanted]
        if exact or cands:
            return (exact or cands)[0].path
        # layout differs: search the whole corpus once by name
        if self._corpus_map is None:
            self._corpus_map = {}
            for e in self.corpus.walk(""):
                self._corpus_map.setdefault(e.name, e.path)
                self._corpus_map.setdefault("stem:" + stem(e.name), e.path)
        return self._corpus_map.get(wanted) or self._corpus_map.get("stem:" + base)

    # ---- queries --------------------------------------------------------------------------------

    def files(self) -> List[FileResult]:
        self.refresh()
        return [self._files[k] for k in sorted(self._files)]

    def file(self, key: str) -> FileResult:
        self.refresh()
        key = clean_path(key)
        if key not in self._files:
            self.refresh(force=True)
        if key not in self._files:
            raise KeyError(f"no results for '{key}'")
        return self._files[key]

    def runs(self) -> List[Dict[str, Any]]:
        self.refresh()
        return [r for r in self._runs if r.get("_file") != "summary.report.json"] or list(self._runs)

    def run_for(self, key: str) -> Dict[str, Any]:
        """The run summary that processed this file (latest run if no run lists it)."""
        runs = self.runs()
        for r in sorted(runs, key=lambda r: r.get("finished", ""), reverse=True):
            for f in r.get("files", []):
                p = stem(str(f.get("input", "")).replace("\\", "/"))
                if p == key or p.endswith("/" + key):
                    return r
        return max(runs, key=lambda r: r.get("finished", ""), default={})

    def overview(self) -> Dict[str, Any]:
        files = self.files()
        totals = {"lines": 0, "decisions": {}, "reasons": {}, "rules": {}, "hits": 0, "check1_windows": 0,
                  "check2_hits": 0}
        conf = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
        by_group: Dict[str, Dict[str, int]] = {}
        for fr in files:
            st = fr.summary.get("stats", {})
            totals["lines"] += st.get("lines", 0)
            for k in ("hits", "check1_windows", "check2_hits"):
                totals[k] += st.get(k, 0)
            for part in ("decisions", "reasons", "rules"):
                for k, v in (st.get(part) or {}).items():
                    totals[part][k] = totals[part].get(k, 0) + v
            ev = st.get("eval")
            if ev:
                for k in conf:
                    conf[k] += ev.get("confusion", {}).get(k, 0)
                for g, c in (ev.get("by_group") or {}).items():
                    gg = by_group.setdefault(g, {"tp": 0, "fp": 0, "tn": 0, "fn": 0})
                    for k in gg:
                        gg[k] += c.get(k, 0)
        totals["reasons"] = {k: totals["reasons"][k] for k in REASONS if k in totals["reasons"]}
        n = sum(conf.values())
        evaluation = None
        if n:
            p = conf["tp"] / (conf["tp"] + conf["fp"]) if conf["tp"] + conf["fp"] else None
            r = conf["tp"] / (conf["tp"] + conf["fn"]) if conf["tp"] + conf["fn"] else None
            evaluation = {**conf, "n": n, "accuracy": (conf["tp"] + conf["tn"]) / n, "precision": p, "recall": r,
                          "f1": 2 * p * r / (p + r) if p and r else None, "by_group": by_group}
        runs = self.runs()
        latest = max(runs, key=lambda r: r.get("finished", ""), default={})
        return {
            "name": self.name, "title": self.title, "description": self.description,
            "corpus": self.corpus.display_uri, "output": self.output.display_uri,
            "files": len(files), "files_complete": sum(1 for f in files if f.summary.get("complete", True)),
            "files_without_corpus": [f.key for f in files if not f.corpus_path],
            # False: no output folder yet (corpus only); the corpus can still be browsed and edited
            "output_ready": getattr(self.output, "ready", True),
            "totals": totals, "evaluation": evaluation,
            "run": {k: latest.get(k) for k in ("country", "hypotheses", "settings", "models", "timing", "command",
                                               "finished")} if latest else None,
            "runs": [{"file": r.get("_file"), "finished": r.get("finished"), "command": r.get("command"),
                      "lines": (r.get("stats") or {}).get("lines"), "timing": r.get("timing")} for r in runs],
        }

    # ---- lines ----------------------------------------------------------------------------------

    MAX_OPEN_LINE_FILES = 128   # each keeps its line offsets in memory (8 bytes per line)
    MAX_OPEN_INDEXES = 64

    @staticmethod
    def _lru_get(store: "OrderedDict", key, make, limit: int):
        if key in store:
            store.move_to_end(key)
            return store[key]
        value = store[key] = make()
        while len(store) > limit:
            store.popitem(last=False)
        return value

    def _line_file(self, storage: Storage, path: str, member: Optional[str] = None) -> LineFile:
        return self._lru_get(self._line_files, (storage.uri, path, member),
                             lambda: LineFile(storage, path, member, self.cache), self.MAX_OPEN_LINE_FILES)

    def decisions(self, key: str) -> DecisionIndex:
        fr = self.file(key)
        if not fr.decisions_path:
            raise KeyError(f"'{key}' has no decisions file (run nli_filter.py with --decisions all or candidates)")
        return self._lru_get(self._indexes, fr.decisions_path,
                             lambda: DecisionIndex(self._line_file(self.output, fr.decisions_path), self.cache),
                             self.MAX_OPEN_INDEXES)

    def corpus_line(self, path: str, line: int, member: Optional[str] = None) -> bytes:
        return self._line_file(self.corpus, clean_path(path), member).line(line)

    def record(self, key: str, row: Optional[int] = None, line: Optional[int] = None, source: Optional[str] = None,
               max_chars: int = 30000, **filters: Any) -> Dict[str, Any]:
        """Everything about one line: decision, original record, explanation, navigation."""
        fr = self.file(key)
        idx = self.decisions(key)
        if row is None:
            if line is None:
                raise ValueError("give row or line")
            row = idx.find_row(int(line), source)
            if row is None:
                raise KeyError(f"line {line} of '{key}' has no decision record")
        lf = self._line_file(self.output, fr.decisions_path)
        try:
            decision = _loads(lf.line(int(row)))
        except IndexError:
            raise KeyError(f"row {row} not in decisions of '{key}'") from None
        run = self.run_for(key)
        settings = run.get("settings") or {}
        text_field = self._text_field or settings.get("text_field") or "text"
        id_field = self._id_field or settings.get("id_field") or "id"
        original: Dict[str, Any] = {"available": False, "path": fr.corpus_path, "member": decision.get("source")}
        text = None
        if fr.corpus_path:
            try:
                raw = self.corpus_line(fr.corpus_path, int(decision["line"]), decision.get("source"))
                original.update(available=True, raw=raw.decode("utf-8", "replace"))
                try:
                    obj = _loads(raw)
                    original["record"] = obj
                    if isinstance(obj, dict):
                        t = obj.get(text_field)
                        text = t if isinstance(t, str) else None
                        original["id"] = obj.get(id_field)
                        original["fields"] = sorted(obj.keys())
                except ValueError as exc:
                    original["error"] = f"not valid JSON: {exc}"
            except (IndexError, FileNotFoundError) as exc:
                original["error"] = f"line {decision.get('line')} not found in {fr.corpus_path}: {exc}"
        else:
            original["error"] = "corpus file not found"
        edit = self._edit_info(fr, decision, original, text)
        if edit.get("edited_after_filter") and edit.get("filtered_text") is not None:
            text = edit["filtered_text"]  # the decision's spans and scores belong to the text before the edits
        if original.get("record") is not None and len(original.get("raw", "")) > 200000:
            original["raw"] = original["raw"][:200000]
            original["raw_truncated"] = True
        id_mismatch = (decision.get("id") is not None and original.get("id") is not None
                       and str(decision["id"]) != str(original["id"]))
        return {
            "dataset": self.name, "file": key, "row": int(row), "line": decision.get("line"),
            "decision": decision, "original": original, "text_field": text_field, "edit": edit,
            "id_check": {"decision_id": decision.get("id"), "original_id": original.get("id"), "match": not id_mismatch},
            "explanation": explain(text, decision, run, max_chars=max_chars),
            "nav": idx.neighbours(int(row), **filters),
            "files": {"corpus": fr.corpus_path, "decisions": fr.decisions_path, "summary": fr.summary_path},
        }

    # ---- editing (see edit.py) ------------------------------------------------------------------

    def edit_problem(self, path: Optional[str] = None, member: Optional[str] = None) -> Optional[str]:
        """Why the corpus (or this corpus file) cannot be edited; None = it can."""
        if self.editor is None:
            return 'editing is off for this dataset (set "editable": true in viewer_config.json)'
        return self.editor.problem(path, member)

    def _decisions_time(self, fr: FileResult) -> Optional[float]:
        try:
            return self.output.stat(fr.decisions_path).mtime if fr.decisions_path else None
        except (FileNotFoundError, OSError):
            return None

    def _edit_info(self, fr: FileResult, decision: Dict[str, Any], original: Dict[str, Any],
                   text: Optional[str]) -> Dict[str, Any]:
        """Can this line be edited, and was it edited after the filter run (then: the text the run saw)."""
        member = decision.get("source") if fr.corpus_path and nli_formats.is_archive(fr.corpus_path) else None
        problem = self.edit_problem(fr.corpus_path, member) if fr.corpus_path else "corpus file not found"
        if problem is None and (not original.get("available") or text is None):
            problem = original.get("error") or "the line has no text field"
        info: Dict[str, Any] = {"editable": problem is None, "problem": problem, "path": fr.corpus_path,
                                "member": member, "line": decision.get("line"), "text": text, "edits": 0,
                                "edited_after_filter": False, "filtered_text": None}
        if original.get("raw") is not None:
            info["sha1"] = hashlib.sha1(original["raw"].encode("utf-8")).hexdigest()
        if self.editor is not None and fr.corpus_path and decision.get("line"):
            edits, before = self.editor.since(fr.corpus_path, int(decision["line"]), self._decisions_time(fr), member)
            info["edits"] = len(self.editor.history(fr.corpus_path, int(decision["line"]), member))
            if edits:
                info.update(edited_after_filter=True, edits_after_filter=len(edits), filtered_text=before,
                            last_edit=edits[-1]["time"])
        return info

    def members(self, path: str) -> List[str]:
        """Readable members of a .zip / .rar corpus file (remembered per file version; a server file is downloaded
        once to list them)."""
        path = clean_path(path)
        fp = self.corpus.fingerprint(path)
        hit = self._members.get(path)
        if hit and hit[0] == fp:
            return hit[1]
        local = self.corpus.local_path(path)
        if local is not None:
            names = archive_members(local)
        else:
            import tempfile
            fd, tmp = tempfile.mkstemp(suffix=Path(path).suffix, prefix="nli_members_")
            os.close(fd)
            try:
                with self.corpus.open(path) as src, open(tmp, "wb") as dst:
                    shutil.copyfileobj(src, dst, 8 << 20)
                names = archive_members(tmp)
            finally:
                with contextlib.suppress(OSError):
                    os.remove(tmp)
        self._members[path] = (fp, names)
        return names

    def corpus_lines(self, path: str, start: int = 1, count: int = 20, preview: int = 0,
                     member: Optional[str] = None) -> Dict[str, Any]:
        """Lines of a corpus file (or of one member of a .zip / .rar) for the corpus page: text, id, sha1, edits,
        link to the decision record."""
        from .edit import line_sha1
        path = clean_path(path)
        members: Optional[List[str]] = None
        if nli_formats.is_archive(path):
            members = self.members(path)
            if not members:
                raise KeyError(f"{path} has no readable member (.jsonl / .json / .gz / .zst)")
            member = member or members[0]
            if member not in members:
                raise KeyError(f"{path} has no member '{member}'")
        else:
            member = None
        lf = self._line_file(self.corpus, path, member)
        total = len(lf)
        if total and not 1 <= start <= total:
            raise KeyError(f"line {start} out of range 1..{total}")
        settings = (max(self.runs(), key=lambda r: r.get("finished", ""), default={}).get("settings") or {})
        text_field = self._text_field or settings.get("text_field") or "text"
        id_field = self._id_field or settings.get("id_field") or "id"
        fr = next((f for f in self.files() if f.corpus_path == path), None)
        idx = self.decisions(fr.key) if fr is not None and fr.decisions_path else None
        decisions_pending = False
        if idx is not None and not idx.ready():
            # building the decisions table of a big file takes a while: show the lines now, links when it is done
            idx.build_in_background()
            decisions_pending, idx = True, None
        edited = self.editor.edited_lines(path, member) if self.editor is not None else {}
        rows = []
        for k, raw in enumerate(lf.lines(start, count) if total else []):
            n = start + k
            row: Dict[str, Any] = {"line": n, "sha1": line_sha1(raw), "id": None, "text": None, "edits": edited.get(n, 0)}
            try:
                obj = _loads(raw)
                if isinstance(obj, dict):
                    t = obj.get(text_field)
                    row["text"] = t if isinstance(t, str) else None
                    row["id"] = obj.get(id_field)
                else:
                    row["error"] = "not a JSON object"
            except ValueError as exc:
                row["error"] = f"not valid JSON: {exc}"
                row["raw"] = raw[:2000].decode("utf-8", "replace")
            if preview and row["text"] is not None and len(row["text"]) > preview:
                row["text_length"] = len(row["text"])
                row["text"] = row["text"][:preview]
                row["truncated"] = True
            if idx is not None:
                r = idx.find_row(n, member)
                if r is not None:
                    row["row"] = r
            rows.append(row)
        return {"path": path, "member": member, "members": members, "total_lines": total, "start": start,
                "count": len(rows), "text_field": text_field,
                "file_key": fr.key if fr else None, "editable": self.edit_problem(path, member) is None,
                "problem": self.edit_problem(path, member), "decisions_pending": decisions_pending, "lines": rows}

    def simulate(self, check1: float, check2: float, max_flips: int = 300,
                 sweep: Iterable[float] = ()) -> Dict[str, Any]:
        """
        Decisions recomputed from the stored final scores with other thresholds (no model is run):
            filter = best check-1 score >= check1  AND NOT (every open hit's best check-2 score >= check2)
        Lines that were check-1 negative never went to check 2; if they become positive their check-2 result is
        unknown: they count as filtered and are marked 'estimated' (a real rerun could rescue some).
        The judge only re-scored pairs inside the run's uncertain band, so for thresholds far outside that band
        the result is an approximation too.
        """
        rows = []
        for fr in self.files():
            if fr.decisions_path:
                rows += [(fr.key,) + r for r in self.decisions(fr.key).score_rows()]
        run = max(self.runs(), key=lambda r: r.get("finished", ""), default={})
        st = run.get("settings") or {}
        cur1, cur2 = st.get("check1_threshold", 0.8), st.get("check2_threshold", 0.8)
        check2_on = bool((run.get("hypotheses") or {}).get("check2", {"x": 1}))
        # early stop (nli_filter default since 2026-11-13): a positive line stored its first check-1 score
        # >= threshold, not its best, and check 2 stopped at the first hit that was not incidental. Results that
        # depend on the scores never computed are marked 'estimated'.
        early = bool(st.get("early_stop", False))

        def decide(c1, c2, decision, t1, t2):
            if c1 is None:
                return decision, False  # never reached NLI: unchanged
            if c1 < t1:
                # an early-stopped positive line may have a higher score in a window that was not scored
                return "keep", early and c1 >= cur1
            if c2 is None:
                # positive now; check 2 ran only if it was positive before (then c2 None = no check 2 at all)
                return "filter", decision == "keep" and check2_on and c1 < cur1
            if c2 >= t2:
                # check 2 stopped at the hit with score c2: the hits after it were not scored
                return "keep", early and c2 < cur2
            return "filter", False

        def evaluate(t1, t2, collect=False):
            counts = {"filter": 0, "keep": 0, "to_filter": 0, "to_keep": 0, "estimated": 0}
            conf = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
            flips = []
            for key, row, line, rid, decision, reason, c1, c2, expect in rows:
                new, est = decide(c1, c2, decision, t1, t2)
                counts[new] += 1
                counts["estimated"] += est
                if new != decision:
                    counts["to_" + new] += 1
                    if collect and len(flips) < max_flips:
                        flips.append({"file": key, "row": row, "line": line, "id": rid, "from": decision, "to": new,
                                      "reason": reason, "c1": c1, "c2": c2, "estimated": est, "expect": expect})
                e = str(expect or "").lower()
                if e in ("filter", "keep"):
                    conf[{("filter", "filter"): "tp", ("keep", "filter"): "fp", ("keep", "keep"): "tn",
                          ("filter", "keep"): "fn"}[(e, new)]] += 1
            n = sum(conf.values())
            metrics = None
            if n:
                p = conf["tp"] / (conf["tp"] + conf["fp"]) if conf["tp"] + conf["fp"] else None
                r = conf["tp"] / (conf["tp"] + conf["fn"]) if conf["tp"] + conf["fn"] else None
                metrics = {**conf, "n": n, "accuracy": (conf["tp"] + conf["tn"]) / n, "precision": p, "recall": r,
                           "f1": 2 * p * r / (p + r) if p and r else None}
            return counts, metrics, flips

        cur_counts, cur_metrics, _ = evaluate(cur1, cur2)
        new_counts, new_metrics, flips = evaluate(check1, check2, collect=True)
        out = {"lines": len(rows), "current": {"check1": cur1, "check2": cur2, "counts": cur_counts,
                                                "metrics": cur_metrics},
               "simulated": {"check1": check1, "check2": check2, "counts": new_counts, "metrics": new_metrics},
               "flips": flips, "flips_truncated": new_counts["to_filter"] + new_counts["to_keep"] > len(flips),
               "band": st.get("uncertain_band"), "sweep": []}
        for t in sweep:
            c, m, _ = evaluate(t, check2)
            out["sweep"].append({"check1": t, "check2": check2, "filter": c["filter"], "estimated": c["estimated"],
                                 "metrics": m})
        return out

    def find_id(self, value: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Rows with this id in any file (indexes the decisions files that are not indexed yet)."""
        out = []
        for fr in self.files():
            if not fr.decisions_path:
                continue
            for r in self.decisions(fr.key).find_id(value, limit - len(out)):
                out.append({"file": fr.key, **r})
            if len(out) >= limit:
                break
        return out

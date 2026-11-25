"""
labels.py - the viewer's Labels pages: nli_label.py runs (policy labels per paragraph).

A label run is a folder with summary.json (written by nli_label.py run / redecide, it has a "policy" key) and
<name>.labels.jsonl per input file, or a progress.json while the run is going. Folders are found in the project
folder (one level deep). Nothing here imports torch: the source text is read with nli_models.JsonlSource.
"""
from __future__ import annotations

import collections
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
        self.extra: Dict[str, Path] = {}  # runs outside the project folder, named after their dataset
        self._exp_cache: Dict[tuple, Dict[int, Dict[str, Any]]] = {}  # (corpus file, mtime) -> expected per line
        if str(self.project) not in sys.path:
            sys.path.insert(0, str(self.project))

    # ---- finding runs ------------------------------------------------------------------------------
    def _is_run(self, d: Path) -> bool:
        s = d / "summary.json"
        if s.is_file():
            data = _read_json(s) or {}
            return "policy" in data
        p = self._progress_files(d)
        return bool(p) and str(_read_json(p[0]) and _read_json(p[0]).get("command", "")).startswith("nli_label.py")

    @staticmethod
    def _progress_files(d: Path) -> List[Path]:
        """progress.json, or progress.shardKofN.json of a run split with --shard."""
        one = d / "progress.json"
        return [one] if one.is_file() else sorted(d.glob("progress.shard*.json"))

    def roots(self) -> List[Path]:
        """Where runs are looked for: the project folder, then its dataset/ folder (runs moved there)."""
        return [self.project, self.project / "dataset"]

    def is_run_folder(self, d: Path) -> bool:
        try:
            return d.is_dir() and self._is_run(d)
        except OSError:
            return False

    def register(self, dataset: str, d: Path) -> Optional[str]:
        """A dataset's local output folder that is an nli_label.py run -> the run's name on the Labels pages (the
        folder name inside the project folder or its dataset/ folder, else the dataset name); None when it is not a
        label run."""
        d = Path(d)
        if not self.is_run_folder(d):
            return None
        try:
            if any(d.resolve().parent == r.resolve() for r in self.roots()):
                return d.name
        except OSError:
            pass
        self.extra[dataset] = d
        return dataset

    def folder(self, name: str) -> Path:
        if not name or "/" in name or "\\" in name or name.startswith("."):
            raise ValueError(f"bad run name '{name}'")
        if name in self.extra:
            return self.extra[name]
        for root in self.roots():  # the project folder first, then dataset/
            d = root / name
            if self.is_run_folder(d):
                return d
        raise KeyError(f"no nli_label.py run '{name}' in {self.project} or its dataset folder")

    def progress(self, d: Path) -> Optional[Dict[str, Any]]:
        parts = []
        for f in self._progress_files(d):
            p = _read_json(f)
            if not p:
                continue
            if p.get("state") == "running":
                try:
                    age = time.time() - f.stat().st_mtime
                except OSError:
                    age = 0
                if age > self.stale:
                    p["state"] = "stale"
                    p["note"] = f"no update for {int(age)} s: the run was probably stopped"
            parts.append(p)
        if not parts:
            return None
        if len(parts) == 1:
            return parts[0]
        # shards: one combined view (running while any shard runs)
        states = [p.get("state") for p in parts]
        state = next((s for s in ("running", "stale", "failed") if s in states), "done")
        return {"state": state, "command": parts[0].get("command"), "shards": len(parts),
                "started": min(p.get("started") or "" for p in parts),
                "updated": max(p.get("updated") or "" for p in parts),
                "files_total": sum(p.get("files_total") or 0 for p in parts),
                "files_done": sum(p.get("files_done") or 0 for p in parts),
                "lines_done": sum(p.get("lines_done") or 0 for p in parts),
                "seconds": max(p.get("seconds") or 0 for p in parts),
                "note": f"{len(parts)} shards: " + ", ".join(f"{p.get('shard')} {p.get('state')}" for p in parts)}

    def list(self) -> Dict[str, Any]:
        runs = []
        seen = set()
        dirs = []
        for root in self.roots():
            try:
                dirs += sorted(root.iterdir())
            except OSError:  # no dataset/ folder
                continue
        for d in dirs:
            if not d.is_dir() or d.name.startswith(".") or d.name in ("viewer", "models", "pkgs", "node_modules",
                                                                       "dataset") or d.name in seen:
                continue
            try:
                if not self._is_run(d):
                    continue
            except OSError:
                continue
            seen.add(d.name)  # the same name in both: the project folder's run is shown
            s = _read_json(d / "summary.json") or {}
            st = s.get("stats") or {}
            runs.append({"name": d.name, "finished": s.get("finished"), "command": s.get("command"),
                         "policy": (s.get("policy") or {}).get("path"), "lines": st.get("lines"),
                         "tokens": st.get("tokens"), "tokens_removed": st.get("tokens_removed"),
                         "docs": st.get("docs") or {}, "redecided": bool(s.get("redecide")),
                         "mode": (s.get("settings") or {}).get("output_mode") or "detail",
                         "unit": (s.get("settings") or {}).get("decision_unit") or "paragraph",
                         "progress": self.progress(d), "folder": str(d.relative_to(self.project))})
        for name, d in self.extra.items():  # dataset outputs outside the project folder
            if any(r["name"] == name for r in runs) or not self.is_run_folder(d):
                continue
            s = _read_json(d / "summary.json") or {}
            st = s.get("stats") or {}
            runs.append({"name": name, "finished": s.get("finished"), "command": s.get("command"),
                         "policy": (s.get("policy") or {}).get("path"), "lines": st.get("lines"),
                         "tokens": st.get("tokens"), "tokens_removed": st.get("tokens_removed"),
                         "docs": st.get("docs") or {}, "redecided": bool(s.get("redecide")),
                         "progress": self.progress(d), "folder": str(d)})
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
        found = [q for q in (d / f"{file}.labels.jsonl", d / f"{file}.labels.jsonl.zst") if q.is_file()]
        if not found:
            raise KeyError(f"no labels file for '{file}'")
        p = max(found, key=lambda q: q.stat().st_mtime)  # .jsonl or .jsonl.zst (nli_label.py --compress zst)
        from nli_models import open_text
        with open_text(p) as fh:
            for raw in fh:
                if raw.strip():
                    yield json.loads(raw)

    # ---- comparing two runs of the same corpus (e.g. a run and its redecide with another policy) ---------------
    def label_files(self, d: Path) -> List[str]:
        names = set()
        for q in list(d.glob("*.labels.jsonl")) + list(d.glob("*.labels.jsonl.zst")):
            names.add(q.name.split(".labels.jsonl")[0])
        return sorted(names)

    def compare(self, a: str, b: str, change: Optional[str] = None, offset: int = 0, limit: int = 100) -> Dict[str, Any]:
        """Run a vs run b, line by line and paragraph by paragraph (paragraphs matched by their span). change =
        "old>new" (e.g. "keep>review") keeps only paragraphs with that change; "doc:old>new" the same for documents."""
        da, db = self.folder(a), self.folder(b)
        fa, fb = self.label_files(da), self.label_files(db)
        files = [f for f in fa if f in set(fb)]
        sa, sb = _read_json(da / "summary.json") or {}, _read_json(db / "summary.json") or {}

        def inputs(s: Dict[str, Any]) -> List[str]:
            return sorted(str(x.get("input") or "").replace("\\", "/") for x in (s.get("files") or []))

        notes = []
        if inputs(sa) and inputs(sb) and inputs(sa) != inputs(sb):
            notes.append("the two runs did not read the same input files: only the files with the same name are compared")
        only_a, only_b = [f for f in fa if f not in set(fb)], [f for f in fb if f not in set(fa)]
        tot = {"a": {"docs": collections.Counter(), "paragraphs": collections.Counter()},
               "b": {"docs": collections.Counter(), "paragraphs": collections.Counter()}}
        para_moves: collections.Counter = collections.Counter()
        doc_moves: collections.Counter = collections.Counter()
        items: List[Dict[str, Any]] = []
        lines = changed_lines = 0

        def para(p: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            if p is None:
                return None
            return {"action": p.get("action"), "reason": p.get("reason"), "labels": p.get("labels") or [],
                    **({"exception": p["exception"]} if p.get("exception") else {})}

        for f in files:
            rows_b = {r.get("line"): r for r in self._rows(db, f)}
            for ra in self._rows(da, f):
                ln = ra.get("line")
                rb = rows_b.get(ln)
                if rb is None:
                    continue
                lines += 1
                tot["a"]["docs"][ra.get("action")] += 1
                tot["b"]["docs"][rb.get("action")] += 1
                pa = {tuple(p["span"]): p for p in ra.get("paragraphs") or []}
                pb = {tuple(p["span"]): p for p in rb.get("paragraphs") or []}
                for p in pa.values():
                    tot["a"]["paragraphs"][p.get("action")] += 1
                for p in pb.values():
                    tot["b"]["paragraphs"][p.get("action")] += 1
                diffs = []
                for span in sorted(set(pa) | set(pb)):
                    x, y = pa.get(span), pb.get(span)
                    ax = x.get("action") if x else "none"
                    ay = y.get("action") if y else "none"
                    if ax != ay:
                        para_moves[f"{ax}>{ay}"] += 1
                        diffs.append({"span": list(span), "a": para(x), "b": para(y), "move": f"{ax}>{ay}"})
                dm = f"{ra.get('action')}>{rb.get('action')}"
                if ra.get("action") != rb.get("action"):
                    doc_moves[dm] += 1
                if not diffs and ra.get("action") == rb.get("action"):
                    continue
                changed_lines += 1
                if change:
                    if change.startswith("doc:"):
                        if dm != change[4:]:
                            continue
                    elif not any(x["move"] == change for x in diffs):
                        continue
                items.append({"file": f, "line": ln, "id": ra.get("id"), "doc": {"a": ra.get("action"), "b": rb.get("action")},
                              "paragraphs": diffs})
        return {"a": a, "b": b, "files": len(files), "only_a": only_a, "only_b": only_b, "notes": notes,
                "policy": {"a": (sa.get("policy") or {}).get("path"), "b": (sb.get("policy") or {}).get("path")},
                "redecide": {"a": sa.get("redecide"), "b": sb.get("redecide")},
                "lines": lines, "changed_lines": changed_lines,
                "totals": {k: {"docs": dict(v["docs"]), "paragraphs": dict(v["paragraphs"])} for k, v in tot.items()},
                "paragraph_moves": dict(para_moves.most_common()), "doc_moves": dict(doc_moves.most_common()),
                "total": len(items), "offset": offset, "items": items[offset:offset + limit]}

    # ---- expected results (test corpora: expected_action / expected_doc_action / expected_paragraphs) ----------
    def _local_source(self, d: Path, file: str) -> Optional[Path]:
        src = (_read_json(d / f"{file}.summary.json") or {}).get("input")
        if not src or "://" in str(src):
            return None
        p = Path(src) if Path(src).is_absolute() else self.project / src
        return p if p.is_file() else None

    def expected(self, d: Path, file: str) -> Dict[int, Dict[str, Any]]:
        """{line: expected fields} from the run's input file; {} for a corpus without expected results (real data:
        only its first lines are read)."""
        src = self._local_source(d, file)
        if src is None:
            return {}
        try:
            key = (str(src), src.stat().st_mtime)
        except OSError:
            return {}
        if key in self._exp_cache:
            return self._exp_cache[key]
        from nli_models import JsonlSource
        out: Dict[int, Dict[str, Any]] = {}
        try:
            for rec in JsonlSource(str(src)).records():
                data = rec.data if isinstance(rec.data, dict) else {}
                if "expected_action" in data or "expected_doc_action" in data:
                    e = {k: data[k] for k in ("expected_action", "acceptable", "expected_doc_action",
                                              "expected_paragraphs", "note", "case") if k in data}
                    if "expected_paragraphs" in data:
                        e["_text"] = data.get("text") or ""
                    out[rec.line] = e
                elif rec.line >= 3 and not out:
                    break  # no expected results in this corpus
        except Exception:  # noqa: BLE001 - an unreadable corpus simply has no expected results here
            out = {}
        self._exp_cache[key] = out
        return out

    @staticmethod
    def _same(actions) -> set:
        out = {str(a).strip() for a in actions if a}
        if out & {"pass", "untouched", "none"}:
            out |= {"pass", "untouched", "none"}  # all three leave the text as it is
        return out

    def verdict(self, row: Dict[str, Any], e: Dict[str, Any], para_cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Expected vs got for one line: a case text (strictest paragraph action) or a test document (its document
        action and every paragraph's action)."""
        paras = row.get("paragraphs") or []
        if "expected_action" in e:
            got = row.get("action", "untouched")
            for a in ("remove", "review", "keep", "pass"):
                if any(p.get("action") == a for p in paras):
                    got = a
                    break
            ok_set = self._same([*str(e["expected_action"]).split(" or "), *(e.get("acceptable") or [])])
            return {"kind": "text", "expected": e["expected_action"], "acceptable": e.get("acceptable") or [],
                    "got": got, "ok": got in ok_set, "note": e.get("note") or ""}
        got_doc = row.get("action")
        res: Dict[str, Any] = {"kind": "document", "expected": e.get("expected_doc_action"), "acceptable": [],
                               "got": got_doc, "ok": got_doc == e.get("expected_doc_action"), "note": "",
                               "paragraphs": []}
        exp_paras = e.get("expected_paragraphs") or []
        if exp_paras and e.get("_text"):
            from nli_label import split_paragraphs
            spans = split_paragraphs(e["_text"], int(para_cfg.get("min_chars", 200)), int(para_cfg.get("max_chars", 2000)))
            by_span = {tuple(p["span"]): p for p in paras}
            if len(spans) == len(exp_paras):
                for (s0, s1), x in zip(spans, exp_paras):
                    p = by_span.get((s0, s1))
                    got = p["action"] if p else "none"
                    ok = got in self._same([x.get("expected_action"), *(x.get("acceptable") or [])])
                    res["paragraphs"].append({"span": [s0, s1], "expected": x.get("expected_action"),
                                              "acceptable": x.get("acceptable") or [], "note": x.get("note") or "",
                                              "got": got, "ok": ok})
                    res["ok"] = res["ok"] and ok
        return res

    def _para_cfg(self, d: Path) -> Dict[str, Any]:
        return ((_read_json(d / "summary.json") or {}).get("policy") or {}).get("paragraphs") or {}

    def expected_summary(self, name: str) -> Optional[Dict[str, Any]]:
        """Over all files of a run: how many lines match their expected result, and the ones that do not."""
        d = self.folder(name)
        files = [sp.name[:-len(".summary.json")] for sp in sorted(d.glob("*.summary.json"))
                 if not sp.name.startswith("summary.")]
        if not files or not self.expected(d, files[0]):
            return None
        cfg = self._para_cfg(d)
        n = ok = 0
        wrong = []
        for f in files:
            exp = self.expected(d, f)
            if not exp:
                continue
            for r in self._rows(d, f):
                e = exp.get(r.get("line"))
                if e is None:
                    continue
                v = self.verdict(r, e, cfg)
                n += 1
                ok += bool(v["ok"])
                if not v["ok"]:
                    wrong.append({"file": f, "line": r.get("line"), "id": r.get("id"), "expected": v["expected"],
                                  "acceptable": v["acceptable"], "got": v["got"], "note": v["note"] or e.get("note", ""),
                                  "paragraphs_wrong": sum(1 for p in v.get("paragraphs", []) if not p["ok"])})
        return {"n": n, "ok": ok, "wrong": wrong}

    def docs(self, name: str, file: str, action: Optional[str] = None, label: Optional[str] = None,
             para_action: Optional[str] = None, gated: bool = True, offset: int = 0, limit: int = 50,
             expect: Optional[str] = None) -> Dict[str, Any]:
        d = self.folder(name)
        counts: Dict[str, int] = {}
        out, total = [], 0
        exp = self.expected(d, file)
        cfg = self._para_cfg(d) if exp else {}
        exp_n = exp_ok = 0
        for r in self._rows(d, file):
            v = self.verdict(r, exp[r.get("line")], cfg) if r.get("line") in exp else None
            if v is not None:
                exp_n += 1
                exp_ok += bool(v["ok"])
            if expect in ("wrong", "right"):
                if v is None or v["ok"] != (expect == "right"):
                    continue
            elif gated and not r.get("gate") and v is None:
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
                            "keywords": sorted({h["kw"] for h in r.get("hits") or [] if not h.get("rule")})[:8],
                            **({"expect": v} if v is not None else {})})
        return {"rows": out, "total": total, "counts": counts, "offset": offset, "limit": limit,
                **({"expected": {"n": exp_n, "ok": exp_ok}} if exp else {})}

    def clean_view(self, d: Path, file: str, row: Dict[str, Any], text_field: str,
                   settings: Dict[str, Any]) -> Dict[str, Any]:
        """The document as it is in <file>.clean.jsonl[.zst]: its text, the place names rewritten in it (positions in
        that text), or "dropped". The clean file has no line numbers: a document's place in it is its line number minus
        the documents before it that were dropped (removed / error), checked against the id when there is one."""
        found = [q for q in (d / f"{file}.clean.jsonl", d / f"{file}.clean.jsonl.zst") if q.is_file()]
        out: Dict[str, Any] = {"available": bool(found), "review_as": settings.get("review_as") or "keep"}
        if not found:
            return out
        line = row.get("line")
        if row.get("action") in ("removed", "error"):
            return dict(out, dropped=True)
        index = 0
        for r in self._rows(d, file):
            if r.get("line") == line:
                break
            if r.get("action") not in ("removed", "error"):
                index += 1
        from nli_models import JsonlSource
        clean_path = max(found, key=lambda q: q.stat().st_mtime)
        rec = None
        for k, rr in enumerate(JsonlSource(str(clean_path)).records()):
            if k == index:
                rec = rr
                break
        if rec is None:
            return dict(out, problem="the clean copy has fewer documents than expected")
        if row.get("id") is not None and rec.get("id") is not None and rec.get("id") != row.get("id"):
            return dict(out, problem=f"the clean copy's document {index + 1} has id {rec.get('id')}, not {row.get('id')}")
        t = rec.get(text_field)
        changes = []
        rw = [q for q in (d / f"{file}.rewrites.jsonl", d / f"{file}.rewrites.jsonl.zst") if q.is_file()]
        if rw and row.get("rewrites"):
            from nli_models import open_text
            with open_text(max(rw, key=lambda q: q.stat().st_mtime)) as fh:
                for raw in fh:
                    c = json.loads(raw) if raw.strip() else {}
                    if c.get("line") == line:
                        changes.append(c)
        spans, shift = [], 0
        for c in sorted(changes, key=lambda c: c["start"]):  # "start" is before the renaming: shift onto the result
            s0 = c["start"] + shift
            spans.append({"start": s0, "end": s0 + len(c["new"]), "old": c["old"], "new": c["new"]})
            shift += len(c["new"]) - len(c["old"])
        return dict(out, dropped=False, text=t if isinstance(t, str) else None, rewrites=spans)

    def source_text(self, d: Path, file: str, line: int) -> tuple:
        """(text, problem, input as stored) of one line of a run's input file."""
        s = _read_json(d / "summary.json") or {}
        fs = _read_json(d / f"{file}.summary.json") or {}
        text, problem = None, None
        src = fs.get("input")
        tf = (s.get("settings") or {}).get("text_field") or "text"
        is_url = bool(src) and "://" in str(src)
        if is_url and not fs.get("reopen"):
            return None, ("the input is on a server and was given with a literal password, which is never stored: run "
                          "with the password in an environment variable to see the text here"), src
        if src:
            try:
                from nli_models import JsonlSource, expand_inputs
                source = expand_inputs([fs["reopen"]])[0] if is_url else \
                    str(Path(src) if Path(src).is_absolute() else self.project / src)
                for rec in JsonlSource(source).records():
                    if rec.line == line:
                        t = rec.get(tf)
                        text = t if isinstance(t, str) else None
                        break
            except Exception as exc:  # noqa: BLE001 - shown on the page
                from nli_storage import mask_uri
                problem = mask_uri(f"cannot read {src}: {exc}")
        return text, problem, src

    # ---- simple-mode runs (--output-mode simple): the decisions file, one row per line, shaped by the schema -----
    def _schema_names(self, s: Dict[str, Any]) -> Dict[str, str]:
        """source -> the field name the run's schema gave it (line, decision, level, reason_text, keyword_counts ...)."""
        out: Dict[str, str] = {}
        for f in (s.get("schema") or {}).get("fields") or []:
            out.setdefault(str(f.get("from")), str(f.get("name")))
        return out

    def _simple_file(self, d: Path, file: str, kind: str) -> Optional[Path]:
        found = [q for q in (d / f"{file}.{kind}.jsonl", d / f"{file}.{kind}.jsonl.zst") if q.is_file()]
        return max(found, key=lambda q: q.stat().st_mtime) if found else None

    def _jsonl(self, p: Path) -> Iterator[Dict[str, Any]]:
        from nli_models import open_text
        with open_text(p) as fh:
            for raw in fh:
                if raw.strip():
                    yield json.loads(raw)

    def simple_rows(self, name: str, file: str, decision: Optional[str] = None, reason: Optional[str] = None,
                    keyword: Optional[str] = None, offset: int = 0, limit: int = 50) -> Dict[str, Any]:
        d = self.folder(name)
        s = _read_json(d / "summary.json") or {}
        st = s.get("settings") or {}
        if st.get("output_mode") != "simple":
            raise ValueError(f"{name} is not a simple-mode run")
        kind = st.get("decisions_file") or "decisions"
        p = self._simple_file(d, file, kind)
        if p is None:
            raise KeyError(f"no {kind} file for '{file}'")
        nm = self._schema_names(s)
        f_dec, f_rsn, f_kw = nm.get("decision"), nm.get("reason_text") or nm.get("reason"), nm.get("keyword_counts")
        f_ln, f_lvl = nm.get("line"), nm.get("level")
        decisions: collections.Counter = collections.Counter()
        reasons: collections.Counter = collections.Counter()
        keywords: collections.Counter = collections.Counter()
        out, total = [], 0
        for r in self._jsonl(p):
            dv = r.get(f_lvl) if f_lvl and r.get(f_lvl) is not None else r.get(f_dec) if f_dec else None
            rv = r.get(f_rsn) if f_rsn else None
            kv = r.get(f_kw) if f_kw else None
            decisions[str(dv)] += 1
            reasons[str(rv)] += 1
            if isinstance(kv, dict):
                keywords.update({k: 1 for k in kv})
            if decision and str(dv) != decision:
                continue
            if reason and str(rv) != reason:
                continue
            if keyword and not (isinstance(kv, dict) and keyword in kv):
                continue
            total += 1
            if offset <= total - 1 < offset + limit:
                out.append({"row": r, "line": r.get(f_ln) if f_ln else None, "decision": dv, "reason": rv,
                            "keywords": kv if isinstance(kv, dict) else {}})
        return {"file": file, "rows": out, "total": total, "offset": offset, "limit": limit,
                "counts": {"decision": dict(decisions.most_common()), "reason": dict(reasons.most_common()),
                           "keyword": dict(keywords.most_common(60))},
                "fields": nm, "evidence": st.get("evidence") or "none",
                "can_open": bool(f_ln), "unit": st.get("decision_unit") or "paragraph"}

    def simple_line(self, name: str, file: str, line: int) -> Dict[str, Any]:
        d = self.folder(name)
        s = _read_json(d / "summary.json") or {}
        st = s.get("settings") or {}
        nm = self._schema_names(s)
        row = None
        p = self._simple_file(d, file, st.get("decisions_file") or "decisions")
        if p is not None and nm.get("line"):
            row = next((r for r in self._jsonl(p) if r.get(nm["line"]) == line), None)
        ev = None
        evp = self._simple_file(d, file, "evidence")
        if evp is not None:
            ev = next((r for r in self._jsonl(evp) if r.get("line") == line), None)
        text, problem, src = self.source_text(d, file, line)
        hits: List[Dict[str, Any]] = []
        if text and s.get("policy_data"):
            try:
                import nli_label
                pol = nli_label.Policy(s["policy_data"], (s.get("policy") or {}).get("path"))
                matcher, _, markers = nli_label.build_matchers(pol)
                hits = [{"start": h.start, "end": h.end, "kw": matcher.keywords[h.kw] if h.kw is not None else None}
                        for h in matcher.find(text)]
                if markers is not None:
                    hits += [{"start": h.start, "end": h.end, "kw": markers.keywords[h.kw] if h.kw is not None else None,
                              "marker": True} for h in markers.find(text)]
            except Exception as exc:  # noqa: BLE001 - only the highlighting is missing
                problem = problem or f"keywords not highlighted: {exc}"
        return {"name": name, "file": file, "line": line, "input": src, "row": row, "evidence": ev, "text": text,
                "problem": problem, "hits": sorted(hits, key=lambda h: h["start"]),
                "policy": {"labels": (s.get("policy") or {}).get("labels") or {}, "run_if": (s.get("policy") or {}).get("run_if") or {},
                           "conflict": (s.get("policy") or {}).get("conflict")},
                "policy_data": s.get("policy_data"), "policy_path": (s.get("policy") or {}).get("path"),
                "settings": st}

    def schema_preview(self, name: str, schema_data: Dict[str, Any], file: Optional[str], limit: int) -> Dict[str, Any]:
        """Rows an (edited) schema would give, from a detail run's labels rows. keyword_hint here counts the hits the
        labels row keeps (at most 50 per line); a real run counts every hit."""
        import nli_simple
        sc = nli_simple.Schema(schema_data, "preview")
        d = self.folder(name)
        s = _read_json(d / "summary.json") or {}
        files = self.label_files(d)
        if not files:
            raise ValueError(f"{name} has no labels files (a simple-mode run cannot be previewed: pick a detail run)")
        f = file if file in files else files[0]
        info = {k: {"level": v.get("level"), "decision": v.get("decision")}
                for k, v in ((s.get("policy") or {}).get("labels") or {}).items()}
        rows, read, included = [], 0, 0
        evidence = 0
        for r in self._rows(d, f):
            read += 1
            counts: Dict[str, int] = collections.Counter(str(h.get("kw") or "").lower() for h in r.get("hits") or [])
            for m in r.get("markers") or []:
                counts[str(m).lower()] += 1
            out = nli_simple.build_row(sc, r, f, info, dict(counts))
            if out is not None:
                included += 1
                if len(rows) < limit:
                    rows.append(out)
            if nli_simple.evidence_row(sc, r) is not None:
                evidence += 1
            if read >= 5000:
                break
        return {"run": name, "file": f, "files": files, "rows": rows, "read": read, "included": included,
                "evidence_rows": evidence, "unit": (s.get("settings") or {}).get("decision_unit") or "paragraph"}

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
        is_url = bool(src) and "://" in str(src)
        if is_url and not fs.get("reopen"):
            problem = ("the input is on a server and was given with a literal password, which is never stored: run "
                       "with the password in an environment variable (sftp://user:${NLI_CORPUS_PASSWORD}@host/...) "
                       "to see the text here")
            src = None
        if src:
            try:
                from nli_models import JsonlSource, expand_inputs  # project module; no torch at import
                if is_url:  # the ${VAR} form: the viewer's environment must have the variable
                    source = expand_inputs([fs["reopen"]])[0]
                else:
                    source = str(Path(src) if Path(src).is_absolute() else self.project / src)
                for rec in JsonlSource(source).records():
                    if rec.line == line:
                        t = rec.get(tf)
                        text = t if isinstance(t, str) else None
                        break
            except Exception as exc:  # noqa: BLE001 - shown on the page
                from nli_storage import mask_uri
                problem = mask_uri(f"cannot read {src}: {exc}")
        if text == "" and row.get("paragraphs"):
            problem = "the source document is empty now (removed after the run, e.g. by content screening)"
            text = None
        elif text is not None and row.get("paragraphs"):
            s_end = max(p["span"][1] for p in row["paragraphs"])
            if s_end > len(text):
                problem = "the source text changed since the run (spans do not fit): the text is not shown"
                text = None
        pol = s.get("policy") or {}
        clean = self.clean_view(d, file, row, tf, s.get("settings") or {})
        e = self.expected(d, file).get(line)
        expect = self.verdict(row, e, pol.get("paragraphs") or {}) if e is not None else None
        return {"name": name, "file": file, "input": src, "row": row, "text": text, "problem": problem,
                **({"expect": expect} if expect is not None else {}),
                "clean": clean,
                "policy": {"labels": pol.get("labels") or {}, "run_if": pol.get("run_if") or {},
                           "conflict": pol.get("conflict")},
                "policy_path": pol.get("path"),
                "settings": s.get("settings") or {}}

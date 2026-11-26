"""
kwstats.py - the /label/kwstats/ page's API: keyword and marker statistics made by 'nli_label.py kwstats'
(nli_kwstats.py). Reads <folder>/kwstats.json (in the project folder or its dataset/ folder); starts a scan through the
model service like the Start-a-run form (the scan needs no models: python nli_playground.py --no-models is enough).

    app.include_router(kwstats.router)     # every route is under /api/labels/kwstats

The project folder and the model service come from app.state.playground (set by create_app).
"""
from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel

__all__ = ["router", "KwStore"]

router = APIRouter(prefix="/api/labels/kwstats", tags=["kwstats"])

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,120}")
_LOCAL = {"127.0.0.1", "::1", "localhost"}
SORTS = ("rank", "term", "kind", "list", "hits", "incidental", "incidental_share", "lines", "line_share",
         "gate_lines", "paragraphs", "sentences", "files", "units_hit")


def is_kwstats_folder(d: Path) -> bool:
    try:
        return d.is_dir() and ((d / "kwstats.json").is_file() or any(d.glob("kwstats.part*.json")))
    except OSError:
        return False


class KwStore:
    """kwstats.json files of a project, cached by modification time."""

    def __init__(self, project: Path):
        self.project = Path(project)
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    def roots(self) -> List[Path]:
        return [self.project, self.project / "dataset"]

    def folder(self, name: str) -> Path:
        if not _NAME.fullmatch(name or "") or ".." in name:
            raise HTTPException(400, "a folder name (letters, digits, _ . -)")
        for r in self.roots():
            d = r / name
            if is_kwstats_folder(d):
                return d
        raise HTTPException(404, f"no keyword statistics '{name}' (a folder with kwstats.json in the project or dataset/)")

    def list(self) -> List[Dict[str, Any]]:
        out, seen = [], set()
        for r in self.roots():
            if not r.is_dir():
                continue
            for d in sorted(r.iterdir()):
                if d.name in seen or not is_kwstats_folder(d):
                    continue
                seen.add(d.name)
                row: Dict[str, Any] = {"name": d.name, "path": str(d.relative_to(self.project)).replace("\\", "/"),
                                       "parts": len(list(d.glob("kwstats.part.shard*.json"))),
                                       "complete": (d / "kwstats.json").is_file()}
                if row["complete"]:
                    try:
                        st = self.load(d.name)
                        tot = st.get("totals") or {}
                        row.update({"created": st.get("created"), "policy": st.get("policy"),
                                    "inputs": (st.get("settings") or {}).get("inputs"),
                                    "lines": tot.get("lines_text", 0), "lines_gated": tot.get("lines_gated", 0),
                                    "terms": len(st.get("terms") or []),
                                    "terms_hit": (st.get("concentration") or {}).get("terms_hit", 0)})
                    except (OSError, ValueError) as exc:
                        row["error"] = str(exc)
                out.append(row)
        return out

    def load(self, name: str) -> Dict[str, Any]:
        p = self.folder(name) / "kwstats.json"
        if not p.is_file():
            raise HTTPException(404, f"{name}: only shard parts so far (kwstats.json is made when all are there, "
                                     "or with 'nli_label.py kwstats --merge')")
        key = str(p)
        mt = p.stat().st_mtime
        hit = self._cache.get(key)
        if hit and hit[0] == mt:
            return hit[1]
        st = json.loads(p.read_text(encoding="utf-8"))
        if st.get("kind") != "kwstats":
            raise ValueError(f"{p} is not a kwstats.json")
        self._cache[key] = (mt, st)
        return st


def _store(request: Request) -> KwStore:
    st = getattr(request.app.state, "kwstats", None)
    if st is None:
        st = KwStore(Path(request.app.state.playground.project))
        request.app.state.kwstats = st
    return st


def _unit(u: str, depth: int) -> str:
    """'russian/companies' at depth 1 -> 'russian' (folders only; 0 = the whole name)."""
    if depth <= 0 or u in (".", "(none)"):
        return u
    return "/".join(u.split("/")[:depth])


def _units(st: Dict[str, Any], dim: str, depth: int) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
    for u, c in (st.get("units") or {}).get(dim, {}).items():
        d = out.setdefault(_unit(u, depth), {})
        for k, v in c.items():
            d[k] = d.get(k, 0) + int(v)
    return out


def _term_units(t: Dict[str, Any], dim: str, depth: int) -> Dict[str, List[int]]:
    out: Dict[str, List[int]] = {}
    for u, (h, l) in (t.get("units") or {}).get(dim, {}).items():
        c = out.setdefault(_unit(u, depth), [0, 0])
        c[0] += h
        c[1] += l
    return out


def _dim(st: Dict[str, Any], dim: Optional[str]) -> str:
    dims = st.get("dims") or []
    if not dim:
        return (st.get("settings") or {}).get("group_by") or (dims[0] if dims else "folder")
    if dim not in dims:
        raise HTTPException(400, f"no unit '{dim}' in this scan (has: {', '.join(dims) or 'none'})")
    return dim


def _row(st: Dict[str, Any], t: Dict[str, Any]) -> Dict[str, Any]:
    terms = st["terms"]
    dim = (st.get("settings") or {}).get("group_by") or "folder"
    return {k: t.get(k) for k in ("id", "rank", "term", "kind", "list", "hits", "incidental", "incidental_share",
                                   "lines", "line_share", "gate_lines", "paragraphs", "sentences", "files")} | {
        "units_hit": len((t.get("units") or {}).get(dim) or {}),
        "co": [{"id": j, "term": terms[j]["term"], "n": c} for j, c in t.get("co") or []]}


def _filter(st: Dict[str, Any], q: str = "", kind: str = "", lst: str = "", hit: str = "") -> List[Dict[str, Any]]:
    rows = st["terms"]
    if q:
        ql = q.lower()
        rows = [t for t in rows if ql in t["term"].lower()]
    if kind:
        rows = [t for t in rows if t["kind"] == kind]
    if lst:
        rows = [t for t in rows if t["list"] == lst]
    if hit == "never":
        rows = [t for t in rows if not t["hits"]]
    elif hit == "hit":
        rows = [t for t in rows if t["hits"]]
    return rows


def _sorted(rows: List[Dict[str, Any]], sort: str, desc: bool, dim: str) -> List[Dict[str, Any]]:
    if sort not in SORTS:
        raise HTTPException(400, f"sort: one of {', '.join(SORTS)}")
    if sort == "units_hit":
        key = lambda t: len((t.get("units") or {}).get(dim) or {})  # noqa: E731
    elif sort in ("term", "kind", "list"):
        key = lambda t: str(t.get(sort) or "").lower()  # noqa: E731
    else:
        key = lambda t: t.get(sort) or 0  # noqa: E731
    return sorted(rows, key=lambda t: (key(t), -t["rank"] if desc else t["rank"]), reverse=desc)


def _csv(rows: List[List[Any]], filename: str) -> Response:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ---- list, overview ---------------------------------------------------------------------------------


@router.get("/runs")
def kw_list(request: Request):
    """Folders with keyword statistics (kwstats.json, or shard parts waiting to be merged). Not at
    /api/labels/kwstats itself: api.py's /api/labels/{name} would answer first when the router is included late."""
    return {"runs": _store(request).list()}


@router.get("/form")
def kw_form(request: Request):
    """For the start form: corpus folders / files in dataset/ (no run or statistics folders) and the policies."""
    store = _store(request)
    project = store.project
    from nli_formats import INPUT_SUFFIXES
    from .labels import LabelRuns
    lr = LabelRuns(project, 0.0)
    corpora = []
    dsd = project / "dataset"
    for d in sorted(dsd.iterdir()) if dsd.is_dir() else []:
        if d.name.startswith(".") or lr.is_run_folder(d) or is_kwstats_folder(d):
            continue
        if d.is_dir():
            n = sum(1 for q in d.rglob("*") if q.is_file() and q.name.lower().endswith(INPUT_SUFFIXES)
                    and not any(x in q.name for x in (".labels.", ".clean.", ".rewrites.", ".decisions.", ".evidence.")))
            if n:
                corpora.append({"path": f"dataset/{d.name}", "files": n})
        elif d.name.lower().endswith(INPUT_SUFFIXES) and not d.name.lower().endswith(".manifest.json"):
            corpora.append({"path": f"dataset/{d.name}", "files": 1})
    pol = project / "policy"
    return {"corpora": corpora, "policies": sorted(f"policy/{p.name}" for p in pol.glob("*.json")) if pol.is_dir() else []}


@router.get("/{name}")
def kw_overview(name: str, request: Request, depth: int = Query(0, ge=0, le=10)):
    """Everything but the term table: totals, histograms, units, concentration, forecast, report, pairs."""
    st = _store(request).load(name)
    terms = st["terms"]
    from_report = st.get("report") or []
    return {"name": name, "created": st.get("created"), "policy": st.get("policy"), "settings": st.get("settings"),
            "totals": st.get("totals"), "hist": st.get("hist"), "dims": st.get("dims") or [],
            "units": {d: _units(st, d, depth if d == "folder" else 0) for d in st.get("dims") or []},
            "concentration": st.get("concentration"), "forecast": st.get("forecast"),
            "n_terms": len(terms), "never_hit": len(st.get("never_hit") or []),
            "lists": sorted({t["list"] for t in terms}), "kinds": sorted({t["kind"] for t in terms}),
            "duplicates": st.get("duplicates") or [], "overlaps": (st.get("overlaps") or [])[:200],
            "n_overlaps": len(st.get("overlaps") or []), "warnings": st.get("warnings") or [],
            "suggest_words": st.get("suggest_words") or [],
            "pairs": [{"a": terms[a]["term"], "b": terms[b]["term"], "a_id": a, "b_id": b, "n": c}
                      for a, b, c in (st.get("pairs") or [])[:100]],
            "pairs_total": st.get("pairs_total", 0), "files": len(st.get("files") or []),
            "report": from_report, "report_md": _report_md(st), "seconds": st.get("seconds_total") or st.get("seconds")}


def _report_md(st: Dict[str, Any]) -> str:
    try:
        import nli_kwstats  # the project folder is on sys.path (labels.py)
        return nli_kwstats.report_md(st)
    except Exception:  # noqa: BLE001 - fall back to the items
        return "\n".join(f"## {it['title']}\n" + "\n".join(f"- {x}" for x in it["lines"]) for it in st.get("report") or [])


@router.get("/{name}/report.md", response_class=PlainTextResponse)
def kw_report(name: str, request: Request):
    store = _store(request)
    p = store.folder(name) / "report.md"
    if p.is_file():
        return PlainTextResponse(p.read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8")
    return PlainTextResponse(_report_md(store.load(name)), media_type="text/markdown; charset=utf-8")


@router.get("/{name}/rankfreq")
def kw_rankfreq(name: str, request: Request):
    """All terms by rank (for the rank-frequency chart): parallel arrays, compact for 10,000+ terms."""
    st = _store(request).load(name)
    rows = sorted(st["terms"], key=lambda t: t["rank"])
    lists = sorted({t["list"] for t in rows})
    li = {x: i for i, x in enumerate(lists)}
    return {"terms": [t["term"] for t in rows], "ids": [t["id"] for t in rows], "hits": [t["hits"] for t in rows],
            "kind": [t["kind"] for t in rows], "list": [li[t["list"]] for t in rows], "lists": lists}


# ---- the term table -----------------------------------------------------------------------------


@router.get("/{name}/terms")
def kw_terms(name: str, request: Request, q: str = "", kind: str = "", lst: str = Query("", alias="list"), hit: str = "",
             sort: str = "rank", desc: bool = False, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=1000),
             format: str = ""):
    st = _store(request).load(name)
    dim = (st.get("settings") or {}).get("group_by") or "folder"
    rows = _sorted(_filter(st, q, kind, lst, hit), sort, desc, dim)
    if format == "csv":
        import nli_kwstats
        return _csv(list(nli_kwstats.csv_rows(st, rows)), f"{name}_terms.csv")
    return {"total": len(rows), "offset": offset, "rows": [_row(st, t) for t in rows[offset:offset + limit]]}


@router.get("/{name}/term/{tid}")
def kw_term(name: str, tid: int, request: Request, dim: str = "", depth: int = Query(0, ge=0, le=10)):
    """One term: its counts, per unit, and every co-occurring term found in the stored pairs."""
    st = _store(request).load(name)
    if not 0 <= tid < len(st["terms"]):
        raise HTTPException(404, f"no term {tid}")
    t = st["terms"][tid]
    d = _dim(st, dim)
    terms = st["terms"]
    co = []
    for a, b, c in st.get("pairs") or []:
        if a == tid or b == tid:
            j = b if a == tid else a
            co.append({"id": j, "term": terms[j]["term"], "n": c})
    if not co:
        co = _row(st, t)["co"]
    return {**_row(st, t), "dim": d, "units": _term_units(t, d, depth if d == "folder" else 0), "pairs": co[:50]}


# ---- heatmap, never-hit, pairs ---------------------------------------------------------------------


@router.get("/{name}/heatmap")
def kw_heatmap(name: str, request: Request, dim: str = "", depth: int = Query(0, ge=0, le=10),
               top: int = Query(30, ge=1, le=300), q: str = "", kind: str = "", lst: str = Query("", alias="list"),
               norm: str = "hits"):
    """Terms x units: hits (or hits per 1,000 lines with norm=per1k). Top N terms by hits, or the filtered ones."""
    st = _store(request).load(name)
    d = _dim(st, dim)
    dep = depth if d == "folder" else 0
    units = _units(st, d, dep)
    names = sorted(units)
    rows = _filter(st, q, kind, lst, "hit")
    rows.sort(key=lambda t: t["rank"])
    rows = rows[:top]
    out = []
    for t in rows:
        tu = _term_units(t, d, dep)
        cells = []
        for u in names:
            h = tu.get(u, [0, 0])[0]
            if norm == "per1k":
                ln = units[u].get("lines", 0)
                cells.append(round(1000.0 * h / ln, 2) if ln else 0)
            else:
                cells.append(h)
        out.append({"id": t["id"], "term": t["term"], "kind": t["kind"], "list": t["list"], "hits": t["hits"],
                    "cells": cells})
    return {"dim": d, "depth": dep, "norm": norm, "units": names,
            "unit_lines": [units[u].get("lines", 0) for u in names],
            "unit_gated": [units[u].get("lines_gated", 0) for u in names], "terms": out}


@router.get("/{name}/never")
def kw_never(name: str, request: Request, dim: str = "", unit: str = "", depth: int = Query(0, ge=0, le=10),
             q: str = "", kind: str = "", lst: str = Query("", alias="list"), format: str = ""):
    """Never-hit terms: overall (no unit), or in one unit (terms with no hit in that unit)."""
    st = _store(request).load(name)
    rows = _filter(st, q, kind, lst, "")
    per_unit: Dict[str, int] = {}
    if unit:
        d = _dim(st, dim)
        dep = depth if d == "folder" else 0
        rows = [t for t in rows if not _term_units(t, d, dep).get(unit)]
    else:
        rows = [t for t in rows if not t["hits"]]
    if dim or unit:
        d = _dim(st, dim)
        dep = depth if d == "folder" else 0
        for u in _units(st, d, dep):
            per_unit[u] = sum(1 for t in st["terms"] if not _term_units(t, d, dep).get(u))
    rows.sort(key=lambda t: t["term"].lower())
    if format == "csv":
        return _csv([["term", "kind", "list", "hits_overall"]] + [[t["term"], t["kind"], t["list"], t["hits"]]
                                                                   for t in rows],
                    f"{name}_never_hit{('_' + re.sub(r'[^A-Za-z0-9_.-]+', '_', unit)) if unit else ''}.csv")
    return {"unit": unit or None, "total": len(rows), "per_unit": per_unit,
            "rows": [{"id": t["id"], "term": t["term"], "kind": t["kind"], "list": t["list"], "hits": t["hits"]}
                     for t in rows[:5000]]}


@router.get("/{name}/pairs")
def kw_pairs(name: str, request: Request, q: str = "", limit: int = Query(100, ge=1, le=1000)):
    """The top co-occurring pairs (same paragraph); q = only pairs with a term containing q."""
    st = _store(request).load(name)
    terms = st["terms"]
    out = []
    ql = q.lower()
    for a, b, c in st.get("pairs") or []:
        if ql and ql not in terms[a]["term"].lower() and ql not in terms[b]["term"].lower():
            continue
        out.append({"a": terms[a]["term"], "b": terms[b]["term"], "a_id": a, "b_id": b, "n": c})
        if len(out) >= limit:
            break
    return {"total_pairs": st.get("pairs_total", 0), "stored": len(st.get("pairs") or []), "rows": out}


# ---- start a scan -----------------------------------------------------------------------------------


class KwStartBody(BaseModel):
    corpus: Optional[str] = None
    policy: str = "policy/russia_llm_policy_v2.json"
    output_dir: Optional[str] = None        # a folder name, made in dataset/
    topic_field: Optional[str] = None
    group_by: str = "folder"
    limit: Optional[int] = None
    shard: Optional[str] = None
    args: Optional[List[str]] = None        # or the arguments after 'kwstats' as a list


def _guard(request: Request) -> None:
    if request.headers.get("X-Viewer-Edit") != "1":
        raise HTTPException(403, "saving needs the header X-Viewer-Edit: 1")
    host = request.client.host if request.client else ""
    server = (request.scope.get("server") or ("",))[0]
    local = host in _LOCAL or (host and host == server)
    reg = getattr(request.app.state, "registry", None)
    allow = bool(getattr(getattr(reg, "cfg", None), "edit_allow_remote", False))
    if not local and not allow:
        raise HTTPException(403, f"starting a scan is only allowed from the PC the viewer runs on (this request came "
                                 f"from {host or '?'})")


def build_args(project: Path, body: KwStartBody) -> Tuple[List[str], str]:
    if body.args is not None:
        args = [str(a) for a in body.args]
        if args and args[0].lower().endswith("nli_label.py"):
            args = args[1:]
        if args and args[0] == "kwstats":
            args = args[1:]
        if "--output-dir" not in args or args.index("--output-dir") + 1 >= len(args):
            raise HTTPException(400, "set the output folder (--output-dir)")
        out = args[args.index("--output-dir") + 1]
        return ["kwstats", *args], Path(out).name
    corpus = (body.corpus or "").strip()
    if not corpus:
        raise HTTPException(400, "choose a corpus")
    rel = (body.policy or "").replace("\\", "/")
    if not re.fullmatch(r"policy/[A-Za-z0-9_.-]+\.json", rel) or not (project / rel).is_file():
        raise HTTPException(400, "policy must be a .json file in the project's policy folder (policy/<name>.json)")
    src = Path(corpus)
    if "://" not in corpus and not src.is_absolute():
        src = project / corpus
    if "://" not in corpus and not src.exists():
        raise HTTPException(400, f"no corpus {corpus}")
    name = body.output_dir or "kwstats_" + re.sub(r"[^A-Za-z0-9_.-]+", "_",
                                                  Path(corpus.rstrip("/\\")).name.split(".")[0] or "corpus")
    if not _NAME.fullmatch(name):
        raise HTTPException(400, "output folder: a name (letters, digits, _ . -), created in the dataset folder")
    if body.group_by not in ("folder", "file"):
        raise HTTPException(400, "group_by: folder or file")
    out = (project / "dataset" / name).resolve()
    args = ["kwstats", corpus if "://" in corpus else str(src.resolve()), "--policy", rel, "--output-dir", str(out),
            "--group-by", body.group_by]
    if body.topic_field and body.topic_field.strip():
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", body.topic_field.strip()):
            raise HTTPException(400, "topic field: a field name (dot path for nested fields)")
        args += ["--topic-field", body.topic_field.strip()]
    if body.limit:
        args += ["--limit", str(int(body.limit))]
    if body.shard:
        args += ["--shard", body.shard]
    return args, name


@router.post("/start")
def kw_start(body: KwStartBody, request: Request):
    """Start 'nli_label.py kwstats …' through the model service (only from this PC: it starts a program)."""
    _guard(request)
    pg = request.app.state.playground
    args, name = build_args(Path(pg.project), body)
    job = pg.start_job(args, {}, f"kwstats: {name}", script="nli_label.py")
    return {"job": job, "run": name, "args": args}

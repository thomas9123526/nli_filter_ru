"""
api.py - FastAPI application: JSON API under /api, the built frontend at /.

    from nli_viewer.api import create_app
    app = create_app(config)          # ViewerConfig
    # uvicorn nli_viewer.api:app  (reads NLI_VIEWER_CONFIG)

Interactive API documentation: /docs
"""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import DatasetRegistry, ViewerConfig, load_config
from .results import Dataset
from .storage import StorageError, clean_path

__all__ = ["create_app"]

DEFAULT_FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend" / "out"


def create_app(cfg: ViewerConfig) -> FastAPI:
    reg = DatasetRegistry(cfg)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        reg.close()

    app = FastAPI(title="NLI filter result viewer", version=__version__, lifespan=lifespan,
                  description="Browse nli_filter.py decisions next to the original corpus lines.")
    app.state.registry = reg
    app.add_middleware(GZipMiddleware, minimum_size=2000)
    if cfg.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=cfg.cors_origins, allow_methods=["GET", "POST"],
                           allow_headers=["*"])

    @app.exception_handler(KeyError)
    async def _not_found(_: Request, exc: KeyError):
        return JSONResponse({"detail": str(exc.args[0]) if exc.args else "not found"}, status_code=404)

    @app.exception_handler(FileNotFoundError)
    async def _no_file(_: Request, exc: FileNotFoundError):
        return JSONResponse({"detail": f"file not found: {exc}"}, status_code=404)

    @app.exception_handler(ValueError)
    async def _bad(_: Request, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(StorageError)
    async def _storage(_: Request, exc: StorageError):
        return JSONResponse({"detail": f"storage error: {exc}"}, status_code=502)

    def ds(name: str) -> Dataset:
        return reg.get(name)

    def filters(decision, reason, q, kw, rule, min_score, max_score, mismatch, judged) -> Dict[str, Any]:
        return {"decision": decision or None, "reason": reason or None, "q": q or None, "kw": kw or None,
                "rule": rule or None, "min_score": min_score, "max_score": max_score, "mismatch": bool(mismatch),
                "judged": judged}

    @app.get("/api/health", tags=["meta"])
    def health():
        return {"status": "ok", "version": __version__, "datasets": len(reg.names())}

    @app.get("/api/datasets", tags=["datasets"])
    def datasets():
        return {"datasets": reg.describe()}

    @app.get("/api/datasets/{name}", tags=["datasets"])
    def overview(name: str):
        return ds(name).overview()

    @app.post("/api/datasets/{name}/refresh", tags=["datasets"])
    def refresh(name: str):
        d = ds(name)
        d.refresh(force=True)
        return {"files": len(d.files())}

    @app.get("/api/datasets/{name}/files", tags=["files"])
    def files(name: str, q: str = "", only: str = Query("", description="'', mistakes, partial, no_corpus")):
        rows = [f.row() for f in ds(name).files()]
        if q:
            rows = [r for r in rows if q.lower() in r["key"].lower()]
        if only == "mistakes":
            rows = [r for r in rows if r["mistakes"]]
        elif only == "partial":
            rows = [r for r in rows if not r["complete"]]
        elif only == "no_corpus":
            rows = [r for r in rows if not r["corpus_path"]]
        return {"files": rows}

    @app.get("/api/datasets/{name}/decisions", tags=["files"])
    def decisions(name: str, file: str, decision: str = "", reason: str = "", q: str = "", kw: str = "",
                  rule: str = "", min_score: Optional[float] = None, max_score: Optional[float] = None,
                  mismatch: bool = False, judged: Optional[bool] = None, sort: str = "row", desc: bool = False,
                  offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=1000)):
        d = ds(name)
        idx = d.decisions(file)
        out = idx.query(offset=offset, limit=limit, sort=sort, desc=desc,
                        **filters(decision, reason, q, kw, rule, min_score, max_score, mismatch, judged))
        out["facets"] = idx.facets()
        out["file"] = d.file(file).row()
        st = d.run_for(file).get("settings") or {}
        out["thresholds"] = {"check1": st.get("check1_threshold", 0.8), "check2": st.get("check2_threshold", 0.8),
                             "band": st.get("uncertain_band")}
        return out

    @app.get("/api/datasets/{name}/record", tags=["records"])
    def record(name: str, file: str, row: Optional[int] = None, line: Optional[int] = None, source: str = "",
               decision: str = "", reason: str = "", q: str = "", kw: str = "", rule: str = "",
               min_score: Optional[float] = None, max_score: Optional[float] = None, mismatch: bool = False,
               judged: Optional[bool] = None, max_chars: int = Query(30000, ge=1000, le=2_000_000)):
        return ds(name).record(file, row=row, line=line, source=source or None, max_chars=max_chars,
                               **filters(decision, reason, q, kw, rule, min_score, max_score, mismatch, judged))

    @app.get("/api/datasets/{name}/simulate", tags=["tuning"])
    def simulate(name: str, check1: float = Query(..., ge=0, le=1), check2: float = Query(..., ge=0, le=1),
                 sweep: bool = False, max_flips: int = Query(300, ge=0, le=5000)):
        """Decisions recomputed from the stored scores with other thresholds (no model is run)."""
        steps = [round(0.5 + 0.05 * i, 2) for i in range(10)] if sweep else []
        return ds(name).simulate(check1, check2, max_flips=max_flips, sweep=steps)

    @app.get("/api/datasets/{name}/find", tags=["records"])
    def find(name: str, id: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=200)):
        return {"matches": ds(name).find_id(id, limit)}

    @app.get("/api/datasets/{name}/browse", tags=["raw"])
    def browse(name: str, root: str = Query("corpus", pattern="^(corpus|output)$"), path: str = ""):
        st = ds(name).corpus if root == "corpus" else ds(name).output
        return {"root": root, "path": clean_path(path),
                "entries": [e.__dict__ for e in st.list(path)]}

    @app.get("/api/datasets/{name}/raw", tags=["raw"])
    def raw(name: str, path: str, root: str = Query("corpus", pattern="^(corpus|output)$"), line: int = Query(1, ge=1),
            count: int = Query(1, ge=1, le=200), member: str = ""):
        d = ds(name)
        st = d.corpus if root == "corpus" else d.output
        lf = d._line_file(st, clean_path(path), member or None)
        total = len(lf)
        if line > total:
            raise HTTPException(404, f"line {line} out of range 1..{total}")
        return {"path": clean_path(path), "root": root, "total_lines": total, "line": line,
                "lines": [b.decode("utf-8", "replace") for b in lf.lines(line, count)]}

    @app.get("/api/cache", tags=["meta"])
    def cache():
        return {"dir": str(reg.cache.root), "bytes": reg.cache.usage(), "max_bytes": reg.cache.max_bytes}

    frontend = Path(cfg.frontend_dir) if cfg.frontend_dir else DEFAULT_FRONTEND
    if not frontend.is_absolute():
        frontend = Path(cfg.base_dir) / frontend
    if (frontend / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(frontend), html=True), name="frontend")
    else:
        @app.get("/", include_in_schema=False)
        def no_frontend():
            return {"detail": f"frontend not built ({frontend} missing); API docs at /docs",
                    "api": "/api/datasets"}

    return app


def _app_from_env() -> FastAPI:
    path = os.environ.get("NLI_VIEWER_CONFIG")
    if not path:
        raise RuntimeError("set NLI_VIEWER_CONFIG to the viewer config file")
    return create_app(load_config(path))


def __getattr__(name: str):  # `uvicorn nli_viewer.api:app` builds the app from NLI_VIEWER_CONFIG
    if name == "app":
        return _app_from_env()
    raise AttributeError(name)

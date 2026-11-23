"""
api.py - FastAPI application: JSON API under /api, the built frontend at /.

    from nli_viewer.api import create_app
    app = create_app(config)          # ViewerConfig
    # uvicorn nli_viewer.api:app  (reads NLI_VIEWER_CONFIG)

Interactive API documentation: /docs
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import time
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import DatasetRegistry, ViewerConfig, load_config
from .edit import EditConflict
from .playground import Playground, PlaygroundError
from . import runs as runs_mod
from .results import Dataset
from .golden import GoldenStore
from .labels import LabelRuns
from .storage import StorageError, clean_path

__all__ = ["create_app", "EDIT_HEADER"]

EDIT_HEADER = "X-Viewer-Edit"  # every editing request must send it (a plain form on another web site cannot)
_LOCAL_CLIENTS = {"127.0.0.1", "::1", "localhost"}


class EditBody(BaseModel):
    path: str
    line: int
    text: str
    sha1: Optional[str] = ""  # sha1 of the line as loaded; a different current line = 409 conflict
    member: Optional[str] = None  # .zip / .rar: the member file the line is in; null or "" = not an archive


class GoldenBody(BaseModel):
    file: str
    row: int
    expect: Optional[str] = None  # filter / keep; empty = remove the label
    note: str = ""


class LineChange(BaseModel):
    line: int
    text: Optional[str] = None              # new text field; null = leave the text
    sha1: Optional[str] = ""
    fields: Optional[Dict[str, Any]] = None  # other fields to set or add (not the id field)
    remove: Optional[List[str]] = None       # other fields to drop


class InsertBody(BaseModel):
    path: str
    after: int                 # 0 = at the top, number of lines = at the end
    record: Dict[str, Any]     # the new line: id field, text field, other fields
    sha1: Optional[str] = ""             # of line `after` (line 1 when after = 0) as loaded
    member: Optional[str] = None  # null or "" = not an archive


class DeleteBody(BaseModel):
    path: str
    line: int
    sha1: Optional[str] = ""
    member: Optional[str] = None  # null or "" = not an archive


class RunBody(BaseModel):
    path: str
    member: Optional[str] = None
    lines: List[int]                    # corpus line numbers to run
    settings: Dict[str, Any] = {}       # keywords, check1, check2, thresholds, use_judge, ... (see nli_playground.py)


class TryLabelBody(BaseModel):
    texts: List[str]
    policy: Optional[str] = None                 # a file in the project's policy/ folder
    policy_data: Optional[Dict[str, Any]] = None  # or a whole policy (edited thresholds / hypotheses)
    all_labels: bool = True                      # score every label (the decision still follows the cascade)
    force_gate: bool = False                     # label the text even without a keyword hit
    use_judge: bool = True
    topics: Optional[List[Optional[str]]] = None  # each text's topic (the corpus' topic field), for --topic-mode tests
    topic_mode: Optional[str] = None             # hint | trust | off (default: the policy's)


class AddTopicBody(BaseModel):
    topic: str


class SaveCasesBody(BaseModel):
    file: str                                     # labels/<name>.json, as GET /api/labels/cases gave it
    data: Dict[str, Any]                          # the whole case set
    base_sha: Optional[str] = None                # the "sha" the page loaded: refused if the file changed since


CASE_ACTIONS = ("remove", "review", "keep", "pass", "untouched")


def check_cases(data: Dict[str, Any]) -> List[str]:
    """Problems that stop a save (empty list = fine)."""
    errs: List[str] = []
    corpus = data.get("corpus")  # rebuilt (deleted and written again) after a save: only test_corpus_cases… folders
    if corpus is not None and not (isinstance(corpus, str) and re.fullmatch(r"test_corpus_cases[A-Za-z0-9_-]*", corpus)):
        errs.append("'corpus' must be a folder name starting with test_corpus_cases (letters, digits, _ -)")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        return ["'cases' must be a non-empty list"]
    seen = set()
    for i, c in enumerate(cases, 1):
        where = f"case {i}"
        if not isinstance(c, dict):
            errs.append(f"{where}: not an object")
            continue
        cid = c.get("id")
        if not isinstance(cid, str) or not cid.strip():
            errs.append(f"{where}: id is empty")
        elif cid in seen:
            errs.append(f"{where}: id '{cid}' is used twice")
        else:
            seen.add(cid)
            where = f"case '{cid}'"
        for k in ("group", "title"):
            if not isinstance(c.get(k), str) or not c[k].strip():
                errs.append(f"{where}: {k} is empty")
        texts = c.get("texts")
        if not isinstance(texts, list) or not texts:
            errs.append(f"{where}: needs at least one text")
            continue
        for k, t in enumerate(texts, 1):
            tw = f"{where}, text {k}"
            if not isinstance(t, dict):
                errs.append(f"{tw}: not an object")
                continue
            if not isinstance(t.get("text"), str) or not t["text"].strip():
                errs.append(f"{tw}: the text is empty")
            elif len(t["text"]) > 20000:
                errs.append(f"{tw}: longer than 20,000 characters")
            exp = t.get("expected_action")
            if not isinstance(exp, str) or any(x.strip() not in CASE_ACTIONS for x in exp.split(" or ")):
                errs.append(f"{tw}: expected_action must be one of {', '.join(CASE_ACTIONS)}")
            if any(a not in CASE_ACTIONS for a in (t.get("acceptable") or [])):
                errs.append(f"{tw}: acceptable actions must be among {', '.join(CASE_ACTIONS)}")
            if not isinstance(t.get("labels_yes", []), list):
                errs.append(f"{tw}: labels_yes must be a list")
            if t.get("topic") is not None and not (isinstance(t["topic"], str) and len(t["topic"]) <= 80):
                errs.append(f"{tw}: topic must be a short text (or left out)")
    return errs


class LabelLinesBody(BaseModel):
    path: str
    member: Optional[str] = None
    lines: List[int]
    policy: str                                   # a file in the project's policy/ folder
    use_judge: bool = True


class LabelRunBody(BaseModel):
    path: str
    member: Optional[str] = None
    policy: str
    output_dir: str                               # a folder name, created in the project's dataset/ folder
    use_judge: bool = True


class StartRunBody(BaseModel):
    args: Optional[List[str]] = None    # nli_filter.py arguments, or
    command: Optional[str] = None       # the same as one command line


class SaveHypBody(BaseModel):
    name: str
    data: Dict[str, Any]
    overwrite: bool = False


class SaveKwBody(BaseModel):
    name: str
    text: str
    overwrite: bool = False


class BatchBody(BaseModel):
    path: str
    changes: List[LineChange]
    member: Optional[str] = None  # null or "" = not an archive

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

    @app.exception_handler(PlaygroundError)
    async def _pg(_: Request, exc: PlaygroundError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.exception_handler(EditConflict)
    async def _conflict(_: Request, exc: EditConflict):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(StorageError)
    async def _storage(_: Request, exc: StorageError):
        return JSONResponse({"detail": f"storage error: {exc}"}, status_code=502)

    def ds(name: str) -> Dataset:
        try:
            return reg.get(name)
        except KeyError:
            refresh_auto()  # a dynamic dataset found since the last scan
            return reg.get(name)

    project = Path(cfg.project_dir)
    if not project.is_absolute():
        project = Path(cfg.base_dir) / project
    edits = Path(cfg.edits_dir)
    if not edits.is_absolute():
        edits = Path(cfg.base_dir) / edits
    pg = Playground(cfg.playground_url, str(project), str(edits / "_project"))
    golden = GoldenStore(project / "golden")
    app.state.golden = golden
    app.state.playground = pg

    def filters(decision, reason, q, kw, rule, min_score, max_score, mismatch, judged) -> Dict[str, Any]:
        return {"decision": decision or None, "reason": reason or None, "q": q or None, "kw": kw or None,
                "rule": rule or None, "min_score": min_score, "max_score": max_score, "mismatch": bool(mismatch),
                "judged": judged}

    @app.get("/api/health", tags=["meta"])
    def health():
        return {"status": "ok", "version": __version__, "datasets": len(reg.names())}

    def label_run_of(name: str) -> Optional[str]:
        """A dataset whose "output" is a local nli_label.py run folder: the run's name on the Labels pages."""
        try:
            c = reg.config(name)
        except Exception:  # noqa: BLE001
            return None
        out = (c.output or "").strip()
        if not out or "://" in out:
            return None
        p = Path(out)
        if not p.is_absolute():
            p = Path(cfg.base_dir) / p
        return labels.register(name, p)

    # ---- dynamic datasets: the run folders of "auto_datasets" (e.g. ../dataset), the most recent run per corpus ----
    auto_dir: Optional[Path] = None
    if cfg.auto_datasets:
        auto_dir = Path(cfg.auto_datasets)
        if not auto_dir.is_absolute():
            auto_dir = (Path(cfg.base_dir) / auto_dir).resolve()

    def refresh_auto() -> List[Any]:
        if auto_dir is None:
            return []
        from . import discover
        runs = discover.scan(project, auto_dir)
        reg.set_auto(discover.auto_datasets(runs, reg.configured_pairs()))
        return runs

    @app.get("/api/run-folders", tags=["datasets"])
    def run_folders():
        """Every run folder of auto_datasets: in use, older, corpus missing, broken (for removing by hand)."""
        from . import discover
        runs = refresh_auto()
        return {"folder": str(auto_dir) if auto_dir else None,
                "runs": [r.as_dict(project) for r in runs],
                "remove_invalid": discover.removal_commands(runs, project, discover.INVALID),
                "remove_unused": discover.removal_commands(runs, project, discover.UNUSED)}

    @app.get("/api/datasets", tags=["datasets"])
    def datasets():
        refresh_auto()
        rows = reg.describe()
        for r in rows:
            lr = label_run_of(r["name"])
            if lr:
                r["label_run"] = lr
                r["error"] = None  # a label run has no decisions files: not an error
        return {"datasets": rows}

    @app.get("/api/datasets/{name}", tags=["datasets"])
    def overview(name: str):
        res = ds(name).overview()
        lr = label_run_of(name)
        if lr:
            res["label_run"] = lr
        return res

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

    # ---- review tools: keywords, lines across files, golden set ----------------------------------

    @app.get("/api/datasets/{name}/keywords", tags=["review"])
    def keyword_stats(name: str):
        """Per keyword over the whole dataset: hits, lines kept / filtered, reasons, labels, level-A audit, flags."""
        return ds(name).keyword_stats()

    @app.get("/api/datasets/{name}/lines", tags=["review"])
    def lines(name: str, decision: str = "", reason: str = "", q: str = "", kw: str = "", rule: str = "",
              min_score: Optional[float] = None, max_score: Optional[float] = None, mismatch: bool = False,
              judged: Optional[bool] = None, labelled: Optional[bool] = None,
              audit: str = Query("", pattern="^(|any|keep|filter)$"), scored: bool = False, single_kw: bool = False,
              kw_state: str = Query("", pattern="^(|strict|rule|incidental|about|open)$"),
              sort: str = Query("row", pattern="^(row|score|check1|check2|hits|id|review)$"), desc: bool = False,
              offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)):
        """Decisions of every file with these filters; sort=review: closest to a threshold first."""
        out = ds(name).lines(offset=offset, limit=limit, sort=sort, desc=desc,
                             labelled=labelled, audit=audit or None, scored=scored or None,
                             single_kw=single_kw or None, kw_state=kw_state or None,
                             **filters(decision, reason, q, kw, rule, min_score, max_score, mismatch, judged))
        labels = golden.summary(name)["labels"]
        for r in out["rows"]:
            r["golden"] = labels.get(GoldenStore.key(r["file"], r["line"]))
        return out

    @app.get("/api/datasets/{name}/golden", tags=["review"])
    def golden_get(name: str):
        """The golden set of this dataset: where it is, how many lines, label per 'file#line'."""
        ds(name)
        return golden.summary(name)

    @app.post("/api/datasets/{name}/golden", tags=["review"])
    def golden_set(name: str, body: GoldenBody, request: Request):
        """Label one line for the golden set (copies its current text; the corpus is not changed)."""
        save_guard(request)  # writes golden/<name>.jsonl in the project: same rules as saving keyword files
        d = ds(name)
        rec = d.record(body.file, row=body.row, max_chars=1000)
        dec, orig = rec["decision"], rec["original"]
        record = orig.get("record") if orig.get("available") else None
        text = (record or {}).get(rec["text_field"])
        if body.expect and not isinstance(text, str):
            raise HTTPException(409, "the line's text cannot be read from the corpus: it cannot be labelled")
        res = golden.set(name, body.file, int(dec.get("line") or rec["line"]), text or "", body.expect or None,
                         rid=dec.get("id"), note=body.note)
        return {**res, "summary": {k: v for k, v in golden.summary(name).items() if k != "labels"}}

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

    # ---- corpus: view any line, edit the text field (editable datasets on a local drive only) ----

    def client_problem(request: Request) -> Optional[str]:
        host = request.client.host if request.client else ""
        server = (request.scope.get("server") or ("",))[0]  # the address the browser connected to
        # same PC: 127.0.0.1 / ::1, or the PC's own network address (http://192.168.x.y:8000 opened on this PC)
        local = host in _LOCAL_CLIENTS or (host and host == server)
        if not cfg.edit_allow_remote and not local:
            return (f"editing is only allowed from the PC the viewer runs on (this request came from {host or '?'}; "
                    'set "edit_allow_remote": true in viewer_config.json to allow other PCs)')
        return None

    def guard(request: Request, d: Dataset, path: Optional[str] = None, member: Optional[str] = None) -> None:
        if request.headers.get(EDIT_HEADER) != "1":
            raise HTTPException(403, f"editing requests need the header {EDIT_HEADER}: 1")
        why = client_problem(request) or d.edit_problem(path, member)
        if why:
            raise HTTPException(403, why)

    @app.get("/api/datasets/{name}/corpus/lines", tags=["corpus"])
    def corpus_lines(name: str, path: str, start: int = Query(1, ge=1), count: int = Query(20, ge=1, le=200),
                     preview: int = Query(0, ge=0), member: str = ""):
        """Lines of a corpus file (or of one member of a .zip / .rar): text, id, sha1, number of edits, decision row
        (if the file has results). For an archive, `members` lists its members (default: the first)."""
        return ds(name).corpus_lines(path, start, count, preview, member or None)

    @app.get("/api/datasets/{name}/corpus/edit-status", tags=["corpus"])
    def edit_status(name: str, request: Request, path: str = "", member: str = ""):
        d = ds(name)
        problem = d.edit_problem(clean_path(path) if path else None, member or None) or client_problem(request)
        return {"editable": problem is None, "problem": problem, "dataset_editable": d.editor is not None}

    @app.post("/api/datasets/{name}/corpus/edit", tags=["corpus"])
    def corpus_edit(name: str, body: EditBody, request: Request):
        """Replace the text field of one line; the corpus file (.zst / .gz / plain) is rewritten safely."""
        d = ds(name)
        path = clean_path(body.path)
        guard(request, d, path, body.member or None)
        host = request.client.host if request.client else None
        return d.editor.edit_text(path, body.line, body.text, body.sha1 or None, client=host, member=body.member or None)

    @app.post("/api/datasets/{name}/corpus/edit-batch", tags=["corpus"])
    def corpus_edit_batch(name: str, body: BatchBody, request: Request):
        """Several lines of one file in one rewrite (all or nothing)."""
        d = ds(name)
        path = clean_path(body.path)
        guard(request, d, path, body.member or None)
        host = request.client.host if request.client else None
        return d.editor.edit_texts(path, [c.model_dump() for c in body.changes], client=host,
                                   member=body.member or None)

    @app.post("/api/datasets/{name}/corpus/insert", tags=["corpus"])
    def corpus_insert(name: str, body: InsertBody, request: Request):
        """Insert a new line; the lines after it move down by one (decisions are mapped to their new lines)."""
        d = ds(name)
        path = clean_path(body.path)
        guard(request, d, path, body.member or None)
        host = request.client.host if request.client else None
        return d.editor.insert_line(path, body.after, body.record, body.sha1 or None, body.member or None, client=host)

    @app.post("/api/datasets/{name}/corpus/delete", tags=["corpus"])
    def corpus_delete(name: str, body: DeleteBody, request: Request):
        """Delete a line (kept in the edit log, so it can be undone); the lines after it move up by one."""
        d = ds(name)
        path = clean_path(body.path)
        guard(request, d, path, body.member or None)
        host = request.client.host if request.client else None
        return d.editor.delete_line(path, body.line, body.sha1 or None, body.member or None, client=host)

    @app.get("/api/datasets/{name}/corpus/edits", tags=["corpus"])
    def corpus_edits(name: str, path: str = "", line: Optional[int] = None, member: str = ""):
        d = ds(name)
        return {"edits": d.editor.history(path or None, line, member or None) if d.editor is not None else []}

    @app.post("/api/datasets/{name}/corpus/edits/{edit_id}/undo", tags=["corpus"])
    def corpus_undo(name: str, edit_id: str, request: Request):
        d = ds(name)
        guard(request, d)
        entry = next((e for e in d.editor.history() if e["edit"] == edit_id), None)
        if entry is None:
            raise KeyError(f"unknown edit '{edit_id}'")
        guard(request, d, entry["file"], entry.get("member"))
        return d.editor.undo(edit_id, client=request.client.host if request.client else None)

    # ---- try settings: model service + shared hypothesis / keyword files ----------------------

    @app.get("/api/playground", tags=["playground"])
    def playground():
        """Model service status, the hypothesis and keyword files of the project, the known countries."""
        status = pg.status()
        countries = pg.info().get("countries") or [{"name": "Russia", "adj": "Russian"}]
        return {"service": status, "countries": countries, "can_save": True, **pg.resources()}

    @app.post("/api/datasets/{name}/playground/run", tags=["playground"])
    def playground_run(name: str, body: RunBody):
        """nli_filter.py's decision for these lines with these settings (through nli_playground.py)."""
        if len(body.lines) > 200:
            raise HTTPException(400, "at most 200 lines per run")
        return pg.run(ds(name), body.path, body.member, body.lines, body.settings)

    # ---- nli_label.py on corpus lines: live on the page, or saved as a labelling run ----

    def _policy_arg(policy: str) -> str:
        rel = (policy or "").replace("\\", "/")
        if not re.fullmatch(r"policy/[A-Za-z0-9_.-]+\.json", rel) or not (project / rel).is_file():
            raise HTTPException(400, "policy must be a .json file in the project's policy folder (policy/<name>.json)")
        return rel

    @app.post("/api/datasets/{name}/label-lines", tags=["labels"])
    def label_lines(name: str, body: LabelLinesBody):
        """nli_label.py's labels for these corpus lines (through the model service); nothing is written."""
        if not body.lines or len(body.lines) > 100:
            raise HTTPException(400, "1 to 100 lines")
        return pg.label_lines(ds(name), body.path, body.member, body.lines, _policy_arg(body.policy), body.use_judge)

    @app.post("/api/datasets/{name}/label-run", tags=["labels"])
    def label_run_start(name: str, body: LabelRunBody, request: Request):
        """Start 'nli_label.py run' on one corpus file into a new folder of the project (a labelling run)."""
        save_guard(request)
        if body.member:
            raise HTTPException(400, "a member of a .zip / .rar file cannot be labelled on its own: label the archive")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,120}", body.output_dir or ""):
            raise HTTPException(400, "output folder: a name (letters, digits, _ . -), created in the dataset folder")
        out = project / "dataset" / body.output_dir
        if out.exists() and any(out.iterdir()):
            raise HTTPException(409, f"{body.output_dir} exists already: choose another name")
        d = ds(name)
        corpus, env, _notes = runs_mod._corpus_arg(reg.config(name), d)
        rel = body.path.replace("\\", "/").strip("/")
        if ".." in rel.split("/"):
            raise HTTPException(400, "bad path")
        if "://" in corpus:
            base, _, query = corpus.partition("?")
            src = base.rstrip("/") + "/" + rel + (f"?{query}" if query else "")
        else:
            src = str(Path(corpus) / rel)
        args = ["run", src, "--policy", _policy_arg(body.policy), "--output-dir", str(out), "--write-clean"]
        if not body.use_judge:
            args += ["--judge-model", "none"]
        job = pg.start_job(args, env, f"labels: {body.output_dir}", script="nli_label.py")
        return {"job": job, "run": body.output_dir}

    # ---- run nli_filter.py on a dataset (started by nli_playground.py, which has the torch environment) ----

    job_dataset: Dict[str, str] = {}  # job id -> dataset name (rescan its output when the job ends)

    @app.get("/api/datasets/{name}/run/defaults", tags=["runs"])
    def run_defaults(name: str):
        """Suggested nli_filter.py arguments for this dataset (corpus, output folder, the last run's settings)."""
        info = pg.info()
        out = runs_mod.default_args(reg.config(name), ds(name), info.get("options"))
        out["service"] = pg.status()
        return out

    @app.post("/api/datasets/{name}/run", tags=["runs"])
    def run_start(name: str, body: StartRunBody, request: Request):
        """Start nli_filter.py with these arguments (only from this PC: it starts a program)."""
        save_guard(request)
        args = body.args if body.args is not None else runs_mod.split_command(body.command or "")
        if not args:
            raise HTTPException(400, "no arguments")
        if "<output folder>" in args:
            raise HTTPException(400, "set the output folder (--output-dir) first")
        job = pg.start_job(args, runs_mod.run_env(reg.config(name), ds(name)), name)
        job_dataset[job["id"]] = name
        return job

    def _job_done(job: Dict[str, Any]) -> Dict[str, Any]:
        name = job_dataset.get(job.get("id"))
        if name and job.get("state") != "running":
            with contextlib.suppress(Exception):
                ds(name).refresh(force=True)  # the new results show up at once
        return job

    @app.get("/api/datasets/{name}/progress", tags=["runs"])
    def progress(name: str):
        """nli_filter.py runs writing into this dataset's output folder (however they were started)."""
        return ds(name).progress(float(cfg.progress_stale_seconds))

    @app.get("/api/runs", tags=["runs"])
    def run_list():
        return pg.jobs()

    @app.get("/api/runs/{jid}", tags=["runs"])
    def run_get(jid: str):
        return _job_done(pg.job(jid))

    @app.post("/api/runs/{jid}/stop", tags=["runs"])
    def run_stop(jid: str, request: Request):
        save_guard(request)
        return pg.stop_job(jid)

    def save_guard(request: Request) -> None:
        if request.headers.get(EDIT_HEADER) != "1":
            raise HTTPException(403, f"saving needs the header {EDIT_HEADER}: 1")
        why = client_problem(request)
        if why:
            raise HTTPException(403, why.replace("editing", "saving"))

    # ---- nli_label.py runs (policy labels per paragraph): list, browse, start -------------------------

    labels = LabelRuns(project, float(cfg.progress_stale_seconds))

    @app.get("/api/labels", tags=["labels"])
    def label_runs():
        """nli_label.py output folders in the project folder (finished, or running with progress.json)."""
        return labels.list()

    @app.get("/api/labels/policies", tags=["labels"])
    def label_policies():
        """policy/*.json files of the project (for the start form)."""
        pol = project / "policy"
        return {"policies": sorted(f"policy/{p.name}" for p in pol.glob("*.json")) if pol.is_dir() else []}

    def _case_files() -> List[Path]:
        """labels/cases_vN.json (newest last), then other labels/*cases_vN.json sets (e.g. russia_llm_cases_v1.json)."""
        lab = project / "labels"
        if not lab.is_dir():
            return []
        main = sorted((f for f in lab.glob("cases_v*.json") if re.fullmatch(r"cases_v\d+", f.stem)),
                      key=lambda f: int(f.stem[7:]))  # cases_v1.json, cases_v2.json, ... (not *_results.json)
        other = sorted(f for f in lab.glob("*_cases_v*.json") if re.fullmatch(r"[a-z0-9_]+_cases_v\d+", f.stem))
        return main + other

    @app.get("/api/labels/case-files", tags=["labels"])
    def label_case_files():
        """The case sets the Try page can show (newest = the default)."""
        files = _case_files()
        main = [f for f in files if f.stem.startswith("cases_v")]
        return {"files": [f"labels/{f.name}" for f in files],
                "newest": f"labels/{main[-1].name}" if main else (f"labels/{files[0].name}" if files else None)}

    @app.get("/api/labels/cases", tags=["labels"])
    def label_cases(file: Optional[str] = None):
        """labels/cases_*.json: the policy Try page's cases (tools/build_cases.py), newest version; ?file= another
        case set from GET /api/labels/case-files."""
        files = _case_files()
        if not files:
            raise HTTPException(404, "no labels/cases_v*.json: run python tools/build_cases.py")
        if file:
            pick = next((f for f in files if f"labels/{f.name}" == file.replace("\\", "/")), None)
            if pick is None:
                raise HTTPException(404, f"unknown case file {file}")
        else:
            main = [f for f in files if f.stem.startswith("cases_v")]
            pick = main[-1] if main else files[0]
        raw = pick.read_bytes()
        data = json.loads(raw.decode("utf-8"))
        data["file"] = f"labels/{pick.name}"
        data["sha"] = hashlib.sha1(raw).hexdigest()  # sent back on save: refused if the file changed meanwhile
        return data

    topics_file = project / "labels" / "topic_labels.json"

    def _read_topics() -> Dict[str, Any]:
        if not topics_file.is_file():
            return {"about": "", "topics": []}
        data = json.loads(topics_file.read_text(encoding="utf-8"))
        data["topics"] = [str(t) for t in (data.get("topics") or []) if str(t).strip()]
        return data

    @app.get("/api/labels/topics", tags=["labels"])
    def label_topics():
        """The topic values of the case editor's dropdown (labels/topic_labels.json)."""
        data = _read_topics()
        return {"file": "labels/topic_labels.json", "topics": data["topics"], "about": data.get("about", "")}

    @app.post("/api/labels/topics", tags=["labels"])
    def label_topics_add(body: AddTopicBody, request: Request):
        """Add a topic value to labels/topic_labels.json (the dropdown's "+ new topic…")."""
        save_guard(request)
        t = " ".join((body.topic or "").split())
        if not t or len(t) > 80 or any(ch in t for ch in '"\\\n'):
            raise HTTPException(400, "a topic: 1 to 80 characters, no quotes or backslashes")
        data = _read_topics()
        if t.lower() in {x.lower() for x in data["topics"]}:
            return {"file": "labels/topic_labels.json", "topics": data["topics"], "added": None}
        data["topics"] = data["topics"] + [t]
        topics_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = topics_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(topics_file)
        return {"file": "labels/topic_labels.json", "topics": data["topics"], "added": t}

    @app.post("/api/labels/cases/save", tags=["labels"])
    def label_cases_save(body: SaveCasesBody, request: Request):
        """Save an edited case set (the Try page's "Edit cases"); the old file is kept in labels/.backup/. Then the
        case corpus is rebuilt (dataset/<the set's "corpus" folder>, or dataset/test_corpus_cases for the newest
        cases_vN.json)."""
        save_guard(request)
        files = _case_files()
        pick = next((f for f in files if f"labels/{f.name}" == body.file.replace("\\", "/")), None)
        if pick is None:
            raise HTTPException(404, f"unknown case file {body.file}")
        if body.base_sha and hashlib.sha1(pick.read_bytes()).hexdigest() != body.base_sha:
            raise HTTPException(409, f"{body.file} was changed by someone else since you loaded it: reload the page "
                                     "(your edits are still on the page; copy what you need first)")
        data = {k: v for k, v in body.data.items() if k not in ("file", "sha")}
        errs = check_cases(data)
        if errs:
            raise HTTPException(400, "; ".join(errs[:12]) + (f" (and {len(errs) - 12} more)" if len(errs) > 12 else ""))
        data["edited"] = time.strftime("%Y-%m-%d %H:%M:%S")
        bdir = pick.parent / ".backup"
        bdir.mkdir(exist_ok=True)
        backup = bdir / f"{pick.stem}.{time.strftime('%Y%m%d-%H%M%S')}.json"
        shutil.copy2(pick, backup)
        tmp = pick.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(pick)
        # the corpus the case set belongs to (not for an older cases_vN.json: test_corpus_cases holds the newest)
        main = [f for f in files if f.stem.startswith("cases_v")]
        corpus = None
        builder = project / "tools" / "build_cases_corpus.py"
        if builder.is_file() and (data.get("corpus") or (main and pick == main[-1])):
            import importlib.util
            spec = importlib.util.spec_from_file_location("build_cases_corpus", builder)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            out = project / "dataset" / (data.get("corpus") or "test_corpus_cases")
            n_files, n_lines = mod.build(data, out)
            corpus = {"path": f"dataset/{out.name}", "files": n_files, "lines": n_lines}
        texts = sum(len(c["texts"]) for c in data["cases"])
        return {"file": body.file, "sha": hashlib.sha1(pick.read_bytes()).hexdigest(), "backup": f"labels/.backup/{backup.name}",
                "cases": len(data["cases"]), "texts": texts, "corpus": corpus}

    @app.post("/api/labels/try", tags=["labels"])
    def label_try(body: TryLabelBody):
        """Policy labels (level 0 / 1 / 2, decision) on up to 20 texts, through the model service."""
        if not body.texts or len(body.texts) > 20:
            raise HTTPException(400, "1 to 20 texts")
        req: Dict[str, Any] = {"texts": body.texts, "all_labels": body.all_labels, "force_gate": body.force_gate,
                               "use_judge": body.use_judge}
        if body.topics is not None:
            if len(body.topics) != len(body.texts):
                raise HTTPException(400, "topics: one per text (null for none)")
            req["topics"] = body.topics
        if body.topic_mode:
            if body.topic_mode not in ("hint", "trust", "off"):
                raise HTTPException(400, "topic_mode must be hint, trust or off")
            req["topic_mode"] = body.topic_mode
        if body.policy_data is not None:
            req["policy_data"] = body.policy_data
        else:
            req["policy"] = body.policy or "policy/russia_policy.json"
        return pg.label(req)

    @app.get("/api/labels/{name}", tags=["labels"])
    def label_run(name: str):
        return labels.run(name)

    @app.get("/api/labels/{name}/docs", tags=["labels"])
    def label_docs(name: str, file: str, action: Optional[str] = None, label: Optional[str] = None,
                   para_action: Optional[str] = None, gated: bool = True,
                   offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)):
        """Documents of one file of a run, filtered by document action, label or paragraph action."""
        return labels.docs(name, file, action, label, para_action, gated, offset, limit)

    @app.get("/api/labels/{name}/doc", tags=["labels"])
    def label_doc(name: str, file: str, line: int = Query(..., ge=1)):
        """One document: its labels row (paragraphs, scores, actions), the source text and the policy."""
        return labels.doc(name, file, line)

    @app.post("/api/labels/start", tags=["labels"])
    def label_start(body: StartRunBody, request: Request):
        """Start 'nli_label.py run …' (through the model service; only from this PC: it starts a program)."""
        save_guard(request)
        args = body.args if body.args is not None else runs_mod.split_command(body.command or "")
        if args and args[0].lower().endswith("nli_label.py"):
            args = args[1:]
        if not args or args[0] not in ("run", "redecide"):
            raise HTTPException(400, "the arguments must start with 'run' or 'redecide'")
        if "--output-dir" not in args:
            raise HTTPException(400, "set the output folder (--output-dir)")
        out = args[args.index("--output-dir") + 1] if args.index("--output-dir") + 1 < len(args) else ""
        return pg.start_job(args, {}, f"labels: {out}", script="nli_label.py")

    @app.post("/api/playground/hypotheses", tags=["playground"])
    def save_hypotheses(body: SaveHypBody, request: Request):
        """Save hypotheses/<name>.json of the project (the old file is backed up)."""
        save_guard(request)
        return pg.save_hypotheses(body.name, body.data, body.overwrite)

    @app.post("/api/playground/keywords", tags=["playground"])
    def save_keywords(body: SaveKwBody, request: Request):
        """Save keywords/<name>.txt of the project (the old file is backed up)."""
        save_guard(request)
        return pg.save_keywords(body.name, body.text, body.overwrite)

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

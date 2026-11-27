"""
api.py - FastAPI application: JSON API under /api, the built frontend at /.

    from nli_viewer.api import create_app
    app = create_app(config)          # ViewerConfig
    # uvicorn nli_viewer.api:app  (reads NLI_VIEWER_CONFIG)

Interactive API documentation: /docs
"""
from __future__ import annotations

import contextlib
import csv
import hashlib
import json
import os
import shutil
import time
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
from . import kwstats as kwstats_mod
from . import translate as translate_mod
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
    decision_unit: Optional[str] = None          # paragraph | line (Explain this line: the run's)
    review_as: Optional[str] = None              # keep | remove (the run's)
    uncertain_band: Optional[List[float]] = None  # the run's judge band
    reuse_scores: bool = False                   # the Experiment page: reuse pairs scored before (model service cache)


class ConfigBody(BaseModel):
    data: Dict[str, Any]


class SaveConfigBody(BaseModel):
    path: str
    data: Dict[str, Any]
    base_sha: Optional[str] = None
    save_as: Optional[str] = None


class SchemaPreviewBody(BaseModel):
    data: Dict[str, Any]
    run: str
    file: Optional[str] = None
    limit: int = 30


class AddTopicBody(BaseModel):
    topic: str


class SaveCasesBody(BaseModel):
    file: str                                     # labels/<name>.json, as GET /api/labels/cases gave it
    data: Dict[str, Any]                          # the whole case set
    base_sha: Optional[str] = None                # the "sha" the page loaded: refused if the file changed since


class CheckPolicyBody(BaseModel):
    data: Dict[str, Any]                          # the whole policy, as it would be saved


class LabSaveBody(BaseModel):
    data: Dict[str, Any]                          # the Experiment page's draft policy
    save_as: Optional[str] = None                 # policy/<name>.json, a new file (never overwrites), or
    replace: Optional[str] = None                 # policy/<name>.json to overwrite (with a backup), only with
    confirm: Optional[str] = None                 # the file name typed again (e.g. russia_llm_policy_v2.json)
    base_sha: Optional[str] = None                # replace: refused when the file changed since the page loaded it


class SavePolicyBody(BaseModel):
    path: str                                     # policy/<name>.json, as GET /api/labels/policy/raw gave it
    data: Dict[str, Any]
    base_sha: Optional[str] = None                # the "sha" the page loaded: refused if the file changed since
    save_as: Optional[str] = None                 # a new policy/<name>.json instead (must not exist)


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


class RedecideBody(BaseModel):
    policy: Optional[str] = None                  # policy/<name>.json, or
    policy_data: Optional[Dict[str, Any]] = None  # the policy editor's unsaved policy
    output_dir: str                               # a new folder name, created in the project's dataset/ folder
    write_clean: bool = False
    review_as: Optional[str] = None               # keep | remove (default: nli_label.py's, keep)
    max_removed_share: Optional[float] = None     # drop a document when more than this share is cut; 0 = off;
    drop_if_first_cut: Optional[bool] = None      # None = the run's own values (nli_label.py redecide)


class SaveDocsBody(BaseModel):
    file: str = "labels/russia_llm_docs_v1.json"
    data: Dict[str, Any]                          # the whole documents test set
    base_sha: Optional[str] = None


class ListFileBody(BaseModel):
    path: str                                     # keywords/<name>.txt, policy/place_names*.csv, policy/place_name_exceptions*.txt
    text: str
    base_sha: Optional[str] = None
    sample: Optional[str] = None                  # check: a text to preview the place-name rewriting on
    policy: Optional[str] = None                  # check: the policy whose other place-name file the preview uses


class DeleteFoldersBody(BaseModel):
    folders: List[str]                            # run folder names in the auto_datasets folder
    allow_in_use: bool = False


class TestSetRunBody(BaseModel):
    file: str                                     # labels/<name>.json, a test set with "corpus"
    policy: Optional[str] = None                  # default: the policy named in the file
    output_dir: Optional[str] = None              # default: out_label_<file name>, in dataset/
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
    app.include_router(kwstats_mod.router)  # /api/labels/kwstats/... (before /api/labels/{name} and the frontend mount)
    translate_mod.install(app, cfg)  # /api/translate, /api/translate/settings, /api/translate/test

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

    @app.post("/api/run-folders/delete", tags=["datasets"])
    def run_folders_delete(body: DeleteFoldersBody, request: Request):
        """Delete run folders of auto_datasets (the viewer's clean-up page). Only out* run folders directly inside the
        auto_datasets folder that the scan knows; never a running one; never a corpus folder; a folder in use (shown
        by the viewer, or the output of a dataset in viewer_config.json) only with allow_in_use."""
        save_guard(request)
        from . import discover
        if auto_dir is None:
            raise HTTPException(400, "no auto_datasets folder in viewer_config.json")
        runs = {r.path.name: r for r in refresh_auto()}
        cfg_outputs = {Path(o).resolve() for _c, o in reg.configured_pairs().values() if o and "://" not in o}
        corpora = {Path(c).resolve() for c, _o in reg.configured_pairs().values() if c and "://" not in c}
        corpora |= {r.corpus.resolve() for r in runs.values() if r.corpus is not None}
        deleted, failed = [], []
        for name in body.folders:
            name = name.replace("\\", "/").split("/")[-1]
            r = runs.get(name)
            if r is None or not r.path.is_dir() or r.path.resolve().parent != auto_dir.resolve():
                failed.append({"folder": name, "error": "not a run folder of the dataset folder"})
                continue
            p = r.path.resolve()
            if r.status == discover.RUNNING:
                failed.append({"folder": name, "error": "running: stop it first"})
                continue
            if any(p == c or p in c.parents for c in corpora):
                failed.append({"folder": name, "error": "a corpus is in this folder"})
                continue
            in_use = r.status == discover.IN_USE or p in cfg_outputs
            if in_use and not body.allow_in_use:
                failed.append({"folder": name, "error": "in use (tick 'also folders in use' to delete it)"})
                continue
            try:
                shutil.rmtree(p)
                labels.extra = {k: v for k, v in labels.extra.items() if Path(v).resolve() != p}
                deleted.append(name)
            except OSError as exc:
                failed.append({"folder": name, "error": f"{exc} (a file may be open in another program)"})
        refresh_auto()
        return {"deleted": deleted, "failed": failed}

    def output_modified(name: str) -> Optional[float]:
        """When a local output folder last changed: the newest mtime of the folder and the files directly in it
        (one level, cheap). None for remote outputs or a missing folder."""
        try:
            out = (reg.config(name).output or "").strip()
        except Exception:  # noqa: BLE001
            return None
        if not out or "://" in out:
            return None
        p = Path(out)
        if not p.is_absolute():
            p = Path(cfg.base_dir) / p
        try:
            if not p.exists():
                return None
            newest = p.stat().st_mtime
            if p.is_dir():
                for q in p.iterdir():
                    try:
                        newest = max(newest, q.stat().st_mtime)
                    except OSError:
                        pass
            return newest
        except OSError:
            return None

    @app.get("/api/datasets", tags=["datasets"])
    def datasets():
        refresh_auto()
        rows = reg.describe()
        for r in rows:
            lr = label_run_of(r["name"])
            if lr:
                r["label_run"] = lr
                r["error"] = None  # a label run has no decisions files: not an error
            r["modified"] = output_modified(r["name"])
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

    @app.get("/api/labels/policy", tags=["labels"])
    def label_policy(path: str):
        """One policy's settings (labels by level, topic field / mode / map) for the Try page."""
        rel = (path or "").replace("\\", "/")
        if not re.fullmatch(r"policy/[A-Za-z0-9_.-]+\.json", rel) or not (project / rel).is_file():
            raise HTTPException(404, f"no policy {path}")
        import nli_label  # the project folder is on sys.path (labels.py)
        try:
            pol = nli_label.Policy.load(str(project / rel))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        out = pol.summary()
        out["topic"] = {"field": pol.topic_field, "mode": pol.topic_mode, "map": pol.topic_map,
                        "subjects": [k for k, lab in pol.labels.items() if lab.level == 1]}
        return out

    @app.get("/api/labels/policies", tags=["labels"])
    def label_policies():
        """policy/*.json files of the project that are policies (for the start form; not the non-English configs)."""
        pol = project / "policy"
        return {"policies": sorted(f"policy/{p.name}" for p in pol.glob("*.json") if not _is_non_english_file(p))
                if pol.is_dir() else []}

    def _is_non_english_file(p: Path) -> bool:
        try:
            d = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return False
        return isinstance(d, dict) and "scripts" in d and "labels" not in d

    # ---- config editors (/label/output: the simple-mode schema; /label/non-english: the non-English config) ------
    CONFIG_KINDS = {"schema": ("output", "the simple-mode schema (output/<name>.json)"),
                    "non_english": ("policy", "the non-English config (policy/<name>.json with \"scripts\")"),
                    "expected_rules": ("labels", "the Expected vs result rules (labels/expected_rules.json)")}

    def _config_file(kind: str, rel: str) -> Path:
        if kind not in CONFIG_KINDS:
            raise HTTPException(404, f"no config kind {kind}")
        folder = CONFIG_KINDS[kind][0]
        rel = (rel or "").replace("\\", "/")
        if kind == "expected_rules" and rel != "labels/expected_rules.json":
            raise HTTPException(400, "the Expected vs result rules are labels/expected_rules.json")
        if not re.fullmatch(rf"{folder}/[A-Za-z0-9_.-]+\.json", rel):
            raise HTTPException(400, f"{CONFIG_KINDS[kind][1]}: {folder}/<name>.json (letters, digits, _ . -)")
        return project / rel

    def _check_config(kind: str, data: Dict[str, Any]) -> Dict[str, Any]:
        errors: List[str] = []
        info: Dict[str, Any] = {}
        try:
            if kind == "expected_rules":
                from .expected_rules import check as check_rules, ACTIONS as RULE_ACTIONS
                errs = check_rules(data)
                if errs:
                    raise ValueError("; ".join(errs))
                info = {"actions": list(RULE_ACTIONS), "profiles": list(data.get("profiles") or {})}
            elif kind == "schema":
                import nli_simple
                sc = nli_simple.Schema(data, "x")
                info = {"file": f"<name>.{sc.kind}.jsonl.zst", "evidence": sc.evidence,
                        "sources": list(nli_simple.SOURCES) + ["input.<field>"],
                        "include_values": list(nli_simple.INCLUDE_VALUES),
                        "evidence_values": list(nli_simple.EVIDENCE_VALUES)}
            else:
                import nli_label
                ne = nli_label.NonEnglish(data, "x")
                info = {"enabled": sorted(ne.ranges), "modes": list(nli_label.NON_ENGLISH_MODES)}
        except ValueError as exc:
            msg = str(exc)
            msg = msg.split(": ", 1)[1] if msg.startswith("x: ") else msg
            errors = [m for m in msg.split("; ") if m]
        return {"ok": not errors, "errors": errors, "info": info}

    @app.get("/api/labels/config/{kind}/files", tags=["labels"])
    def config_files(kind: str):
        if kind not in CONFIG_KINDS:
            raise HTTPException(404, f"no config kind {kind}")
        folder = project / CONFIG_KINDS[kind][0]
        out = []
        for p in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            if kind == "non_english" and not _is_non_english_file(p):
                continue
            if kind == "expected_rules" and p.name != "expected_rules.json":
                continue
            out.append(f"{CONFIG_KINDS[kind][0]}/{p.name}")
        return {"files": out}

    @app.get("/api/labels/expected-rules", tags=["labels"])
    def expected_rules(run: Optional[str] = None):
        """labels/expected_rules.json as the viewer uses it (profiles, aliases, default, a problem if the file is
        refused); with ?run= also that run's n / ok under every profile. Edited through
        /api/labels/config/expected_rules/raw|check|save."""
        out = labels.rules.info()
        if run:
            out["preview"] = labels.expected_profiles(run)
        return out

    @app.get("/api/labels/config/{kind}/raw", tags=["labels"])
    def config_raw(kind: str, path: str):
        f = _config_file(kind, path)
        if not f.is_file():
            raise HTTPException(404, f"no file {path}")
        raw = f.read_bytes()
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except ValueError as exc:
            raise HTTPException(400, f"{path} is not valid JSON: {exc}")
        return {"path": path.replace("\\", "/"), "data": data, "sha": hashlib.sha1(raw).hexdigest(),
                "check": _check_config(kind, data)}

    @app.post("/api/labels/config/{kind}/check", tags=["labels"])
    def config_check(kind: str, body: ConfigBody):
        if kind not in CONFIG_KINDS:
            raise HTTPException(404, f"no config kind {kind}")
        return _check_config(kind, body.data)

    @app.post("/api/labels/config/{kind}/save", tags=["labels"])
    def config_save(kind: str, body: SaveConfigBody, request: Request):
        """Save an edited config (refused when nli_label.py would refuse it, or when the file changed since it was
        loaded). The old file goes to <folder>/.backup/."""
        save_guard(request)
        target = _config_file(kind, body.save_as or body.path)
        if body.save_as:
            if target.exists():
                raise HTTPException(409, f"{body.save_as} exists already: pick another name")
        else:
            if not target.is_file():
                raise HTTPException(404, f"no file {body.path}")
            if body.base_sha and hashlib.sha1(target.read_bytes()).hexdigest() != body.base_sha:
                raise HTTPException(409, f"{body.path} was changed by someone else since you loaded it: reload the page")
        chk = _check_config(kind, body.data)
        if not chk["ok"]:
            raise HTTPException(400, "; ".join(chk["errors"][:12]))
        backup = None
        if target.is_file():
            bdir = target.parent / ".backup"
            bdir.mkdir(exist_ok=True)
            b = bdir / f"{target.stem}.{time.strftime('%Y%m%d-%H%M%S')}.json"
            shutil.copy2(target, b)
            backup = f"{CONFIG_KINDS[kind][0]}/.backup/{b.name}"
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(body.data, ensure_ascii=False, indent=2) + "\n")
        tmp.replace(target)
        return {"path": f"{CONFIG_KINDS[kind][0]}/{target.name}", "sha": hashlib.sha1(target.read_bytes()).hexdigest(),
                "backup": backup}

    @app.post("/api/labels/config/schema/preview", tags=["labels"])
    def schema_preview(body: SchemaPreviewBody):
        """Simple-mode rows built with this (edited) schema from a finished detail run's first lines."""
        chk = _check_config("schema", body.data)
        if not chk["ok"]:
            raise HTTPException(400, "; ".join(chk["errors"][:6]))
        try:
            return labels.schema_preview(body.run, body.data, body.file, max(1, min(body.limit, 200)))
        except (KeyError, ValueError) as exc:
            raise HTTPException(404, str(exc))

    @app.get("/api/labels/simple/{name}/rows", tags=["labels"])
    def simple_rows(name: str, file: str, decision: Optional[str] = None, reason: Optional[str] = None,
                    keyword: Optional[str] = None, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
                    expect: Optional[str] = None, profile: Optional[str] = None):
        """A simple-mode run's rows of one file, filtered by decision / reason / keyword (and expect=wrong / right on a
        corpus with expected results), with the counts."""
        try:
            return labels.simple_rows(name, file, decision, reason, keyword, offset, limit, expect, profile)
        except (KeyError, ValueError) as exc:
            raise HTTPException(404, str(exc))

    @app.get("/api/labels/simple/{name}/line", tags=["labels"])
    def simple_line(name: str, file: str, line: int = Query(..., ge=1), profile: Optional[str] = None):
        """One line of a simple-mode run: its row, the source text with the keywords found in it, the evidence."""
        try:
            return labels.simple_line(name, file, line, profile)
        except (KeyError, ValueError) as exc:
            raise HTTPException(404, str(exc))

    # ---- policy editor (/label/policy): read the JSON as it is, check it like nli_label.py does, save with a backup ----
    def _policy_file(rel: str) -> Path:
        rel = (rel or "").replace("\\", "/")
        if not re.fullmatch(r"policy/[A-Za-z0-9_.-]+\.json", rel):
            raise HTTPException(400, "a policy is policy/<name>.json (letters, digits, _ . -)")
        return project / rel

    def _check_policy(data: Dict[str, Any]) -> Dict[str, Any]:
        """errors = what nli_label.py refuses (the run would not start); warnings = files the policy names that are
        missing (a run would fail later)."""
        import nli_label
        errors: List[str] = []
        summary = None
        try:
            summary = nli_label.Policy(data, "policy_data").summary()
        except ValueError as exc:
            msg = str(exc)
            msg = msg.split(": ", 1)[1] if msg.startswith("policy_data: ") else msg
            errors = [m for m in msg.split("; ") if m]
        warnings: List[str] = []
        files = data.get("keywords_file")
        for f in ([files] if isinstance(files, str) else list(files or [])):
            if not (project / str(f)).is_file():
                warnings.append(f"keywords_file {f} does not exist")
        for k in ("place_names_file", "place_name_exceptions_file", "company_names_file"):
            f = data.get(k)
            if f and not (project / str(f)).is_file():
                warnings.append(f"{k} {f} does not exist")
        return {"ok": not errors, "errors": errors, "warnings": warnings, "summary": summary}

    @app.get("/api/labels/policy/raw", tags=["labels"])
    def label_policy_raw(path: str):
        """A policy file as JSON, for the editor (with its sha: a save is refused if the file changed since)."""
        f = _policy_file(path)
        if not f.is_file():
            raise HTTPException(404, f"no policy {path}")
        raw = f.read_bytes()
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except ValueError as exc:
            raise HTTPException(400, f"{path} is not valid JSON: {exc}")
        return {"path": path.replace("\\", "/"), "data": data, "sha": hashlib.sha1(raw).hexdigest(),
                "check": _check_policy(data)}

    @app.post("/api/labels/policy/check", tags=["labels"])
    def label_policy_check(body: CheckPolicyBody):
        return _check_policy(body.data)

    @app.post("/api/labels/policy/save", tags=["labels"])
    def label_policy_save(body: SavePolicyBody, request: Request):
        """Save an edited policy (to its own file, or to a new policy/<name>.json with save_as). Refused when
        nli_label.py would refuse it, or when the file changed since it was loaded. The old file goes to policy/.backup/."""
        save_guard(request)
        target = _policy_file(body.save_as or body.path)
        if body.save_as:
            if target.exists():
                raise HTTPException(409, f"{body.save_as} exists already: pick another name")
        else:
            if not target.is_file():
                raise HTTPException(404, f"no policy {body.path}")
            if body.base_sha and hashlib.sha1(target.read_bytes()).hexdigest() != body.base_sha:
                raise HTTPException(409, f"{body.path} was changed by someone else since you loaded it: reload the page "
                                         "(your edits are still on the page; copy what you need first)")
        chk = _check_policy(body.data)
        if not chk["ok"]:
            raise HTTPException(400, "; ".join(chk["errors"][:12]) + (f" (and {len(chk['errors']) - 12} more)" if len(chk["errors"]) > 12 else ""))
        backup = None
        if target.is_file():
            bdir = target.parent / ".backup"
            bdir.mkdir(exist_ok=True)
            b = bdir / f"{target.stem}.{time.strftime('%Y%m%d-%H%M%S')}.json"
            shutil.copy2(target, b)
            backup = f"policy/.backup/{b.name}"
        tmp = target.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(body.data, ensure_ascii=False, indent=2) + "\n")
        tmp.replace(target)
        rel = f"policy/{target.name}"
        return {"path": rel, "sha": hashlib.sha1(target.read_bytes()).hexdigest(), "backup": backup,
                "warnings": chk["warnings"]}

    # ---- the Experiment page (/label/lab): a draft of the whole policy, saved only on an explicit confirm ----------
    @app.get("/api/labels/lab/base", tags=["labels"])
    def lab_base(run: Optional[str] = None, file: Optional[str] = None, line: Optional[int] = None,
                 para: Optional[int] = None, policy: Optional[str] = None):
        """Where an experiment starts: the text of a run's line (and the paragraph asked for), the policy that run
        recorded (policy_data; else its policy file, else the Russia-side policy) and the run's settings."""
        out: Dict[str, Any] = {"text": None, "paragraph": None, "problem": None, "settings": {}}
        pol_path = policy
        if run:
            try:
                d = labels.folder(run)
            except (KeyError, ValueError) as exc:
                raise HTTPException(404, str(exc))
            s = json.loads((d / "summary.json").read_text(encoding="utf-8")) if (d / "summary.json").is_file() else {}
            out["settings"] = s.get("settings") or {}
            pol_path = pol_path or ((s.get("policy") or {}).get("path"))
            if s.get("policy_data") and not policy:
                out["policy_data"], out["policy_from"] = s["policy_data"], f"recorded by run {run}"
            if file and line:
                text, problem, src = labels.source_text(d, file, int(line))
                out.update(text=text, problem=problem, source={"run": run, "file": file, "line": line, "input": src})
                e = labels.expected(d, file).get(int(line))
                if e and e.get("expected_action"):   # the line's expected result (a test / benchmark corpus)
                    out["expected"] = {k: e[k] for k in ("expected_action", "acceptable", "note", "clarity",
                                                         "clarity_reason", "gate_expected") if k in e}
                if text and para is not None:
                    row = None
                    try:
                        row = next((r for r in labels._rows(d, file) if r.get("line") == line), None)
                    except KeyError:  # a simple run: the evidence file has the paragraphs, when the schema wrote it
                        ev = labels._simple_file(d, file, "evidence")
                        row = next((r for r in labels._jsonl(ev) if r.get("line") == line), None) if ev else None
                    paras = (row or {}).get("paragraphs") or []
                    if 0 <= para < len(paras):
                        a, b = paras[para]["span"]
                        out["paragraph"] = text[a:b]
        rel = (pol_path or "policy/russia_llm_policy_v2.json").replace("\\", "/")
        m = re.search(r"policy/[A-Za-z0-9_.-]+\.json$", rel)
        rel = m.group(0) if m else "policy/russia_llm_policy_v2.json"
        if not pol_path and not (project / rel).is_file():   # no default policy here: the first one there is
            first = sorted(p for p in (project / "policy").glob("*.json") if not _is_non_english_file(p))
            rel = f"policy/{first[0].name}" if first else rel
        f = project / rel
        if f.is_file():
            raw = f.read_bytes()
            out["policy_path"], out["policy_sha"] = rel, hashlib.sha1(raw).hexdigest()
            if "policy_data" not in out:
                out["policy_data"], out["policy_from"] = json.loads(raw.decode("utf-8-sig")), f"the file {rel}"
            out["file_differs"] = json.loads(raw.decode("utf-8-sig")) != out["policy_data"]
        elif "policy_data" not in out:
            raise HTTPException(404, f"no policy {rel}")
        out["policies"] = sorted(f"policy/{p.name}" for p in (project / "policy").glob("*.json")
                                 if not _is_non_english_file(p))
        return out

    @app.post("/api/labels/lab/check", tags=["labels"])
    def lab_check(body: ConfigBody):
        """The draft checked like nli_label.py checks a policy (errors stop a run; warnings = missing files)."""
        return _check_policy(body.data)

    # ---- the Experiment page's drafts (dataset/lab_drafts/, see lab_drafts.py): kept to be loaded again elsewhere
    from . import lab_drafts as _drafts

    @app.get("/api/labels/lab/drafts", tags=["labels"])
    def lab_drafts_list():
        """Every saved draft (automatic and named), newest first, without policy and texts."""
        return {"drafts": _drafts.listing(project), "folder": str(_drafts.drafts_dir(project)), "max_auto": _drafts.MAX_AUTO}

    @app.get("/api/labels/lab/drafts/{draft_id}", tags=["labels"])
    def lab_drafts_get(draft_id: str):
        return _drafts.get(project, draft_id)

    @app.post("/api/labels/lab/drafts/save", tags=["labels"])
    def lab_drafts_save(body: Dict[str, Any], request: Request):
        """{auto: true, id?} = the page's automatic save; {auto: false, name, overwrite?} = "Save draft as"."""
        save_guard(request)
        return _drafts.save(project, body)

    @app.post("/api/labels/lab/drafts/delete", tags=["labels"])
    def lab_drafts_delete(body: Dict[str, Any], request: Request):
        save_guard(request)
        return _drafts.delete(project, str(body.get("id") or ""))

    @app.post("/api/labels/lab/save", tags=["labels"])
    def lab_save(body: LabSaveBody, request: Request):
        """Save the Experiment page's draft, only on an explicit confirm: save_as = a new policy file (never overwrites);
        replace = overwrite a policy file, only when confirm repeats its file name, with a backup in policy/.backup/,
        refused when the file changed since the page loaded it."""
        save_guard(request)
        if bool(body.save_as) == bool(body.replace):
            raise HTTPException(400, "either save_as (a new file) or replace (with confirm)")
        if body.save_as:
            return label_policy_save(SavePolicyBody(path=body.save_as, data=body.data, save_as=body.save_as), request)
        target = _policy_file(body.replace or "")
        if not body.confirm or body.confirm.strip() != target.name:
            raise HTTPException(400, f"type the file name {target.name} to confirm the replace")
        if not body.base_sha:
            raise HTTPException(400, "base_sha is needed to replace (the version the page loaded)")
        return label_policy_save(SavePolicyBody(path=body.replace, data=body.data, base_sha=body.base_sha), request)

    # ---- documents test sets (/label/docs): labels/*docs*.json with "docs" (multi-paragraph test documents) ------
    DOC_ACTIONS = ("remove", "review", "keep", "pass", "none")

    def _docs_tool():
        import importlib.util
        spec = importlib.util.spec_from_file_location("build_russia_llm_docs", project / "tools" / "build_russia_llm_docs.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _docs_file(rel: str) -> Path:
        rel = (rel or "").replace("\\", "/")
        if not re.fullmatch(r"labels/[A-Za-z0-9_.-]+\.json", rel) or not (project / rel).is_file():
            raise HTTPException(404, f"no documents test set {rel}")
        return project / rel

    def _check_docs(data: Dict[str, Any]) -> Tuple[List[str], Dict[str, Any]]:
        """Problems that stop a save; the cleaned data (document text and expected document action recomputed from
        the paragraphs, as tools/build_russia_llm_docs.py does)."""
        errs: List[str] = []
        docs = data.get("docs")
        if not isinstance(docs, list) or not docs:
            return ["'docs' must be a non-empty list"], data
        corpus = data.get("corpus")
        if not (isinstance(corpus, str) and re.fullmatch(r"test_corpus[A-Za-z0-9_-]*", corpus)):
            errs.append("'corpus' must be a folder name starting with test_corpus (letters, digits, _ -)")
        mod = _docs_tool()
        ids, places = set(), set()
        out_docs = []
        for i, d in enumerate(docs, 1):
            where = f"document {i} ({d.get('id') or '?'})"
            for k in ("id", "group", "file", "title"):
                if not str(d.get(k) or "").strip():
                    errs.append(f"{where}: '{k}' is empty")
            if d.get("id") in ids:
                errs.append(f"{where}: id listed twice")
            ids.add(d.get("id"))
            for k in ("group", "file"):
                if d.get(k) and not re.fullmatch(r"[a-z0-9_]+", str(d[k])):
                    errs.append(f"{where}: '{k}' must be lower-case letters, digits and _")
            if (d.get("group"), d.get("file")) in places:
                errs.append(f"{where}: group/file {d.get('group')}/{d.get('file')} used twice")
            places.add((d.get("group"), d.get("file")))
            paras = d.get("paragraphs") or []
            if not paras:
                errs.append(f"{where}: no paragraphs")
            clean_paras = []
            for k, p in enumerate(paras, 1):
                t = str(p.get("text") or "").strip()
                if not t:
                    errs.append(f"{where}, paragraph {k}: empty text")
                if "\n\n" in t:
                    errs.append(f"{where}, paragraph {k}: a blank line inside (make two paragraphs)")
                if p.get("expected_action") not in DOC_ACTIONS:
                    errs.append(f"{where}, paragraph {k}: expected must be one of {', '.join(DOC_ACTIONS)}")
                acc = [a for a in (p.get("acceptable") or []) if a != p.get("expected_action")]
                if any(a not in DOC_ACTIONS for a in acc):
                    errs.append(f"{where}, paragraph {k}: also-fine actions must be among {', '.join(DOC_ACTIONS)}")
                clean_paras.append({"text": t, "expected_action": p.get("expected_action"), **({"acceptable": acc} if acc else {}),
                                    "note": str(p.get("note") or "")})
            out_docs.append({**{k: v for k, v in d.items() if k not in ("text", "paragraphs", "expected_doc_action")},
                             "text": "\n\n".join(p["text"] for p in clean_paras), "paragraphs": clean_paras,
                             "expected_doc_action": mod.doc_action([p["expected_action"] for p in clean_paras])})
        clean = {**{k: v for k, v in data.items() if k not in ("docs", "file", "sha")}, "docs": out_docs}
        if not errs:
            try:
                mod.check_split(clean)
            except SystemExit as exc:
                errs.append(f"{exc} — each paragraph must be at least {_min_chars(clean)} characters "
                            "(shorter ones are joined to the next one when the document is split)")
        return errs, clean

    def _min_chars(data: Dict[str, Any]) -> int:
        try:
            import nli_label
            return nli_label.Policy.load(str(project / data.get("policy", ""))).min_chars
        except Exception:  # noqa: BLE001
            return 200

    @app.get("/api/labels/docs", tags=["labels"])
    def label_docs_get(file: str = "labels/russia_llm_docs_v1.json"):
        f = _docs_file(file)
        raw = f.read_bytes()
        data = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(data.get("docs"), list):
            raise HTTPException(400, f"{file} is not a documents test set (no \"docs\" list)")
        data["file"] = file.replace("\\", "/")
        data["sha"] = hashlib.sha1(raw).hexdigest()
        data["min_chars"] = _min_chars(data)
        return data

    @app.post("/api/labels/docs/check", tags=["labels"])
    def label_docs_check(body: SaveDocsBody):
        errs, clean = _check_docs(body.data)
        return {"ok": not errs, "errors": errs, "doc_actions": [d.get("expected_doc_action") for d in clean.get("docs", [])]}

    @app.post("/api/labels/docs/save", tags=["labels"])
    def label_docs_save(body: SaveDocsBody, request: Request):
        """Save an edited documents test set (old file in labels/.backup/), then rebuild its corpus in dataset/."""
        save_guard(request)
        f = _docs_file(body.file)
        if body.base_sha and hashlib.sha1(f.read_bytes()).hexdigest() != body.base_sha:
            raise HTTPException(409, f"{body.file} was changed by someone else since you loaded it: reload the page "
                                     "(your edits are still on the page; copy what you need first)")
        errs, clean = _check_docs(body.data)
        if errs:
            raise HTTPException(400, "; ".join(errs[:10]) + (f" (and {len(errs) - 10} more)" if len(errs) > 10 else ""))
        clean.pop("min_chars", None)
        clean["edited"] = time.strftime("%Y-%m-%d %H:%M:%S")
        bdir = f.parent / ".backup"
        bdir.mkdir(exist_ok=True)
        backup = bdir / f"{f.stem}.{time.strftime('%Y%m%d-%H%M%S')}.json"
        shutil.copy2(f, backup)
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(f)
        out = _docs_tool().write_corpus(clean)
        return {"file": body.file, "sha": hashlib.sha1(f.read_bytes()).hexdigest(), "backup": f"labels/.backup/{backup.name}",
                "docs": len(clean["docs"]), "paragraphs": sum(len(d["paragraphs"]) for d in clean["docs"]),
                "corpus": f"dataset/{Path(out).name}"}

    # ---- keyword lists and place-name tables (/label/files): the files a labelling policy uses ----------------
    FILE_KINDS = {"keywords": "keyword list (one per line, optional TAB columns)",
                  "place_names": "place-name table (CSV: from_form,to_form,variants,notes; # = switched off)",
                  "exceptions": "place-name exceptions (one regex per line; case: = case-sensitive)"}

    def _list_file(rel: str) -> Tuple[Path, str]:
        rel = (rel or "").replace("\\", "/")
        m = re.fullmatch(r"(keywords/[A-Za-z0-9_.-]+\.txt)|(policy/place_names[A-Za-z0-9_.-]*\.csv)|"
                         r"(policy/place_name_exceptions[A-Za-z0-9_.-]*\.txt)", rel)
        if not m:
            raise HTTPException(400, "editable here: keywords/<name>.txt, policy/place_names*.csv, policy/place_name_exceptions*.txt")
        kind = "keywords" if m.group(1) else "place_names" if m.group(2) else "exceptions"
        return project / rel, kind

    def _tidy_list(kind: str, text: str) -> Tuple[str, List[str]]:
        """Stray spaces in a keyword list / place-name table / exceptions file: every cell without spaces at its start
        and end, and a run of spaces inside the keyword (first cell) made one. Comment and blank lines, the tabs between
        columns and the inside of other cells (e.g. exclude regexes) stay as they are. Returns (text, notes per line)."""
        import csv
        import io
        notes: List[str] = []
        out_lines = []
        for i, line in enumerate(text.split("\n"), 1):
            end = "\r" if line.endswith("\r") else ""
            body = line[:-1] if end else line
            if not body.strip() or body.lstrip().startswith("#"):
                out_lines.append(line)
                continue
            if kind == "keywords":
                cells = body.split("\t")
            elif kind == "place_names":
                try:
                    cells = next(csv.reader([body]))
                except (csv.Error, StopIteration):
                    out_lines.append(line)
                    continue
            else:
                cells = [body]
            new = [c.strip() for c in cells]
            if new and kind != "exceptions":
                new[0] = re.sub(r" {2,}", " ", new[0])
            if new == cells:
                out_lines.append(line)
                continue
            what = []
            for k, (a, b) in enumerate(zip(cells, new)):
                if a != b:
                    what.append(f"{a!r}" + (" starts with a space" if a[:1].isspace() else
                                            " ends with a space" if a[-1:].isspace() else " has a double space"))
            notes.append(f"line {i}: " + "; ".join(what))
            if kind == "keywords":
                body = "\t".join(new)
            elif kind == "place_names":
                buf = io.StringIO()
                csv.writer(buf, lineterminator="").writerow(new)
                body = buf.getvalue()
            else:
                body = new[0]
            out_lines.append(body + end)
        return "\n".join(out_lines), notes

    def _check_list(kind: str, text: str, sample: Optional[str] = None,
                    other: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Problems that stop a save (the same parsers nli_label.py uses), counts, and a place-name preview."""
        import io
        import tempfile
        errors: List[str] = []
        out: Dict[str, Any] = {"ok": True, "errors": errors}
        tidy_text, tidy_notes = _tidy_list(kind, text)
        if tidy_notes:
            out["spaces"] = {"count": len(tidy_notes), "lines": tidy_notes[:50], "text": tidy_text}
        if kind == "keywords":
            from nli_filter import parse_keywords
            try:
                entries = parse_keywords(io.StringIO(text))
                out["entries"] = len(entries)
                seen, dup = set(), []
                for e in entries:
                    k = e.keyword.lower()
                    if k in seen:
                        dup.append(e.keyword)
                    seen.add(k)
                if dup:
                    out["warnings"] = [f"listed twice: {', '.join(sorted(set(dup))[:10])}"]
            except ValueError as exc:
                errors.append(str(exc))
        elif kind == "exceptions":
            n = 0
            for i, line in enumerate(text.splitlines(), 1):
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                pat = s[5:].strip() if s.lower().startswith("case:") else s
                try:
                    re.compile(pat)
                    n += 1
                except re.error as exc:
                    errors.append(f"line {i}: {exc} in {pat!r}")
            out["entries"] = n
        if kind in ("place_names", "exceptions") and not errors:
            from nli_names import NameRewriter
            with tempfile.TemporaryDirectory() as td:
                t = Path(td) / "t.csv"
                x = Path(td) / "x.txt"
                t.write_text(text if kind == "place_names" else (other or {}).get("table", ""), encoding="utf-8")
                x.write_text(text if kind == "exceptions" else (other or {}).get("exceptions", ""), encoding="utf-8")
                try:
                    rw = NameRewriter.from_files(str(t) if t.read_text(encoding="utf-8").strip() else None, str(x))
                    if kind == "place_names":
                        out["entries"] = len(getattr(rw, "mapping", {}) or {})
                    if sample:
                        new, changes = rw.rewrite(sample)
                        out["preview"] = {"text": new, "changes": changes}
                except (ValueError, KeyError, csv.Error) as exc:
                    errors.append(str(exc))
        out["ok"] = not errors
        return out

    def _policy_files(pol_path: Optional[str]) -> Dict[str, str]:
        """Which list files a policy uses (keywords_file, place_names_file, place_name_exceptions_file)."""
        if not pol_path:
            return {}
        try:
            data = json.loads(_policy_file(pol_path).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, HTTPException):
            return {}
        used: Dict[str, str] = {}
        kw = data.get("keywords_file")
        for f in ([kw] if isinstance(kw, str) else list(kw or [])):
            used[str(f).replace("\\", "/")] = "keywords_file"
        for k in ("place_names_file", "place_name_exceptions_file"):
            if data.get(k):
                used[str(data[k]).replace("\\", "/")] = k
        return used

    @app.get("/api/labels/files", tags=["labels"])
    def label_files(policy: Optional[str] = None):
        """The keyword lists and place-name files of the project; those the given policy uses are marked."""
        used = _policy_files(policy)
        files = []
        for pat in ("keywords/*.txt", "policy/place_names*.csv", "policy/place_name_exceptions*.txt"):
            for f in sorted(project.glob(pat)):
                rel = f.relative_to(project).as_posix()
                files.append({"path": rel, "kind": _list_file(rel)[1], "used_by_policy": used.get(rel)})
        return {"files": files, "kinds": FILE_KINDS, "policy": policy}

    @app.get("/api/labels/files/raw", tags=["labels"])
    def label_file_raw(path: str):
        f, kind = _list_file(path)
        if not f.is_file():
            raise HTTPException(404, f"no file {path}")
        raw = f.read_bytes()
        text = raw.decode("utf-8-sig")
        return {"path": path.replace("\\", "/"), "kind": kind, "text": text.replace("\r\n", "\n"),
                "crlf": "\r\n" in text, "sha": hashlib.sha1(raw).hexdigest(), "check": _check_list(kind, text)}

    @app.post("/api/labels/files/check", tags=["labels"])
    def label_file_check(body: ListFileBody):
        _f, kind = _list_file(body.path)
        other = {}
        if body.policy and kind in ("place_names", "exceptions"):  # the preview uses the policy's other file
            used = {v: k for k, v in _policy_files(body.policy).items()}
            want = "place_name_exceptions_file" if kind == "place_names" else "place_names_file"
            if want in used and (project / used[want]).is_file():
                other["exceptions" if kind == "place_names" else "table"] = (project / used[want]).read_text(encoding="utf-8-sig")
        return _check_list(kind, body.text, body.sample, other)

    @app.post("/api/labels/files/save", tags=["labels"])
    def label_file_save(body: ListFileBody, request: Request):
        """Save a keyword list / place-name file; the old one goes to <folder>/.backup/; refused when it changed
        since it was loaded or when nli_label.py could not read it."""
        save_guard(request)
        f, kind = _list_file(body.path)
        if not f.is_file():
            raise HTTPException(404, f"no file {body.path}")
        raw = f.read_bytes()
        if body.base_sha and hashlib.sha1(raw).hexdigest() != body.base_sha:
            raise HTTPException(409, f"{body.path} was changed by someone else since you loaded it: reload the page "
                                     "(your edits are still on the page; copy what you need first)")
        text_in, trimmed = _tidy_list(kind, body.text.replace("\r\n", "\n"))
        chk = _check_list(kind, text_in)
        if not chk["ok"]:
            raise HTTPException(400, "; ".join(chk["errors"][:8]))
        bdir = f.parent / ".backup"
        bdir.mkdir(exist_ok=True)
        b = bdir / f"{f.stem}.{time.strftime('%Y%m%d-%H%M%S')}{f.suffix}"
        shutil.copy2(f, b)
        text = text_in
        if not text.endswith("\n"):
            text += "\n"
        crlf = b"\r\n" in raw
        tmp = f.with_suffix(f.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8", newline="\r\n" if crlf else "\n") as fh:
            fh.write(text)
        tmp.replace(f)
        return {"path": body.path, "sha": hashlib.sha1(f.read_bytes()).hexdigest(),
                "backup": b.relative_to(project).as_posix(), "check": chk, "trimmed": len(trimmed),
                **({"trimmed_lines": trimmed[:50]} if trimmed else {})}

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
        corpora: Dict[str, str] = {}  # case file -> the dataset/ corpus folder built from it (to open a run's case)
        for f in files:
            try:
                c = json.loads(f.read_text(encoding="utf-8")).get("corpus")
            except Exception:  # noqa: BLE001 - a broken file just has no corpus
                c = None
            if not c and main and f == main[-1]:
                c = "test_corpus_cases"
            if c:
                corpora[f"labels/{f.name}"] = str(c)
        return {"files": [f"labels/{f.name}" for f in files], "corpora": corpora,
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

    @app.post("/api/labels/cache/clear", tags=["labels"])
    def label_cache_clear(request: Request):
        """The Experiment page's "Clear score cache": the model service forgets every scored pair, so the next run
        scores everything with the models again."""
        save_guard(request)
        return pg.clear_cache()

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
        if body.decision_unit:
            if body.decision_unit not in ("paragraph", "line"):
                raise HTTPException(400, "decision_unit must be paragraph or line")
            req["decision_unit"] = body.decision_unit
        if body.review_as:
            req["review_as"] = body.review_as
        if body.reuse_scores:
            req["reuse_scores"] = True
        if body.uncertain_band and len(body.uncertain_band) == 2:
            req["uncertain_band"] = list(body.uncertain_band)
        if body.policy_data is not None:
            req["policy_data"] = body.policy_data
        else:
            req["policy"] = body.policy or "policy/russia_llm_policy_v2.json"  # the Russia-side policy
        return pg.label(req)

    @app.get("/api/labels/compare", tags=["labels"])
    def label_compare(a: str, b: str, change: Optional[str] = None, offset: int = Query(0, ge=0),
                      limit: int = Query(100, ge=1, le=500)):
        """Two runs of the same corpus side by side: totals, which actions moved (old>new), the changed lines."""
        try:
            return labels.compare(a, b, change, offset, limit)
        except (KeyError, ValueError) as exc:
            raise HTTPException(404, str(exc))

    @app.post("/api/labels/{name}/redecide", tags=["labels"])
    def label_redecide(name: str, body: RedecideBody, request: Request):
        """Start 'nli_label.py redecide' on a run with another policy (no models: the stored scores are reused; a
        reworded hypothesis counts as not scored). Runs through the model service's job runner, like Start a run."""
        save_guard(request)
        try:
            src = labels.folder(name)
        except (KeyError, ValueError) as exc:
            raise HTTPException(404, str(exc))
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,120}", body.output_dir or ""):
            raise HTTPException(400, "output folder: a name (letters, digits, _ . -), created in the dataset folder")
        out = project / "dataset" / body.output_dir
        if out.exists() and any(out.iterdir()):
            raise HTTPException(409, f"{body.output_dir} exists already: choose another name")
        if body.policy_data is not None:
            chk = _check_policy(body.policy_data)
            if not chk["ok"]:
                raise HTTPException(400, "the edited policy has problems: " + "; ".join(chk["errors"][:6]))
            drafts = project / "dataset" / ".policy_drafts"
            drafts.mkdir(parents=True, exist_ok=True)
            pfile = drafts / f"{body.output_dir}.json"
            pfile.write_text(json.dumps(body.policy_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            policy = f"dataset/.policy_drafts/{pfile.name}"
        else:
            policy = _policy_arg(body.policy or "")
        args = ["redecide", str(src.resolve()), "--policy", policy, "--output-dir", str(out.resolve())]
        if body.write_clean:
            args.append("--write-clean")
        if body.review_as:
            if body.review_as not in ("keep", "remove"):
                raise HTTPException(400, "review_as must be keep or remove")
            args += ["--review-as", body.review_as]
        if body.max_removed_share is not None:
            if not 0 <= body.max_removed_share <= 1:
                raise HTTPException(400, "max_removed_share must be between 0 (off) and 1")
            args += ["--max-removed-share", format(body.max_removed_share, "g")]
        if body.drop_if_first_cut is not None:
            args.append("--drop-if-first-cut" if body.drop_if_first_cut else "--no-drop-if-first-cut")
        job = pg.start_job(args, {}, f"labels: redecide {name} -> {body.output_dir}", script="nli_label.py")
        return {"job": job, "run": body.output_dir, "policy": policy}

    @app.get("/api/labels/{name}", tags=["labels"])
    def label_run(name: str):
        return labels.run(name)

    @app.get("/api/labels/{name}/docs", tags=["labels"])
    def label_docs(name: str, file: str, action: Optional[str] = None, label: Optional[str] = None,
                   para_action: Optional[str] = None, gated: bool = True,
                   offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
                   expect: Optional[str] = None, profile: Optional[str] = None, clarity: Optional[str] = None):
        """Documents of one file of a run, filtered by document action, label or paragraph action; for a test corpus
        with expected results, each row has "expect" (expected vs got) and expect=wrong / right filters them;
        clarity=clear / hard / ambiguous keeps the lines with that benchmark tag."""
        return labels.docs(name, file, action, label, para_action, gated, offset, limit, expect, profile, clarity)

    @app.get("/api/labels/{name}/nav", tags=["labels"])
    def label_nav(name: str, file: str, line: int = Query(..., ge=1), crit: str = "all", dir: str = "none"):
        """Prev / Next through a run's lines (the Experiment page): crit = comma-separated all, remove, review, keep,
        pass, wrong:<profile> (any matches); dir = next, prev or none (only the position)."""
        if dir not in ("next", "prev", "none"):
            raise HTTPException(400, "dir is next, prev or none")
        cs = [c.strip() for c in crit.split(",") if c.strip()]
        try:
            return labels.nav(name, file, line, cs, dir)
        except (KeyError, ValueError) as exc:
            raise HTTPException(404, str(exc))

    @app.get("/api/labels/{name}/expected", tags=["labels"])
    def label_expected(name: str, profile: Optional[str] = None):
        """For a run on a test corpus with expected results: how many lines match, and the ones that do not (detail
        and simple runs; profile = a profile of labels/expected_rules.json, else its default)."""
        return {"expected": labels.expected_summary(name, profile)}

    @app.get("/api/labels/{name}/doc", tags=["labels"])
    def label_doc(name: str, file: str, line: int = Query(..., ge=1), profile: Optional[str] = None):
        """One document: its labels row (paragraphs, scores, actions), the source text and the policy."""
        return labels.doc(name, file, line, profile)

    # ---- the "Start a run" form: what it can offer, and "Run this test set" ------------------------------------
    def _test_set_tool():
        import importlib.util
        spec = importlib.util.spec_from_file_location("label_test_set", project / "tools" / "label_test_set.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _test_sets() -> List[Dict[str, Any]]:
        """labels/*.json that are test sets with their own corpus ("cases" or "docs" + "corpus"): the Russia-side ones."""
        out = []
        lab = project / "labels"
        for f in sorted(lab.glob("*.json")) if lab.is_dir() else []:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict) or not data.get("corpus"):
                continue
            kind = "docs" if isinstance(data.get("docs"), list) else "cases" if isinstance(data.get("cases"), list) else None
            if not kind:
                continue
            stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", f.stem)
            out.append({"file": f"labels/{f.name}", "kind": kind, "items": len(data[kind]), "corpus": f"dataset/{data['corpus']}",
                        "policy": data.get("policy"), "output": f"out_label_{stem}", "about": str(data.get("about") or "")[:200]})
        return out

    @app.get("/api/labels/forms/run", tags=["labels"])
    def label_run_form():
        """For the Start-a-run form: corpus folders in dataset/ (not run folders), the test sets, the policies."""
        corpora = []
        dsd = project / "dataset"
        from nli_formats import INPUT_SUFFIXES
        for d in sorted(dsd.iterdir()) if dsd.is_dir() else []:
            if d.name.startswith(".") or labels.is_run_folder(d) or (d / "kwstats.json").is_file():
                continue
            if d.is_dir():
                n = sum(1 for q in d.rglob("*") if q.is_file() and q.name.lower().endswith(INPUT_SUFFIXES)
                        and ".labels." not in q.name and ".clean." not in q.name and ".rewrites." not in q.name)
                if n:
                    corpora.append({"path": f"dataset/{d.name}", "files": n})
            elif d.name.lower().endswith(INPUT_SUFFIXES) and not d.name.lower().endswith(".manifest.json"):
                corpora.append({"path": f"dataset/{d.name}", "files": 1})
        pol = project / "policy"
        return {"corpora": corpora, "test_sets": _test_sets(),
                "policies": sorted(f"policy/{p.name}" for p in pol.glob("*.json")) if pol.is_dir() else []}

    @app.post("/api/labels/test-sets/run", tags=["labels"])
    def label_test_set_run(body: TestSetRunBody, request: Request):
        """Run a test set from its JSON file (what tools/label_test_set.py does): rebuild its corpus in dataset/,
        then 'nli_label.py run <corpus> --policy <its policy> --output-dir dataset/<out> --overwrite --write-clean'."""
        save_guard(request)
        ts = next((t for t in _test_sets() if t["file"] == body.file.replace("\\", "/")), None)
        if ts is None:
            raise HTTPException(404, f"no test set {body.file} (labels/<name>.json with \"corpus\" and cases or docs)")
        name = body.output_dir or ts["output"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,120}", name):
            raise HTTPException(400, "output folder: a name (letters, digits, _ . -), created in the dataset folder")
        policy = _policy_arg(body.policy or ts["policy"] or "")
        src = project / ts["file"]
        tool = _test_set_tool()
        try:
            corpus, kind = tool.build_corpus(src, json.loads(src.read_text(encoding="utf-8")))
        except SystemExit as exc:  # the builders stop with a message
            raise HTTPException(400, str(exc))
        out = (project / "dataset" / name).resolve()
        args = ["run", str(Path(corpus).resolve()), "--policy", policy, "--output-dir", str(out), "--overwrite", "--write-clean"]
        if not body.use_judge:
            args += ["--judge-model", "none"]
        job = pg.start_job(args, {}, f"labels: test set {ts['file']} -> {name}", script="nli_label.py")
        return {"job": job, "run": name, "corpus": ts["corpus"], "kind": kind}

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

"""
discover.py - dynamic datasets: find the run folders (nli_filter.py and nli_label.py outputs) in a folder such as
the project's dataset/, work out which corpus each one was made from, and pick the most recent run per corpus.

Each run records its input files in summary.json, so the pairing does not depend on folder names:
    dataset/out_label_ru_v2_judge  ->  input dataset/test_corpus_cases_ru/...  ->  corpus dataset/test_corpus_cases_ru

viewer_config.json:   "auto_datasets": "../dataset"
Report (which run folders are in use, older, broken):   python -m nli_viewer runs --config ../viewer_config.json
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# status of a run folder
IN_USE = "in use"            # the most recent finished run of its kind for its corpus: shown by the viewer
OLDER = "older run"          # a newer run of the same kind exists for the same corpus
RUNNING = "running"          # progress.json says running (not touched)
NO_CORPUS = "corpus missing"  # the input it was made from is gone
SINGLE_FILE = "single-file input"  # made from one file, not a corpus folder (not shown as a dataset)
SERVER = "server input"      # made from a server corpus (ftp:// sftp:// s3:// ...): not paired automatically
BROKEN = "no summary"        # unfinished or broken: no summary.json
UNKNOWN = "input unknown"    # summary.json without an input path


@dataclass
class RunFolder:
    path: Path
    kind: str                    # "filter" (nli_filter.py) | "label" (nli_label.py) | "?"
    finished: str = ""           # "YYYY-mm-dd HH:MM:SS" (or the folder's time when the summary has none)
    input: str = ""              # the first input file as recorded
    corpus: Optional[Path] = None
    status: str = UNKNOWN
    reason: str = ""
    newer: Optional[str] = None  # the run that replaces it (status OLDER)
    extra: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self, root: Path) -> Dict[str, Any]:
        def rel(p: Optional[Path]) -> Optional[str]:
            if p is None:
                return None
            try:
                return str(p.relative_to(root)).replace("\\", "/")
            except ValueError:
                return str(p)
        return {"folder": rel(self.path), "kind": self.kind, "finished": self.finished, "input": self.input,
                "corpus": rel(self.corpus), "status": self.status, "reason": self.reason, "newer": self.newer}


def _read_json(p: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _first_input(summary: Dict[str, Any], folder: Path) -> str:
    for f in summary.get("files") or []:
        if isinstance(f, dict) and f.get("input"):
            return str(f["input"])
    for sp in sorted(folder.glob("*.summary.json")):  # per-file summaries (nli_label.py, nli_filter.py)
        if sp.name.startswith("summary."):
            continue
        d = _read_json(sp) or {}
        if d.get("input"):
            return str(d["input"])
    return ""


def _corpus_of(inp: str, project: Path, scan_dir: Path) -> (Optional[Path], str, str):
    """(corpus folder, status, reason) for a recorded input path."""
    if "://" in inp:
        return None, SERVER, "made from a server corpus: add it to viewer_config.json by hand"
    p = inp.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    path = Path(p)
    if path.is_absolute():
        try:
            path = path.resolve().relative_to(project.resolve())
            p = str(path).replace("\\", "/")
        except (ValueError, OSError):
            top = Path(*path.parts[:2]) if len(path.parts) > 1 else path
            return None, SINGLE_FILE, f"input outside the project folder ({top})"
    parts = [x for x in p.split("/") if x]
    if not parts:
        return None, UNKNOWN, "no input recorded"
    scan_name = scan_dir.name
    if parts[0] == scan_name and len(parts) > 2:            # dataset/<corpus>/...
        cand = scan_dir / parts[1]
    elif len(parts) > 1 and (scan_dir / parts[0]).is_dir():  # <corpus>/... made before the corpus moved into dataset/
        cand = scan_dir / parts[0]
    elif len(parts) > 1:                                     # another folder of the project (corpus_olmo/...)
        cand = project / parts[0]
    else:
        return None, SINGLE_FILE, f"made from the single file {parts[0]} (not a corpus folder)"
    if not cand.is_dir():
        return cand, NO_CORPUS, f"the corpus {cand.name} is not there any more"
    return cand, "", ""


def scan(project: Path, scan_dir: Path) -> List[RunFolder]:
    """Every out* run folder in scan_dir with its corpus and status; the most recent per (corpus, kind) is IN_USE."""
    project, scan_dir = Path(project), Path(scan_dir)
    runs: List[RunFolder] = []
    if not scan_dir.is_dir():
        return runs
    for d in sorted(scan_dir.iterdir()):
        if not d.is_dir() or not d.name.startswith("out"):
            continue
        s = _read_json(d / "summary.json")
        prog = _read_json(d / "progress.json") or next(
            (_read_json(p) for p in sorted(d.glob("progress.shard*.json"))), None)
        if s is None:
            r = RunFolder(d, "label" if prog and str(prog.get("command", "")).startswith("nli_label") else "?")
            if prog and prog.get("state") == "running":
                r.status, r.reason = RUNNING, "progress.json says running"
            else:
                r.status, r.reason = BROKEN, "no summary.json: unfinished, stopped or broken"
            runs.append(r)
            continue
        kind = "label" if "policy" in s else "filter"
        finished = str(s.get("finished") or "")
        if not finished:
            try:
                finished = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime((d / "summary.json").stat().st_mtime))
            except OSError:
                finished = ""
        r = RunFolder(d, kind, finished, _first_input(s, d))
        if prog and prog.get("state") == "running":
            r.status, r.reason = RUNNING, "progress.json says running"
        elif not r.input:
            r.status, r.reason = UNKNOWN, "summary.json records no input"
        else:
            r.corpus, st, why = _corpus_of(r.input, project, scan_dir)
            r.status, r.reason = (st, why) if st else ("", "")
        runs.append(r)
    best: Dict[tuple, RunFolder] = {}
    for r in runs:
        if r.status == "" and r.corpus is not None:
            key = (str(r.corpus.resolve()), r.kind)
            if key not in best or r.finished > best[key].finished:
                best[key] = r
    for r in runs:
        if r.status != "":
            continue
        top = best[(str(r.corpus.resolve()), r.kind)]
        if top is r:
            r.status, r.reason = IN_USE, f"the most recent {r.kind} run for {r.corpus.name}"
        else:
            r.status, r.reason, r.newer = OLDER, f"{top.path.name} is newer ({top.finished})", top.path.name
    return runs


def auto_datasets(runs: List[RunFolder], taken: Dict[str, tuple]) -> List[Dict[str, Any]]:
    """Dataset entries for the IN_USE runs. taken = {name: (corpus, output)} of the configured datasets (resolved):
    a configured pair is not added twice, and a configured name is never reused."""
    pairs = {v for v in taken.values()}
    out = []
    for r in runs:
        if r.status != IN_USE:
            continue
        corpus, output = str(r.corpus.resolve()), str(r.path.resolve())
        if (corpus, output) in pairs:
            continue
        name = r.corpus.name + ("-labels" if r.kind == "label" else "")
        if name in taken:
            name = "auto-" + name
        tool = "nli_label.py" if r.kind == "label" else "nli_filter.py"
        out.append({"name": name, "corpus": corpus, "output": output, "auto": True,
                    "title": f"{r.corpus.name} · {r.path.name}",
                    "description": f"Found automatically: the most recent {tool} run on {r.corpus.name} "
                                   f"(finished {r.finished})."})
    return out


INVALID = (NO_CORPUS, BROKEN, UNKNOWN)     # no matching corpus / no longer valid
UNUSED = (OLDER, SINGLE_FILE, SERVER)      # valid, but not what the viewer shows


def removal_commands(runs: List[RunFolder], root: Path, statuses=INVALID) -> List[str]:
    """PowerShell lines to remove the folders with these statuses (for the user to run by hand)."""
    lines = []
    for r in runs:
        if r.status not in statuses:
            continue
        try:
            rel = str(r.path.relative_to(root))
        except ValueError:
            rel = str(r.path)
        lines.append(f"Remove-Item -Recurse -Force '{rel}'   # {r.status}: {r.reason}")
    return lines


def report(runs: List[RunFolder], root: Path) -> str:
    order = [IN_USE, RUNNING, OLDER, NO_CORPUS, SINGLE_FILE, SERVER, BROKEN, UNKNOWN]
    L = [f"{'folder':<34} {'kind':<7} {'finished':<20} {'status':<18} reason"]
    for r in sorted(runs, key=lambda x: (order.index(x.status) if x.status in order else 99, x.path.name)):
        L.append(f"{r.path.name:<34} {r.kind:<7} {r.finished[:19]:<20} {r.status:<18} {r.reason}")
    bad = removal_commands(runs, root, INVALID)
    old = removal_commands(runs, root, UNUSED)
    L += ["", "Nothing is deleted by the viewer. Check the lists, then run the lines you want in the project folder."]
    L += ["", "No matching corpus or no longer valid (safe to remove):"] + (bad or ["  (none)"])
    L += ["", "Still valid but not shown (older runs, single-file or server input): remove only if you no longer "
              "need them (some are cited in cmds/design reports):"] + (old or ["  (none)"])
    return "\n".join(L)

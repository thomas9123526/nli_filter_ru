"""
smoke_test.py - a short end-to-end check of nli_filter.py and the result viewer on THIS machine (CPU, one GPU or
many), on a few labelled lines. Writes smoke_<machine>_<date>.json and prints a PASS / WARN / FAIL table.

    python smoke_test.py                 # everything this machine can do (about 5-10 min on a CPU, less on a GPU)
    python smoke_test.py --lines 20      # fewer lines: faster
    python smoke_test.py --skip-models-check --skip-viewer
    python smoke_test.py --keep          # keep the temporary folder (inputs, outputs, logs) to look at

What it does, in a temporary folder (your corpus and outputs are not touched):
  1. environment: Python, torch (+ CUDA build), GPUs, packages
  2. models: nli_models.py --check all (the three models load and score two easy pairs right)
  3. reference run on the CPU (--mode single) of N lines of test_russia.jsonl (they have "expect" labels)
  4. the same lines on this machine's other set-ups: CPU threads / processes, one GPU, all GPUs (thread, process)
     -> every run must give the same decisions as the reference (GPUs use bfloat16: a flip is only a WARN when
        the score is near a threshold)
  5. two --shard copies at the same time on .zst files with --write-split, then --report
  6. the viewer backend (no browser) on the shard results: datasets, files, a record, progress, an edit + undo
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
NEAR = 0.05  # a decision flip between CPU (fp32) and GPU (bf16) is only a WARN when a score is this close to 0.8
THRESHOLD = 0.8

results: List[Dict[str, Any]] = []


def step(name: str, fn: Callable[[], Tuple[str, str, Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """Run one check: fn returns (PASS | WARN | FAIL | SKIP, one-line detail, data)."""
    print(f"... {name}", flush=True)
    t0 = time.perf_counter()
    try:
        status, detail, data = fn()
    except Exception as exc:  # noqa: BLE001  (a failed check, reported)
        status, detail, data = "FAIL", f"{type(exc).__name__}: {exc}", {"traceback": traceback.format_exc()}
    r = {"name": name, "status": status, "seconds": round(time.perf_counter() - t0, 1), "detail": detail, **data}
    results.append(r)
    print(f"    {status}  {detail}  ({r['seconds']} s)", flush=True)
    return r


# ---- environment -------------------------------------------------------------------------------------------

def environment() -> Tuple[str, str, Dict[str, Any]]:
    import importlib.metadata as md
    info: Dict[str, Any] = {"python": platform.python_version(), "platform": platform.platform(),
                            "machine": socket.gethostname(), "cpu_count": os.cpu_count(), "packages": {}}
    for name in ("torch", "transformers", "tokenizers", "zstandard", "orjson", "pyahocorasick", "sentencepiece",
                 "pyarrow", "fastapi", "uvicorn", "httpx", "paramiko", "boto3"):
        try:
            info["packages"][name] = md.version(name)
        except md.PackageNotFoundError:
            info["packages"][name] = None
    missing = [n for n in ("torch", "transformers", "tokenizers", "zstandard") if not info["packages"][n]]
    gpus: List[str] = []
    try:
        import torch
        info["torch_cuda_build"] = torch.version.cuda
        if torch.cuda.is_available():
            gpus = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
            info["gpu_capability"] = [list(torch.cuda.get_device_capability(i)) for i in range(len(gpus))]
            info["bf16"] = bool(torch.cuda.is_bf16_supported())
    except Exception as exc:  # noqa: BLE001
        info["torch_error"] = str(exc)
    info["gpus"] = gpus
    if missing:
        return "FAIL", "missing packages: " + ", ".join(missing), info
    where = f"{len(gpus)} GPU(s): {', '.join(sorted(set(gpus)))}" if gpus else "no GPU (CPU only)"
    return "PASS", f"Python {info['python']}, torch {info['packages']['torch']} (CUDA {info.get('torch_cuda_build')}), {where}", info


# ---- running nli_filter.py ---------------------------------------------------------------------------------

def run_py(args: List[str], log: Path, timeout: float) -> Tuple[int, float]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    t0 = time.perf_counter()
    with open(log, "w", encoding="utf-8") as fh:
        p = subprocess.run([sys.executable, *args], cwd=str(HERE), stdout=fh, stderr=subprocess.STDOUT, env=env,
                           timeout=timeout)
    return p.returncode, time.perf_counter() - t0


def tail(log: Path, n: int = 15) -> str:
    try:
        return "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except OSError:
        return ""


def read_decisions(out: Path) -> Dict[str, Dict[str, Any]]:
    """id -> decision record, from every *.decisions.jsonl[.zst|.gz] under out."""
    import gzip
    rows: Dict[str, Dict[str, Any]] = {}
    for p in sorted(out.rglob("*.decisions.jsonl*")):
        if p.name.endswith(".zst"):
            import zstandard
            with open(p, "rb") as fh:
                data = zstandard.ZstdDecompressor().stream_reader(fh).read()
        elif p.name.endswith(".gz"):
            data = gzip.decompress(p.read_bytes())
        else:
            data = p.read_bytes()
        for raw in data.decode("utf-8").splitlines():
            if raw.strip():
                d = json.loads(raw)
                rows[str(d.get("id"))] = d
    return rows


def scores_of(d: Dict[str, Any]) -> List[float]:
    out = []
    c1 = d.get("check1") or {}
    if isinstance(c1.get("score"), (int, float)):
        out.append(float(c1["score"]))
    for h in d.get("hits") or []:
        c2 = h.get("check2") or {}
        if isinstance(c2.get("score"), (int, float)):
            out.append(float(c2["score"]))
    return out


def compare(ref: Dict[str, Dict[str, Any]], got: Dict[str, Dict[str, Any]]) -> Tuple[str, str, Dict[str, Any]]:
    """Decisions of a run vs the reference: same ids, same decisions (flips near a threshold: WARN)."""
    missing = sorted(set(ref) - set(got))
    flips, near = [], []
    max_diff = 0.0
    for k, r in ref.items():
        g = got.get(k)
        if g is None:
            continue
        a, b = scores_of(r), scores_of(g)
        if len(a) == len(b):
            max_diff = max([max_diff] + [abs(x - y) for x, y in zip(a, b)])
        if r.get("decision") != g.get("decision"):
            item = {"id": k, "ref": r.get("decision"), "got": g.get("decision"), "ref_scores": a, "got_scores": b}
            (near if any(abs(s - THRESHOLD) <= NEAR for s in a + b) else flips).append(item)
    data = {"lines": len(got), "missing": missing[:20], "flips": flips[:20], "near_threshold_flips": near[:20],
            "max_score_diff": round(max_diff, 4)}
    if missing or flips:
        return "FAIL", f"{len(missing)} line(s) missing, {len(flips)} decision(s) differ from the CPU reference", data
    if near:
        return "WARN", f"{len(near)} decision(s) flip near the threshold (score within {NEAR}); max score diff {max_diff:.3f}", data
    return "PASS", f"same decisions as the CPU reference for {len(got)} lines; max score diff {max_diff:.4f}", data


def summary_of(out: Path, name: str = "summary.json") -> Dict[str, Any]:
    p = out / name
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def run_filter(tag: str, inputs: List[str], out: Path, opts: List[str], logs: Path, timeout: float,
               ref: Optional[Dict[str, Dict[str, Any]]]) -> Tuple[str, str, Dict[str, Any]]:
    log = logs / f"{tag}.log"
    code, secs = run_py(["nli_filter.py", *inputs, "--output-dir", str(out), *opts], log, timeout)
    if code != 0:
        return "FAIL", f"nli_filter.py exit {code}; see {log}", {"log_tail": tail(log)}
    got = read_decisions(out)
    s = summary_of(out)
    ev = ((s.get("stats") or {}).get("eval") or {}).get("metrics") or {}
    data = {"options": opts, "wall_seconds": round(secs, 1), "timing": s.get("timing"),
            "accuracy": ev.get("accuracy"), "models": {k: {x: v.get(x) for x in ("model", "devices", "mode", "dtype")}
                                                       for k, v in (s.get("models") or {}).items() if isinstance(v, dict)}}
    speed = (s.get("timing") or {}).get("lines_per_second")
    acc = f", accuracy {ev['accuracy']:.2f}" if ev.get("accuracy") is not None else ""
    if ref is None:
        return "PASS", f"{len(got)} lines, {speed} lines/s{acc}", {**data, "decisions": len(got)}
    status, detail, cmp = compare(ref, got)
    return status, f"{detail}; {speed} lines/s{acc}", {**data, **cmp}


# ---- inputs ------------------------------------------------------------------------------------------------

def make_inputs(tmp: Path, n: int) -> Tuple[Path, Path, int]:
    """N lines spread over test_russia.jsonl (a mix of filter / keep) as one .jsonl, and as 4 .zst files."""
    import zstandard
    lines = [x for x in (HERE / "test_russia.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    step_ = max(1, len(lines) // max(1, n))
    picked = lines[::step_][:n]
    data = tmp / "data"
    (data / "zst").mkdir(parents=True, exist_ok=True)
    jsonl = data / "sample.jsonl"
    jsonl.write_text("\n".join(picked) + "\n", encoding="utf-8")
    parts = [picked[i::4] for i in range(4)]
    for i, part in enumerate(parts):
        raw = ("\n".join(part) + "\n").encode("utf-8")
        (data / "zst" / f"part-{i}.jsonl.zst").write_bytes(zstandard.ZstdCompressor().compress(raw))
    return jsonl, data / "zst", len(picked)


# ---- viewer ------------------------------------------------------------------------------------------------

def viewer_check(corpus: Path, out: Path, tmp: Path, n_lines: int) -> Tuple[str, str, Dict[str, Any]]:
    try:
        import fastapi  # noqa: F401
        import httpx  # noqa: F401
    except ImportError as exc:
        return "SKIP", f"viewer packages not installed here ({exc.name}); install viewer/backend/requirements.txt", {}
    sys.path.insert(0, str(HERE / "viewer" / "backend"))
    from fastapi.testclient import TestClient
    from nli_viewer.api import EDIT_HEADER, create_app
    from nli_viewer.config import DatasetConfig, ViewerConfig

    cfg = ViewerConfig(datasets=[DatasetConfig(name="smoke", corpus=str(corpus), output=str(out), editable=True)],
                       cache_dir=str(tmp / "viewer_cache"), edits_dir=str(tmp / "viewer_edits"),
                       frontend_dir=str(tmp / "nofrontend"), base_dir=str(tmp), project_dir=str(tmp / "project"))
    problems: List[str] = []
    data: Dict[str, Any] = {}
    with TestClient(create_app(cfg), client=("127.0.0.1", 50000)) as c:
        names = [d["name"] for d in c.get("/api/datasets").json()["datasets"]]
        if "smoke" not in names:
            problems.append(f"dataset list: {names}")
        files = c.get("/api/datasets/smoke/files").json()["files"]
        data["files"] = len(files)
        if len(files) != 4 or sum(f["lines"] for f in files) != n_lines:
            problems.append(f"files: {len(files)} files, {sum(f['lines'] for f in files)} lines (want 4, {n_lines})")
        if any(not f["corpus_path"] for f in files):
            problems.append("a result file is not linked to its corpus file")
        key = files[0]["key"] if files else ""
        rec = c.get("/api/datasets/smoke/record", params={"file": key, "row": 1})
        if rec.status_code != 200 or not rec.json()["original"].get("available"):
            problems.append(f"record page: HTTP {rec.status_code}")
        else:
            data["record_decision"] = rec.json()["decision"]["decision"]
        prog = c.get("/api/datasets/smoke/progress").json()
        data["progress_runs"] = [(r.get("state"), r.get("shard")) for r in prog.get("runs", [])]
        if len(prog.get("runs", [])) != 2 or any(r.get("state") != "done" for r in prog["runs"]):
            problems.append(f"progress files: {data['progress_runs']} (want 2 x done)")
        # review tools: keyword stats, lines across files (review order), a golden-set label (outside the corpus)
        import time as _time
        kw = {}
        for _ in range(100):
            kw = c.get("/api/datasets/smoke/keywords").json()
            if not kw.get("pending"):
                break
            _time.sleep(0.1)
        data["keywords_with_hits"] = sum(1 for k in kw.get("keywords", []) if k["hits"])
        if not data["keywords_with_hits"]:
            problems.append("keywords page: no keyword with hits")
        rv = c.get("/api/datasets/smoke/lines", params={"sort": "review", "scored": True, "limit": 5}).json()
        data["review_rows"] = len(rv.get("rows", []))
        g = c.post("/api/datasets/smoke/golden", json={"file": key, "row": 1, "expect": "keep"}, headers={EDIT_HEADER: "1"})
        if g.status_code != 200 or g.json().get("count") != 1:
            problems.append(f"golden label: HTTP {g.status_code} {g.text[:200]}")
        # edit text + a field of line 1, then undo: the file must be byte for byte as before
        path = files[0]["corpus_path"] if files else ""
        before = (corpus / path).read_bytes() if path else b""
        row = c.get("/api/datasets/smoke/corpus/lines", params={"path": path, "count": 1}).json()["lines"][0]
        body = {"path": path, "changes": [{"line": 1, "sha1": row["sha1"], "text": "Smoke test edit.",
                                           "fields": {"expect": "keep", "smoke": True}}]}
        r = c.post("/api/datasets/smoke/corpus/edit-batch", json=body, headers={EDIT_HEADER: "1"})
        if r.status_code != 200 or r.json().get("changed") != 1:
            problems.append(f"edit: HTTP {r.status_code} {r.text[:200]}")
        else:
            edits = c.get("/api/datasets/smoke/corpus/edits", params={"path": path, "line": 1}).json()["edits"]
            u = c.post(f"/api/datasets/smoke/corpus/edits/{edits[-1]['edit']}/undo", headers={EDIT_HEADER: "1"})
            import zstandard
            dec = zstandard.ZstdDecompressor()
            same = dec.decompress((corpus / path).read_bytes(), max_output_size=1 << 30) == \
                dec.decompress(before, max_output_size=1 << 30)
            if u.status_code != 200 or not same:
                problems.append(f"undo: HTTP {u.status_code}, content restored: {same}")
    data["frontend_built"] = (HERE / "viewer" / "frontend" / "out" / "index.html").is_file()
    if problems:
        return "FAIL", "; ".join(problems), data
    note = "" if data["frontend_built"] else " (web pages not built here: viewer/frontend/out missing)"
    return "PASS", (f"datasets, {data['files']} files, record, 2 progress files, keywords ({data['keywords_with_hits']} "
                    f"with hits), review, golden label, edit + undo OK{note}"), data


# ---- main --------------------------------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--lines", type=int, default=40, help="lines of test_russia.jsonl to use (default 40)")
    p.add_argument("--skip-models-check", action="store_true", help="skip nli_models.py --check all")
    p.add_argument("--skip-viewer", action="store_true")
    p.add_argument("--keep", action="store_true", help="keep the temporary folder")
    p.add_argument("--out", help="result JSON (default smoke_<machine>_<date>.json here)")
    p.add_argument("--timeout", type=float, default=3600, help="seconds per nli_filter.py run (default 3600)")
    args = p.parse_args(argv)

    env = step("environment", environment)
    if env["status"] == "FAIL":
        return finish(args, None)
    gpus = env.get("gpus") or []
    tmp = Path(tempfile.mkdtemp(prefix="nli_smoke_"))
    logs = tmp / "logs"
    logs.mkdir()
    print(f"    temporary folder: {tmp}")
    try:
        if not args.skip_models_check:
            dev = "cuda:0" if gpus else "cpu"

            def models() -> Tuple[str, str, Dict[str, Any]]:
                log = logs / "models_check.log"
                code, _ = run_py(["nli_models.py", "--check", "all", "--device", dev], log, args.timeout)
                lines = [x for x in tail(log, 40).splitlines() if x.startswith("[")]
                return ("PASS" if code == 0 else "FAIL"), (f"3 models on {dev}" if code == 0 else f"exit {code}"), {"lines": lines}
            step("models load and score (nli_models.py --check all)", models)

        jsonl, zst, n = make_inputs(tmp, args.lines)
        print(f"    input: {n} lines ({jsonl}), and 4 .zst files ({zst})")
        gpu_opts = ["--batch-size", "64", "--judge-batch-size", "32"]

        ref_res = step("reference: CPU, --mode single", lambda: run_filter(
            "ref_cpu_single", [str(jsonl)], tmp / "out_ref", ["--device", "cpu", "--mode", "single"], logs, args.timeout, None))
        ref = read_decisions(tmp / "out_ref") if ref_res and ref_res["status"] == "PASS" else None
        if ref is None:
            return finish(args, tmp)

        setups: List[Tuple[str, List[str]]] = []
        if not gpus:
            setups += [("CPU, 2 workers, --mode thread", ["--device", "cpu*2", "--mode", "thread"]),
                       ("CPU, 2 workers, --mode process", ["--device", "cpu*2", "--mode", "process"])]
        else:
            setups.append(("1 GPU (cuda:0)", ["--device", "cuda:0", *gpu_opts]))
            if len(gpus) > 1:
                setups += [(f"all {len(gpus)} GPUs, --mode thread", ["--device", "cuda", "--mode", "thread", *gpu_opts]),
                           (f"all {len(gpus)} GPUs, --mode process", ["--device", "cuda", "--mode", "process", *gpu_opts])]
        for i, (label, opts) in enumerate(setups):
            step(label, lambda o=opts, k=i: run_filter(f"setup{k}", [str(jsonl)], tmp / f"out_setup{k}", o, logs,
                                                       args.timeout, ref))

        # two shard copies side by side (on GPU 0, or the CPU), .zst in and out, --write-split, then --report
        def shards() -> Tuple[str, str, Dict[str, Any]]:
            out = tmp / "out_shards"
            dev = "cuda:0" if gpus else "cpu"
            env_ = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
            procs = []
            for k in range(2):
                fh = open(logs / f"shard{k}.log", "w", encoding="utf-8")
                procs.append((subprocess.Popen(
                    [sys.executable, "nli_filter.py", str(zst), "--device", dev, "--shard", f"{k}/2", "--output-dir",
                     str(out), "--write-split", "--progress-every", "5", *(gpu_opts if gpus else [])],
                    cwd=str(HERE), stdout=fh, stderr=subprocess.STDOUT, env=env_), fh))
            codes = []
            for proc, fh in procs:
                codes.append(proc.wait(timeout=args.timeout))
                fh.close()
            if any(codes):
                return "FAIL", f"shard exit codes {codes}", {"log_tail": tail(logs / "shard0.log") + "\n" + tail(logs / "shard1.log")}
            code, _ = run_py(["nli_filter.py", "--report", "--output-dir", str(out)], logs / "report.log", 600)
            rep = summary_of(out, "summary.report.json")
            problems = []
            if code != 0 or not rep:
                problems.append(f"--report exit {code}")
            elif rep["stats"]["lines"] != n or len(rep.get("runs", [])) != 2:
                problems.append(f"report: {rep['stats']['lines']} lines from {rep.get('runs')} (want {n} from 2 shards)")
            got = read_decisions(out)
            status, detail, cmp = compare(ref, got)
            # --write-split: kept + filtered = all lines, filtered = the 'filter' decisions
            import zstandard

            def count(pattern: str) -> int:
                total = 0
                for f in out.rglob(pattern):
                    total += sum(1 for x in zstandard.ZstdDecompressor().stream_reader(open(f, "rb")).read().splitlines() if x.strip())
                return total
            kept, filt = count("*.kept.jsonl.zst"), count("*.filtered.jsonl.zst")
            want_f = sum(1 for d in got.values() if d.get("decision") == "filter")
            if kept + filt != n or filt != want_f:
                problems.append(f"--write-split: kept {kept} + filtered {filt} (want {n} lines, {want_f} filtered)")
            if problems:
                return "FAIL", "; ".join(problems) + f"; decisions: {detail}", cmp
            return status, f"2 copies, .zst + --write-split + --report OK; {detail}", {**cmp, "kept": kept, "filtered": filt}
        step(f"2 --shard copies at once on {'cuda:0' if gpus else 'cpu'} (.zst, --write-split, --report)", shards)

        # replay with the run's own thresholds must give the same decisions; nli_compare must agree
        def replay_same() -> Tuple[str, str, Dict[str, Any]]:
            import nli_compare
            import nli_replay
            src, dst = tmp / "out_shards", tmp / "out_replay"
            nli_replay.replay(src, dst, None, None, [], [])  # shards have no summary.json: default thresholds
            r = nli_compare.compare(src, dst)
            info = {"lines": r["lines"], "changed": len(r["changed"])}
            if r["lines"] != n or r["changed"]:
                return "FAIL", f"replay of the same settings changed {len(r['changed'])} of {r['lines']} lines (want 0 of {n})", info
            return "PASS", f"nli_replay.py + nli_compare.py: {r['lines']} lines, none changed", info
        step("replay + compare (no models): same settings give the same decisions", replay_same)

        if not args.skip_viewer:
            step("viewer backend on the shard results", lambda: viewer_check(zst, tmp / "out_shards", tmp, n))
    finally:
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)
    return finish(args, tmp if args.keep else None)


def finish(args, kept: Optional[Path]) -> int:
    machine = socket.gethostname()
    out = Path(args.out or f"smoke_{machine}_{datetime.datetime.now():%Y%m%d-%H%M}.json")
    out.write_text(json.dumps({"machine": machine, "finished": datetime.datetime.now().isoformat(timespec="seconds"),
                               "temporary_folder": str(kept) if kept else None, "results": results},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n" + "=" * 100)
    for r in results:
        print(f"{r['status']:<5} {r['name']:<62} {r['seconds']:>7.1f} s")
    worst = "FAIL" if any(r["status"] == "FAIL" for r in results) else "WARN" if any(r["status"] == "WARN" for r in results) else "PASS"
    print("=" * 100)
    print(f"{worst}: details in {out.resolve()}" + (f"; files kept in {kept}" if kept else ""))
    return 1 if worst == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())

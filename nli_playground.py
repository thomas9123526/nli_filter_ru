#!/usr/bin/env python3
"""
nli_playground.py - small model service: run nli_filter.py's decision on a few lines with any keywords and
hypotheses, at once. The viewer's Corpus page ("Try settings") sends lines here; the models stay loaded.
It also starts whole nli_filter.py runs for the viewer's "Run filter" page (in this environment, with this
Python), one at a time, and keeps their output.

Start it in the environment that has torch and the models (where nli_filter.py runs):

    python nli_playground.py                              # http://127.0.0.1:8100, fast + judge, device auto
    python nli_playground.py --device cuda:0 --judge-model none
    python nli_playground.py --host 0.0.0.0 --port 8100   # reachable from the viewer on another PC
    python nli_playground.py --no-models                  # only for "Run filter" (no models loaded here)

Then in viewer_config.json (default shown): "playground_url": "http://127.0.0.1:8100"

API (JSON):
  GET  /health   -> {"ok": true, "fast": "modernbert", "judge": "deberta" | null, "devices": [...]}
  GET  /info     -> nli_filter.py facts the viewer needs without importing it: known countries, the options and
                    how many values each takes, the defaults
  POST /filter   {"lines": [{"line": 12, "raw": "<the JSON line>"}], "country": "Russia", "country_adj": "Russian",
                  "keywords": [...], "check1": {key: template}, "check2": {...}, "use_judge": true,
                  "check1_threshold": 0.8, "check2_threshold": 0.8, "uncertain_band": [0.6, 0.95],
                  "max_windows": 2, "rules": true, "early_stop": true, "text_field": "text", "id_field": "id",
                  "check1_early_stop": true, "check2_early_stop": true}   (per check; default = early_stop)
                  max_windows 0 = a check-1 window around every keyword hit
              -> {"decisions": [<the record nli_filter.py writes per line>], "hypotheses": {...}, "pairs": {...},
                  "seconds": ...}
Every setting left out has nli_filter.py's default. One request at a time (the models are shared).

  POST /jobs     {"args": ["test_corpus", "--output-dir", "out", ...], "env": {"NLI_CORPUS_PASSWORD": "..."},
                  "label": "dataset name"} -> {"id": ...}   (python nli_filter.py <args>, cwd = project folder)
  GET  /jobs     -> {"jobs": [...]}          GET /jobs/<id> -> state, return code, the last output lines
  POST /jobs/<id>/stop
Only one job runs at a time; env values are given to the run only, never shown or logged.
"""
from __future__ import annotations

import argparse
import collections
import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nli_filter as nf  # noqa: E402
import nli_hypotheses  # noqa: E402
from nli_models import NLIPool, Record, json_loads, quiet_transformers  # noqa: E402

log = logging.getLogger("nli_playground")
HERE = Path(__file__).resolve().parent
MAX_LINES = 200
MAX_BODY = 64 << 20


class Jobs:
    """nli_filter.py runs started for the viewer: one at a time, output kept (last lines in memory, all in a file)."""

    def __init__(self, log_dir: Optional[Path] = None, python: Optional[str] = None):
        self.python = python or sys.executable
        self.log_dir = Path(log_dir or HERE / ".playground_jobs")
        self.jobs: "collections.OrderedDict[str, Dict[str, Any]]" = collections.OrderedDict()
        self.lock = threading.Lock()

    def running(self) -> Optional[Dict[str, Any]]:
        return next((j for j in self.jobs.values() if j["state"] == "running"), None)

    SCRIPTS = ("nli_filter.py", "nli_label.py")  # the only programs a job may run

    def start(self, args: List[str], env: Optional[Dict[str, str]] = None, label: str = "",
              script: Optional[str] = None) -> Dict[str, Any]:
        script = script or "nli_filter.py"
        if script not in self.SCRIPTS:
            raise ValueError(f"'script' must be one of {', '.join(self.SCRIPTS)}")
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise ValueError(f"'args' must be a list of strings (the arguments of {script})")
        with self.lock:
            busy = self.running()
            if busy:
                raise RuntimeError(f"a run is already going ({busy['label'] or busy['id']}); stop it or wait")
            jid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
            self.log_dir.mkdir(parents=True, exist_ok=True)
            log_file = self.log_dir / f"{jid}.log"
            full_env = {**os.environ, **{k: str(v) for k, v in (env or {}).items()}, "PYTHONUNBUFFERED": "1",
                        "PYTHONIOENCODING": "utf-8"}
            cmd = [self.python, str(HERE / script), *args]
            proc = subprocess.Popen(cmd, cwd=str(HERE), env=full_env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            job = {"id": jid, "label": label, "script": script, "args": args, "state": "running", "returncode": None,
                   "started": time.strftime("%Y-%m-%d %H:%M:%S"), "ended": None, "t0": time.time(), "seconds": None,
                   "lines": collections.deque(maxlen=2000), "log_file": str(log_file), "proc": proc}
            self.jobs[jid] = job
            while len(self.jobs) > 20:
                self.jobs.popitem(last=False)
        threading.Thread(target=self._read, args=(job,), daemon=True).start()
        return self.view(job)

    def _read(self, job: Dict[str, Any]) -> None:
        proc = job["proc"]
        with open(job["log_file"], "w", encoding="utf-8") as fh:
            for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                job["lines"].append(line)
                fh.write(line + "\n")
                fh.flush()
        rc = proc.wait()
        job.update(returncode=rc, ended=time.strftime("%Y-%m-%d %H:%M:%S"),
                   seconds=round(time.time() - job["t0"], 1),
                   state="stopped" if job.get("stopping") else ("done" if rc == 0 else "failed"))

    def stop(self, jid: str) -> Dict[str, Any]:
        job = self.jobs.get(jid)
        if job is None:
            raise KeyError(jid)
        if job["state"] == "running":
            job["stopping"] = True
            job["proc"].terminate()
        return self.view(job)

    def view(self, job: Dict[str, Any], tail: int = 400) -> Dict[str, Any]:
        lines = list(job["lines"])
        return {k: job.get(k) for k in ("id", "label", "script", "args", "state", "returncode", "started", "ended",
                                        "log_file")} | {
            "seconds": job["seconds"] if job["seconds"] is not None else round(time.time() - job["t0"], 1),
            "output": lines[-tail:], "output_lines": len(lines)}

    def list(self) -> List[Dict[str, Any]]:
        return [self.view(j, tail=3) for j in reversed(self.jobs.values())]


class Playground:
    """The loaded models + building a LineFilter per request (settings change, models do not)."""

    def __init__(self, fast, judge=None, jobs: Optional[Jobs] = None):
        self.fast, self.judge = fast, judge
        self.defaults = nf.build_parser().parse_args([])  # nli_filter.py's defaults
        self.lock = threading.Lock()
        self.jobs = jobs or Jobs()

    def health(self) -> Dict[str, Any]:
        return {"ok": True, "fast": self.fast.name if self.fast else None,
                "judge": self.judge.name if self.judge else None,
                "devices": list(getattr(self.fast, "devices", []) or []) if self.fast else [],
                "max_lines": MAX_LINES, "models": self.fast is not None, "python": self.jobs.python,
                "project_dir": str(HERE)}

    def info(self) -> Dict[str, Any]:
        """What the viewer needs to know about nli_filter.py (it does not import it: no torch / models there)."""
        parser = nf.build_parser()
        options, defaults = {}, {}
        for act in parser._actions:  # noqa: SLF001 - argparse has no public table of option arities
            for opt in act.option_strings:
                options[opt] = 0 if act.nargs == 0 else (act.nargs if isinstance(act.nargs, int) else 1)
            if act.option_strings and act.dest != "help":
                defaults[act.option_strings[-1]] = act.default
        countries = [{"name": c["name"], "adj": c.get("adj")} for c in nf.COUNTRIES.values()]
        return {"countries": countries, "options": options, "defaults": defaults}

    def run(self, req: Dict[str, Any]) -> Dict[str, Any]:
        d = self.defaults
        if self.fast is None:
            raise ValueError("this service was started with --no-models: no lines can be scored")
        lines = req.get("lines") or []
        if not isinstance(lines, list) or not lines:
            raise ValueError("'lines' must be a non-empty list of {line, raw}")
        if len(lines) > MAX_LINES:
            raise ValueError(f"at most {MAX_LINES} lines per request")
        known = nf.COUNTRIES.get(str(req.get("country") or d.country).strip().lower(), {})
        country = known.get("name", str(req.get("country") or d.country).strip())
        adj = req.get("country_adj") or known.get("adj")
        if not adj:
            raise ValueError(f"country_adj is needed for '{country}'")
        # keyword file lines: plain keywords or lexicon lines (tab-separated: keyword, level, type, gloss, ...)
        keywords = nf.parse_keywords([k for k in (req.get("keywords") or []) if isinstance(k, str)])
        if not keywords:
            keywords = list(known.get("keywords", []))
        if not keywords:
            raise ValueError("no keywords")
        hyps = nli_hypotheses.validate({"check1": req.get("check1") or nli_hypotheses.DEFAULT_CHECK1,
                                        "check2": req.get("check2") if req.get("check2") is not None
                                        else nli_hypotheses.DEFAULT_CHECK2,
                                        "check1_types": req.get("check1_types") or {},
                                        "check2_types": req.get("check2_types") or {}})
        check1 = nli_hypotheses.render(hyps["check1"], country, adj)
        check2 = nli_hypotheses.render(hyps["check2"], country, adj)
        check1_types = nli_hypotheses.render_types(hyps.get("check1_types"), country, adj)
        check2_types = nli_hypotheses.render_types(hyps.get("check2_types"), country, adj)
        max_kw_hyps = int(req.get("max_keyword_hyps", getattr(d, "max_keyword_hyps", 4)))
        if max_kw_hyps < 0:
            raise ValueError("max_keyword_hyps must be 0 or more")
        lo, hi = req.get("uncertain_band") or d.uncertain_band
        if not (0 <= float(lo) < float(hi) <= 1):
            raise ValueError("uncertain_band needs 0 <= LOW < HIGH <= 1")
        use_judge = bool(req.get("use_judge", True)) and self.judge is not None
        settings = nf.FilterSettings(country, adj, check1, check2,
                                     float(req.get("check1_threshold", d.check1_threshold)),
                                     float(req.get("check2_threshold", d.check2_threshold)),
                                     req.get("text_field") or d.text_field, req.get("id_field") or d.id_field or None,
                                     req.get("expect_field") or d.expect_field or None,
                                     req.get("group_field") or d.group_field or None,
                                     early_stop=bool(req.get("early_stop", not d.no_early_stop)),
                                     check1_early_stop=None if req.get("check1_early_stop") is None
                                     else bool(req["check1_early_stop"]),
                                     check2_early_stop=None if req.get("check2_early_stop") is None
                                     else bool(req["check2_early_stop"]),
                                     strict_rules=bool(req.get("strict_rules", False)),
                                     check1_types=check1_types, check2_types=check2_types,
                                     max_keyword_hyps=max_kw_hyps,
                                     audit_strict=min(1.0, max(0.0, float(req.get("audit_strict", 0) or 0))))
        excludes = [x for x in (req.get("exclude_patterns") or known.get("exclude", [])) if isinstance(x, str)]
        matcher = nf.KeywordMatcher(keywords, excludes)
        rules = nf.IncidentalRules(adj, int(req.get("language_menu_min", d.language_menu_min))) \
            if req.get("rules", True) else None
        max_windows = int(req.get("max_windows", d.max_windows))
        if max_windows < 0:
            raise ValueError("max_windows must be 0 (no limit) or more")
        windows = nf.WindowBuilder(int(req.get("check1_chars", d.check1_chars)),
                                   int(req.get("check2_chars", d.check2_chars)), max_windows)
        records = []
        for item in lines:
            raw = str(item.get("raw", "")).encode("utf-8")
            n = int(item.get("line", 0))
            if not raw.strip():
                records.append(Record("playground", n, None, raw, "blank"))
                continue
            try:
                records.append(Record("playground", n, json_loads(raw), raw))
            except ValueError as exc:
                records.append(Record("playground", n, None, raw, f"bad_json: {exc}"))
        t0 = time.perf_counter()
        with self.lock:  # the models are shared: one request at a time
            scorer = nf.CascadeScorer(self.fast, self.judge if use_judge else None, (float(lo), float(hi)))
            outcomes = nf.LineFilter(settings, matcher, rules, windows, scorer).process(records)
        return {"decisions": [o.decision for o in outcomes], "seconds": round(time.perf_counter() - t0, 3),
                "pairs": {"fast": scorer.fast_pairs, "judge": scorer.judge_pairs},
                "hypotheses": {"check1": check1, "check2": check2,
                               **({"check1_types": check1_types} if check1_types else {}),
                               **({"check2_types": check2_types} if check2_types else {})},
                "keywords": matcher.keywords, "lexicon": matcher.counts(), "country": {"name": country, "adj": adj},
                "models": {"fast": {"model": self.fast.name}, "judge": {"model": self.judge.name} if use_judge else None},
                "settings": {"check1_threshold": settings.check1_threshold,
                             "check2_threshold": settings.check2_threshold, "uncertain_band": [lo, hi],
                             "early_stop": settings.early_stop, "check1_early_stop": settings.check1_early_stop,
                             "check2_early_stop": settings.check2_early_stop, "strict_rules": settings.strict_rules,
                             "max_keyword_hyps": settings.max_keyword_hyps, "audit_strict": settings.audit_strict,
                             "max_windows": windows.max_windows
                             if hasattr(windows, "max_windows") else None,
                             "text_field": settings.text_field, "id_field": settings.id_field}}


MAX_LABEL_TEXTS = 20
MAX_LABEL_CHARS = 20000


def label_texts(pg: "Playground", req: Dict[str, Any]) -> Dict[str, Any]:
    """POST /label: nli_label.py's policy labels on a few texts (the viewer's policy Try page).
    {"texts": [str], "policy": "policy/russia_policy.json" | "policy_data": {...}, "all_labels": true,
     "force_gate": false, "use_judge": true} -> one labels row per text (paragraphs, scores, levels, action)."""
    import nli_label
    from nli_names import NameRewriter
    if pg.fast is None:
        raise ValueError("this service was started with --no-models: no text can be scored")
    texts = req.get("texts")
    if not isinstance(texts, list) or not texts or not all(isinstance(t, str) for t in texts):
        raise ValueError("'texts' must be a non-empty list of strings")
    if len(texts) > MAX_LABEL_TEXTS or any(len(t) > MAX_LABEL_CHARS for t in texts):
        raise ValueError(f"at most {MAX_LABEL_TEXTS} texts of {MAX_LABEL_CHARS} characters")
    if isinstance(req.get("policy_data"), dict):
        policy = nli_label.Policy(req["policy_data"], "policy_data")
    else:
        rel = str(req.get("policy") or "policy/russia_policy.json")
        path = (HERE / rel).resolve()
        if (HERE / "policy").resolve() not in path.parents or path.suffix != ".json":
            raise ValueError("'policy' must be a .json file in the project's policy folder")
        policy = nli_label.Policy.load(str(path))
    matcher, rules, markers = nli_label.build_matchers(policy)
    records = [Record("try", i + 1, {"text": t}, t.encode("utf-8")) for i, t in enumerate(texts)]
    lo, hi = req.get("uncertain_band") or (0.6, 0.95)
    use_judge = bool(req.get("use_judge", True)) and pg.judge is not None
    t0 = time.perf_counter()
    with pg.lock:  # the models are shared: one request at a time
        scorer = nf.CascadeScorer(pg.fast, pg.judge if use_judge else None, (float(lo), float(hi)))
        lab = nli_label.Labeller(policy, matcher, rules, scorer,
                                 NameRewriter.from_files() if policy.rewrite_place_names else None,
                                 all_labels=bool(req.get("all_labels", True)), marker_matcher=markers,
                                 force_gate=bool(req.get("force_gate", False)),
                                 narrative_matcher=nli_label.build_narrative_matcher(policy))
        outs = lab.process(records)
    return {"rows": [o.row for o in outs], "clean": [(o.clean or {}).get("text") for o in outs],
            "rewrites": [o.rewrites for o in outs], "seconds": round(time.perf_counter() - t0, 3),
            "pairs": {"fast": scorer.fast_pairs, "judge": scorer.judge_pairs},
            "models": {"fast": pg.fast.name, "judge": pg.judge.name if use_judge else None},
            "policy": policy.summary()}


def make_handler(pg: Playground):
    class Handler(BaseHTTPRequestHandler):
        server_version = "nli_playground"

        def _send(self, code: int, body: Dict[str, Any]) -> None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            path = self.path.rstrip("/")
            if path in ("", "/health"):
                return self._send(200, pg.health())
            if path == "/info":
                return self._send(200, pg.info())
            if path == "/jobs":
                return self._send(200, {"jobs": pg.jobs.list()})
            if path.startswith("/jobs/"):
                job = pg.jobs.jobs.get(path.split("/")[2])
                return self._send(200, pg.jobs.view(job)) if job else self._send(404, {"detail": "unknown job"})
            self._send(404, {"detail": "unknown path"})

        def do_POST(self):  # noqa: N802
            path = self.path.rstrip("/")
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                return self._send(413, {"detail": "request too large"})
            try:
                req = json.loads(self.rfile.read(n) or b"{}")
                if path == "/jobs":
                    return self._send(200, pg.jobs.start(req.get("args"), req.get("env"), str(req.get("label") or ""),
                                                         req.get("script")))
                if path.startswith("/jobs/") and path.endswith("/stop"):
                    return self._send(200, pg.jobs.stop(path.split("/")[2]))
                if path == "/label":
                    return self._send(200, label_texts(pg, req))
                if path != "/filter":
                    return self._send(404, {"detail": "unknown path"})
                return self._send(200, pg.run(req))
            except KeyError:
                return self._send(404, {"detail": "unknown job"})
            except RuntimeError as exc:
                return self._send(409, {"detail": str(exc)})
            except ValueError as exc:
                return self._send(400, {"detail": str(exc)})
            except Exception as exc:  # noqa: BLE001 - reported to the viewer
                log.exception("filter request failed")
                return self._send(500, {"detail": f"{type(exc).__name__}: {exc}"})

        def log_message(self, fmt, *args):  # quiet: one line per request at INFO
            log.info("%s %s", self.address_string(), fmt % args)
    return Handler


def serve(pg: Playground, host: str = "127.0.0.1", port: int = 8100) -> ThreadingHTTPServer:
    """Start the HTTP server in a thread; returns it (server.shutdown() stops it)."""
    server = ThreadingHTTPServer((host, port), make_handler(pg))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Model service for the viewer's 'Try settings' panel.")
    p.add_argument("--host", default="127.0.0.1", help="127.0.0.1 = this PC only; 0.0.0.0 = reachable from the LAN")
    p.add_argument("--port", type=int, default=8100)
    p.add_argument("--fast-model", default="modernbert")
    p.add_argument("--judge-model", default="deberta", help="judge model or 'none'")
    p.add_argument("--device", default="auto", help="auto | cpu | cuda | cuda:0 ...")
    p.add_argument("--dtype", default="auto")
    p.add_argument("--models-root", help="folder with the model folders (default ./models)")
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--no-models", action="store_true", help="load no models: only start nli_filter.py runs")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(asctime)s %(message)s")
    if not args.verbose:
        quiet_transformers()
    t0 = time.perf_counter()
    common = dict(devices=args.device, mode="single", dtype=args.dtype, models_root=args.models_root)
    fast = judge = None
    if not args.no_models:
        fast = NLIPool(args.fast_model, batch_size=args.batch_size, **common)
        judge = None if args.judge_model.lower() == "none" else NLIPool(args.judge_model, batch_size=args.batch_size,
                                                                         **common)
    pg = Playground(fast, judge)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(pg))
    models = (f"fast {fast.name}, judge {judge.name if judge else 'none'}, devices {','.join(fast.devices)}"
              if fast else "no models (--no-models: Run filter only)")
    print(f"nli_playground: {models}, ready in {time.perf_counter() - t0:.0f}s -> http://{args.host}:{args.port}  "
          f"(Ctrl+C stops)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        job = pg.jobs.running()
        if job:
            job["proc"].terminate()
        if fast:
            fast.close()
        if judge:
            judge.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

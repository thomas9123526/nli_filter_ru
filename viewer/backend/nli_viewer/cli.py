"""
cli.py - command line for the viewer.

    python -m nli_viewer serve --config viewer_config.json            # web UI + API on http://127.0.0.1:8000
    python -m nli_viewer serve --corpus ../test_corpus --output ../out_test_corpus
    python -m nli_viewer datasets  --config viewer_config.json
    python -m nli_viewer files     --config viewer_config.json test
    python -m nli_viewer decisions --config viewer_config.json test books/part-00/shard-00000 --decision filter
    python -m nli_viewer show      --config viewer_config.json test books/part-00/shard-00000 --line 4
    python -m nli_viewer find      --config viewer_config.json test about-010
    python -m nli_viewer index     --config viewer_config.json test       # prepare caches for every file
    python -m nli_viewer verify    --config viewer_config.json test       # every decision vs its original line
    python -m nli_viewer check     --config viewer_config.json            # can every storage be reached?

Without --config: $NLI_VIEWER_CONFIG, else ./viewer_config.json, else --corpus/--output.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
from typing import Any, Dict, Optional, Sequence

from . import __version__
from .config import DatasetRegistry, ViewerConfig, load_config, quick_config

COLORS = {"filter": "\033[31m", "keep": "\033[32m", "about": "\033[1;31m", "open": "\033[1;33m",
          "incidental": "\033[1;36m", "rule": "\033[1;34m", "win": "\033[4m", "dim": "\033[2m", "end": "\033[0m"}


def _config(args) -> ViewerConfig:
    if getattr(args, "corpus", None) or getattr(args, "output", None):
        if not (args.corpus and args.output):
            raise SystemExit("error: give both --corpus and --output")
        return quick_config(args.corpus, args.output, args.name or "default")
    path = args.config or os.environ.get("NLI_VIEWER_CONFIG") or "viewer_config.json"
    if not os.path.exists(path):
        raise SystemExit(f"error: config '{path}' not found (give --config, or --corpus and --output)")
    return load_config(path)


def _c(text: str, color: str, on: bool) -> str:
    return f"{COLORS[color]}{text}{COLORS['end']}" if on else text


def cmd_serve(args) -> int:
    import uvicorn
    from .api import create_app
    cfg = _config(args)
    if args.frontend:
        cfg.frontend_dir = os.path.abspath(args.frontend)
    app = create_app(cfg)
    print(f"NLI viewer {__version__}: http://{args.host}:{args.port}  (API docs /docs, "
          f"{len(cfg.datasets)} dataset(s))", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning" if not args.verbose else "info")
    return 0


def cmd_datasets(args) -> int:
    reg = DatasetRegistry(_config(args))
    for d in reg.describe():
        status = "ERROR " + d["error"] if d["error"] else "ok"
        print(f"{d['name']:<16} {status}\n  corpus {d['corpus']}\n  output {d['output']}")
    return 0


def cmd_files(args) -> int:
    ds = DatasetRegistry(_config(args)).get(args.dataset)
    rows = [f.row() for f in ds.files()]
    print(f"{'file':<45} {'lines':>7} {'filtered':>9} {'acc':>6}  corpus")
    for r in rows:
        acc = "-" if r["accuracy"] is None else f"{r['accuracy']:.3f}"
        print(f"{r['key']:<45} {r['lines']:>7} {r['filtered']:>9} {acc:>6}  {r['corpus_path'] or 'NOT FOUND'}"
              f"{'' if r['complete'] else '  (partial)'}")
    print(f"{len(rows)} files")
    return 0


def cmd_decisions(args) -> int:
    ds = DatasetRegistry(_config(args)).get(args.dataset)
    res = ds.decisions(args.file).query(offset=args.offset, limit=args.limit, decision=args.decision,
                                        reason=args.reason, q=args.q, mismatch=args.mismatch, sort=args.sort,
                                        desc=args.desc)
    print(f"{res['total']} matching decisions; showing {len(res['rows'])} from {args.offset}")
    print(f"{'row':>5} {'line':>6} {'id':<24} {'decision':<8} {'reason':<18} {'check1':>7}  keywords")
    for r in res["rows"]:
        c1 = "-" if r["c1"] is None else f"{r['c1']:.3f}"
        mark = "  WRONG" if r["ok"] is False else ""
        print(f"{r['row']:>5} {r['line']:>6} {str(r['id'] or '')[:24]:<24} {r['decision']:<8} {r['reason']:<18} "
              f"{c1:>7}  {','.join(r['kws'])}{mark}")
    return 0


def render_text(ex: Dict[str, Any], color: bool) -> str:
    """Text with hits in colour (rule = blue, incidental = cyan, about = red, open = yellow), windows underlined."""
    marks = {m["id"]: m for m in ex["marks"]}
    out = []
    for seg in ex["segments"]:
        if "gap" in seg:
            out.append(_c(f" [... {seg['gap']} characters ...] ", "dim", color))
            continue
        kinds = [marks[i] for i in seg["marks"]]
        hit = next((m for m in kinds if m["kind"] == "hit"), None)
        text = seg["text"]
        if hit and color:
            text = _c(text, hit["state"], True)
        elif hit:
            text = f"[{text}]"
        if color and any(m["kind"] == "check1_window" and m.get("best") for m in kinds) and not hit:
            text = _c(text, "win", True)
        out.append(text)
    return "".join(out)


def cmd_show(args) -> int:
    ds = DatasetRegistry(_config(args)).get(args.dataset)
    rec = ds.record(args.file, row=args.row, line=args.line)
    if args.json:
        print(json.dumps(rec, ensure_ascii=False, indent=1))
        return 0
    color = sys.stdout.isatty() and not args.no_color
    ex, d = rec["explanation"], rec["decision"]
    v = ex["verdict"]
    print(_c(f"{v['decision'].upper()}  ({v['reason']})", v["decision"], color) +
          f"   {rec['file']} line {rec['line']} (decisions row {rec['row']})  id {d.get('id')}")
    print(v["summary"])
    for s in v["steps"]:
        print("  - " + s)
    if ex["expect"]:
        print(f"  expected: {ex['expect']['value']} -> {'correct' if ex['expect']['correct'] else 'WRONG'}")
    if not rec["id_check"]["match"]:
        print(f"  WARNING: id in decisions {rec['id_check']['decision_id']} != id in corpus {rec['id_check']['original_id']}")
    print()
    if ex["text_available"]:
        print(render_text(ex, color))
    else:
        print("(original text not available: " + str(rec["original"].get("error")) + ")")
    if ex["check1"]:
        print(f"\ncheck 1 (threshold {ex['check1']['threshold']}):")
        for r in ex["check1"]["rows"]:
            print(f"  {r['hyp']:<14} fast {r['fast']}  judge {r['judge']}  -> {r['score']} "
                  f"{'PASS' if r['passed'] else 'no'}   window {r['window']}\n    {r['hypothesis']}")
    if ex["check2"]:
        print(f"\ncheck 2 (threshold {ex['check2']['threshold']}):")
        for r in ex["check2"]["rows"]:
            print(f"  '{r['kw']}' {r['hyp']:<18} fast {r['fast']}  judge {r['judge']}  -> {r['score']} "
                  f"{'incidental' if r['incidental'] else 'NOT incidental'}\n    {r['hypothesis']}")
    m = ex["models"]
    print(f"\nmodels: fast {m['fast']}, judge {m['judge']}, band {m['band']}")
    n = rec["nav"]
    print(f"nav: prev row {n['prev']}, next row {n['next']}")
    return 0


def cmd_find(args) -> int:
    ds = DatasetRegistry(_config(args)).get(args.dataset)
    rows = ds.find_id(args.id, args.limit)
    for r in rows:
        print(f"{r['file']}  line {r['line']}  row {r['row']}  {r['decision']} ({r['reason']})")
    print(f"{len(rows)} match(es)")
    return 0 if rows else 1


def cmd_index(args) -> int:
    reg = DatasetRegistry(_config(args))
    names = [args.dataset] if args.dataset else reg.names()
    for name in names:
        ds = reg.get(name)
        t0 = time.perf_counter()
        files = ds.files()
        for i, f in enumerate(files, 1):
            if f.decisions_path:
                ds.decisions(f.key).facets()
            if f.corpus_path and not args.decisions_only:
                ds._line_file(ds.corpus, f.corpus_path).__len__()
            print(f"\r{name}: {i}/{len(files)} files indexed", end="", flush=True)
        print(f"  ({time.perf_counter() - t0:.1f}s)")
    print(f"cache {reg.cache.root}: {reg.cache.usage() / 1e6:.1f} MB")
    return 0


def cmd_verify(args) -> int:
    """Every decision: original line found, same id, every hit span really contains its keyword."""
    ds = DatasetRegistry(_config(args)).get(args.dataset)
    problems: Dict[str, int] = {}
    examples = []
    n = edited = 0
    t0 = time.perf_counter()
    for f in ds.files():
        if args.file and f.key != args.file:
            continue
        if not f.decisions_path:
            problems["no decisions file"] = problems.get("no decisions file", 0) + 1
            continue
        total = ds.decisions(f.key).query(limit=1)["total"]
        for start in range(0, total, 1000):
            for r in ds.decisions(f.key).query(offset=start, limit=1000)["rows"]:
                n += 1
                rec = ds.record(f.key, row=r["row"], max_chars=10 ** 9)
                issues = []
                if not rec["original"]["available"]:
                    issues.append("original line missing")
                elif not rec["id_check"]["match"]:
                    issues.append("id differs")
                text = (rec["original"].get("record") or {}).get(rec["text_field"]) if rec["original"].get("record") else None
                if (rec.get("edit") or {}).get("edited_after_filter"):
                    edited += 1  # edited in the viewer after the run: check the spans against the text the run saw
                    text = rec["edit"].get("filtered_text")
                if isinstance(text, str):
                    for h in rec["decision"].get("hits") or []:
                        s, e = h["span"]
                        if text[s:e] != h["kw"]:
                            issues.append("hit span does not match keyword")
                            break
                for i in issues:
                    problems[i] = problems.get(i, 0) + 1
                    if len(examples) < 10:
                        examples.append(f"{f.key} row {r['row']} line {r['line']}: {i}")
        print(f"\r{n} decisions checked", end="", flush=True)
    print(f"\r{n} decisions checked in {time.perf_counter() - t0:.1f}s: "
          + ("all consistent" if not problems else ", ".join(f"{k}: {v}" for k, v in problems.items())))
    if edited:
        print(f"  {edited} line(s) were edited in the viewer after the run (not errors; their decisions are for the"
              " text before the edit: rerun nli_filter.py on those files to update them)")
    for e in examples:
        print("  " + e)
    return 1 if problems else 0


def cmd_edits(args) -> int:
    """Edits made in the viewer (oldest first)."""
    ds = DatasetRegistry(_config(args)).get(args.dataset)
    if ds.editor is None:
        print(f"{args.dataset}: editing is off (no \"editable\": true in the config)")
        return 0
    rows = ds.editor.history(args.path or None, args.line)
    if args.json:
        for e in rows:
            print(json.dumps(e, ensure_ascii=False))
        return 0
    for e in rows:
        undo = f" (undo of {e['undo_of']})" if e.get("undo_of") else ""
        print(f"{e['time']}  {e['edit']}  {e['file']}:{e['line']}  id {e.get('id')}{undo}")
        print(f"    old: {_short(e['old'])}")
        print(f"    new: {_short(e['new'])}")
    print(f"{len(rows)} edit(s); log: {ds.editor.log_path}; original files: {ds.editor.dir / 'originals'}")
    return 0


def _short(text: str, n: int = 160) -> str:
    t = text.replace("\n", " ")
    return t if len(t) <= n else t[:n] + f"... ({len(text)} chars)"


def cmd_check(args) -> int:
    reg = DatasetRegistry(_config(args))
    bad = 0
    for name in reg.names():
        try:
            ds = reg.get(name)
            t0 = time.perf_counter()
            n = len(ds.files())
            missing = sum(1 for f in ds.files() if not f.corpus_path)
            print(f"[ok]   {name}: {n} result files, {missing} without corpus file ({time.perf_counter() - t0:.2f}s)")
        except Exception as exc:
            bad += 1
            print(f"[FAIL] {name}: {exc}")
    return 1 if bad else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m nli_viewer", description="NLI filter result viewer",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n")[1])
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, dataset=True, file=False):
        sp.add_argument("--config", help="viewer config JSON (default $NLI_VIEWER_CONFIG or ./viewer_config.json)")
        sp.add_argument("--corpus", help="corpus folder / URI (instead of --config)")
        sp.add_argument("--output", help="nli_filter.py output folder / URI (instead of --config)")
        sp.add_argument("--name", default="default", help="dataset name with --corpus/--output (default 'default')")
        if dataset:
            sp.add_argument("dataset", nargs="?" if dataset == "optional" else None, default=None)
        if file:
            sp.add_argument("file", help="file key, e.g. books/part-00/shard-00000")

    s = sub.add_parser("serve", help="start the web UI and API")
    common(s, dataset=False)
    s.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to allow other machines (default 127.0.0.1)")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--frontend", help="built frontend folder (default viewer/frontend/out)")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("datasets", help="list the configured datasets")
    common(s, dataset=False)
    s.set_defaults(fn=cmd_datasets)
    s = sub.add_parser("files", help="result files of a dataset")
    common(s)
    s.set_defaults(fn=cmd_files)
    s = sub.add_parser("decisions", help="decisions of one file, filtered")
    common(s, file=True)
    s.add_argument("--decision", choices=["filter", "keep"])
    s.add_argument("--reason")
    s.add_argument("--q", help="id / keyword substring or line number")
    s.add_argument("--mismatch", action="store_true", help="only lines where decision != expect")
    s.add_argument("--sort", default="row", choices=["row", "line", "score", "check2", "hits", "id"])
    s.add_argument("--desc", action="store_true")
    s.add_argument("--offset", type=int, default=0)
    s.add_argument("--limit", type=int, default=30)
    s.set_defaults(fn=cmd_decisions)
    s = sub.add_parser("show", help="one decision with the original text, highlights and scores")
    common(s, file=True)
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--line", type=int, help="line number in the corpus file")
    g.add_argument("--row", type=int, help="row number in the decisions file")
    s.add_argument("--json", action="store_true", help="print the full JSON the API returns")
    s.add_argument("--no-color", action="store_true")
    s.set_defaults(fn=cmd_show)
    s = sub.add_parser("find", help="find a line by its id in every file")
    common(s)
    s.add_argument("id")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(fn=cmd_find)
    s = sub.add_parser("index", help="build the caches for every file in advance")
    common(s, dataset="optional")
    s.add_argument("--decisions-only", action="store_true", help="skip decompressing the corpus files")
    s.set_defaults(fn=cmd_index)
    s = sub.add_parser("verify", help="check every decision against its original line (ids, hit spans)")
    common(s)
    s.add_argument("--file", help="only this file key")
    s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("edits", help="corpus edits made in the viewer (old and new text)")
    common(s)
    s.add_argument("--path", default="", help="only this corpus file")
    s.add_argument("--line", type=int, default=None, help="only this line")
    s.add_argument("--json", action="store_true", help="one JSON object per edit")
    s.set_defaults(fn=cmd_edits)
    s = sub.add_parser("check", help="check that every dataset's storage can be reached")
    common(s, dataset=False)
    s.set_defaults(fn=cmd_check)
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if os.name == "nt":
        os.system("")  # enable ANSI colours in the Windows console
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except KeyError as exc:
        print(f"error: {exc.args[0] if exc.args else exc}", file=sys.stderr)
        return 2
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

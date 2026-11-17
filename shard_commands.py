"""
shard_commands.py - print the nli_filter.py commands for a run split into copies (shards) over GPUs, and check the
options first (unknown or wrong options, options the helper sets itself, useful options that are missing).

Every copy gets its own --shard K/N (a disjoint set of files) and one GPU (--device cuda:G, round robin), and all
write into the same --output-dir. Nothing is started: the commands are printed and written to a file
(shard_run_<N>copies.sh / .bat / .txt, or --save NAME; --no-save: print only), with the checks as comments on top. Afterwards `python nli_filter.py --report --output-dir OUT` combines the copies' summaries.

Examples
--------
  # 8 GPUs, 2 copies each = 16 copies (bash, Ubuntu)
  python shard_commands.py "/data/corpus/**/*.zst" --output-dir /data/nli_out --gpus 8 --copies-per-gpu 2 \\
      -- --batch-size 256 --judge-batch-size 128 --max-batch-tokens 65536

  # only GPUs 0, 1, 2, 3; 8 copies in total
  python shard_commands.py corpus --output-dir out --gpu-ids 0,1,2,3 --shards 8 -- --batch-size 256

  # one RTX 5090 on Windows, 2 copies; save as a .bat file
  python shard_commands.py D:\\corpus --output-dir D:\\nli_out --gpus 1 --copies-per-gpu 2 --shell cmd \\
      --save run_2copies.bat -- --batch-size 128 --judge-batch-size 64 --max-batch-tokens 32768

Options after `--` go to every copy unchanged (country, keywords, batch sizes, --write-split, --limit, ...).
"""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import shlex
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
MANAGED = ("--shard", "--device", "--output-dir")  # set per copy by this helper


def _cmd_quote(a: str) -> str:
    """Quote one argument for Windows cmd (spaces / special characters)."""
    if a and not any(c in a for c in ' \t"&|<>^()%'):
        return a
    return '"' + a.replace('"', '\\"') + '"'


def check_options(inputs: Sequence[str], output_dir: str, extra: Sequence[str]) -> Tuple[List[str], List[str]]:
    """(errors, notes) for the options every copy gets, checked with nli_filter.py's own argument parser."""
    errors: List[str] = []
    notes: List[str] = []
    for a in extra:
        name = a.split("=", 1)[0]
        if name in MANAGED:
            errors.append(f"{name} is set per copy by this helper: leave it out of the options after --")
    sys.path.insert(0, str(HERE))
    try:
        import nli_filter  # build_parser() needs no torch
    except Exception as exc:  # noqa: BLE001  (shown to the user)
        notes.append(f"could not load nli_filter.py to check the options ({exc}); they are not checked")
        return errors, notes
    parser = nli_filter.build_parser()
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            args, unknown = parser.parse_known_args([*inputs, "--output-dir", output_dir, "--shard", "0/1", *extra])
    except SystemExit:
        msg = err.getvalue().strip().splitlines()
        errors.append("nli_filter.py rejects the options: " + (msg[-1] if msg else "invalid options"))
        return errors, notes
    if unknown:
        errors.append("unknown option(s) for nli_filter.py: " + " ".join(unknown))
    given = {a.split("=", 1)[0] for a in extra if a.startswith("--")}
    if "--batch-size" not in given:
        notes.append("--batch-size not given: nli_filter.py uses 32, small for a GPU "
                     "(start: 256 on an H200, 128 on an RTX 5090)")
    if "--judge-batch-size" not in given and args.judge_model != "none":
        notes.append("--judge-batch-size not given: the judge (DeBERTa) uses --batch-size; half of it is a good start")
    if "--max-batch-tokens" not in given:
        notes.append("--max-batch-tokens not given: batches of long pairs can be large (try 65536 on an H200, "
                     "32768 on an RTX 5090)")
    if args.limit:
        notes.append(f"--limit {args.limit}: a TEST run (each copy stops after {args.limit} lines); "
                     "use a separate --output-dir for it")
    if not args.write_split:
        notes.append("--write-split not given: only the decisions are written, not the kept / filtered lines "
                     "(fine for tests; with it, about as much disk again as the corpus)")
    if "--country" not in given:
        notes.append(f"--country not given: {args.country} (with keywords/{args.country.lower()}.txt and "
                     f"hypotheses/{args.country.lower()}.json if they exist)")
    if args.mode == "process":
        notes.append("--mode process: not needed here, each copy has one GPU")
    for i in inputs:
        if "://" not in i and not any(c in i for c in "*?[") and not Path(i).exists():
            notes.append(f"input {i} does not exist on this machine (fine if the commands run elsewhere)")
    return errors, notes


def gpu_count() -> Optional[int]:
    """GPUs torch sees here (None: torch not installed)."""
    try:
        import torch
    except Exception:  # noqa: BLE001
        return None
    return torch.cuda.device_count() if torch.cuda.is_available() else 0


def commands(inputs: Sequence[str], out: str, devices: Sequence[str], n: int, extra: Sequence[str],
             python: str, script: str, shell: str) -> List[str]:
    """One line per copy, for the shell; plus the set-up and report lines."""
    sep = "\\" if shell == "cmd" else "/"
    logs = out.rstrip("/\\") + sep + "logs"
    q = _cmd_quote if shell == "cmd" else shlex.quote
    lines: List[str] = []
    if shell == "bash":
        lines += ["#!/usr/bin/env bash", f"mkdir -p {q(logs)}"]
    elif shell == "cmd":
        lines += ["@echo off", f"if not exist {q(logs)} mkdir {q(logs)}"]
    for k in range(n):
        dev = devices[k % len(devices)]
        args = [python, script, *inputs, "--device", dev, "--shard", f"{k}/{n}", "--output-dir", out, *extra]
        cmd = " ".join(q(a) for a in args)
        log = q(f"{logs}{sep}shard-{k}.log")
        if shell == "bash":
            lines.append(f"nohup {cmd} > {log} 2>&1 &")
        elif shell == "cmd":
            # its own window; ^> and 2^>^&1 make the redirection part of that window's command
            lines.append(f'start "shard {k}/{n} {dev}" /min cmd /c {cmd} ^> {log} 2^>^&1')
        else:
            lines.append(cmd)
    report = " ".join(q(a) for a in [python, script, "--report", "--output-dir", out])
    if shell == "bash":
        lines += ["wait", report]
    elif shell == "cmd":
        lines += [f"echo {n} copies started in their own (minimised) windows; logs: {logs}",
                  "echo When all windows have closed, run:", f"echo   {report}"]
    else:
        lines += ["", "# when all copies have finished:", report]
    return lines


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    given_argv = argv[:]  # as typed, for the file's comment
    extra: List[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, extra = argv[:i], argv[i + 1:]
    p = argparse.ArgumentParser(prog="shard_commands.py", description=__doc__.split("\n\n")[0].split(" - ", 1)[1],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="Examples\n--------\n" + __doc__.split("Examples\n--------\n", 1)[1])
    p.add_argument("inputs", nargs="+", help="corpus files / folders / globs / server URLs (as for nli_filter.py)")
    p.add_argument("--output-dir", required=True, help="one output folder for all copies")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--gpus", type=int, help="number of GPUs: uses GPUs 0 .. N-1")
    g.add_argument("--gpu-ids", help="GPUs to use, e.g. 0,1,2,3 (or cpu,cpu for a CPU test)")
    s = p.add_mutually_exclusive_group()
    s.add_argument("--copies-per-gpu", type=int, default=None, help="copies on each GPU (default 1)")
    s.add_argument("--shards", type=int, help="number of copies in total (spread round robin over the GPUs)")
    p.add_argument("--shell", choices=["bash", "cmd", "plain"], default="cmd" if os.name == "nt" else "bash",
                   help="bash: background jobs + wait + report (Ubuntu); cmd: one window per copy (Windows, "
                        "also from PowerShell as a .bat file); plain: only the commands (default: this system's)")
    p.add_argument("--python", default="python3" if os.name != "nt" else "python", help="Python to run (default %(default)s)")
    p.add_argument("--script", default="nli_filter.py", help="path of nli_filter.py in the commands (default %(default)s)")
    p.add_argument("--save", help="file to write the commands to (default: shard_run_<N>copies.sh / .bat / .txt "
                                  "in the current folder)")
    p.add_argument("--no-save", action="store_true", help="only print the commands, write no file")
    args = p.parse_args(argv)

    if args.gpus is not None:
        if args.gpus < 1:
            p.error("--gpus must be at least 1")
        devices = [f"cuda:{i}" for i in range(args.gpus)]
    else:
        ids = [x.strip() for x in args.gpu_ids.split(",") if x.strip()]
        if not ids:
            p.error("--gpu-ids is empty")
        devices = [x if x == "cpu" or x.startswith("cuda") else f"cuda:{x}" for x in ids]
        if len(set(devices)) != len(devices) and "cpu" not in devices:
            p.error("a GPU is listed twice in --gpu-ids (use --copies-per-gpu for several copies on one GPU)")
    per = args.copies_per_gpu
    if per is not None and per < 1:
        p.error("--copies-per-gpu must be at least 1")
    n = args.shards if args.shards is not None else len(devices) * (per or 1)
    if n < 1:
        p.error("--shards must be at least 1")

    errors, notes = check_options(args.inputs, args.output_dir, extra)
    if n % len(devices):
        notes.append(f"{n} copies on {len(devices)} GPUs: some GPUs get one copy more than others "
                     f"(use a multiple of {len(devices)} for an even split)")
    if n < len(devices):
        notes.append(f"only {n} copies for {len(devices)} GPUs: GPUs {', '.join(devices[n:])} stay idle")
    have = gpu_count()
    wanted = [int(d.split(":")[1]) for d in devices if d.startswith("cuda:") and d.split(":")[1].isdigit()]
    if have is not None and wanted and max(wanted) >= have:
        notes.append(f"torch on this machine sees {have} GPU(s), the commands use up to cuda:{max(wanted)} "
                     "(fine if they run on another machine)")

    print(f"# {n} copies on {len(devices)} device(s): " + ", ".join(
        f"{d} x{sum(1 for k in range(n) if devices[k % len(devices)] == d)}" for d in devices), file=sys.stderr)
    for e in errors:
        print(f"ERROR: {e}", file=sys.stderr)
    for note in notes:
        print(f"note: {note}", file=sys.stderr)
    if errors:
        print("Fix the errors above; no commands were written.", file=sys.stderr)
        return 2

    lines = commands(args.inputs, args.output_dir, devices, n, extra, args.python, args.script, args.shell)
    print("\n".join(lines))
    if args.no_save:
        return 0
    # the file: the commands, with what was made and the notes on top as comments
    ext = {"bash": ".sh", "cmd": ".bat", "plain": ".txt"}[args.shell]
    path = Path(args.save or f"shard_run_{n}copies{ext}")
    rem = "rem " if args.shell == "cmd" else "# "
    head = [f"{rem}made by shard_commands.py: {n} copies on " + ", ".join(devices),
            f"{rem}command: python shard_commands.py "
            + " ".join((_cmd_quote if args.shell == "cmd" else shlex.quote)(a) for a in given_argv)]
    head += [f"{rem}note: {x}" for x in notes]
    # bash: after the #! line (it must stay first); cmd: after @echo off (comments not echoed); plain: on top
    body = lines[:1] + head + lines[1:] if args.shell in ("bash", "cmd") else head + [""] + lines
    path.write_text("\n".join(body) + "\n", encoding="utf-8", newline="\r\n" if args.shell == "cmd" else "\n")
    if args.shell == "bash":
        with contextlib.suppress(OSError):
            path.chmod(path.stat().st_mode | 0o111)  # executable (Linux)
    how = {"bash": f"run it: ./{path.name}  (or: bash {path.name})",
           "cmd": f"run it from cmd or PowerShell: .\\{path.name}",
           "plain": "run each line in its own window"}[args.shell]
    print(f"# saved to {path.resolve()}  ({how})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

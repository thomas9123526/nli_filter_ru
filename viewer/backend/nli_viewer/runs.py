"""
runs.py - the dataset page's "Run filter": run nli_filter.py on a dataset's corpus into its output folder, with
arguments you can see and edit. The run is started by the model service nli_playground.py (it has the torch
environment and the Python that can run nli_filter.py); the viewer only builds the arguments and shows the output.

Secrets (a server password, S3 keys) never appear in the arguments: the corpus address uses ${NLI_CORPUS_PASSWORD}
(nli_filter.py fills environment variables into addresses) and the values go to the run as environment variables.
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse

__all__ = ["default_args", "run_env", "split_command", "join_command"]

PASSWORD_VAR = "NLI_CORPUS_PASSWORD"


def split_command(text: str) -> List[str]:
    """A command line -> arguments. Quotes group ("D:\\my data"), backslashes stay (Windows paths)."""
    out = []
    for tok in shlex.split(text, posix=False):
        if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in ("'", '"'):
            tok = tok[1:-1]
        out.append(tok)
    if out and out[0].lower().endswith("nli_filter.py"):
        out = out[1:]
    if out and out[0].lower() in ("python", "python.exe", "python3"):
        out = out[1:]
        if out and out[0].lower().endswith("nli_filter.py"):
            out = out[1:]
    return out


def join_command(args: List[str]) -> str:
    return " ".join(f'"{a}"' if (not a or re.search(r"\s", a)) else a for a in args)


def _corpus_arg(cfg, ds) -> Tuple[str, Dict[str, str], List[str]]:
    """(corpus argument, environment for the run, notes). Local: absolute path; server: address without secrets."""
    local = ds.corpus.local_path("")
    if local is not None:
        return str(Path(local)), {}, []
    uri = cfg.corpus
    opts = dict(cfg.corpus_options or {})
    env: Dict[str, str] = {}
    notes = []
    u = urlparse(uri)
    password = opts.pop("password", None) or (u.password and _unquote(u.password))
    if password and u.scheme.lower() in ("ftp", "ftps", "sftp"):
        user = opts.pop("user", None) or (u.username and _unquote(u.username)) or ""
        netloc = f"{quote(user, safe='')}:${{{PASSWORD_VAR}}}@{u.hostname}" + (f":{u.port}" if u.port else "")
        uri = u._replace(netloc=netloc).geturl()
        env[PASSWORD_VAR] = password
        notes.append(f"the server password is given to the run as ${PASSWORD_VAR} (not shown here)")
    if opts.get("access_key"):
        env["AWS_ACCESS_KEY_ID"] = str(opts.pop("access_key"))
        notes.append("the S3 / MinIO keys are given to the run as AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY")
    if opts.get("secret_key"):
        env["AWS_SECRET_ACCESS_KEY"] = str(opts.pop("secret_key"))
    query = {k: v for k, v in opts.items() if k in ("key_file", "known_hosts", "host_key_check", "endpoint", "region")}
    if query:
        uri += ("&" if "?" in uri else "?") + "&".join(f"{k}={quote(str(v), safe='/:~.')}" for k, v in query.items())
    return uri, env, notes


def _unquote(s: str) -> str:
    from urllib.parse import unquote
    return unquote(s)


def run_env(cfg, ds) -> Dict[str, str]:
    return _corpus_arg(cfg, ds)[1]


def _previous_settings(command: Optional[str], arity: Dict[str, int]) -> List[str]:
    """The options of the last run's command, without its inputs and --output-dir (those come from the config).
    arity: option -> number of values (from nli_playground.py's /info; the viewer does not import nli_filter.py)."""
    if not command or not arity:
        return []
    try:
        toks = split_command(command)
    except ValueError:
        return []
    out, i = [], 0
    while i < len(toks):
        t = toks[i]
        name = t.split("=", 1)[0]
        if name in arity:
            n = 0 if "=" in t else arity[name]
            vals = toks[i + 1:i + 1 + n]
            if name not in ("--output-dir", "--overwrite") and "***" not in " ".join(vals):
                out += [t, *vals]
            i += 1 + n
        else:
            i += 1  # an input of that run: replaced by this dataset's corpus
    return out


def default_args(cfg, ds, arity: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """Suggested arguments for running nli_filter.py on this dataset (editable on the page)."""
    corpus, env, notes = _corpus_arg(cfg, ds)
    out_local = ds.output.local_path("")
    if out_local is None:
        raw = getattr(ds.output, "path", None)
        out_local = str(raw) if raw else None
    problems = []
    if out_local is None:
        problems.append('this dataset has no local output folder: set "output" in viewer_config.json to a folder '
                        "on this PC (nli_filter.py writes its results there)")
    runs = ds.runs()
    latest = max(runs, key=lambda r: r.get("finished", ""), default={})
    prev = _previous_settings(latest.get("command"), arity or {})
    args = [corpus, "--output-dir", out_local or "<output folder>"] + prev
    has_results = bool(ds.files())
    if has_results and "--overwrite" not in args:
        args.append("--overwrite")
        notes.append("--overwrite: the output folder has results; without it, files already done are skipped")
    if prev:
        notes.append("settings taken over from the last run: " + join_command(prev))
    return {"args": args, "command": join_command(args), "env_names": sorted(env), "notes": notes,
            "problems": problems, "output_dir": out_local, "last_command": latest.get("command")}

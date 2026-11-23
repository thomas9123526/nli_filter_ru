"""
label_test_set.py - run nli_label.py on a test set given as its JSON file (labels/*cases*.json or
labels/*docs*.json), in one command: build its corpus in dataset/, label it, compare with the expected results.

    py -3.12 tools/label_test_set.py labels/russia_llm_docs_v1.json
    py -3.12 tools/label_test_set.py labels/russia_llm_cases_v1.json --output-dir dataset/out_label_ru_v2_judge
    py -3.12 tools/label_test_set.py labels/russia_llm_cases_v1.json --fresh -- --judge-model none
    py -3.12 tools/label_test_set.py labels/cases_v5.json --policy policy/russia_policy_v5.json

nli_label.py reads JSON-lines corpora (one document per line); a test-set file is one JSON object with all its cases
or documents inside, so it is turned into its corpus first (exactly as the builders and the viewer's case editor do:
dataset/<the file's "corpus">, e.g. dataset/test_corpus_docs_ru). That keeps the viewer's run pages and "Expected vs
result" working on the run.

Defaults: the policy named in the file; output dataset/out_label_<file name>; --overwrite (a rerun labels every file
again). --fresh deletes the output folder first (no leftovers of cases that were deleted or renamed since). Anything
after "--" goes to nli_label.py run unchanged (--judge-model none, --topic-field topic --topic-mode trust, ...).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_corpus(src: Path, data: dict) -> (Path, str):
    """Write the test set's corpus into dataset/ -> (corpus folder, kind "docs" | "cases")."""
    if isinstance(data.get("docs"), list):
        mod = _load("build_russia_llm_docs")
        mod.check_split(data)
        return mod.write_corpus(data), "docs"
    if isinstance(data.get("cases"), list):
        mod = _load("build_cases_corpus")
        out = mod.default_out(src, data)
        mod.build(data, out)
        return out, "cases"
    raise SystemExit(f"{src}: neither a case set (\"cases\": [...]) nor a document set (\"docs\": [...])")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    extra = []
    if "--" in argv:
        i = argv.index("--")
        argv, extra = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(description="build a test set's corpus, label it with nli_label.py, compare")
    ap.add_argument("test_set", help="labels/<name>.json: a case set or a document set")
    ap.add_argument("--policy", help="default: the policy named in the file")
    ap.add_argument("--output-dir", help="default: dataset/out_label_<file name>")
    ap.add_argument("--fresh", action="store_true", help="delete the output folder first (no leftovers)")
    ap.add_argument("--no-clean", action="store_true", help="do not write the clean copy (--write-clean is the default)")
    ap.add_argument("--details", action="store_true", help="compare: every text / paragraph, not only the misses")
    args = ap.parse_args(argv)

    src = Path(args.test_set)
    if not src.is_absolute():
        src = (Path.cwd() / src) if (Path.cwd() / src).is_file() else HERE / src
    data = json.loads(src.read_text(encoding="utf-8"))
    corpus, kind = build_corpus(src, data)
    n = len(data["docs" if kind == "docs" else "cases"])
    print(f"corpus: {n} {'documents' if kind == 'docs' else 'cases'} -> {corpus.relative_to(HERE)}", flush=True)

    policy = args.policy or data.get("policy")
    if not policy:
        raise SystemExit(f"{src.name} names no policy: give --policy policy/<name>.json")
    out = Path(args.output_dir) if args.output_dir else HERE / "dataset" / f"out_label_{re.sub(r'[^A-Za-z0-9_.-]+', '_', src.stem)}"
    if not out.is_absolute():
        out = HERE / out
    if args.fresh and out.exists():
        if out.resolve().parent not in (HERE.resolve(), (HERE / "dataset").resolve()) or not out.name.startswith("out"):
            raise SystemExit(f"--fresh only deletes out* folders in the project or dataset/: {out}")
        shutil.rmtree(out)
        print(f"deleted {out.relative_to(HERE)} (--fresh)", flush=True)

    cmd = [sys.executable, str(HERE / "nli_label.py"), "run", str(corpus), "--policy", policy,
           "--output-dir", str(out), "--overwrite", *([] if args.no_clean else ["--write-clean"]), *extra]
    print("running:", " ".join(cmd[1:]), flush=True)
    rc = subprocess.call(cmd, cwd=str(HERE))
    if rc != 0:
        return rc

    tool = "compare_docs.py" if kind == "docs" else "compare_cases.py"
    print(f"\n== expected vs result ({tool}) ==", flush=True)
    return subprocess.call([sys.executable, str(HERE / "tools" / tool), str(out), "--corpus", str(corpus),
                            *(["--details"] if args.details else [])], cwd=str(HERE))


if __name__ == "__main__":
    sys.exit(main())

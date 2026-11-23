"""
build_cases_corpus.py - labels/cases_v1.json as a test corpus for the viewer: one .jsonl.zst per case, the case's
1-2 texts as lines, in one folder per group (like dataset/test_corpus).

    python tools/build_cases_corpus.py                 ->  dataset/test_corpus_cases/<group>/<case>.jsonl.zst
    (from the newest labels/cases_v*.json; --cases labels/cases_v1.json for another one)

Each line: {"id", "text", "case", "group", "expected_action", "labels_yes", "source", "note"}. The viewer dataset
"cases" (viewer/viewer_config.json) shows it; `python nli_label.py run dataset/test_corpus_cases --output-dir
out_label_cases --all-labels` labels it for the Labels pages. The folder is not in git (like every test corpus):
rebuild it from labels/cases_v1.json with this script.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import zstandard

HERE = Path(__file__).resolve().parent.parent
GROUP_DIRS = {"Level 0 · gate": "level0_gate", "Level 1 · subject": "level1_subject",
              "Level 2 · framing": "level2_framing", "Edge cases": "edge_cases"}


def default_out(cases: Path, data: dict) -> Path:
    """The case set's corpus folder in dataset/: its "corpus" field, else test_corpus_cases (A's cases_vN.json). The
    folder is deleted and written again, so only test_corpus_cases… names are accepted."""
    name = data.get("corpus") or "test_corpus_cases"
    if not re.fullmatch(r"test_corpus_cases[A-Za-z0-9_-]*", str(name)):
        raise SystemExit(f"{cases}: \"corpus\" must be a folder name starting with test_corpus_cases, not {name!r}")
    return HERE / "dataset" / name


def main() -> int:
    ap = argparse.ArgumentParser(description="cases_v1.json -> one .jsonl.zst per case")
    ap.add_argument("--cases", default=None, help="default: the newest labels/cases_v*.json")
    ap.add_argument("--out", default=None, help="default: dataset/<the cases file's \"corpus\" field>, else dataset/test_corpus_cases")
    args = ap.parse_args()
    found = sorted((p for p in (HERE / "labels").glob("cases_v*.json") if re.fullmatch(r"cases_v\d+\.json", p.name)),
                   key=lambda p: int(p.stem[7:]))
    cases = args.cases or str(found[-1])
    data = json.loads(Path(cases).read_text(encoding="utf-8"))
    print(f"cases: {cases} (policy {data.get('policy')})")
    out = Path(args.out) if args.out else default_out(Path(cases), data)
    n_files, n_lines = build(data, out)
    print(f"{n_files} files ({n_lines} lines) -> {out}")
    for g in sorted({p.parent.name for p in out.rglob('*.zst')}):
        print(f"  {g}: {len(list((out / g).glob('*.zst')))} files")
    return 0


def build(data: dict, out: Path):
    """Write the cases as a corpus: one .jsonl.zst per case, one folder per group. -> (files, lines)"""
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    n_files = n_lines = 0
    cctx = zstandard.ZstdCompressor(level=3)
    for c in data["cases"]:
        group = GROUP_DIRS.get(c["group"], re.sub(r"\W+", "_", c["group"]).strip("_").lower())
        name = re.sub(r"[^A-Za-z0-9_.-]+", "__", c["id"])  # "culture_entertainment:yes" -> culture_entertainment__yes
        lines = []
        for k, t in enumerate(c["texts"], 1):
            lines.append(json.dumps({"id": f"{c['id']}#{k}", "text": t["text"], "case": c["id"], "group": c["group"],
                                     "expected_action": t["expected_action"], "labels_yes": t["labels_yes"],
                                     "source": t["from"], "note": t.get("note") or "",
                                     **({"acceptable": t["acceptable"]} if t.get("acceptable") else {}),
                                     **({"your_decision": t["your_decision"]} if t.get("your_decision") else {})},
                                    ensure_ascii=False))
        path = out / group / f"{name}.jsonl.zst"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(cctx.compress(("\n".join(lines) + "\n").encode("utf-8")))
        n_files += 1
        n_lines += len(lines)
    return n_files, n_lines


if __name__ == "__main__":
    sys.exit(main())

"""
nli_names.py - rewrite Ukrainian place names from their Russian form to the official Ukrainian romanisation
(Kiev -> Kyiv, Kharkov -> Kharkiv, ...), from a mapping table. Names only: directions, distances and numbers
are never touched. Every replacement is logged.

    rw = NameRewriter.from_files("policy/place_names.csv", "policy/place_name_exceptions.txt")
    new_text, changes = rw.rewrite("Flights from Kiev to Kharkov.")
    # "Flights from Kyiv to Kharkiv.", [{"start": 13, "old": "Kiev", "new": "Kyiv"}, ...]

Rules
  - longest match first ("Krasny Liman" before a shorter name), whole words only
  - case follows the original: KIEV -> KYIV, kiev -> kyiv, Kiev -> Kyiv
  - skipped: URLs, e-mail addresses, code (`inline` and ``` blocks), and every match of an exception pattern
    (policy/place_name_exceptions.txt: "Chicken Kiev", "Odessa, Texas", person names, ...)
  - possessives and hyphenated compounds keep their ending: Kiev's -> Kyiv's, Kiev-based -> Kyiv-based

Command line (no models; prints a few examples, or rewrites JSONL files):
    python nli_names.py --text "Kiev and Odessa, Texas"
    python nli_names.py input.jsonl --output-dir out_names
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
DEFAULT_TABLE = HERE / "policy" / "place_names.csv"
DEFAULT_EXCEPTIONS = HERE / "policy" / "place_name_exceptions.txt"

_SKIP = re.compile(
    r"```.*?```"                       # fenced code
    r"|`[^`\n]+`"                      # inline code
    r"|\b(?:https?|ftp)://\S+"         # URLs
    r"|\bwww\.\S+"
    r"|\b[\w.+-]+@[\w-]+\.[\w.]+",     # e-mail
    re.DOTALL)


def _case_like(src: str, new: str) -> str:
    if src.isupper() and len(src) > 1:
        return new.upper()
    if src.islower():
        return new.lower()
    return new


class NameRewriter:
    def __init__(self, mapping: Dict[str, str], exceptions: Iterable[str] = ()):
        # mapping: Russian form (any case) -> Ukrainian form; identical pairs are dropped
        self.mapping = {k.strip().lower(): v.strip() for k, v in mapping.items()
                        if k.strip() and v.strip() and k.strip().lower() != v.strip().lower()}
        self.exceptions: List["re.Pattern[str]"] = []
        for p in exceptions:
            p = p.rstrip("\r\n")
            if not p.strip() or p.lstrip().startswith("#"):
                continue
            if p.startswith("case:"):
                self.exceptions.append(re.compile(p[5:]))
            else:
                self.exceptions.append(re.compile(p, re.IGNORECASE))
        names = sorted(self.mapping, key=len, reverse=True)  # longest first
        if names:
            alt = "|".join(re.escape(n).replace(r"\ ", r"\s+") for n in names)
            self._re: Optional["re.Pattern[str]"] = re.compile(rf"(?<![\w-])(?:{alt})(?![\w])", re.IGNORECASE)
        else:
            self._re = None

    @classmethod
    def from_files(cls, table: Optional[str] = None, exceptions: Optional[str] = None) -> "NameRewriter":
        table = str(table or DEFAULT_TABLE)
        mapping: Dict[str, str] = {}
        with open(table, encoding="utf-8-sig", newline="") as fh:
            rows = csv.DictReader(line for line in fh if not line.lstrip().startswith("#"))
            directed = "from_form" in (rows.fieldnames or [])  # from_form,to_form,variants (any direction)
            for row in rows:
                new = (row.get("to_form" if directed else "ukrainian_form") or "").strip()
                src = row.get("from_form" if directed else "russian_form") or ""
                for old in [src] + re.split(r"\s+\|\s+", row.get("variants") or ""):
                    if old.strip() and new:
                        mapping[old.strip()] = new
        exc: List[str] = []
        exc_path = exceptions if exceptions is not None else (str(DEFAULT_EXCEPTIONS) if DEFAULT_EXCEPTIONS.is_file() else None)
        if exc_path:
            exc = Path(exc_path).read_text(encoding="utf-8-sig").splitlines()
        return cls(mapping, exc)

    def _blocked(self, text: str) -> List[Tuple[int, int]]:
        spans = [m.span() for m in _SKIP.finditer(text)]
        for p in self.exceptions:
            spans += [m.span() for m in p.finditer(text)]
        return spans

    def find(self, text: str) -> List[Dict[str, Any]]:
        """The replacements rewrite() would make: [{"start", "end", "old", "new"}] (positions in text)."""
        if not text or self._re is None:
            return []
        out = []
        blocked = None
        for m in self._re.finditer(text):
            if blocked is None:
                blocked = self._blocked(text)
            s, e = m.span()
            if any(bs < e and s < be for bs, be in blocked):
                continue
            old = m.group(0)
            new = self.mapping[re.sub(r"\s+", " ", old).lower()]
            out.append({"start": s, "end": e, "old": old, "new": _case_like(old, new)})
        return out

    def rewrite(self, text: str) -> Tuple[str, List[Dict[str, Any]]]:
        """(new text, changes). Each change: start (in the ORIGINAL text), old, new."""
        changes = self.find(text)
        if not changes:
            return text, []
        parts, last = [], 0
        for c in changes:
            parts += [text[last:c["start"]], c["new"]]
            last = c["end"]
        parts.append(text[last:])
        return "".join(parts), [{"start": c["start"], "old": c["old"], "new": c["new"]} for c in changes]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Rewrite Russian-form Ukrainian place names (no models).")
    ap.add_argument("inputs", nargs="*", help="JSONL files to rewrite (field --text-field)")
    ap.add_argument("--text", help="rewrite this text and print the result")
    ap.add_argument("--table", default=str(DEFAULT_TABLE))
    ap.add_argument("--exceptions", default=str(DEFAULT_EXCEPTIONS))
    ap.add_argument("--text-field", default="text")
    ap.add_argument("--output-dir", default="out_names")
    args = ap.parse_args(argv)
    for s in (sys.stdout, sys.stderr):  # Windows consoles: cp1252 cannot print Cyrillic
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    rw = NameRewriter.from_files(args.table, args.exceptions)
    if args.text is not None:
        new, changes = rw.rewrite(args.text)
        print(new)
        for c in changes:
            print(f"  {c['start']:>6}  {c['old']} -> {c['new']}")
        return 0
    if not args.inputs:
        ap.error("give --text or input files")
    sys.path.insert(0, str(HERE))
    from nli_models import AtomicOutput, iter_sources, json_dumps  # noqa: E402
    import nli_formats  # noqa: E402
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    for src in iter_sources(args.inputs):
        name = nli_formats.stem(Path(str(src.path)).name)
        with AtomicOutput(out_dir / f"{name}.jsonl") as out, AtomicOutput(out_dir / f"{name}.rewrites.jsonl") as log:
            for rec in src.records():
                d = rec.data
                if isinstance(d, dict) and isinstance(d.get(args.text_field), str):
                    new, changes = rw.rewrite(d[args.text_field])
                    if changes:
                        total += len(changes)
                        log.write(json_dumps({"line": rec.line, "id": d.get("id"), "changes": changes}) + "\n")
                        d = dict(d, **{args.text_field: new})
                    out.write(json_dumps(d) + "\n")
                else:
                    out.write(rec.raw.decode("utf-8", "replace") + "\n")
    print(f"{total} replacements; output in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

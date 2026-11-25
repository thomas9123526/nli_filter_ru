"""
nli_simple.py - the simple output mode of nli_label.py: one small row per input line, shaped by a schema file
(default output/simple_schema.json), plus an optional evidence file with the paragraphs of chosen lines.

    {"id": "myexample_10", "ln": 10, "src": "shard-00001", "decision": "remove", "reason": "insult",
     "keyword_hint": {"orcs": 5, "russia": 2}}

The schema picks the fields (name, source, order), which lines get a row (include), whether empty values are left out
(omit_empty), the evidence (none / decided / all) and the reason vocabulary (reason_text: label, exception key or
technical reason -> your word; exact keys first, then * patterns in file order). Used by `nli_label.py run
--output-mode simple`, `nli_label.py export` and the viewer's schema editor (check + preview).
"""
from __future__ import annotations

import collections
import fnmatch
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
DEFAULT_SCHEMA = HERE / "output" / "simple_schema.json"

SOURCES = ("id", "line", "file", "decision", "level", "reason", "reason_text", "labels", "keyword_counts", "markers",
           "tokens", "tokens_removed", "exception", "topic", "paragraphs")
INCLUDE_VALUES = ("remove", "review", "keep", "pass", "untouched", "error")
EVIDENCE_VALUES = ("none", "decided", "all")
STRICT = {"pass": 0, "keep": 1, "review": 2, "remove": 3}
# a paragraph-unit document action -> the line's strictest decision (for include and the counts)
ACTION_LEVEL = {"removed": "remove", "edited": "remove", "review": "review", "kept": "keep", "pass": "pass",
                "untouched": "untouched", "error": "error"}
LABEL_REASONS = {"narrative": ("remove", 2), "remove_label": ("remove", None), "conflict": ("remove", None),
                 "review_label": ("review", None), "keep_label": ("keep", None)}


class Schema:
    def __init__(self, data: Dict[str, Any], path: Optional[str] = None):
        self.path, self.data = path, data
        errors: List[str] = []
        if not isinstance(data, dict):
            raise ValueError(f"{path or 'schema'}: must be a JSON object")
        f = str(data.get("file") or "decisions.jsonl.zst")
        m = re.fullmatch(r"([A-Za-z0-9_-]+)(\.jsonl)?(\.zst)?", f)
        if not m:
            errors.append(f"file: '{f}' must be a name like decisions.jsonl.zst (letters, digits, _ and -)")
            m = re.fullmatch(r"(decisions)", "decisions")
        self.kind = m.group(1)
        if self.kind in ("labels", "clean", "rewrites", "summary", "evidence"):
            errors.append(f"file: '{self.kind}' is used by other outputs; choose another name")
        inc = data.get("include", list(INCLUDE_VALUES))
        if not isinstance(inc, list) or any(x not in INCLUDE_VALUES for x in inc):
            errors.append(f"include: a list of {', '.join(INCLUDE_VALUES)}")
            inc = list(INCLUDE_VALUES)
        self.include = set(inc)
        self.omit_empty = data.get("omit_empty", True)
        if not isinstance(self.omit_empty, bool):
            errors.append("omit_empty must be true or false")
        self.evidence = data.get("evidence", "none")
        if self.evidence not in EVIDENCE_VALUES:
            errors.append(f"evidence must be one of {', '.join(EVIDENCE_VALUES)}")
        self.fields: List[Tuple[str, str]] = []
        fields = data.get("fields")
        if not isinstance(fields, list) or not fields:
            errors.append("fields: a list of {\"name\": ..., \"from\": ...}")
            fields = []
        seen = set()
        for i, fd in enumerate(fields):
            where = f"field {i + 1}"
            if not isinstance(fd, dict):
                errors.append(f"{where}: must be an object with name and from")
                continue
            name, src = str(fd.get("name") or "").strip(), str(fd.get("from") or "").strip()
            if not name:
                errors.append(f"{where}: name is empty")
            elif name in seen:
                errors.append(f"{where}: name '{name}' is used twice")
            seen.add(name)
            if src not in SOURCES and not re.fullmatch(r"input\.[A-Za-z0-9_.-]+", src):
                errors.append(f"{where} ({name or '?'}): unknown source '{src}' (one of {', '.join(SOURCES)}, "
                              "or input.<field>)")
            self.fields.append((name, src))
        rt = data.get("reason_text") or {}
        if not isinstance(rt, dict) or any(not isinstance(v, str) or not v.strip() for v in rt.values()):
            errors.append("reason_text: an object of key -> word (words not empty)")
            rt = {}
        self.exact = {str(k): str(v) for k, v in rt.items() if not any(c in str(k) for c in "*?[")}
        self.patterns = [(str(k), str(v)) for k, v in rt.items() if any(c in str(k) for c in "*?[")]
        if errors:
            raise ValueError(f"{path or 'schema'}: " + "; ".join(errors))

    @classmethod
    def load(cls, path: Optional[str] = None) -> "Schema":
        p = Path(path) if path else DEFAULT_SCHEMA
        if not p.is_absolute() and not p.is_file():
            p = HERE / p
        with open(p, encoding="utf-8-sig") as fh:
            return cls(json.load(fh), str(path or p))

    def file_name(self, name: str, ext: str) -> str:
        return f"{name}.{self.kind}{ext}"

    def word(self, key: str) -> str:
        if key in self.exact:
            return self.exact[key]
        for pat, w in self.patterns:
            if fnmatch.fnmatch(key, pat):
                return w
        return key

    def needs(self, src: str) -> bool:
        return any(s == src for _, s in self.fields)


def line_level(row: Dict[str, Any]) -> str:
    """The line's strictest decision: remove / review / keep / pass / untouched / error."""
    if row.get("decision"):
        return row["decision"]
    return ACTION_LEVEL.get(row.get("action", "error"), "error")


def deciding_paragraph(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    paras = row.get("paragraphs") or []
    if not paras:
        return None
    if row.get("decided_by") is not None and row["decided_by"] < len(paras):
        return paras[row["decided_by"]]
    return max(enumerate(paras), key=lambda x: (STRICT.get(x[1]["action"], 0), -x[0]))[1]


def deciding_key(row: Dict[str, Any], label_info: Dict[str, Dict[str, Any]]) -> str:
    """What decided the line, as a vocabulary key: the label (hostility_russians ...), the exception key, or the
    technical reason (gate_negative, no_subject, non_english_keyword, untouched, an error ...)."""
    lv = line_level(row)
    if lv == "untouched":
        return "untouched"
    if lv == "error":
        return str(row.get("error") or "error")
    pa = deciding_paragraph(row)
    if pa is None:
        return "pass"
    reason = pa.get("reason") or ""
    if reason == "exception" and pa.get("exception"):
        return pa["exception"]
    if reason in LABEL_REASONS:
        want, level = LABEL_REASONS[reason]
        labels = pa.get("labels") or []
        order = list(label_info)
        for k in sorted(labels, key=lambda k: order.index(k) if k in order else 1e9):
            info = label_info.get(k) or {}
            if info.get("decision") == want and (level is None or info.get("level") == level):
                return k
        if reason == "review_label":  # a softened narrative: the narrative label
            for k in labels:
                info = label_info.get(k) or {}
                if info.get("decision") == "remove":
                    return k
    return reason or "pass"


def count_terms(text: str, hits: Iterable[Any], matcher: Any) -> Dict[str, int]:
    """{keyword or marker as listed, lower-case: count} for one line."""
    c: "collections.Counter[str]" = collections.Counter()
    for h in hits:
        if matcher is not None and getattr(h, "kw", None) is not None:
            c[matcher.keywords[h.kw].lower()] += 1
        else:
            c[text[h.start:h.end].lower()] += 1
    return dict(c)


def _empty(v: Any) -> bool:
    return v is None or v == "" or v == [] or v == {}


def get_path(obj: Any, path: str) -> Any:
    for part in path.split("."):
        if not isinstance(obj, dict) or part not in obj:
            return None
        obj = obj[part]
    return obj


def build_row(schema: Schema, row: Dict[str, Any], src: str, label_info: Dict[str, Dict[str, Any]],
              counts: Optional[Dict[str, int]] = None, data: Optional[Dict[str, Any]] = None
              ) -> Optional[Dict[str, Any]]:
    """The simple-mode row of one labels row (None when the schema's include leaves the line out)."""
    lv = line_level(row)
    if lv not in schema.include:
        return None
    pa = deciding_paragraph(row)
    out: Dict[str, Any] = {}
    for name, s in schema.fields:
        if s == "id":
            v = row.get("id")
        elif s == "line":
            v = row.get("line")
        elif s == "file":
            v = src
        elif s == "decision":
            v = row.get("decision") or row.get("action")
        elif s == "level":
            v = lv
        elif s == "reason":
            v = ("untouched" if lv == "untouched" else (row.get("error") or "error") if lv == "error"
                 else (pa or {}).get("reason") or "pass")
        elif s == "reason_text":
            v = schema.word(deciding_key(row, label_info))
        elif s == "labels":
            v = row.get("labels")
        elif s == "keyword_counts":
            v = counts if counts is not None else {}
        elif s == "markers":
            v = row.get("markers")
        elif s == "tokens":
            v = row.get("tokens")
        elif s == "tokens_removed":
            v = row.get("tokens_removed")
        elif s == "exception":
            v = (pa or {}).get("exception")
        elif s == "topic":
            v = row.get("topic")
        elif s == "paragraphs":
            v = [[p["span"][0], p["span"][1], p["action"]] for p in row.get("paragraphs") or []]
        else:  # input.<field>
            v = get_path(data or {}, s[len("input."):])
        if schema.omit_empty and _empty(v):
            continue
        out[name] = v
    return out


def evidence_row(schema: Schema, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The evidence row of a line (its paragraphs with scores), or None (evidence none, not chosen, no paragraphs)."""
    if schema.evidence == "none" or not row.get("paragraphs"):
        return None
    lv = line_level(row)
    if schema.evidence == "decided" and lv not in ("remove", "review"):
        return None
    keep = ("line", "id", "gate", "action", "decision", "reason", "decided_by", "labels", "flags", "markers", "topic",
            "paragraphs", "tokens", "tokens_removed")
    return {k: row[k] for k in keep if k in row}

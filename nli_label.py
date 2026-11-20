#!/usr/bin/env python3
"""
nli_label.py - label Russia-related content per A's policy, paragraph by paragraph, and store the labels as
columns (the raw data is never changed). Guide: cmds/labeling/README.md. Policy: policy/russia_policy.json.

Pipeline per document (cheap -> expensive):
  gate       keywords (keywords/russia.txt) + marker terms (policy "markers"); the cheap language-menu /
             company-name rules of nli_filter.py drop incidental hits. Documents without a hit are untouched.
  paragraphs matched documents are split into paragraphs; only paragraphs with a hit or a marker are labelled
  level 0    gate hypothesis ("involves Russia?"); below its threshold the paragraph passes (incidental)
  level 1    subject hypotheses, each a separate yes/no label with its own threshold and decision
  level 2    framing hypotheses (narratives), only after politics / war / history or a marker term
  decide     per paragraph: remove / keep / review / pass  (see resolve() for the exact rule)
  rewrite    Ukrainian place names in Russian form -> Ukrainian romanisation (policy/place_names.csv), in every
             kept text, also in documents without a hit

Commands
  run     python nli_label.py run INPUT... --output-dir out_label [--write-clean] [--all-labels]
  sample  python nli_label.py sample out_label --out labels/seed.jsonl         (paragraphs to hand-label)
  eval    python nli_label.py eval labels/seed.jsonl                            (per-label accuracy, thresholds)
  report  python nli_label.py report out_label                                  (composition, token-weighted)
  review  python nli_label.py review out_label --out labels/review_01.jsonl           (human-review queue)
  redecide python nli_label.py redecide out_label --policy new.json --output-dir out_label2
                                                   (changed thresholds / decisions from stored scores, no models)

Outputs of run, per input file (in --output-dir):
  <name>.labels.jsonl      one row per input line: gate, paragraphs (span, scores, labels, action), doc action
  <name>.clean.jsonl[.zst] the line with removed paragraphs cut out and names rewritten (with --write-clean);
                           documents left empty are dropped
  <name>.rewrites.jsonl    every place-name replacement (line, id, old, new)
  <name>.summary.json      counts for the file (also marks it done -> a rerun skips it)
  summary.json             the whole run: settings, policy, counts, token composition
"""
from __future__ import annotations

import argparse
import collections
import fnmatch
import hashlib
import json
import logging
import math
import random
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from nli_models import AtomicOutput, JsonlSource, Record, expand_inputs, json_dumps, zstd_available  # noqa: E402
import nli_formats  # noqa: E402
from nli_names import NameRewriter  # noqa: E402

log = logging.getLogger("nli_label")

DEFAULT_POLICY = HERE / "policy" / "russia_policy.json"
DECISIONS = ("gate", "remove", "keep", "review", "flag")
ACTIONS = ("remove", "review", "keep", "pass")


def est_tokens(text: str) -> int:
    """Rough token count (~4 characters per token). Only for composition tables, never for decisions."""
    return (len(text) + 3) // 4


# --------------------------------------------------------------------------------------------------
# Policy
# --------------------------------------------------------------------------------------------------


@dataclass
class Label:
    key: str
    level: int
    decision: str
    threshold: float
    hypothesis: str
    softens: List[str] = field(default_factory=list)
    note: str = ""

    def as_dict(self) -> Dict[str, Any]:
        d = {"level": self.level, "decision": self.decision, "threshold": self.threshold,
             "hypothesis": self.hypothesis}
        if self.softens:
            d["softens"] = list(self.softens)
        if self.note:
            d["note"] = self.note
        return d


class Policy:
    def __init__(self, data: Dict[str, Any], path: Optional[str] = None):
        self.path = path
        self.data = data
        self.country = data.get("country", "Russia")
        self.keywords_file = data.get("keywords_file")
        self.company_names_file = data.get("company_names_file")
        self.markers: List[str] = list(data.get("markers") or [])
        para = data.get("paragraphs") or {}
        self.min_chars = int(para.get("min_chars", 200))
        self.max_chars = int(para.get("max_chars", 2000))
        self.conflict = data.get("conflict", "review")
        # a level-2 'remove' label at or above its threshold opens the gate like a marker term: narratives about
        # Ukraine / NATO that never mention Russia still reach the policy (costs level-2 scores on gate-negative
        # paragraphs)
        self.narrative_opens_gate = bool(data.get("narrative_opens_gate", False))
        errors: List[str] = []
        if self.conflict not in ("review", "remove", "keep"):
            errors.append(f"conflict must be review, remove or keep, not '{self.conflict}'")
        self.labels: Dict[str, Label] = {}
        for key, v in (data.get("labels") or {}).items():
            if not re.match(r"^[a-z][a-z0-9_]*$", key):
                errors.append(f"label key '{key}': lower-case letters, digits and _ only")
                continue
            try:
                lab = Label(key, int(v.get("level", 1)), str(v.get("decision", "")), float(v.get("threshold", 0.8)),
                            str(v.get("hypothesis", "")).strip(), list(v.get("softens") or []), str(v.get("note", "")))
            except (TypeError, ValueError) as exc:
                errors.append(f"label {key}: {exc}")
                continue
            if lab.level not in (0, 1, 2):
                errors.append(f"label {key}: level must be 0, 1 or 2")
            if lab.decision not in DECISIONS:
                errors.append(f"label {key}: decision must be one of {', '.join(DECISIONS)}")
            if not 0.0 <= lab.threshold <= 1.0:
                errors.append(f"label {key}: threshold must be between 0 and 1")
            if not lab.hypothesis:
                errors.append(f"label {key}: hypothesis is empty")
            if (lab.decision == "gate") != (lab.level == 0):
                errors.append(f"label {key}: level 0 and decision 'gate' go together")
            self.labels[key] = lab
        gates = [k for k, lab in self.labels.items() if lab.level == 0]
        if len(gates) > 1:
            errors.append(f"only one level-0 (gate) label is allowed, found {', '.join(gates)}")
        self.gate: Optional[Label] = self.labels[gates[0]] if gates else None
        self.run_if: Dict[int, List[str]] = {}
        for lvl, keys in (data.get("run_if") or {}).items():
            try:
                lv = int(lvl)
            except ValueError:
                errors.append(f"run_if: '{lvl}' is not a level")
                continue
            for k in keys:
                if k != "@marker" and k not in self.labels:
                    errors.append(f"run_if {lvl}: unknown label '{k}'")
            self.run_if[lv] = list(keys)
        for lab in self.labels.values():
            for pat in lab.softens:
                if not any(fnmatch.fnmatch(k, pat) for k in self.labels):
                    errors.append(f"label {lab.key}: softens '{pat}' matches no label")
        if not self.labels:
            errors.append("no labels")
        if errors:
            raise ValueError(f"{path or 'policy'}: " + "; ".join(errors))

    @classmethod
    def load(cls, path: Optional[str] = None) -> "Policy":
        p = Path(path) if path else DEFAULT_POLICY
        with open(p, encoding="utf-8-sig") as fh:
            return cls(json.load(fh), str(p))

    def level(self, n: int) -> List[Label]:
        return [lab for lab in self.labels.values() if lab.level == n]

    def summary(self) -> Dict[str, Any]:
        return {"path": self.path, "country": self.country, "conflict": self.conflict,
                "narrative_opens_gate": self.narrative_opens_gate,
                "paragraphs": {"min_chars": self.min_chars, "max_chars": self.max_chars},
                "run_if": {str(k): v for k, v in self.run_if.items()}, "markers": len(self.markers),
                "labels": {k: lab.as_dict() for k, lab in self.labels.items()}}

    def runs(self, level: int, scores: Dict[str, float], marker: bool) -> bool:
        """Whether a level's labels are scored for a paragraph, given the scores so far."""
        keys = self.run_if.get(level)
        if not keys:
            return True
        for k in keys:
            if k == "@marker":
                if marker:
                    return True
            elif k in scores and scores[k] is not None and scores[k] >= self.labels[k].threshold:
                return True
        return False


def resolve(policy: Policy, scores: Dict[str, Optional[float]], marker: bool = False) -> Dict[str, Any]:
    """
    One paragraph's action from its label scores (missing / None = not scored = negative).

      pass    the gate label is below its threshold and there is no marker term (the keyword was incidental)
      remove  a level-2 'remove' label is positive and not softened (narratives win over 'keep' subjects), or
              level-1 'remove' labels are positive and no 'keep' label is
      review  a 'review' label is positive, a softened narrative is positive, or 'remove' and 'keep' labels are
              both positive (policy "conflict": review by default)
      keep    otherwise ('keep' labels, or Russia-related without any subject label)
    'flag' labels never change the action; they are listed in flags.
    """
    pos = {k for k, s in scores.items() if s is not None and k in policy.labels
           and policy.labels[k].level > 0 and s >= policy.labels[k].threshold}
    flags = sorted(k for k in pos if policy.labels[k].decision == "flag")
    g = policy.gate
    if g is not None and not marker and (scores.get(g.key) is None or scores[g.key] < g.threshold):
        return {"action": "pass", "reason": "gate_negative", "labels": sorted(pos), "flags": flags}
    softened = set()
    for k in pos:
        for pat in policy.labels[k].softens:
            softened |= {x for x in pos if fnmatch.fnmatch(x, pat)}
    narr = sorted(k for k in pos if policy.labels[k].level == 2 and policy.labels[k].decision == "remove"
                  and k not in softened)
    if narr:
        return {"action": "remove", "reason": "narrative", "labels": sorted(pos), "flags": flags}
    ds = set()
    for k in pos:
        lab = policy.labels[k]
        if lab.softens or lab.decision == "flag":
            continue
        ds.add("review" if (lab.decision == "remove" and k in softened) else lab.decision)
    if "remove" in ds and "keep" in ds:
        action, reason = policy.conflict, "conflict"
    elif "remove" in ds:
        action, reason = "remove", "remove_label"
    elif "review" in ds:
        action, reason = "review", "review_label"
    elif "keep" in ds:
        action, reason = "keep", "keep_label"
    else:
        action, reason = "keep", "no_subject"
    return {"action": action, "reason": reason, "labels": sorted(pos), "flags": flags}


def action_from_labels(policy: Policy, labels: Dict[str, Optional[bool]], marker: bool = False) -> Optional[str]:
    """The action hand labels imply (yes = 1.0, no / unknown = 0.0). None when the gate label is unknown."""
    if policy.gate is not None and labels.get(policy.gate.key) is None and not marker:
        return None
    return resolve(policy, {k: (1.0 if v else 0.0) for k, v in labels.items() if k in policy.labels},
                   marker)["action"]


# --------------------------------------------------------------------------------------------------
# Paragraphs
# --------------------------------------------------------------------------------------------------

_BLANK = re.compile(r"\n[ \t\r\f\v]*\n")
_SENT_END = re.compile(r"(?<=[.!?。！？])\s+")


def _trim(text: str, s: int, e: int) -> Optional[Tuple[int, int]]:
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return (s, e) if e > s else None


def _blocks(text: str, sep: "re.Pattern[str]") -> List[Tuple[int, int]]:
    out, last = [], 0
    for m in sep.finditer(text):
        t = _trim(text, last, m.start())
        if t:
            out.append(t)
        last = m.end()
    t = _trim(text, last, len(text))
    if t:
        out.append(t)
    return out


def _split_long(text: str, s: int, e: int, max_chars: int) -> List[Tuple[int, int]]:
    if e - s <= max_chars:
        return [(s, e)]
    out, cur = [], s
    cuts = [s + m.end() for m in _SENT_END.finditer(text[s:e])]
    start = s
    for c in cuts + [e]:
        if c - start > max_chars and cur > start:
            out.append((start, cur))
            start = cur
        cur = c
    out.append((start, e))
    final = []
    for a, b in out:  # a single sentence longer than max_chars: hard cut
        while b - a > max_chars:
            final.append((a, a + max_chars))
            a += max_chars
        final.append((a, b))
    return [t for t in (_trim(text, a, b) for a, b in final) if t]


def split_paragraphs(text: str, min_chars: int = 200, max_chars: int = 2000) -> List[Tuple[int, int]]:
    """Paragraph spans: blank lines, else single line breaks; short pieces are joined to the next one,
    long ones are cut at sentence ends (max_chars)."""
    if not text or not text.strip():
        return []
    blocks = _blocks(text, _BLANK)
    if len(blocks) == 1 and "\n" in text[blocks[0][0]:blocks[0][1]]:
        blocks = _blocks(text, re.compile(r"\n"))
    merged: List[Tuple[int, int]] = []
    cur: Optional[Tuple[int, int]] = None
    for s, e in blocks:
        if cur is None:
            cur = (s, e)
        elif cur[1] - cur[0] < min_chars:
            cur = (cur[0], e)
        else:
            merged.append(cur)
            cur = (s, e)
    if cur is not None:
        if merged and cur[1] - cur[0] < min_chars // 2:
            merged[-1] = (merged[-1][0], cur[1])
        else:
            merged.append(cur)
    out: List[Tuple[int, int]] = []
    for s, e in merged:
        out += _split_long(text, s, e, max_chars)
    return out


# --------------------------------------------------------------------------------------------------
# Labelling
# --------------------------------------------------------------------------------------------------


@dataclass
class Outcome:
    row: Dict[str, Any]                  # the labels row
    clean: Optional[Dict[str, Any]]      # the cleaned document (None = dropped)
    rewrites: List[Dict[str, Any]]
    group: Optional[str] = None          # value of the group field (composition breakdown)


class Labeller:
    """Applies the policy to records. scorer.score(premises, hypotheses) -> [(fast, judge or None, final)]."""

    def __init__(self, policy: Policy, matcher, rules, scorer, rewriter: Optional[NameRewriter] = None,
                 all_labels: bool = False, text_field: str = "text", id_field: Optional[str] = "id",
                 review_as: str = "keep", min_doc_chars: int = 50, marker_matcher=None,
                 group_field: Optional[str] = None, force_gate: bool = False):
        self.p, self.matcher, self.rules, self.scorer = policy, matcher, rules, scorer
        self.group_field = group_field
        self.force_gate = force_gate  # label every paragraph, also without a keyword hit (Try page: gate cases)
        self.rewriter = rewriter
        self.all_labels = all_labels
        self.text_field, self.id_field = text_field, id_field
        self.review_as = review_as
        self.min_doc_chars = min_doc_chars
        self.marker_matcher = marker_matcher

    # -- scoring rounds ----------------------------------------------------------------------------
    def _score(self, items: List[Tuple[Dict[str, Any], str, Label]]) -> None:
        """items: (paragraph dict, premise, label) -> fills para["scores"][key] (and para["judge"])."""
        if not items:
            return
        res = self.scorer.score([t for _, t, _ in items], [lab.hypothesis for _, _, lab in items])
        for (para, _, lab), (fast, judge, final) in zip(items, res):
            para["scores"][lab.key] = round(float(final), 4)
            if judge is not None:
                para.setdefault("judged", []).append(lab.key)

    def process(self, records: Sequence[Record]) -> List[Outcome]:
        p = self.p
        docs: List[Dict[str, Any]] = []
        for rec in records:
            d: Dict[str, Any] = {"rec": rec, "row": {"line": rec.line}, "paras": [], "text": None}
            text = rec.get(self.text_field) if rec.error is None else None
            if self.id_field and rec.get(self.id_field) is not None:
                d["row"]["id"] = rec.get(self.id_field)
            if rec.error is not None:
                d["row"]["error"] = rec.error.split(":")[0]
            elif not isinstance(text, str):
                d["row"]["error"] = "no_text"
            else:
                d["text"] = text
                hits = self.matcher.find(text)
                if self.rules is not None and hits:
                    self.rules.apply(text, hits)
                open_hits = [h for h in hits if not h.rule]
                marks = self.marker_matcher.find(text) if self.marker_matcher is not None else []
                d["row"]["gate"] = bool(open_hits or marks or self.force_gate)
                if hits:
                    d["row"]["hits"] = [{"kw": self.matcher.keywords[h.kw] if h.kw is not None else text[h.start:h.end],
                                         "span": [h.start, h.end], **({"rule": h.rule} if h.rule else {})}
                                        for h in hits[:50]]
                if marks:
                    d["row"]["markers"] = sorted({text[m.start:m.end] for m in marks})
                if open_hits or marks or self.force_gate:
                    for s, e in split_paragraphs(text, p.min_chars, p.max_chars):
                        ph = [h for h in open_hits if s <= h.start < e]
                        pm = [m for m in marks if s <= m.start < e]
                        if ph or pm or self.force_gate:
                            d["paras"].append({"span": [s, e], "marker": bool(pm), "scores": {},
                                               "_text": text[s:e]})
            docs.append(d)
        paras = [pa for d in docs for pa in d["paras"]]
        if self.all_labels:
            self._score([(pa, pa["_text"], lab) for pa in paras for lab in p.labels.values()])
        else:
            if p.gate is not None:
                self._score([(pa, pa["_text"], p.gate) for pa in paras])
                if p.narrative_opens_gate:  # gate-negative paragraphs: do they make a narrative claim anyway?
                    closed = [pa for pa in paras if not pa["marker"]
                              and pa["scores"].get(p.gate.key, 0.0) < p.gate.threshold]
                    self._score([(pa, pa["_text"], lab) for pa in closed for lab in self.opening_labels()])
            for lvl in (1, 2):
                todo = [(pa, pa["_text"], lab) for pa in paras if p.runs(lvl, pa["scores"], self.is_open(pa))
                        for lab in p.level(lvl) if lab.key not in pa["scores"]]
                self._score(todo)
        return [self._finish(d) for d in docs]

    def opening_labels(self) -> List[Label]:
        """Level-2 'remove' labels: with narrative_opens_gate, one of them at or above its threshold opens the gate."""
        return [lab for lab in self.p.level(2) if lab.decision == "remove"]

    def opened_by(self, scores: Dict[str, float]) -> List[str]:
        if not self.p.narrative_opens_gate:
            return []
        return sorted(lab.key for lab in self.opening_labels()
                      if scores.get(lab.key) is not None and scores[lab.key] >= lab.threshold)

    def is_open(self, pa: Dict[str, Any]) -> bool:
        """Past the gate without the gate label: a marker term, or (narrative_opens_gate) a narrative claim."""
        return bool(pa["marker"]) or bool(self.opened_by(pa["scores"]))

    def levels_used(self, scores: Dict[str, float], marker: bool) -> List[int]:
        """The levels the cascade runs for a paragraph (run_if). With --all-labels the other levels are scored
        too, but only for information: the decision uses the same levels as a normal run."""
        used = [0]
        so_far = {k: v for k, v in scores.items() if self.p.labels[k].level == 0}
        for lvl in (1, 2):
            if not self.p.runs(lvl, so_far, marker):
                break
            used.append(lvl)
            so_far.update({k: v for k, v in scores.items() if self.p.labels[k].level == lvl})
        return used

    def _finish(self, d: Dict[str, Any]) -> Outcome:
        row, text, rec = d["row"], d["text"], d["rec"]
        if text is None:
            row["action"] = "error"
            return Outcome(row, None, [])
        removed: List[Tuple[int, int]] = []
        doc_labels, flags = set(), set()
        para_rows = []
        tokens_removed = 0
        review = False
        for pa in d["paras"]:
            opened = self.is_open(pa)
            used = self.levels_used(pa["scores"], opened)
            r = resolve(self.p, {k: v for k, v in pa["scores"].items() if self.p.labels[k].level in used}, opened)
            out = {"span": pa["span"], "action": r["action"], "reason": r["reason"], "labels": r["labels"],
                   "scores": pa["scores"], "levels": used, "tokens": est_tokens(pa["_text"])}
            if pa["marker"]:
                out["marker"] = True
            gate = self.p.gate
            ob = self.opened_by(pa["scores"])
            if ob and not pa["marker"] and gate is not None and pa["scores"].get(gate.key, 0.0) < gate.threshold:
                out["opened_by"] = ob  # the gate said no; a narrative claim let the paragraph through
            if r["flags"]:
                out["flags"] = r["flags"]
            if pa.get("judged"):
                out["judged"] = pa["judged"]
            para_rows.append(out)
            doc_labels |= set(r["labels"])
            flags |= set(r["flags"])
            if r["action"] == "review":
                review = True
            if r["action"] == "remove" or (r["action"] == "review" and self.review_as == "remove"):
                removed.append(tuple(pa["span"]))
                tokens_removed += out["tokens"]
        clean_text = text
        if removed:
            parts, last = [], 0
            for s, e in sorted(removed):
                parts.append(text[last:s])
                last = e
                while last < len(text) and text[last] in " \t\r\n":  # the separator after it goes too
                    last += 1
            parts.append(text[last:])
            clean_text = "".join(parts).strip()
        rewrites: List[Dict[str, Any]] = []
        if self.rewriter is not None and clean_text:
            clean_text, rewrites = self.rewriter.rewrite(clean_text)
        row["tokens"] = est_tokens(text)
        if para_rows:
            row["paragraphs"] = para_rows
            row["labels"] = sorted(doc_labels)
            if flags:
                row["flags"] = sorted(flags)
            row["tokens_removed"] = tokens_removed
            row["review"] = review
        if rewrites:
            row["rewrites"] = len(rewrites)
        if not row.get("gate"):
            action = "untouched"
        elif not removed:
            action = "review" if review else ("pass" if all(pr["action"] == "pass" for pr in para_rows) else "kept")
        elif len(clean_text) < self.min_doc_chars:
            action = "removed"
        else:
            action = "edited"
        row["action"] = action
        clean = None
        if action != "removed":
            obj = rec.data if isinstance(rec.data, dict) else {}
            clean = dict(obj, **{self.text_field: clean_text}) if (removed or rewrites) else obj
        log_rows = [dict(c, line=rec.line, **({"id": row["id"]} if "id" in row else {})) for c in rewrites]
        group = rec.get(self.group_field) if self.group_field else None
        return Outcome(row, clean, log_rows, None if group is None else str(group))


# --------------------------------------------------------------------------------------------------
# Statistics (token-weighted composition)
# --------------------------------------------------------------------------------------------------


class Stats:
    def __init__(self, data: Optional[Dict[str, Any]] = None):
        data = data or {}
        self.lines = data.get("lines", 0)
        self.tokens = data.get("tokens", 0)
        self.docs = collections.Counter(data.get("docs") or {})
        self.doc_tokens = collections.Counter(data.get("doc_tokens") or {})
        self.paras = collections.Counter(data.get("paragraphs") or {})
        self.para_tokens = collections.Counter(data.get("paragraph_tokens") or {})
        self.reasons = collections.Counter(data.get("reasons") or {})
        self.label_paras = collections.Counter(data.get("label_paragraphs") or {})
        self.label_tokens = collections.Counter(data.get("label_tokens") or {})
        self.flags = collections.Counter(data.get("flags") or {})
        self.tokens_removed = data.get("tokens_removed", 0)
        self.rewrites = data.get("rewrites", 0)
        self.rewrite_names = collections.Counter(data.get("rewrite_names") or {})
        self.groups: Dict[str, collections.Counter] = {k: collections.Counter(v) for k, v in
                                                       (data.get("groups") or {}).items()}

    def add(self, o: Outcome, group: Optional[str] = None) -> None:
        r = o.row
        self.lines += 1
        t = r.get("tokens", 0)
        self.tokens += t
        a = r.get("action", "error")
        self.docs[a] += 1
        self.doc_tokens[a] += t
        self.tokens_removed += r.get("tokens_removed", 0)
        for pa in r.get("paragraphs") or []:
            self.paras[pa["action"]] += 1
            self.para_tokens[pa["action"]] += pa["tokens"]
            self.reasons[pa["reason"]] += 1
            for k in pa["labels"]:
                self.label_paras[k] += 1
                self.label_tokens[k] += pa["tokens"]
            for k in pa.get("flags") or []:
                self.flags[k] += 1
        self.rewrites += len(o.rewrites)
        for c in o.rewrites:
            self.rewrite_names[f"{c['old']} -> {c['new']}"] += 1
        if group is not None:
            g = self.groups.setdefault(str(group), collections.Counter())
            g["docs"] += 1
            g["tokens"] += t
            g["tokens_removed"] += r.get("tokens_removed", 0)
            g[f"docs_{a}"] += 1

    def merge(self, o: "Stats") -> None:
        self.lines += o.lines
        self.tokens += o.tokens
        self.tokens_removed += o.tokens_removed
        self.rewrites += o.rewrites
        for a in ("docs", "doc_tokens", "paras", "para_tokens", "reasons", "label_paras", "label_tokens", "flags",
                  "rewrite_names"):
            getattr(self, a).update(getattr(o, a))
        for k, v in o.groups.items():
            self.groups.setdefault(k, collections.Counter()).update(v)

    def to_dict(self) -> Dict[str, Any]:
        return {"lines": self.lines, "tokens": self.tokens, "tokens_removed": self.tokens_removed,
                "docs": dict(self.docs), "doc_tokens": dict(self.doc_tokens), "paragraphs": dict(self.paras),
                "paragraph_tokens": dict(self.para_tokens), "reasons": dict(self.reasons),
                "label_paragraphs": dict(self.label_paras), "label_tokens": dict(self.label_tokens),
                "flags": dict(self.flags), "rewrites": self.rewrites,
                "rewrite_names": dict(self.rewrite_names.most_common(50)),
                "groups": {k: dict(v) for k, v in self.groups.items()}}


def _pct(a: float, b: float) -> str:
    return f"{100.0 * a / b:5.1f}%" if b else "    -"


def format_report(summary: Dict[str, Any]) -> str:
    st = summary["stats"]
    pol = (summary.get("policy") or {}).get("labels") or {}
    T = st["tokens"] or 0
    L: List[str] = []
    L.append(f"lines {st['lines']:,}   tokens (est.) {T:,}   removed {st['tokens_removed']:,} "
             f"({_pct(st['tokens_removed'], T).strip()})   place-name rewrites {st['rewrites']:,}")
    L.append("")
    L.append("documents       docs        tokens (est.)   share of tokens")
    for a in ("untouched", "pass", "kept", "review", "edited", "removed", "error"):
        if st["docs"].get(a):
            L.append(f"  {a:<10} {st['docs'][a]:>9,}  {st['doc_tokens'].get(a, 0):>15,}   "
                     f"{_pct(st['doc_tokens'].get(a, 0), T)}")
    if st["paragraphs"]:
        L.append("")
        L.append("paragraphs      count       tokens (est.)")
        for a in ACTIONS:
            if st["paragraphs"].get(a):
                L.append(f"  {a:<10} {st['paragraphs'][a]:>9,}  {st['paragraph_tokens'].get(a, 0):>15,}")
        L.append("  reasons: " + ", ".join(f"{k} {v:,}" for k, v in sorted(st["reasons"].items(),
                                                                            key=lambda x: -x[1])))
    if st["label_paragraphs"]:
        L.append("")
        L.append("labels (positive paragraphs)        decision   paragraphs   tokens (est.)")
        for k in pol or sorted(st["label_paragraphs"]):
            if k in st["label_paragraphs"]:
                L.append(f"  {k:<34} {pol.get(k, {}).get('decision', '?'):<9} {st['label_paragraphs'][k]:>10,}  "
                         f"{st['label_tokens'].get(k, 0):>14,}")
    if st.get("flags"):
        L.append("  flagged (not removed): " + ", ".join(f"{k} {v:,}" for k, v in st["flags"].items()))
    if st.get("rewrite_names"):
        L.append("")
        L.append("place names: " + ", ".join(f"{k} ({v:,})" for k, v in list(st["rewrite_names"].items())[:12]))
    if st.get("groups"):
        L.append("")
        L.append("by group        docs        tokens (est.)   removed")
        for g, c in sorted(st["groups"].items(), key=lambda x: -x[1].get("tokens", 0))[:30]:
            L.append(f"  {g[:20]:<20} {c.get('docs', 0):>8,}  {c.get('tokens', 0):>13,}  "
                     f"{_pct(c.get('tokens_removed', 0), c.get('tokens', 0))}")
    return "\n".join(L)


# --------------------------------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------------------------------


def _is_url(s: str) -> bool:
    return bool(re.match(r"^(ftps?|sftp|s3|minios?)://", str(s), re.IGNORECASE))


def _mask(text: Any) -> str:
    """Hide passwords of server addresses (user:secret@host -> user:***@host) in anything written or printed."""
    from nli_storage import mask_uri
    return mask_uri(str(text))


def reopen_uri(typed: str, rf: Any) -> Optional[str]:
    """A server file's address that is safe to store AND can be opened again later: only when the typed address
    takes the password from an environment variable (${NLI_CORPUS_PASSWORD} ...). A literal password is never
    stored, so such inputs cannot be reopened by sample / review / redecide / the viewer."""
    if not hasattr(rf, "storage") or "$" not in typed:
        return None
    from urllib.parse import urlparse
    t = typed.split("?", 1)
    tu, ru = urlparse(t[0]), urlparse(str(rf))
    return f"{tu.scheme}://{tu.netloc}{ru.path}" + (f"?{t[1]}" if len(t) > 1 else "")


def expand_typed(inputs: Sequence[str]) -> List[Tuple[Any, Optional[str]]]:
    """[(file, reopen address or None)] for the inputs as typed: local paths, folders, globs, server addresses."""
    out: List[Tuple[Any, Optional[str]]] = []
    for item in inputs:
        for f in expand_inputs([item]):
            out.append((f, reopen_uri(item, f) if _is_url(item) else None))
    seen, uniq = set(), []
    for f, ro in out:
        if str(f) not in seen:
            seen.add(str(f))
            uniq.append((f, ro))
    return uniq


def open_input(row: Dict[str, Any]) -> Any:
    """The input file of a run's per-file summary, for reading it again: a local path, or a server file
    (from 'reopen', the ${VAR} form of the address). Raises ValueError for a server file stored without one."""
    src = row.get("reopen") or row.get("input")
    if not src:
        raise ValueError("the run does not record its input file")
    if _is_url(src):
        if not row.get("reopen"):
            raise ValueError(f"{src} is on a server and was given with a literal password, which is never stored: "
                             "run with the password in an environment variable (sftp://user:${NLI_CORPUS_PASSWORD}"
                             "@host/...) to be able to open it again")
        return expand_inputs([src])[0]
    return src


def _out_names(files: Sequence[str]) -> List[str]:
    """Output base name per input file (stem; a counter is added when two files share a stem)."""
    seen: Dict[str, int] = collections.Counter()
    out = []
    for f in files:
        base = nli_formats.stem(Path(str(f)).name)
        seen[base] += 1
        out.append(base if seen[base] == 1 else f"{base}.{seen[base]}")
    return out


def build_matchers(policy: Policy):
    from nli_filter import COUNTRIES, IncidentalRules, KeywordMatcher, load_keywords, load_lexicon
    cdef = COUNTRIES.get(policy.country.lower(), {"adj": policy.country, "keywords": [policy.country],
                                                   "exclude": []})
    kw_file = policy.keywords_file
    if kw_file and not Path(kw_file).is_absolute():
        kw_file = str(HERE / kw_file)
    entries = load_lexicon(kw_file) if kw_file and Path(kw_file).is_file() else list(cdef["keywords"])
    matcher = KeywordMatcher(entries, cdef.get("exclude") or [])
    companies: List[str] = []
    if policy.company_names_file:
        cf = policy.company_names_file
        companies = load_keywords(cf if Path(cf).is_absolute() else str(HERE / cf))
    rules = IncidentalRules(cdef.get("adj", policy.country), company_names=companies)
    markers = KeywordMatcher(policy.markers) if policy.markers else None
    return matcher, rules, markers


def build_scorer(args):
    from nli_filter import CascadeScorer
    from nli_models import NLIPool, quiet_transformers
    quiet_transformers()
    common = dict(devices=args.device, mode=args.mode, dtype=args.dtype, max_length=args.max_length,
                  models_root=args.models_root, cpu_threads=args.cpu_threads)
    fast = NLIPool(args.fast_model, batch_size=args.batch_size, **common)
    judge = None
    if args.judge_model and args.judge_model.lower() != "none":
        judge = NLIPool(args.judge_model, batch_size=args.batch_size, **common)
    return CascadeScorer(fast, judge, tuple(args.uncertain_band)), fast, judge


def cmd_run(args, scorer_override=None, records_for=None, extra: Optional[Dict[str, Any]] = None) -> int:
    """run; redecide reuses it with a scorer that returns stored scores (scorer_override) and a record reader
    that loads each line's stored scores first (records_for)."""
    policy = Policy.load(args.policy)
    try:
        if scorer_override is not None:  # redecide: the files are given already (with their reopen addresses)
            typed = [(f, getattr(args, "reopen", {}).get(str(f))) for f in args.inputs]
        else:
            typed = expand_typed(args.inputs)
    except FileNotFoundError as exc:
        print(f"error: input not found: {_mask(exc)}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - server errors: no password in the message
        print(f"error: cannot read the input: {_mask(exc)}", file=sys.stderr)
        return 2
    shard = getattr(args, "shard", None)
    sk = sn = None
    if shard:
        try:
            sk, sn = (int(x) for x in str(shard).split("/"))
            assert 0 <= sk < sn
        except (ValueError, AssertionError):
            print("error: --shard K/N needs 0 <= K < N (e.g. 0/4)", file=sys.stderr)
            return 2
        typed = typed[sk::sn]
    files = [f for f, _ in typed]
    reopen = {str(f): ro for f, ro in typed}
    if not files:
        print("error: no input files" + (f" for shard {shard}" if shard else ""), file=sys.stderr)
        return 2
    if any(str(f).lower().endswith((".zst", ".zstd")) for f in files) and not zstd_available():
        print("error: .zst input needs the 'zstandard' package", file=sys.stderr)
        return 2
    if args.compress == "zst" and not zstd_available():
        print("error: --compress zst needs the 'zstandard' package", file=sys.stderr)
        return 2
    matcher, rules, markers = build_matchers(policy)
    rewriter = None if args.no_rewrite else NameRewriter.from_files(args.place_names, args.place_name_exceptions)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    scorer, fast, judge = (scorer_override, None, None) if scorer_override is not None else build_scorer(args)
    load_s = time.perf_counter() - t0
    labeller = Labeller(policy, matcher, None if args.no_rules else rules, scorer, rewriter, args.all_labels,
                        args.text_field, args.id_field or None, args.review_as, args.min_doc_chars, markers,
                        args.group_field)
    total = Stats()
    files_rows: List[Dict[str, Any]] = []
    failed = 0
    ext = ".jsonl.zst" if args.compress == "zst" else ".jsonl"
    t_run = time.perf_counter()
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    tag = f".shard{sk}of{sn}" if shard else ""
    prog_path = out_dir / f"progress{tag}.json"
    command = _mask("nli_label.py " + " ".join(sys.argv[1:]))

    def progress(state: str, **kw: Any) -> None:
        """progress.json: what the viewer's Labels page shows while a run goes (state, files, lines)."""
        d = {"state": state, "command": command, "started": started, "shard": shard,
             "updated": time.strftime("%Y-%m-%d %H:%M:%S"), "files_total": len(files), "files_done": len(files_rows),
             "files_failed": failed, "lines_done": total.lines, "seconds": round(time.perf_counter() - t_run, 1),
             **{k: (_mask(v) if isinstance(v, str) else v) for k, v in kw.items()}}
        try:
            tmp = prog_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(prog_path)
        except OSError:
            pass

    names = _out_names(files)
    needed = [args.overwrite or not (out_dir / f"{n}.summary.json").is_file() for n in names]
    fetch = None
    if records_for is None and any(hasattr(f, "storage") for f in files):
        from nli_filter import Prefetcher  # download the next server file while this one is labelled; retries
        fetch = Prefetcher(files, needed, Path(args.download_dir) if getattr(args, "download_dir", None)
                           else out_dir / ".download", getattr(args, "retries", 3))
    progress("running")
    ok = False
    try:
        for i, (path, name) in enumerate(zip(files, names)):
            shown = _mask(path)
            summ_path = out_dir / f"{name}.summary.json"
            if not needed[i]:
                old = json.loads(summ_path.read_text(encoding="utf-8"))
                total.merge(Stats(old.get("stats")))
                files_rows.append({"input": shown, "name": name, "status": "skipped (done)"})
                log.warning("skip %s (done; --overwrite to redo)", shown)
                continue
            local = None
            if fetch is not None:
                try:
                    local = fetch.get(i)
                except Exception as exc:  # noqa: BLE001 - download failed after the retries: go on with the rest
                    failed += 1
                    files_rows.append({"input": shown, "name": name, "status": f"failed: {_mask(exc)}"})
                    log.error("skip %s: %s", shown, _mask(exc))
                    progress("running")
                    continue
            st = Stats()
            t_file = time.perf_counter()
            done = 0
            try:
                with AtomicOutput(out_dir / f"{name}.labels.jsonl") as lab_fh, \
                        AtomicOutput(out_dir / f"{name}.rewrites.jsonl") as rw_fh:
                    clean_cm = AtomicOutput(out_dir / f"{name}.clean{ext}") if args.write_clean else None
                    clean_fh = clean_cm.__enter__() if clean_cm else None
                    try:
                        chunk: List[Record] = []

                        def flush() -> None:
                            for o in labeller.process(chunk):
                                st.add(o, o.group)
                                lab_fh.write(json_dumps(o.row) + "\n")
                                for c in o.rewrites:
                                    rw_fh.write(json_dumps(c) + "\n")
                                if clean_fh is not None and o.clean is not None:
                                    clean_fh.write(json_dumps(o.clean) + "\n")
                            chunk.clear()

                        reader = records_for(path) if records_for else \
                            JsonlSource(path, local=local).records(limit=args.limit)
                        for rec in reader:
                            chunk.append(rec)
                            if len(chunk) >= args.chunk_lines:
                                flush()
                                done += args.chunk_lines
                                progress("running", current_file=shown, current_lines=done)
                                if done % (args.chunk_lines * 8) == 0:
                                    log.warning("%s: %d lines, %.1f lines/min", name, done,
                                                60.0 * done / max(1e-6, time.perf_counter() - t_file))
                        if chunk:
                            flush()
                    except BaseException as exc:
                        if clean_cm:
                            clean_cm.__exit__(type(exc), exc, exc.__traceback__)
                        raise
                    if clean_cm:
                        clean_cm.__exit__(None, None, None)
            finally:
                if local and fetch is not None:
                    fetch.release(local)
            data = {"input": shown, "name": name, "complete": args.limit is None,
                    "seconds": round(time.perf_counter() - t_file, 2), "stats": st.to_dict()}
            ro = reopen.get(str(path))
            if ro:
                data["reopen"] = ro  # the ${VAR} form: safe to store, opens the file again later
            summ_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            total.merge(st)
            files_rows.append({"input": shown, "name": name, "status": "done", "lines": st.lines,
                               "seconds": data["seconds"]})
            progress("running")
        ok = True
    finally:
        progress("done" if ok else "failed")
        if fetch is not None:
            fetch.close()
        for pool in (fast, judge):
            if pool is not None:
                pool.close()
    if shard:  # every shard writes the run summary from ALL finished files in the folder (the last one is complete)
        total = Stats()
        for sp in sorted(out_dir.glob("*.summary.json")):
            if not sp.name.startswith("summary."):
                total.merge(Stats((json.loads(sp.read_text(encoding="utf-8")) or {}).get("stats")))
    summary = {
        "command": command,
        "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
        "policy": policy.summary(),
        "settings": {"fast_model": args.fast_model, "judge_model": args.judge_model,
                     "uncertain_band": list(args.uncertain_band), "all_labels": args.all_labels,
                     "review_as": args.review_as, "rewrite": not args.no_rewrite, "rules": not args.no_rules,
                     "text_field": args.text_field, "max_length": args.max_length, "group_field": args.group_field,
                     "shard": shard},
        "timing": {"load_seconds": round(load_s, 1), "run_seconds": round(time.perf_counter() - t_run, 1),
                   "fast_pairs": scorer.fast_pairs, "judge_pairs": scorer.judge_pairs},
        "files": files_rows, "files_failed": failed, "stats": total.to_dict(), "output_dir": str(out_dir),
    }
    if scorer_override is not None and hasattr(scorer_override, "report"):
        summary["redecide"] = dict(extra or {}, **scorer_override.report())
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    if shard:
        (out_dir / f"summary{tag}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(format_report(summary))
    if failed:
        print(f"\n{failed} file(s) failed (download): see 'files' in summary.json; rerun to retry them")
    if "redecide" in summary:
        r = summary["redecide"]
        print(f"\nredecided from stored scores of {r.get('from')}: {r['stored']:,} scores reused, "
              f"{r['missing']:,} needed but not stored (treated as No"
              + (f"; changed hypotheses: {', '.join(r['changed'])}" if r.get("changed") else "")
              + f"); output in {out_dir}")
        if r["missing"]:
            print("  missing scores: the old run used the cascade, or keywords / hypotheses / paragraph settings "
                  "changed. For exact results, rerun with 'run' (--all-labels stores every label).")
    else:
        print(f"\nmodel pairs: fast {scorer.fast_pairs:,}, judge {scorer.judge_pairs:,}; "
              f"{summary['timing']['run_seconds']}s; output in {out_dir}")
    return 0


class StoredScorer:
    """Stands in for the models in 'redecide': returns the scores a run stored, looked up by (paragraph text,
    label). A label whose hypothesis changed since that run is not reused. Missing scores count as 0 (No)."""

    def __init__(self, policy: Policy, old_labels: Dict[str, Any]):
        self.hyp2key = {lab.hypothesis: k for k, lab in policy.labels.items()}
        self.changed = sorted(k for k, lab in policy.labels.items()
                              if (old_labels.get(k) or {}).get("hypothesis") != lab.hypothesis)
        self.table: Dict[Tuple[str, str], float] = {}
        self.fast_pairs = self.judge_pairs = 0
        self.stored = self.missing = 0

    @staticmethod
    def _h(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

    def load(self, text: Optional[str], row: Dict[str, Any]) -> None:
        if not isinstance(text, str):
            return
        for pa in row.get("paragraphs") or []:
            s, e = pa["span"]
            h = self._h(text[s:e])
            for k, v in (pa.get("scores") or {}).items():
                if k not in self.changed and v is not None:
                    self.table[(h, k)] = float(v)

    def score(self, premises: List[str], hyps: List[str]) -> List[Tuple[float, Optional[float], float]]:
        out = []
        for p, h in zip(premises, hyps):
            v = self.table.get((self._h(p), self.hyp2key.get(h, "")))
            if v is None:
                self.missing += 1
                v = 0.0
            else:
                self.stored += 1
            out.append((v, None, v))
        return out

    def report(self) -> Dict[str, Any]:
        return {"stored": self.stored, "missing": self.missing, "changed": self.changed}


def cmd_redecide(args) -> int:
    """Apply a (changed) policy to a finished run from its stored scores: new thresholds, decisions, run_if,
    conflict rule; also writes the clean copy. No model is loaded."""
    run = Path(args.run)
    old_summary_p = run / "summary.json"
    if not old_summary_p.is_file():
        print(f"error: {old_summary_p} not found", file=sys.stderr)
        return 2
    if Path(args.output_dir).resolve() == run.resolve():
        print("error: --output-dir must be a new folder, not the run itself", file=sys.stderr)
        return 2
    old = json.loads(old_summary_p.read_text(encoding="utf-8"))
    policy = Policy.load(args.policy)
    scorer = StoredScorer(policy, ((old.get("policy") or {}).get("labels") or {}))
    pairs = _run_files(run)
    if not pairs:
        print(f"error: {run} has no finished files", file=sys.stderr)
        return 2
    rows_of = {inp: lp for inp, lp in pairs}
    open_of = _opener(run)
    tf = (old.get("settings") or {}).get("text_field") or args.text_field

    def records_for(path: str):
        with open(rows_of[path], encoding="utf-8") as fh:
            for rec in JsonlSource(open_of(path)).records():
                raw = fh.readline()
                if not raw:
                    break
                row = json.loads(raw)
                if row.get("line") == rec.line:
                    scorer.load(rec.get(tf), row)
                yield rec

    st = old.get("settings") or {}
    ns = argparse.Namespace(**vars(args))
    ns.inputs = [inp for inp, _ in pairs]
    ns.reopen = {row["input"]: row.get("reopen") for row, _ in _run_file_rows(run)}
    ns.all_labels = bool(st.get("all_labels"))  # same cascade as the old run
    ns.text_field = tf
    for k in ("fast_model", "judge_model", "max_length"):
        setattr(ns, k, st.get(k))
    ns.uncertain_band = st.get("uncertain_band") or [0.6, 0.95]
    ns.limit, ns.overwrite = None, True
    return cmd_run(ns, scorer_override=scorer, records_for=records_for, extra={"from": str(run)})


def cmd_report(args) -> int:
    p = Path(args.run) / "summary.json"
    if not p.is_file():
        print(f"error: {p} not found", file=sys.stderr)
        return 2
    print(format_report(json.loads(p.read_text(encoding="utf-8"))))
    return 0


# --------------------------------------------------------------------------------------------------
# sample: paragraphs to hand-label
# --------------------------------------------------------------------------------------------------


def _run_files(run: Path) -> List[Tuple[str, Path]]:
    """[(input path, labels file)] of a run folder (the input as stored: never with a password)."""
    return [(row["input"], lp) for row, lp in _run_file_rows(run)]


def _run_file_rows(run: Path) -> List[Tuple[Dict[str, Any], Path]]:
    """[(per-file summary row, labels file)] of a run folder."""
    out = []
    for sp in sorted(run.glob("*.summary.json")):
        d = json.loads(sp.read_text(encoding="utf-8"))
        lp = run / f"{d.get('name') or sp.name[:-len('.summary.json')]}.labels.jsonl"
        if lp.is_file() and d.get("input"):
            out.append((d, lp))
    return out


def _opener(run: Path):
    """input as stored -> something JsonlSource opens (a local path, or a server file via its ${VAR} address)."""
    rows = {row["input"]: row for row, _ in _run_file_rows(run)}
    return lambda f: open_input(rows.get(f) or {"input": f})


def read_labels_file(path: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """(meta, items) of a hand-label file."""
    meta: Dict[str, Any] = {}
    items: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8-sig") as fh:
        for raw in fh:
            if not raw.strip():
                continue
            d = json.loads(raw)
            if "_meta" in d:
                meta = d["_meta"]
            else:
                items.append(d)
    return meta, items


def write_labels_file(path: str, meta: Dict[str, Any], items: Sequence[Dict[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({"_meta": meta}, ensure_ascii=False) + "\n")
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")
    tmp.replace(p)


def setup_key(fast: Any, judge: Any, band: Sequence[float], max_length: Any) -> str:
    """Model setup a score belongs to (scores of different setups are never mixed)."""
    band = list(band or [0.6, 0.95])
    return f"{fast}|{str(judge).lower() if judge else 'none'}|{band[0]}-{band[1]}|{max_length}"


def label_meta(policy: Policy, **extra: Any) -> Dict[str, Any]:
    return {"policy": policy.path, "conflict": policy.conflict,
            "labels": {k: lab.as_dict() for k, lab in policy.labels.items()},
            "run_if": {str(k): v for k, v in policy.run_if.items()},
            "created": time.strftime("%Y-%m-%d %H:%M:%S"), **extra}


def paragraph_items(cands: List[Dict[str, Any]], policy: Policy, text_field: str = "text",
                    context: int = 300, opener=None) -> List[Dict[str, Any]]:
    """Hand-label items (label tool format) for paragraphs of a run: cands = {key, file, line, span, id, scores,
    action, marker, picked_for}. The text is read from the run's input files; emptied documents are skipped."""
    by_file: Dict[str, Dict[int, List[Dict[str, Any]]]] = collections.defaultdict(lambda: collections.defaultdict(list))
    for c in cands:
        by_file[c["file"]][int(c["line"])].append(c)
    matcher, rules, markers = build_matchers(policy)
    items = []
    for f, lines in by_file.items():
        need = set(lines)
        for rec in JsonlSource(opener(f) if opener else f).records():
            if rec.line not in need:
                continue
            text = rec.get(text_field) or ""
            for c in lines[rec.line]:
                s, e = c["span"]
                ptext = text[s:e]
                if not ptext.strip():  # the document was emptied (e.g. content screening) after the run
                    continue
                hs = matcher.find(ptext)
                if rules is not None and hs:
                    rules.apply(ptext, hs)
                hl = [[h.start, h.end] for h in hs if not h.rule]
                if markers is not None:
                    hl += [[m.start, m.end] for m in markers.find(ptext)]
                items.append({
                    "key": c["key"], "source": {"file": f, "line": c["line"], "span": c["span"], "id": c.get("id")},
                    "text": ptext, "before": text[max(0, s - context):s], "after": text[e:e + context],
                    "hits": sorted(hl), "marker": bool(c.get("marker")), "picked_for": c["picked_for"],
                    "model": {"scores": c["scores"], "action": c["action"], **({"reason": c["reason"]} if c.get("reason") else {}),
                              **({"labels": c["labels"]} if c.get("labels") is not None else {})},
                    "labels": {k: None for k in policy.labels}, "action": None,
                    "status": "todo", "by": None, "note": ""})
            need.discard(rec.line)
            if not need:
                break
    return items


def cmd_review(args) -> int:
    """The human-review queue of a run: every paragraph whose action is 'review' (or --actions ...), as a
    hand-label file that tools/label_tool.html opens. The reviewer decides with 'your action' (+ a note)."""
    run = Path(args.run)
    pairs = _run_files(run)
    if not pairs:
        print(f"error: {run} has no finished files", file=sys.stderr)
        return 2
    summ = json.loads((run / "summary.json").read_text(encoding="utf-8")) if (run / "summary.json").is_file() else {}
    pol_path = args.policy or (summ.get("policy") or {}).get("path")
    policy = Policy.load(pol_path)
    want = set(args.actions)
    cands = []
    for inp, lp in pairs:
        with open(lp, encoding="utf-8") as fh:
            for raw in fh:
                r = json.loads(raw)
                for pa in r.get("paragraphs") or []:
                    if pa["action"] not in want:
                        continue
                    cands.append({"key": f"{inp}#{r['line']}#{pa['span'][0]}-{pa['span'][1]}", "file": inp,
                                  "line": r["line"], "id": r.get("id"), "span": pa["span"], "scores": pa["scores"],
                                  "action": pa["action"], "reason": pa.get("reason"), "labels": pa.get("labels"),
                                  "marker": pa.get("marker", False),
                                  "picked_for": [f"{pa['action']}:{pa.get('reason')}"] +
                                                [f"label:{k}" for k in pa.get("labels") or []]})
    if not cands:
        print(f"no paragraphs with action {', '.join(sorted(want))} in {run}")
        return 0
    items = paragraph_items(cands, policy, args.text_field, args.context, _opener(run))
    out = Path(args.out)
    if out.exists() and not args.overwrite:
        print(f"error: {out} exists (use --overwrite)", file=sys.stderr)
        return 2
    rs = summ.get("settings") or {}
    setup = setup_key(rs.get("fast_model"), rs.get("judge_model"), rs.get("uncertain_band"), rs.get("max_length")) \
        if rs else None
    write_labels_file(str(out), label_meta(policy, run=str(run), kind=f"review queue ({', '.join(sorted(want))})",
                                           setup=setup), items)
    why = collections.Counter(it["picked_for"][0] for it in items)
    labs = collections.Counter(w[6:] for it in items for w in it["picked_for"][1:])
    print(f"{len(items)} paragraphs -> {out}")
    print("  by reason: " + ", ".join(f"{k} {v}" for k, v in why.most_common()))
    print("  by label:  " + ", ".join(f"{k} {v}" for k, v in labs.most_common()))
    if len(items) < len(cands):
        print(f"  {len(cands) - len(items)} skipped: their documents are empty now")
    print("open it in tools/label_tool.html: answer the labels, set 'your action' (remove / keep), note why")
    return 0


def cmd_sample(args) -> int:
    policy = Policy.load(args.policy)
    run = Path(args.run)
    pairs = _run_files(run)
    if not pairs:
        print(f"error: {run} has no finished files (*.summary.json + *.labels.jsonl)", file=sys.stderr)
        return 2
    cands: List[Dict[str, Any]] = []
    for inp, lp in pairs:
        with open(lp, encoding="utf-8") as fh:
            for raw in fh:
                r = json.loads(raw)
                for pa in r.get("paragraphs") or []:
                    cands.append({"file": inp, "line": r["line"], "id": r.get("id"), "span": pa["span"],
                                  "scores": pa["scores"], "action": pa["action"], "marker": pa.get("marker", False)})
    if not cands:
        print("error: the run has no labelled paragraphs", file=sys.stderr)
        return 2
    existing = set()
    for f in args.exclude or []:
        _, its = read_labels_file(f)
        existing |= {it.get("key") for it in its}
    rng = random.Random(args.seed)
    picked: Dict[str, Dict[str, Any]] = {}

    def key(c: Dict[str, Any]) -> str:
        return f"{c['file']}#{c['line']}#{c['span'][0]}-{c['span'][1]}"

    def take(c: Dict[str, Any], why: str) -> None:
        k = key(c)
        if k in existing:
            return
        if k not in picked:
            picked[k] = dict(c, picked_for=[], key=k)
        if why not in picked[k]["picked_for"]:
            picked[k]["picked_for"].append(why)

    pool = [c for c in cands if key(c) not in existing]
    for c in rng.sample(pool, min(args.random, len(pool))):
        take(c, "random")
    keys = [args.label] if args.label else list(policy.labels)
    for k in keys:
        if k not in policy.labels:
            print(f"error: unknown label '{k}'", file=sys.stderr)
            return 2
        thr = policy.labels[k].threshold
        scored = [c for c in pool if c["scores"].get(k) is not None]
        if not scored:
            continue
        top = sorted(scored, key=lambda c: -c["scores"][k])[:args.top]
        near = sorted([c for c in scored if 0.15 <= c["scores"][k] <= 0.97],
                      key=lambda c: abs(c["scores"][k] - thr))[:args.near]
        low = [c for c in scored if c["scores"][k] < 0.15]
        for c in top:
            take(c, f"top:{k}")
        for c in near:
            take(c, f"near:{k}")
        for c in rng.sample(low, min(args.low, len(low))):
            take(c, f"low:{k}")
    items = paragraph_items(list(picked.values()), policy, args.text_field, args.context, _opener(run))
    rng.shuffle(items)
    out = Path(args.out)
    if out.exists() and not args.overwrite:
        print(f"error: {out} exists (use --overwrite, or --exclude it and write a new file)", file=sys.stderr)
        return 2
    rs = (json.loads((run / "summary.json").read_text(encoding="utf-8")).get("settings") or {}) \
        if (run / "summary.json").is_file() else {}
    setup = setup_key(rs.get("fast_model"), rs.get("judge_model"), rs.get("uncertain_band"), rs.get("max_length")) \
        if rs else None
    write_labels_file(str(out), label_meta(policy, run=str(run), seed=args.seed, setup=setup), items)
    reasons = collections.Counter(w.split(":")[0] for it in items for w in it["picked_for"])
    print(f"{len(items)} paragraphs -> {out}  ({', '.join(f'{k} {v}' for k, v in reasons.items())})")
    print("label them in tools/label_tool.html (open the file in a browser), then: "
          f"python nli_label.py eval {out}")
    return 0


# --------------------------------------------------------------------------------------------------
# eval: per-label accuracy and thresholds against hand labels
# --------------------------------------------------------------------------------------------------


class ScoreCache:
    """Scores per (model setup, hypothesis, text), stored next to the labels file: re-running eval after
    labelling more items or editing a hypothesis only scores what is new."""

    def __init__(self, path: Path, setup: str):
        self.path, self.setup = path, setup
        self.data: Dict[str, float] = {}
        if path.is_file():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                self.data = {}

    def key(self, hyp: str, text: str) -> str:
        return hashlib.sha1(f"{self.setup}\x00{hyp}\x00{text}".encode("utf-8")).hexdigest()

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(self.data), encoding="utf-8")
        tmp.replace(self.path)


def _metrics(pairs: List[Tuple[float, bool]], t: float) -> Dict[str, Any]:
    tp = sum(1 for s, y in pairs if y and s >= t)
    fp = sum(1 for s, y in pairs if not y and s >= t)
    fn = sum(1 for s, y in pairs if y and s < t)
    tn = sum(1 for s, y in pairs if not y and s < t)
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f1 = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": p, "recall": r, "f1": f1}


def best_threshold(pairs: List[Tuple[float, bool]]) -> Optional[float]:
    """Threshold with the best F1 (ties: the higher threshold)."""
    if not any(y for _, y in pairs):
        return None
    best, best_t = -1.0, None
    for t in sorted({round(s, 4) for s, _ in pairs} | {0.5, 0.8, 0.9}):
        f = _metrics(pairs, t)["f1"] or 0.0
        if f >= best:
            best, best_t = f, t
    return best_t


def recall_threshold(pairs: List[Tuple[float, bool]], target: float) -> Optional[float]:
    """Highest threshold whose recall on the labelled yes items is >= target."""
    pos = sorted((s for s, y in pairs if y), reverse=True)
    if not pos:
        return None
    k = math.ceil(target * len(pos))
    return round(pos[k - 1], 4) if k >= 1 else None


def crc_threshold(pos_scores: List[float], alpha: float) -> Optional[float]:
    """Conformal Risk Control for the miss rate of a yes/no label (Angelopoulos et al. 2022): the highest
    threshold t with (misses(t) + 1) / (n + 1) <= alpha, misses(t) = yes items scoring below t. The yes items
    must be a RANDOM sample of the paragraphs the policy will see. None if n is too small for alpha."""
    n = len(pos_scores)
    if n == 0 or 1.0 / (n + 1) > alpha:
        return None
    allowed = math.floor(alpha * (n + 1) - 1 + 1e-9)  # misses allowed
    s = sorted(pos_scores)
    # t = the (allowed+1)-th smallest yes score: exactly `allowed` yes items lie below it
    return round(s[allowed], 4) if allowed < n else 1.0


def cmd_eval(args) -> int:
    policy = Policy.load(args.policy)
    items: List[Dict[str, Any]] = []
    metas: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []
    for f in args.labels:
        meta, its = read_labels_file(f)
        items += its
        metas.append((meta, its))
    statuses = {"done"} | ({"draft"} if args.include_drafts else set())
    use = [it for it in items if it.get("status") in statuses]
    if not use:
        print(f"no items with status {sorted(statuses)} in {', '.join(args.labels)} "
              f"({len(items)} items; label some, or --include-drafts)", file=sys.stderr)
        return 2
    setup = setup_key(args.fast_model, args.judge_model, args.uncertain_band, args.max_length)
    cache = ScoreCache(Path(args.cache or (args.labels[0] + ".scores.json")), setup)
    # scores the sampled run already computed: reused when the model setup and the hypothesis are the same
    reused = 0
    for meta, its in metas:
        if meta.get("setup") != setup:
            continue
        old_h = {k: (v or {}).get("hypothesis") for k, v in (meta.get("labels") or {}).items()}
        for it in its:
            for k, v in ((it.get("model") or {}).get("scores") or {}).items():
                lab = policy.labels.get(k)
                if lab is not None and v is not None and old_h.get(k) == lab.hypothesis:
                    ck = cache.key(lab.hypothesis, it["text"])
                    if ck not in cache.data:
                        cache.data[ck] = float(v)
                        reused += 1
    if reused:
        log.warning("reused %d scores stored by the sampled run", reused)
        cache.save()
    todo = []
    for it in use:
        for lab in policy.labels.values():
            k = cache.key(lab.hypothesis, it["text"])
            if k not in cache.data:
                todo.append((k, it["text"], lab.hypothesis))
    if todo:
        log.warning("scoring %d new (paragraph, hypothesis) pairs", len(todo))
        scorer, fast, judge = build_scorer(args)
        try:
            for i in range(0, len(todo), 256):
                part = todo[i:i + 256]
                res = scorer.score([t for _, t, _ in part], [h for _, _, h in part])
                for (k, _, _), (_, _, final) in zip(part, res):
                    cache.data[k] = round(float(final), 4)
                cache.save()
        finally:
            for pool in (fast, judge):
                if pool is not None:
                    pool.close()
    rows = []
    for it in use:
        scores = {k: cache.data[cache.key(lab.hypothesis, it["text"])] for k, lab in policy.labels.items()}
        rows.append((it, scores))
    report: Dict[str, Any] = {"items": len(use), "labels": {}, "settings": {"setup": setup, "files": args.labels}}
    L = [f"{len(use)} labelled paragraphs ({', '.join(sorted(statuses))})  model setup {setup}", "",
         "label                          dec.     yes   no |  thr   prec  recall    F1 | best-F1 thr  "
         f"thr@recall{args.target_recall:.2f}  CRC@miss{args.miss:.2f}"]
    for k, lab in policy.labels.items():
        pairs = [(sc[k], bool(it["labels"].get(k))) for it, sc in rows if it["labels"].get(k) is not None]
        rnd = [sc[k] for it, sc in rows if it["labels"].get(k) and "random" in (it.get("picked_for") or [])]
        yes = sum(1 for _, y in pairs if y)
        no = len(pairs) - yes
        m = _metrics(pairs, lab.threshold) if pairs else {}
        bt = best_threshold(pairs) if pairs else None
        rt = recall_threshold(pairs, args.target_recall) if pairs else None
        ct = crc_threshold(rnd, args.miss) if lab.decision in ("remove", "gate") else None
        report["labels"][k] = {"decision": lab.decision, "threshold": lab.threshold, "yes": yes, "no": no,
                               **m, "best_f1_threshold": bt, "recall_threshold": rt,
                               "crc_threshold": ct, "crc_random_yes": len(rnd)}

        def f(x: Optional[float]) -> str:
            return f"{x:5.2f}" if x is not None else "    -"
        warn = " (<50 yes/no)" if yes < 50 or no < 50 else ""
        crc_txt = f(ct) if ct is not None else (f"n={len(rnd)}<{math.ceil(1 / args.miss) - 1}"
                                                  if lab.decision in ("remove", "gate") else "    -")
        L.append(f"{k[:30]:<30} {lab.decision:<7} {yes:>4} {no:>4} | {lab.threshold:4.2f} {f(m.get('precision'))} "
                 f"{f(m.get('recall'))} {f(m.get('f1'))} |     {f(bt)}         {f(rt)}       {crc_txt}{warn}")
    # actions
    conf = collections.Counter()
    wrong_removed = missed = 0
    for it, sc in rows:
        truth = it.get("action") or action_from_labels(policy, it.get("labels") or {})
        if not truth:
            continue
        marker = bool(it.get("marker"))
        pred = resolve(policy, sc, marker)["action"]
        conf[(truth, pred)] += 1
        tok = est_tokens(it["text"])
        if pred == "remove" and truth in ("keep", "pass"):
            wrong_removed += tok
        if truth == "remove" and pred != "remove":
            missed += tok
    n_act = sum(conf.values())
    report["actions"] = {"n": n_act, "confusion": {f"{a}->{b}": v for (a, b), v in conf.items()},
                         "tokens_wrongly_removed": wrong_removed, "tokens_missed": missed}
    if n_act:
        L += ["", f"actions ({n_act} items; rows = your action, columns = policy action from the scores)",
              "            " + "".join(f"{a:>8}" for a in ACTIONS)]
        for a in ACTIONS:
            L.append(f"  {a:<9} " + "".join(f"{conf.get((a, b), 0):>8}" for b in ACTIONS))
        agree = sum(v for (a, b), v in conf.items() if a == b)
        L.append(f"  agreement {agree}/{n_act} ({_pct(agree, n_act).strip()});  wrongly removed ~{wrong_removed:,} "
                 f"tokens, missed ~{missed:,} tokens")
    L += ["", "thr = policy threshold; best-F1 / thr@recall / CRC = suggestions from these labels. CRC uses only "
          "items picked at random (picked_for 'random') and gives: expected miss rate <= "
          f"{args.miss:.2f} for that label, if the corpus is like the sample (cmds/labeling/thresholds.md)."]
    print("\n".join(L))
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nreport -> {args.out}")
    return 0


# --------------------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------------------


def _model_args(p: argparse.ArgumentParser, judge_default: str = "deberta") -> None:
    g = p.add_argument_group("models")
    g.add_argument("--fast-model", default="modernbert", help="modernbert | deberta | bge-m3 (default modernbert)")
    g.add_argument("--judge-model", default=judge_default,
                   help=f"re-scores scores inside --uncertain-band; none = off (default {judge_default})")
    g.add_argument("--uncertain-band", type=float, nargs=2, default=[0.6, 0.95], metavar=("LOW", "HIGH"))
    g.add_argument("--device", default="auto", help="auto | cpu | cuda | cuda:0,cuda:1 ...")
    g.add_argument("--mode", default="auto", help="auto | single | thread | process")
    g.add_argument("--dtype", default="auto")
    g.add_argument("--batch-size", type=int, default=32)
    g.add_argument("--max-length", type=int, default=512, help="tokens per (paragraph, hypothesis) pair")
    g.add_argument("--models-root", default=None)
    g.add_argument("--cpu-threads", type=int, default=None)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Label Russia-related content per A's policy (cmds/labeling/README.md).")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="label input files (paragraph labels as columns; optional cleaned copy)")
    r.add_argument("inputs", nargs="+", help="files / folders / globs (.jsonl .jsonl.zst .parquet ...)")
    r.add_argument("--output-dir", required=True)
    r.add_argument("--policy", default=str(DEFAULT_POLICY))
    r.add_argument("--write-clean", action="store_true", help="also write <name>.clean.jsonl (removed paragraphs "
                   "cut out, place names rewritten, empty documents dropped)")
    r.add_argument("--compress", choices=["none", "zst"], default="none", help="for the clean output")
    r.add_argument("--all-labels", action="store_true",
                   help="score every label on every gated paragraph (no level cascade): slower; for sampling")
    r.add_argument("--review-as", choices=["keep", "remove"], default="keep",
                   help="what the clean output does with 'review' paragraphs (default keep; they are counted)")
    r.add_argument("--no-rules", action="store_true", help="no language-menu / company-name rules")
    r.add_argument("--no-rewrite", action="store_true", help="no place-name rewrite")
    r.add_argument("--place-names", default=None, help="mapping CSV (default policy/place_names.csv)")
    r.add_argument("--place-name-exceptions", default=None)
    r.add_argument("--text-field", default="text")
    r.add_argument("--id-field", default="id")
    r.add_argument("--group-field", default=None, help="field to break the composition down by (e.g. source)")
    r.add_argument("--min-doc-chars", type=int, default=50, help="shorter after cleaning = document removed")
    r.add_argument("--chunk-lines", type=int, default=64)
    r.add_argument("--limit", type=int, default=None, help="first N lines per file")
    r.add_argument("--overwrite", action="store_true", help="redo files that are already done")
    g = r.add_argument_group("server input (ftp:// ftps:// sftp:// s3:// minio://, as in nli_filter.py)")
    g.add_argument("--shard", metavar="K/N", help="only every N-th file, starting at K (0/4 .. 3/4 on 4 machines "
                                                   "or GPUs, same --output-dir or one each)")
    g.add_argument("--download-dir", help="where server files are downloaded while the previous one is labelled "
                                          "(default <output-dir>/.download); each is deleted when done")
    g.add_argument("--retries", type=int, default=3, help="download retries before the file is skipped (default 3)")
    _model_args(r)

    s = sub.add_parser("sample", help="pick paragraphs of a run to hand-label")
    s.add_argument("run", help="output folder of 'run' (best with --all-labels)")
    s.add_argument("--out", required=True, help="hand-label file to write (e.g. labels/seed.jsonl)")
    s.add_argument("--policy", default=str(DEFAULT_POLICY))
    s.add_argument("--random", type=int, default=80, help="paragraphs picked at random (default 80)")
    s.add_argument("--top", type=int, default=3, help="per label: highest scores (likely yes)")
    s.add_argument("--near", type=int, default=3, help="per label: closest to the threshold (near misses)")
    s.add_argument("--low", type=int, default=1, help="per label: random low scores (likely no)")
    s.add_argument("--label", help="only this label (a focused round, e.g. --label celebrities --top 40 --near 30)")
    s.add_argument("--exclude", nargs="+", help="label files whose paragraphs are not picked again")
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--context", type=int, default=300, help="characters before / after shown while labelling")
    s.add_argument("--text-field", default="text")
    s.add_argument("--overwrite", action="store_true")

    e = sub.add_parser("eval", help="per-label precision / recall and suggested thresholds from hand labels")
    e.add_argument("labels", nargs="+", help="hand-label files")
    e.add_argument("--policy", default=str(DEFAULT_POLICY))
    e.add_argument("--include-drafts", action="store_true", help="also use status 'draft' items (unchecked)")
    e.add_argument("--target-recall", type=float, default=0.9)
    e.add_argument("--miss", type=float, default=0.05, help="target miss rate for the CRC threshold (default 0.05)")
    e.add_argument("--cache", help="score cache (default <first labels file>.scores.json)")
    e.add_argument("--out", help="write the report as JSON")
    _model_args(e)

    rp = sub.add_parser("report", help="print a run's token-weighted composition again")
    rp.add_argument("run")

    rv = sub.add_parser("review", help="the human-review queue of a run (paragraphs with action 'review') as a "
                                       "hand-label file for tools/label_tool.html")
    rv.add_argument("run", help="output folder of 'run' or 'redecide'")
    rv.add_argument("--out", required=True, help="e.g. labels/review_dclm_01.jsonl")
    rv.add_argument("--policy", help="default: the policy the run used")
    rv.add_argument("--actions", nargs="+", default=["review"], choices=list(ACTIONS),
                    help="which paragraph actions to queue (default review; e.g. review remove to check removals too)")
    rv.add_argument("--context", type=int, default=300)
    rv.add_argument("--text-field", default="text")
    rv.add_argument("--overwrite", action="store_true")

    d = sub.add_parser("redecide", help="apply a changed policy (thresholds, decisions, run_if) to a finished run "
                                        "from its stored scores, no models")
    d.add_argument("run", help="output folder of 'run'")
    d.add_argument("--output-dir", required=True, help="a new folder")
    d.add_argument("--policy", default=str(DEFAULT_POLICY))
    d.add_argument("--write-clean", action="store_true")
    d.add_argument("--compress", choices=["none", "zst"], default="none")
    d.add_argument("--review-as", choices=["keep", "remove"], default="keep")
    d.add_argument("--no-rules", action="store_true")
    d.add_argument("--no-rewrite", action="store_true")
    d.add_argument("--place-names", default=None)
    d.add_argument("--place-name-exceptions", default=None)
    d.add_argument("--text-field", default="text")
    d.add_argument("--id-field", default="id")
    d.add_argument("--group-field", default=None)
    d.add_argument("--min-doc-chars", type=int, default=50)
    d.add_argument("--chunk-lines", type=int, default=256)
    return ap


def _utf8_console() -> None:
    """Windows consoles default to cp1252: Cyrillic in a report would crash print()."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    _utf8_console()
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        return {"run": cmd_run, "sample": cmd_sample, "eval": cmd_eval, "report": cmd_report,
                "redecide": cmd_redecide, "review": cmd_review}[args.cmd](args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

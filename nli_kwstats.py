#!/usr/bin/env python3
"""
nli_kwstats.py - keyword and marker statistics over a corpus (no models, CPU only). Guide: cmds/labeling/keyword_stats.md.

    python nli_label.py kwstats CORPUS --policy policy/russia_llm_policy_v2.json --output-dir dataset/kwstats_<name>
        [--topic-field FIELD] [--group-by folder|file] [--shard K/N] [--limit N]
    python nli_kwstats.py CORPUS ...            (the same, standalone)

The terms are the policy's keyword files, its markers and its narrative_keywords. Every line is matched exactly as an
nli_label run's keyword gate does it (nli_label.build_matchers: the same KeywordMatcher and the same cheap
language-menu / company-name rules), so "gated lines" and "candidate paragraphs" are what a run would label.

Outputs (in --output-dir):
  kwstats.json             everything the viewer's /label/kwstats/ page shows (terms, units, histograms, pairs, report)
  terms.csv                one row per term
  report.md                the written report (coverage, dominant / dead / incidental terms, spread, overlaps,
                           the GPU-time forecast, suggestions)
  kwstats.part[.shardKofN].json   the raw counts of one scan; shards are merged when all N parts are there
                                  (or with --merge)
"""
from __future__ import annotations

import argparse
import bisect
import collections
import csv
import hashlib
import json
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import nli_formats  # noqa: E402
from nli_label import (Policy, _mask, build_matchers, build_narrative_matcher, expand_typed, get_path,  # noqa: E402
                       split_paragraphs)
from nli_models import JsonlSource, expand_inputs, zstd_available  # noqa: E402

VERSION = 1
PAIR_CAP_PART = 50_000      # co-occurring pairs kept per shard part
PAIR_CAP_FINAL = 1_000      # pairs kept in kwstats.json
CO_PER_TERM = 5             # co-occurring terms per term
MAX_TERMS_PER_PARA = 60     # distinct terms of one paragraph used for pairs (60 -> 1,770 pairs)
HIST_CAP = 100              # histogram keys 0..99, then "100+"
WORD_CAP = 300_000          # suggestion-word counter size before pruning
WORDS_PART = 3_000          # suggestion words kept per part
OVERLAP_CAP = 2_000
DEFAULT_PPS = (3000.0, 5000.0)  # ModernBERT pairs/s per H200 (estimate, cmds/h200/nli_label_h200.md section 4)

_SENT = re.compile(r"(?<=[.!?…])\s+|(?<=[。！？])|\n+")
_WORD = re.compile(r"(?<![\w])[A-ZА-ЯЁІЇЄҐ][\w'’-]{2,}")


# --------------------------------------------------------------------------------------------------
# terms
# --------------------------------------------------------------------------------------------------


def _here(f: str) -> Path:
    return Path(f) if Path(f).is_absolute() else HERE / f


class Terms:
    """The terms of a policy, as the run's matchers see them: id -> (term, kind, list)."""

    def __init__(self, policy: Policy, no_rules: bool = False):
        from nli_filter import load_lexicon
        self.policy = policy
        self.matcher, rules, self.markers = build_matchers(policy)
        self.rules = None if no_rules else rules
        self.narrative = build_narrative_matcher(policy)
        # which list a keyword comes from (the matcher keeps the first of a word listed twice)
        first_file: Dict[str, str] = {}
        self.raw: List[Tuple[str, str, str, Optional[int]]] = []  # (lower, kind, list, line) incl. repeats
        for kf in policy.keywords_files:
            p = _here(kf)
            if not p.is_file():
                continue
            for e in load_lexicon(str(p)):
                low = e.keyword.strip().lower()
                first_file.setdefault(low, p.name)
                self.raw.append((low, "keyword", p.name, e.line))
        self.items: List[Dict[str, Any]] = []
        self.kw_id = []
        for k in self.matcher.keywords:
            self.kw_id.append(len(self.items))
            self.items.append({"term": k, "kind": "keyword", "list": first_file.get(k.lower(), "(built-in)")})
        self.marker_id = []
        if self.markers is not None:
            for i, k in enumerate(self.markers.keywords):
                self.marker_id.append(len(self.items))
                self.items.append({"term": k, "kind": "marker", "list": "markers"})
        for i, k in enumerate(policy.markers):
            self.raw.append((k.strip().lower(), "marker", "markers", i + 1))
        self.narr_id = []
        if self.narrative is not None:
            for k in self.narrative.keywords:
                self.narr_id.append(len(self.items))
                self.items.append({"term": k, "kind": "narrative", "list": "narrative_keywords"})
        for i, k in enumerate(policy.narrative_keywords):
            self.raw.append((k.strip().lower(), "narrative", "narrative_keywords", i + 1))
        self.warnings = list(self.matcher.warnings) + (list(self.markers.warnings) if self.markers else [])

    def __len__(self) -> int:
        return len(self.items)

    def signature(self) -> str:
        h = hashlib.sha1()
        for t in self.items:
            h.update(f"{t['kind']}\t{t['term']}\n".encode("utf-8"))
        return h.hexdigest()[:16]

    def duplicates(self) -> List[Dict[str, Any]]:
        """Terms listed more than once (same word, any case): in one file, in two files, or as keyword and marker."""
        by: Dict[str, List[str]] = collections.defaultdict(list)
        for low, kind, lst, line in self.raw:
            by[low].append(f"{lst}:{line}" if line else lst)
        return [{"term": low, "places": places} for low, places in by.items() if len(places) > 1]

    def overlaps(self) -> List[Dict[str, Any]]:
        """Pairs (inner, outer): the inner term is a whole-word part of the outer one. Where the outer term matches,
        the run counts only the outer one (the longest match wins)."""
        from nli_filter import _word_char, is_cjk
        index: Dict[str, int] = {}
        for i, t in enumerate(self.items):
            index.setdefault(t["term"].lower(), i)
        out = []
        for i, t in enumerate(self.items):
            low = t["term"].lower()
            n = len(low)
            if n > 200:
                continue
            cjk = any(is_cjk(c) for c in low)
            starts = [0] + [k for k in range(1, n) if cjk or (not _word_char(low[k - 1]) and _word_char(low[k]))]
            ends = [k for k in range(1, n) if cjk or (_word_char(low[k - 1]) and not _word_char(low[k]))] + [n]
            seen = set()
            for s in starts:
                for e in ends:
                    if e <= s or (s == 0 and e == n):
                        continue
                    j = index.get(low[s:e])
                    if j is not None and j != i and j not in seen:
                        seen.add(j)
                        out.append({"inner": self.items[j]["term"], "inner_id": j, "outer": t["term"], "outer_id": i})
                        if len(out) >= OVERLAP_CAP:
                            return out
        return out


# --------------------------------------------------------------------------------------------------
# scanning
# --------------------------------------------------------------------------------------------------


def _hist_key(n: int) -> str:
    return str(n) if n < HIST_CAP else f"{HIST_CAP}+"


def new_part(terms: Terms) -> Dict[str, Any]:
    n = len(terms)
    return {"kind": "kwstats-part", "version": VERSION, "signature": terms.signature(), "n_terms": n,
            "totals": collections.Counter(), "hist_hits": collections.Counter(), "hist_terms": collections.Counter(),
            "units": {}, "t": {k: [0] * n for k in ("hits", "incidental", "lines", "gate_lines", "paragraphs",
                                                     "sentences", "files")},
            "t_units": {}, "pairs": collections.Counter(), "words": {}, "files": [], "seconds": 0.0}


class Scanner:
    def __init__(self, policy: Policy, terms: Terms, text_field: str = "text", topic_field: Optional[str] = None,
                 group_by: str = "folder", suggest: bool = True):
        self.p, self.terms = policy, terms
        self.text_field, self.topic_field, self.group_by = text_field, topic_field, group_by
        self.suggest = suggest
        self.part = new_part(terms)

    # -- one line --------------------------------------------------------------------------------
    def _unit_add(self, dim: str, unit: str, **kw: int) -> None:
        c = self.part["units"].setdefault(dim, {}).setdefault(unit, collections.Counter())
        for k, v in kw.items():
            c[k] += v

    def line(self, text: str, units: Dict[str, List[str]], file_terms: set) -> None:
        P, T = self.part, self.terms
        tot = P["totals"]
        tot["lines_text"] += 1
        tot["chars"] += len(text)
        paras = split_paragraphs(text, self.p.min_chars, self.p.max_chars)
        p_starts = [s for s, _ in paras]
        seg_starts = [0]
        n_sent = 0
        last = 0
        for m in _SENT.finditer(text):
            if text[last:m.start()].strip():
                n_sent += 1
            last = m.end()
            seg_starts.append(m.end())
        if text[last:].strip():
            n_sent += 1
        tot["paragraphs"] += len(paras)
        tot["sentences"] += n_sent

        hits = T.matcher.find(text)
        if T.rules is not None and hits:
            T.rules.apply(text, hits)
        marks = T.markers.find(text) if T.markers is not None else []
        nks = T.narrative.find(text) if T.narrative is not None else []
        # (term id, start, incidental, opens the gate)
        found: List[Tuple[int, int, bool, bool]] = []
        for h in hits:
            if h.kw is None:
                continue
            found.append((T.kw_id[h.kw], h.start, bool(h.rule), not h.rule))
        for h in marks:
            if h.kw is not None:
                found.append((T.marker_id[h.kw], h.start, False, True))
        for h in nks:
            if h.kw is not None:
                found.append((T.narr_id[h.kw], h.start, False, True))
        n_hits = len(found)
        gated = any(f[3] for f in found)
        tot["hits"] += n_hits
        P["hist_hits"][_hist_key(n_hits)] += 1
        line_terms = {f[0] for f in found}
        P["hist_terms"][_hist_key(len(line_terms))] += 1
        para_hit, para_open = set(), set()
        if found:
            tot["lines_with_hit"] += 1
            tc = P["t"]
            per_para: Dict[int, set] = collections.defaultdict(set)
            t_paras: Dict[int, set] = collections.defaultdict(set)
            t_sents: Dict[int, set] = collections.defaultdict(set)
            t_gate = set()
            for tid, start, inc, opens in found:
                tc["hits"][tid] += 1
                if inc:
                    tc["incidental"][tid] += 1
                    tot["incidental_hits"] += 1
                kind = T.items[tid]["kind"]
                tot[f"{kind}_hits"] += 1
                pi = max(0, bisect.bisect_right(p_starts, start) - 1)
                si = max(0, bisect.bisect_right(seg_starts, start) - 1)
                para_hit.add(pi)
                if opens:
                    para_open.add(pi)
                    t_gate.add(tid)
                per_para[pi].add(tid)
                t_paras[tid].add(pi)
                t_sents[tid].add(si)
            for tid in line_terms:
                tc["lines"][tid] += 1
                tc["paragraphs"][tid] += len(t_paras[tid])
                tc["sentences"][tid] += len(t_sents[tid])
                file_terms.add(tid)
            for tid in t_gate:
                tc["gate_lines"][tid] += 1
            per_term_hits = collections.Counter(f[0] for f in found)
            for dim, vals in units.items():
                tu = P["t_units"].setdefault(dim, {})
                for u in vals:
                    for tid, n in per_term_hits.items():
                        d = tu.setdefault(tid, {})
                        c = d.get(u)
                        if c is None:
                            d[u] = [n, 1]
                        else:
                            c[0] += n
                            c[1] += 1
            for tids in per_para.values():
                ids = sorted(tids)[:MAX_TERMS_PER_PARA]
                for a in range(len(ids)):
                    for b in range(a + 1, len(ids)):
                        P["pairs"][(ids[a], ids[b])] += 1
        if gated:
            tot["lines_gated"] += 1
        tot["paragraphs_with_hit"] += len(para_hit)
        cand = len(para_open) if gated else 0  # the paragraphs a run labels (a hit, a marker or a narrative word)
        tot["paragraphs_candidate"] += cand
        for dim, vals in units.items():
            for u in vals:
                self._unit_add(dim, u, lines=1, lines_with_hit=int(bool(found)), lines_gated=int(gated),
                               paragraphs=len(paras), paragraphs_candidate=cand, hits=n_hits)
        if self.suggest:
            self._words(text, gated)

    def _words(self, text: str, gated: bool) -> None:
        words = self.part["words"]
        k = 0 if gated else 1
        for w in set(_WORD.findall(text)):
            c = words.get(w)
            if c is None:
                c = words[w] = [0, 0]
            c[k] += 1
        if len(words) > WORD_CAP:  # keep the counter bounded: drop words seen in one line only
            for w in [w for w, c in words.items() if c[0] + c[1] <= 1]:
                del words[w]

    # -- one file --------------------------------------------------------------------------------
    def file(self, path: Any, name: str, unit: str, limit: Optional[int] = None, id_field: str = "id") -> int:
        P = self.part
        tot = P["totals"]
        file_terms: set = set()
        n = 0
        for rec in JsonlSource(path).records(limit=limit):
            n += 1
            tot["lines"] += 1
            if rec.error is not None:
                tot["errors"] += 1
                continue
            text = rec.get(self.text_field)
            if not isinstance(text, str):
                tot["no_text"] += 1
                continue
            units: Dict[str, List[str]] = {self.group_by: [unit]}
            if self.topic_field:
                v = get_path(rec.data, self.topic_field) if isinstance(rec.data, dict) else None
                vals = [str(x).strip() for x in (v if isinstance(v, list) else [v])
                        if x is not None and str(x).strip()]
                units["topic"] = sorted(set(vals)) or ["(none)"]
            self.line(text, units, file_terms)
        for tid in file_terms:
            P["t"]["files"][tid] += 1
        tot["files"] += 1
        P["files"].append({"input": _mask(path), "name": name, "unit": unit, "lines": n})
        return n


# --------------------------------------------------------------------------------------------------
# parts: write, read, merge
# --------------------------------------------------------------------------------------------------


def part_to_json(part: Dict[str, Any]) -> Dict[str, Any]:
    pairs = part["pairs"].most_common(PAIR_CAP_PART)
    words = sorted(part["words"].items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))[:WORDS_PART]
    return {**{k: v for k, v in part.items() if k not in ("totals", "hist_hits", "hist_terms", "units", "t_units",
                                                          "pairs", "words")},
            "totals": dict(part["totals"]), "hist_hits": dict(part["hist_hits"]), "hist_terms": dict(part["hist_terms"]),
            "units": {d: {u: dict(c) for u, c in us.items()} for d, us in part["units"].items()},
            "t_units": {d: {str(t): v for t, v in tu.items()} for d, tu in part["t_units"].items()},
            "pairs": [[a, b, c] for (a, b), c in pairs], "pairs_total": len(part["pairs"]),
            "words": [[w, c[0], c[1]] for w, c in words]}


def merge_parts(parts: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """JSON parts -> one JSON part (sums). All parts must come from the same policy terms."""
    if not parts:
        raise ValueError("no parts to merge")
    sig = {p["signature"] for p in parts}
    if len(sig) > 1:
        raise ValueError("the parts were made with different keyword lists (scan every shard with the same policy)")
    n = parts[0]["n_terms"]
    out: Dict[str, Any] = {"kind": "kwstats-part", "version": VERSION, "signature": parts[0]["signature"],
                           "n_terms": n, "seconds": 0.0, "files": [], "pairs_total": 0}
    tot, hh, ht = collections.Counter(), collections.Counter(), collections.Counter()
    units: Dict[str, Dict[str, collections.Counter]] = {}
    t = {k: [0] * n for k in parts[0]["t"]}
    t_units: Dict[str, Dict[str, Dict[str, List[int]]]] = {}
    pairs: collections.Counter = collections.Counter()
    words: Dict[str, List[int]] = {}
    for p in parts:
        out["seconds"] = max(out["seconds"], float(p.get("seconds", 0)))
        out["files"] += p["files"]
        out["pairs_total"] = max(out["pairs_total"], int(p.get("pairs_total", 0)))
        tot.update(p["totals"])
        hh.update(p["hist_hits"])
        ht.update(p["hist_terms"])
        for d, us in p["units"].items():
            for u, c in us.items():
                units.setdefault(d, {}).setdefault(u, collections.Counter()).update(c)
        for k, arr in p["t"].items():
            dst = t[k]
            for i, v in enumerate(arr):
                dst[i] += v
        for d, tu in p["t_units"].items():
            dd = t_units.setdefault(d, {})
            for tid, us in tu.items():
                x = dd.setdefault(tid, {})
                for u, (h, l) in us.items():
                    c = x.get(u)
                    if c is None:
                        x[u] = [h, l]
                    else:
                        c[0] += h
                        c[1] += l
        for a, b, c in p["pairs"]:
            pairs[(a, b)] += c
        for w, g, o in p["words"]:
            c = words.setdefault(w, [0, 0])
            c[0] += g
            c[1] += o
    out.update({"totals": dict(tot), "hist_hits": dict(hh), "hist_terms": dict(ht),
                "units": {d: {u: dict(c) for u, c in us.items()} for d, us in units.items()}, "t": t,
                "t_units": t_units, "pairs": [[a, b, c] for (a, b), c in pairs.most_common(PAIR_CAP_PART)],
                "words": [[w, c[0], c[1]] for w, c in
                          sorted(words.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))[:WORDS_PART]]})
    return out


# --------------------------------------------------------------------------------------------------
# finishing: kwstats.json, terms.csv, report.md
# --------------------------------------------------------------------------------------------------


def pairs_per_paragraph(policy: Policy) -> Dict[str, Any]:
    """Model pairs per candidate paragraph: low = only the gate (and what is always scored), high = every level."""
    gate = 1 if policy.gate is not None else 0
    exc = sum(1 for e in policy.exceptions if e.hypothesis)
    l1, l2 = len(policy.level(1)), len(policy.level(2))
    opening = sum(1 for lab in policy.level(2) if lab.decision == "remove") if policy.narrative_opens_gate else 0
    return {"gate": gate, "exceptions": exc, "level1": l1, "level2": l2, "opening": opening,
            "low": gate + exc + opening, "high": gate + exc + l1 + l2}


def forecast(policy: Policy, tot: Dict[str, int], gpus: int = 8, pps: Sequence[float] = DEFAULT_PPS,
             corpus_lines: Optional[int] = None) -> Dict[str, Any]:
    ppp = pairs_per_paragraph(policy)
    lines = int(tot.get("lines_text", 0))
    cand = int(tot.get("paragraphs_candidate", 0))
    scale = (corpus_lines / lines) if corpus_lines and lines else 1.0
    paras = cand * scale
    pairs_low, pairs_high = paras * ppp["low"], paras * ppp["high"]
    lo, hi = min(pps), max(pps)
    gpus = max(1, int(gpus))

    def hours(pairs: float, speed: float) -> float:
        return pairs / (speed * gpus) / 3600.0
    return {"pairs_per_paragraph": ppp, "candidate_paragraphs": cand, "scanned_lines": lines,
            "corpus_lines": corpus_lines or lines, "scale": scale, "paragraphs": paras,
            "pairs_low": pairs_low, "pairs_high": pairs_high, "gpus": gpus, "pairs_per_second": [lo, hi],
            "hours_high": [hours(pairs_high, hi), hours(pairs_high, lo)],
            "hours_low": [hours(pairs_low, hi), hours(pairs_low, lo)],
            "paragraphs_per_million_lines": (cand / lines * 1e6) if lines else 0.0}


def finish(part: Dict[str, Any], terms: Terms, policy: Policy, settings: Dict[str, Any],
           gpus: int = 8, pps: Sequence[float] = DEFAULT_PPS, corpus_lines: Optional[int] = None) -> Dict[str, Any]:
    if part["signature"] != terms.signature():
        raise ValueError("the parts were made with a different keyword list than the policy's now")
    tot = dict(part["totals"])
    n = len(terms)
    t = part["t"]
    lines_text = max(1, int(tot.get("lines_text", 0)))
    co: Dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
    for a, b, c in part["pairs"]:
        co[a][b] += c
        co[b][a] += c
    rows = []
    for i, it in enumerate(terms.items):
        r = {"id": i, **it}
        for k in t:
            r[k] = int(t[k][i])
        r["line_share"] = round(r["lines"] / lines_text, 6)
        r["incidental_share"] = round(r["incidental"] / r["hits"], 4) if r["hits"] else 0.0
        r["units"] = {d: tu.get(str(i), {}) for d, tu in part["t_units"].items()}
        r["co"] = [[j, c] for j, c in co[i].most_common(CO_PER_TERM)] if i in co else []
        rows.append(r)
    total_hits = sum(r["hits"] for r in rows)
    ranked = sorted(rows, key=lambda r: (-r["hits"], r["term"].lower()))
    for rank, r in enumerate(ranked, 1):
        r["rank"] = rank
    top1 = max(1, math.ceil(n * 0.01))
    conc = {"top10": (sum(r["hits"] for r in ranked[:10]) / total_hits) if total_hits else 0.0,
            "top1pct_n": top1, "top1pct": (sum(r["hits"] for r in ranked[:top1]) / total_hits) if total_hits else 0.0,
            "terms_hit": sum(1 for r in rows if r["hits"]), "terms": n}
    never = [r["id"] for r in rows if not r["hits"]]
    pairs = [[a, b, c] for a, b, c in sorted(part["pairs"], key=lambda x: (-x[2], x[0], x[1]))[:PAIR_CAP_FINAL]]
    words = []
    g_lines, o_lines = int(tot.get("lines_gated", 0)), lines_text - int(tot.get("lines_gated", 0))
    lower_terms = {it["term"].lower() for it in terms.items}
    term_tokens = {w for x in lower_terms for w in re.split(r"[^\w]+", x) if w}
    for w, g, o in part["words"]:
        if g < 3 or w.lower() in lower_terms or w.lower() in term_tokens:
            continue
        lift = (g / max(1, g_lines)) / ((o + 1) / (o_lines + 1))
        if lift >= 5:
            words.append({"word": w, "gated_lines": g, "other_lines": o, "lift": round(lift, 1)})
    words.sort(key=lambda x: (-x["gated_lines"], -x["lift"], x["word"]))
    stats = {"kind": "kwstats", "version": VERSION, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
             "settings": settings, "policy": policy.path, "signature": part["signature"],
             "totals": tot, "hist": {"hits_per_line": part["hist_hits"], "terms_per_line": part["hist_terms"]},
             "units": part["units"], "dims": sorted(part["units"]), "files": part["files"],
             "terms": rows, "concentration": conc, "never_hit": never, "pairs": pairs,
             "pairs_total": part.get("pairs_total", len(pairs)), "duplicates": terms.duplicates(),
             "overlaps": terms.overlaps(), "warnings": terms.warnings, "suggest_words": words[:50],
             "forecast": forecast(policy, tot, gpus, pps, corpus_lines), "seconds": part.get("seconds", 0.0)}
    stats["report"] = report_items(stats)
    return stats


def _pct(a: float, b: float, nd: int = 1) -> str:
    return f"{100.0 * a / b:.{nd}f} %" if b else "–"


def _n(x: float) -> str:
    return f"{int(round(x)):,}"


def _h(x: float) -> str:
    """hours -> '12 s' / '7 min' / '3.4 h'."""
    if x * 3600 < 1:
        return "< 1 s"
    if x * 3600 < 60:
        return f"{x * 3600:.0f} s"
    return f"{x * 60:.0f} min" if x < 1 else f"{x:.1f} h"


def _names(rows: Iterable[Dict[str, Any]], k: int = 12, with_hits: bool = False) -> str:
    rows = list(rows)
    s = ", ".join(f"{r['term']} ({_n(r['hits'])})" if with_hits else r["term"] for r in rows[:k])
    return s + (f" … and {len(rows) - k} more" if len(rows) > k else "")


def report_items(st: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The written report: [{key, title, lines: [markdown]}], generated from the numbers only."""
    tot, rows = st["totals"], st["terms"]
    lines = int(tot.get("lines_text", 0))
    ranked = sorted(rows, key=lambda r: -r["hits"])
    total_hits = sum(r["hits"] for r in rows)
    out: List[Dict[str, Any]] = []

    def sec(key: str, title: str, items: List[str]) -> None:
        out.append({"key": key, "title": title, "lines": items})

    by_kind = collections.Counter(r["kind"] for r in rows)
    sec("coverage", "Coverage", [
        f"{_n(lines)} lines with text in {_n(tot.get('files', 0))} files; {_n(tot.get('paragraphs', 0))} paragraphs, "
        f"{_n(tot.get('sentences', 0))} sentences.",
        f"Terms: {_n(len(rows))} ({', '.join(f'{v} {k}s' for k, v in sorted(by_kind.items()))}); "
        f"{_n(st['concentration']['terms_hit'])} hit at least once.",
        f"Lines with any hit: {_n(tot.get('lines_with_hit', 0))} ({_pct(tot.get('lines_with_hit', 0), lines)}); "
        f"lines a run would gate (a hit that no cheap rule marks incidental, a marker or a narrative word): "
        f"{_n(tot.get('lines_gated', 0))} ({_pct(tot.get('lines_gated', 0), lines)}).",
        f"Hits: {_n(total_hits)}, of them {_n(tot.get('incidental_hits', 0))} incidental "
        f"({_pct(tot.get('incidental_hits', 0), total_hits)}). Paragraphs with a hit: "
        f"{_n(tot.get('paragraphs_with_hit', 0))}; paragraphs a run labels: {_n(tot.get('paragraphs_candidate', 0))}.",
    ] + ([f"{_n(tot.get('errors', 0))} lines could not be read; {_n(tot.get('no_text', 0))} had no text field."]
         if tot.get("errors") or tot.get("no_text") else []))

    c = st["concentration"]
    dom = [f"The top 10 terms make {_pct(c['top10'], 1)} of all hits; the top 1 % ({c['top1pct_n']} terms) make "
           f"{_pct(c['top1pct'], 1)}."]
    if ranked and ranked[0]["hits"]:
        dom.append("Most frequent: " + _names([r for r in ranked[:10] if r["hits"]], 10, True) + ".")
        big = [r for r in ranked[:20] if total_hits and r["hits"] / total_hits >= 0.2]
        if big:
            dom.append("Each of these alone makes at least 20 % of the hits, so the gate depends on them: "
                       + _names(big, 10) + ". Check that they mean what the policy is about.")
    sec("dominant", "Dominant terms", dom)

    never = [rows[i] for i in st["never_hit"]]
    dead = [f"{_n(len(never))} of {_n(len(rows))} terms never hit ({_pct(len(never), len(rows))})."]
    if never:
        dead.append("Never hit: " + _names(never, 25) + ".")
    once = [r for r in rows if 0 < r["hits"] <= 2]
    if once:
        dead.append(f"{_n(len(once))} terms hit only once or twice: " + _names(once, 15) + ".")
    dims = st.get("dims") or []
    for d in dims:
        us = st["units"].get(d) or {}
        if 1 < len(us) <= 60:
            per = []
            for u in sorted(us):
                k = sum(1 for r in rows if not (r["units"].get(d) or {}).get(u))
                per.append(f"{u} {k}")
            dead.append(f"Never hit per {d}: " + "; ".join(per) + ".")
    sec("dead", "Dead terms", dead)

    inc = [r for r in rows if r["hits"] >= 3 and r["incidental_share"] >= 0.5]
    inc.sort(key=lambda r: (-r["incidental"], r["term"]))
    sec("incidental", "Mostly incidental terms",
        [f"{_n(len(inc))} terms with at least 3 hits are incidental in half or more of their hits (language menus, "
         "locale codes, company names): they rarely open the gate."]
        + ([("These: " + ", ".join(f"{r['term']} ({_pct(r['incidental'], r['hits'], 0)} of {_n(r['hits'])})"
                                   for r in inc[:15]) + ".")] if inc else []))

    spread: List[str] = []
    for d in dims:
        us = st["units"].get(d) or {}
        if len(us) < 2:
            continue
        shares = sorted(((u, (c.get("lines_gated", 0) / c["lines"]) if c.get("lines") else 0.0, c)
                         for u, c in us.items()), key=lambda x: -x[1])
        hi = shares[0]
        lo = shares[-1]
        spread.append(f"By {d}: gated lines range from {_pct(lo[1], 1)} ({lo[0]}) to {_pct(hi[1], 1)} ({hi[0]}).")
        conc_terms = []
        for r in ranked:
            if r["hits"] < 10:
                break
            ud = r["units"].get(d) or {}
            if not ud:
                continue
            u, (h, _l) = max(ud.items(), key=lambda kv: kv[1][0])
            if h / r["hits"] >= 0.9 and len(us) > 2:
                conc_terms.append(f"{r['term']} ({_pct(h, r['hits'], 0)} in {u})")
        if conc_terms:
            spread.append(f"Terms with at least 10 hits that come almost only from one {d}: "
                          + ", ".join(conc_terms[:12]) + (" …" if len(conc_terms) > 12 else "") + ".")
    if not spread:
        spread.append("Only one unit (folder / file / topic): no spread to compare. Use --topic-field or a corpus "
                      "with sub-folders.")
    sec("spread", "Spread over units", spread)

    dup, ov = st["duplicates"], st["overlaps"]
    du = [f"{_n(len(dup))} terms are listed more than once."]
    if dup:
        du.append("Listed twice: " + "; ".join(f"{d['term']} ({', '.join(d['places'][:4])})" for d in dup[:12])
                  + (" …" if len(dup) > 12 else "") + ".")
    du.append(f"{_n(len(ov))} overlaps (one term is a whole-word part of another; where the longer one matches, only "
              "it is counted).")
    if ov:
        du.append("For example: " + "; ".join(f"{o['inner']} in {o['outer']}" for o in ov[:12]) + ".")
    if st.get("warnings"):
        du.append("Matcher warnings: " + "; ".join(st["warnings"][:5]) + ".")
    sec("duplicates", "Duplicates and overlaps", du)

    f = st["forecast"]
    ppp = f["pairs_per_paragraph"]
    fc = [f"Paragraphs a run labels: {_n(f['candidate_paragraphs'])} in {_n(f['scanned_lines'])} lines "
          f"({f['paragraphs_per_million_lines']:,.0f} per million lines)."]
    if f["scale"] != 1.0:
        fc.append(f"Scaled to {_n(f['corpus_lines'])} lines: about {_n(f['paragraphs'])} paragraphs.")
    fc += [f"Model pairs per paragraph: {ppp['high']} when the gate passes (gate {ppp['gate']} + level 1 {ppp['level1']} "
           f"+ level 2 {ppp['level2']}" + (f" + {ppp['exceptions']} exception hypotheses" if ppp['exceptions'] else "")
           + f"), {ppp['low']} when it does not.",
           f"So {_n(f['pairs_low'])} to {_n(f['pairs_high'])} pairs: on {f['gpus']} GPUs at "
           f"{f['pairs_per_second'][0]:,.0f}–{f['pairs_per_second'][1]:,.0f} pairs/s each, about "
           f"{_h(f['hours_high'][0])} – {_h(f['hours_high'][1])} at most (every paragraph past the gate), "
           f"{_h(f['hours_low'][0])} – {_h(f['hours_low'][1])} at least. Reading and the keyword scan come on top "
           "(CPU), and the judge adds pairs for uncertain scores."]
    sec("forecast", "GPU-time forecast", fc)

    sug: List[str] = []
    if never:
        sug.append(f"Drop or check: {_n(len(never))} never-hit terms (spelling, inflected forms, or not in this "
                   "corpus; keep them if a bigger corpus may have them).")
    if inc:
        sug.append("Fix: mostly incidental terms (" + _names(inc, 8) + "): add exclude patterns or company names, "
                   "or drop them.")
    if dup:
        sug.append(f"Fix: remove the {_n(len(dup))} repeated entries.")
    shadow = [o for o in ov if rows[o["inner_id"]]["hits"] == 0 and rows[o["outer_id"]]["hits"] > 0]
    if shadow:
        sug.append("Check: inner terms that never hit on their own while the longer term does ("
                   + "; ".join(f"{o['inner']} / {o['outer']}" for o in shadow[:8]) + ").")
    big = [r for r in ranked[:5] if total_hits and r["hits"] / total_hits >= 0.2]
    if big:
        sug.append("Check the precision of the dominant terms (" + _names(big, 5) + "): they decide most of the GPU "
                   "time.")
    if st.get("suggest_words"):
        sug.append("Add? Capitalised words much more frequent in gated lines than elsewhere and not in the lists: "
                   + ", ".join(f"{w['word']} ({w['gated_lines']})" for w in st["suggest_words"][:15]) + ".")
    if not sug:
        sug.append("No changes suggested by the numbers.")
    sec("suggestions", "Suggestions", sug)
    return out


def report_md(st: Dict[str, Any]) -> str:
    s = st.get("settings") or {}
    head = [f"# Keyword statistics: {', '.join(s.get('inputs') or []) or '?'}", "",
            f"Policy `{st.get('policy')}`, made {st.get('created')}"
            + (f", {s['limit']} lines per file" if s.get("limit") else "") + ".", ""]
    body = []
    for it in st["report"]:
        body += [f"## {it['title']}", ""] + [f"- {x}" for x in it["lines"]] + [""]
    return "\n".join(head + body)


CSV_COLUMNS = ["rank", "term", "kind", "list", "hits", "incidental", "incidental_share", "lines", "line_share",
               "gate_lines", "paragraphs", "sentences", "files", "units_hit", "co_terms"]  # units_hit: --group-by units


def csv_rows(st: Dict[str, Any], rows: Optional[Iterable[Dict[str, Any]]] = None) -> Iterable[List[Any]]:
    terms = st["terms"]
    dim = (st.get("settings") or {}).get("group_by") or "folder"
    yield CSV_COLUMNS
    for r in (rows if rows is not None else sorted(terms, key=lambda r: r["rank"])):
        units_hit = len(r["units"].get(dim) or {})
        co = "; ".join(f"{terms[j]['term']} ({c})" for j, c in r["co"])
        yield [r["rank"], r["term"], r["kind"], r["list"], r["hits"], r["incidental"], r["incidental_share"],
               r["lines"], r["line_share"], r["gate_lines"], r["paragraphs"], r["sentences"], r["files"], units_hit, co]


def write_outputs(st: Dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / "kwstats.json.tmp"
    tmp.write_text(json.dumps(st, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(out_dir / "kwstats.json")
    with open(out_dir / "terms.csv", "w", encoding="utf-8-sig", newline="") as fh:
        csv.writer(fh).writerows(csv_rows(st))
    (out_dir / "report.md").write_text(report_md(st), encoding="utf-8")


# --------------------------------------------------------------------------------------------------
# command
# --------------------------------------------------------------------------------------------------


def _units_for(inputs: Sequence[str], typed: Sequence[Tuple[Any, Optional[str]]], group_by: str) -> Dict[str, str]:
    """file -> unit name: 'file' = the file's name without suffixes; 'folder' = its folder relative to the input
    folder it came from ('.' for files directly in it)."""
    out: Dict[str, str] = {}
    if group_by == "file":
        for f, _ in typed:
            out[str(f)] = nli_formats.stem(Path(str(f)).name)
        return out
    roots: List[str] = []
    for item in inputs:
        s = str(item).replace("\\", "/").rstrip("/")
        if "://" in s or any(ch in s for ch in "*?["):
            s = s.split("*")[0].split("?")[0].split("[")[0]
            s = s.rsplit("/", 1)[0] if not s.endswith("/") else s.rstrip("/")
        elif os.path.isfile(s):
            s = os.path.dirname(s).replace("\\", "/")
        roots.append(s)
    for f, _ in typed:
        fs = str(f).replace("\\", "/")
        parent = fs.rsplit("/", 1)[0] if "/" in fs else ""
        best = max((r for r in roots if parent == r or fs.startswith(r + "/")), key=len, default=None)
        if best is None:
            out[str(f)] = parent.rsplit("/", 1)[-1] or "."
            continue
        idx = parent.find(best)
        rel = parent[idx + len(best):].strip("/") if idx >= 0 else ""
        out[str(f)] = rel or "."
    return out


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("inputs", nargs="*", help="files / folders / globs (.jsonl .jsonl.zst .parquet ...)")
    p.add_argument("--output-dir", required=True)
    p.add_argument("--policy", default="policy/russia_llm_policy_v2.json")
    p.add_argument("--topic-field", default=None, help="a field per line used as the topic unit (dot path; "
                   "the benchmark's case / group). Without it, the units are folders or files only")
    p.add_argument("--group-by", choices=["folder", "file"], default="folder",
                   help="the second unit: the file's folder below the input folder (default) or the file")
    p.add_argument("--shard", metavar="K/N", help="only every N-th file, starting at K (like run); the parts are "
                   "merged into kwstats.json when all N are in the output folder")
    p.add_argument("--merge", action="store_true", help="only merge the shard parts already in --output-dir")
    p.add_argument("--limit", type=int, default=None, help="first N lines per file")
    p.add_argument("--text-field", default="text")
    p.add_argument("--id-field", default="id")
    p.add_argument("--no-rules", action="store_true", help="no language-menu / company-name rules (as run --no-rules)")
    p.add_argument("--no-suggest", action="store_true", help="skip counting capitalised words for 'terms to add'")
    p.add_argument("--gpus", type=int, default=8, help="forecast: GPUs (default 8, one 8 x H200 machine)")
    p.add_argument("--pairs-per-second", default="3000,5000",
                   help="forecast: model pairs/s per GPU, a range 'low,high' (default 3000,5000: H200 estimate)")
    p.add_argument("--corpus-lines", type=int, default=None,
                   help="forecast: scale to this many lines (when the scan used --limit or a sample)")


def _pps(s: str) -> Tuple[float, float]:
    vals = [float(x) for x in str(s).replace(" ", "").split(",") if x]
    if not vals or any(v <= 0 for v in vals):
        raise ValueError("--pairs-per-second: one or two positive numbers, e.g. 3000,5000")
    return (min(vals), max(vals))


def cmd_kwstats(args) -> int:
    t0 = time.perf_counter()
    policy = Policy.load(args.policy)
    terms = Terms(policy, no_rules=args.no_rules)
    pps = _pps(args.pairs_per_second)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    settings = {"inputs": [_mask(x) for x in args.inputs], "text_field": args.text_field,
                "topic_field": args.topic_field, "group_by": args.group_by, "limit": args.limit,
                "shard": args.shard, "no_rules": bool(args.no_rules), "gpus": args.gpus, "pairs_per_second": list(pps),
                "corpus_lines": args.corpus_lines, "command": _mask("nli_label.py kwstats " + " ".join(
                    a for a in sys.argv[1:] if a != "kwstats"))}
    sk = sn = None
    if args.shard:
        try:
            sk, sn = (int(x) for x in str(args.shard).split("/"))
            assert 0 <= sk < sn
        except (ValueError, AssertionError):
            print("error: --shard K/N needs 0 <= K < N (e.g. 0/4)", file=sys.stderr)
            return 2
    if not args.merge:
        if not args.inputs:
            print("error: no input (give a corpus file or folder)", file=sys.stderr)
            return 2
        try:
            typed = expand_typed(args.inputs)
        except FileNotFoundError as exc:
            print(f"error: input not found: {_mask(exc)}", file=sys.stderr)
            return 2
        except Exception as exc:  # noqa: BLE001 - server errors: no password in the message
            print(f"error: cannot read the input: {_mask(exc)}", file=sys.stderr)
            return 2
        units = _units_for(args.inputs, typed, args.group_by)
        if sk is not None:
            typed = typed[sk::sn]
        files = [f for f, _ in typed]
        if not files:
            print("error: no input files" + (f" for shard {args.shard}" if args.shard else ""), file=sys.stderr)
            return 2
        if any(str(f).lower().endswith((".zst", ".zstd")) for f in files) and not zstd_available():
            print("error: .zst input needs the 'zstandard' package", file=sys.stderr)
            return 2
        sc = Scanner(policy, terms, args.text_field, args.topic_field, args.group_by, suggest=not args.no_suggest)
        names: Dict[str, int] = collections.Counter()
        for i, f in enumerate(files, 1):
            base = nli_formats.stem(Path(str(f)).name)
            names[base] += 1
            name = base if names[base] == 1 else f"{base}.{names[base]}"
            tf = time.perf_counter()
            n = sc.file(f, name, units.get(str(f), "."), args.limit, args.id_field)
            print(f"[{i}/{len(files)}] {_mask(f)}: {n:,} lines, {time.perf_counter() - tf:.1f}s", file=sys.stderr,
                  flush=True)
        sc.part["seconds"] = time.perf_counter() - t0
        part = part_to_json(sc.part)
        part["settings"] = settings
        tag = f".shard{sk}of{sn}" if sk is not None else ""
        (out_dir / f"kwstats.part{tag}.json").write_text(json.dumps(part, ensure_ascii=False), encoding="utf-8")
        if sk is None:
            for old in out_dir.glob("kwstats.part.shard*.json"):  # a whole scan replaces earlier shard parts
                old.unlink()
            parts = [part]
        else:
            parts = None
    if args.merge or sk is not None:
        found = sorted(out_dir.glob("kwstats.part.shard*.json"))
        want = {f"kwstats.part.shard{k}of{sn}.json" for k in range(sn)} if sn else None
        if want is not None and not want <= {p.name for p in found}:
            missing = sorted(want - {p.name for p in found})
            print(f"part written; waiting for {len(missing)} more shard part(s) ({', '.join(missing[:4])}"
                  f"{' …' if len(missing) > 4 else ''}): kwstats.json is made when all are there "
                  "(or run with --merge)", file=sys.stderr)
            return 0
        if want is not None:
            found = [p for p in found if p.name in want]
        if not found:
            print(f"error: no kwstats.part.shard*.json in {out_dir}", file=sys.stderr)
            return 2
        parts = [json.loads(p.read_text(encoding="utf-8")) for p in found]
        settings = {**(parts[0].get("settings") or settings), "shard": None,
                    "shards": [p.get("settings", {}).get("shard") for p in parts]}
    merged = merge_parts(parts) if len(parts) > 1 else parts[0]
    st = finish(merged, terms, policy, settings, args.gpus, pps, args.corpus_lines)
    st["seconds_total"] = time.perf_counter() - t0
    write_outputs(st, out_dir)
    tot = st["totals"]
    lt = tot.get("lines_text", 0)
    print(f"kwstats: {lt:,} lines, {tot.get('lines_gated', 0):,} gated ({_pct(tot.get('lines_gated', 0), lt)}), "
          f"{st['concentration']['terms_hit']:,} of {len(st['terms']):,} terms hit, "
          f"{tot.get('paragraphs_candidate', 0):,} paragraphs to label -> {out_dir / 'kwstats.json'} "
          f"({time.perf_counter() - t0:.1f}s)")
    return 0


def add_parser(sub) -> argparse.ArgumentParser:
    """For nli_label.py: sub.add_parser('kwstats', ...) with the same arguments."""
    p = sub.add_parser("kwstats", help="keyword / marker statistics over a corpus, no models "
                       "(cmds/labeling/keyword_stats.md)")
    add_arguments(p)
    return p


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Keyword and marker statistics over a corpus "
                                 "(cmds/labeling/keyword_stats.md).")
    add_arguments(ap)
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        return cmd_kwstats(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

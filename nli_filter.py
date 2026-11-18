#!/usr/bin/env python3
"""
nli_filter.py - drop JSONL lines that are ABOUT a country, keep lines that only mention it in passing.

Uses nli_models.py (same folder). For every line:

  0. keywords   find the country's keywords in the text field (word boundaries for Latin/Cyrillic,
                substring for CJK); lines without a hit are kept
  1. rules      cheap CPU rules mark hits that are only a language name in a menu / after a
                "Language:" label / next to a locale code (ru-RU), or part of a listed company name;
                lines whose hits are all marked are kept
  2. check 1    fast NLI model on text windows around the remaining hits:
                "This text is about Russia, a Russian person, ... or the history of Russia."
                scores inside the uncertain band are re-scored by the judge model
  3. check 2    only for check-1-positive lines, per hit, on the sentence around it:
                "This text mentions Russia or Russian only as part of a company or brand name." ...
                if every remaining hit is incidental the line is kept
  4. decide     filter = check-1 positive AND NOT all hits incidental

Outputs in --output-dir, per input file (folder structure mirrored):
  <name>.decisions.jsonl[.zst]   one JSON per input line: decision, reason, hits, scores
  <name>.summary.json            counts for that file (also marks the file as done -> resumable)
  <name>.kept.jsonl[.zst]        original lines kept       (with --write-split)
  <name>.filtered.jsonl[.zst]    original lines filtered   (with --write-split)
and summary.json for the whole run; the summary is also printed. While a run goes, it rewrites
progress/<run>.json every 60 s (--progress-every; state, files and bytes done, current file, lines/s, time
left): the viewer's "Runs in progress" (--no-progress-file turns it off). If the lines carry an "expect"
field ("filter"/"keep"), precision / recall / F1 and the mistakes are reported too.

Examples
--------
  python nli_filter.py                                   # test_russia.jsonl, CPU or GPU auto
  python nli_filter.py data/a.jsonl --device cpu --mode single --judge-model none
  python nli_filter.py corpus/ --device cuda --mode process --write-split --output-dir out/
  python nli_filter.py "shards/**/*.zst" --country China --keywords-file keywords/china.txt
  python nli_filter.py corpus/ --shard 0/4               # run 4 copies with 0/4 .. 3/4 on 4 machines
  python nli_filter.py "sftp://user:${PW}@host/data/corpus" --output-dir out/   # corpus on a server

Input on a server (ftp:// ftps:// sftp:// s3:// minio://, see nli_storage.py): every file is downloaded to
--download-dir (default <output-dir>/.download) while the previous one is filtered, read from there and
deleted; failed downloads are retried (--retries). Outputs are always written locally.
"""
from __future__ import annotations

import argparse
import bisect
import collections
import contextlib
import json
import logging
import os
import posixpath
import re
import sys
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nli_storage import StorageError, download, mask_uri  # noqa: E402
from nli_models import (MODEL_SPECS, AtomicOutput, JsonlSource, NLIPool, Record, expand_inputs,  # noqa: E402
                        json_dumps, quiet_transformers, zstd_available)
import nli_formats  # noqa: E402  (.rar / .parquet input, output names)

try:
    import ahocorasick  # pyahocorasick
except ImportError:  # pragma: no cover
    ahocorasick = None

HERE = Path(__file__).resolve().parent
log = logging.getLogger("nli_filter")

# --------------------------------------------------------------------------------------------------
# Defaults
# --------------------------------------------------------------------------------------------------

COUNTRIES: Dict[str, Dict[str, Any]] = {
    "russia": {"name": "Russia", "adj": "Russian", "exclude": [],
               "keywords": ["Russia", "Russian", "Russians", "Russian Federation", "Moscow", "Kremlin",
                            "Saint Petersburg", "Россия", "российский", "ロシア"]},
    "china": {"name": "China", "adj": "Chinese", "exclude": ["中国地方"],
              "keywords": ["China", "Chinese", "People's Republic of China", "Beijing", "中国", "中國",
                           "中华人民共和国", "Китай"]},
}

# built-in hypotheses (also hypotheses/default.json); hypothesis files: see nli_hypotheses.py
from nli_hypotheses import DEFAULT_CHECK1, DEFAULT_CHECK2  # noqa: E402
import nli_hypotheses  # noqa: E402

LANGUAGE_NAMES = [
    # English names
    "English", "German", "French", "Spanish", "Italian", "Portuguese", "Brazilian Portuguese", "Dutch", "Russian",
    "Ukrainian", "Polish", "Czech", "Slovak", "Hungarian", "Romanian", "Bulgarian", "Serbian", "Croatian",
    "Slovenian", "Greek", "Turkish", "Arabic", "Hebrew", "Persian", "Farsi", "Hindi", "Bengali", "Urdu", "Tamil",
    "Telugu", "Thai", "Vietnamese", "Indonesian", "Malay", "Filipino", "Tagalog", "Chinese", "Simplified Chinese",
    "Traditional Chinese", "Mandarin", "Cantonese", "Japanese", "Swedish", "Norwegian", "Danish",
    "Finnish", "Icelandic", "Estonian", "Latvian", "Lithuanian", "Georgian", "Armenian", "Kazakh", "Belarusian",
    "Catalan", "Basque", "Galician", "Irish", "Welsh", "Swahili", "Afrikaans",
    # native names
    "Deutsch", "Français", "Español", "Italiano", "Português", "Nederlands", "Русский", "Українська", "Polski",
    "Čeština", "Magyar", "Română", "Български", "Ελληνικά", "Türkçe", "العربية", "עברית", "فارسی", "हिन्दी", "ไทย",
    "Tiếng Việt", "Bahasa Indonesia", "Bahasa Melayu", "Svenska", "Norsk", "Dansk", "Suomi",
    "中文", "简体中文", "繁體中文", "汉语", "漢語", "普通话", "日本語",
    # Chinese / Japanese names of common languages
    "英語", "英语", "英文", "ロシア語", "俄语", "俄語", "中国語", "日语", "日語", "ドイツ語", "德语", "フランス語", "法语",
    "スペイン語", "西班牙语",
]

# --------------------------------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------------------------------


def is_cjk(ch: str) -> bool:
    c = ord(ch)
    return (0x3040 <= c <= 0x30FF or 0x3400 <= c <= 0x4DBF or 0x4E00 <= c <= 0x9FFF or 0xF900 <= c <= 0xFAFF
            or 0xAC00 <= c <= 0xD7AF or 0x1100 <= c <= 0x11FF or 0x3130 <= c <= 0x318F or 0xFF66 <= c <= 0xFF9F)


def _word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _needs_boundary(ch: str) -> bool:
    return ch.isalnum() and not is_cjk(ch)


def _trie_pattern(words: Iterable[str]) -> str:
    """Regex for a set of words shaped as a trie ("Russian|Rwandan" -> "R(?:ussian|wandan)"): the regex engine
    branches on the next character instead of trying every word at every position. Longer words win."""
    trie: Dict[str, Any] = {}
    for w in words:
        node = trie
        for ch in w.lower():
            node = node.setdefault(ch, {})
        node[""] = True

    def build(node: Dict[str, Any]) -> str:
        branches = [re.escape(ch) + build(child) for ch, child in sorted(node.items()) if ch != ""]
        if not branches:
            return ""
        body = branches[0] if len(branches) == 1 else "(?:" + "|".join(branches) + ")"
        if "" in node:  # a word ends here: the rest is optional (tried first, so the longest word wins)
            return "(?:" + body + ")?"
        return body

    return build(trie)


def _phrase_regex(phrases: Iterable[str]) -> Optional["re.Pattern[str]"]:
    """Case-insensitive matcher for phrases, longest match first, word boundaries on Latin/Cyrillic ends only."""
    groups: Dict[Tuple[bool, bool], List[str]] = collections.defaultdict(list)
    for p in {p for p in phrases if p}:
        groups[(_needs_boundary(p[0]), _needs_boundary(p[-1]))].append(p)
    if not groups:
        return None
    parts = []
    for (left, right), words in sorted(groups.items()):
        parts.append((r"(?<!\w)" if left else "") + "(?:" + _trie_pattern(words) + ")" + (r"(?!\w)" if right else ""))
    return re.compile("|".join(parts), re.IGNORECASE)


def _overlaps(a0: int, a1: int, b0: int, b1: int) -> bool:
    return a0 < b1 and b0 < a1


# --------------------------------------------------------------------------------------------------
# Stage 0: keywords
# --------------------------------------------------------------------------------------------------


@dataclass
class Hit:
    start: int
    end: int
    rule: Optional[str] = None             # cheap rule that marked the hit incidental
    check2: Optional[Dict[str, Any]] = None  # best check-2 result for this hit
    kw: Optional[int] = None               # index of the keyword in KeywordMatcher.entries

    @property
    def incidental(self) -> bool:
        return self.rule is not None or bool(self.check2 and self.check2.get("incidental"))


KEYWORD_LEVELS = ("A", "B")
KEYWORD_COLUMNS = ("keyword", "level", "type", "gloss", "other", "exclude")
_TYPE_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


@dataclass
class KeywordEntry:
    """One keyword of a keyword file (lexicon). A plain line is just the keyword (level B, nothing else).
    Tab-separated columns: keyword, level (A strict / B models), type, gloss, other meanings, exclude patterns;
    '-' or empty = not given; several other meanings / exclude patterns are separated by ' | '."""
    keyword: str
    level: str = "B"
    type: Optional[str] = None
    gloss: Optional[str] = None
    other: List[str] = field(default_factory=list)
    exclude: List[str] = field(default_factory=list)
    line: Optional[int] = None              # line number in the keyword file

    @property
    def strict(self) -> bool:
        return self.level == "A"

    def as_dict(self) -> Dict[str, Any]:
        """Only what is set (a plain keyword -> {"keyword": ...})."""
        d: Dict[str, Any] = {"keyword": self.keyword}
        if self.level != "B":
            d["level"] = self.level
        for k in ("type", "gloss"):
            if getattr(self, k):
                d[k] = getattr(self, k)
        for k in ("other", "exclude"):
            if getattr(self, k):
                d[k] = list(getattr(self, k))
        return d


def _cell(v: str) -> Optional[str]:
    v = v.strip()
    return None if v in ("", "-") else v


def _multi(v: str) -> List[str]:
    """'a | b' -> ['a', 'b']: ' | ' WITH spaces, so a regex alternation like (FL|Florida) stays whole."""
    v = _cell(v) or ""
    return [p.strip() for p in re.split(r"\s+\|\s+", v) if p.strip() and p.strip() != "-"]


def parse_keyword_line(line: str, lineno: Optional[int] = None) -> Optional[KeywordEntry]:
    """One line of a keyword file -> KeywordEntry (None for blank lines and # comments). ValueError if invalid."""
    s = line.rstrip("\r\n")
    if not s.strip() or s.lstrip().startswith("#"):
        return None
    where = f"line {lineno}: " if lineno else ""
    cols = s.split("\t")
    if len(cols) > len(KEYWORD_COLUMNS):
        raise ValueError(f"{where}{len(cols)} tab-separated columns, at most {len(KEYWORD_COLUMNS)} "
                         f"({', '.join(KEYWORD_COLUMNS)})")
    cols += [""] * (len(KEYWORD_COLUMNS) - len(cols))
    kw = cols[0].strip()
    if not kw or kw == "-":
        raise ValueError(f"{where}the first column (the keyword) is empty")
    level = (_cell(cols[1]) or "B").upper()
    if level not in KEYWORD_LEVELS:
        raise ValueError(f"{where}level '{cols[1].strip()}' for '{kw}': use A (strict) or B (decided by the models)")
    typ = _cell(cols[2])
    if typ is not None:
        typ = typ.lower()
        if not _TYPE_RE.match(typ):
            raise ValueError(f"{where}type '{cols[2].strip()}' for '{kw}': one word (letters, digits, _ or -)")
    exclude = _multi(cols[5])
    for p in exclude:
        try:
            re.compile(p)
        except re.error as exc:
            raise ValueError(f"{where}bad exclude pattern '{p}' for '{kw}': {exc}") from None
    return KeywordEntry(kw, level, typ, _cell(cols[3]), _multi(cols[4]), exclude, lineno)


def parse_keywords(lines: Iterable[str]) -> List[KeywordEntry]:
    """Keyword file lines -> entries. All problems are collected into one ValueError."""
    out, errors = [], []
    for i, line in enumerate(lines, 1):
        try:
            e = parse_keyword_line(line, i)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if e is not None:
            out.append(e)
    if errors:
        raise ValueError("; ".join(errors[:20]) + (f"; ... {len(errors) - 20} more" if len(errors) > 20 else ""))
    return out


def load_lexicon(path: Optional[str]) -> List[KeywordEntry]:
    if not path:
        return []
    with open(path, encoding="utf-8-sig") as fh:
        try:
            return parse_keywords(fh)
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from None


class KeywordMatcher:
    """Finds keyword hits: case-insensitive, longest match wins, word boundaries except for CJK keywords.
    Keywords are strings or KeywordEntry (lexicon lines); each hit knows its keyword (Hit.kw)."""

    def __init__(self, keywords: Iterable[Any], exclude_patterns: Iterable[str] = (), use_ahocorasick: bool = True):
        seen: Dict[str, KeywordEntry] = {}
        entries: List[KeywordEntry] = []
        self.warnings: List[str] = []
        for k in keywords:
            e = k if isinstance(k, KeywordEntry) else KeywordEntry(str(k))
            e.keyword = e.keyword.strip()
            if not e.keyword or e.keyword.startswith("#"):
                continue
            low = e.keyword.lower()
            if low in seen:
                if e.as_dict() != seen[low].as_dict() and e.as_dict() != {"keyword": e.keyword}:
                    at = f" (line {e.line})" if e.line else ""
                    self.warnings.append(f"keyword '{e.keyword}'{at} is listed twice: the first one is used")
                continue
            seen[low] = e
            entries.append(e)
        if not entries:
            raise ValueError("no keywords")
        self.entries = entries
        self.keywords = [e.keyword for e in entries]
        self.warnings += [f"single-character keyword '{k}' will match inside ordinary words" for k in self.keywords
                          if len(k) == 1 and is_cjk(k)]
        self._lower = [k.lower() for k in self.keywords]
        self._index = {k: i for i, k in enumerate(self._lower)}
        self._left = [_needs_boundary(k[0]) for k in self._lower]
        self._right = [_needs_boundary(k[-1]) for k in self._lower]
        self._regex = _phrase_regex(self.keywords)
        self.excludes = [re.compile(p) for p in exclude_patterns]
        # per keyword: its own exclude patterns (case-insensitive)
        self._kw_excludes = {i: [re.compile(p, re.IGNORECASE) for p in e.exclude]
                             for i, e in enumerate(entries) if e.exclude}
        self._automaton = None
        if use_ahocorasick and ahocorasick is not None:
            a = ahocorasick.Automaton()
            for i, k in enumerate(self._lower):
                a.add_word(k, i)
            a.make_automaton()
            self._automaton = a

    @property
    def engine(self) -> str:
        return "aho-corasick" if self._automaton is not None else "regex"

    def entry(self, hit: "Hit") -> Optional[KeywordEntry]:
        return self.entries[hit.kw] if hit.kw is not None else None

    def counts(self) -> Dict[str, Any]:
        """Lexicon summary: keywords per level and per type."""
        levels = collections.Counter(e.level for e in self.entries)
        types = collections.Counter(e.type or "-" for e in self.entries)
        return {"keywords": len(self.entries), "levels": dict(sorted(levels.items())),
                "types": dict(sorted(types.items())), "with_gloss": sum(1 for e in self.entries if e.gloss),
                "with_other": sum(1 for e in self.entries if e.other),
                "with_exclude": sum(1 for e in self.entries if e.exclude)}

    def find(self, text: str) -> List[Hit]:
        if not text:
            return []
        low = text.lower()
        hits: List[Hit] = []
        if self._automaton is not None and len(low) == len(text):
            cands = []
            n = len(text)
            for end, i in self._automaton.iter(low):
                s, e = end - len(self._lower[i]) + 1, end + 1
                if self._left[i] and s > 0 and _word_char(text[s - 1]):
                    continue
                if self._right[i] and e < n and _word_char(text[e]):
                    continue
                cands.append((s, e, i))
            cands.sort(key=lambda c: (c[0], c[0] - c[1]))
            last = -1
            for s, e, i in cands:
                if s >= last:
                    hits.append(Hit(s, e, kw=i))
                    last = e
        else:  # no pyahocorasick, or lower() changed the length (rare Unicode)
            hits = [Hit(m.start(), m.end(), kw=self._index.get(m.group(0).lower()))
                    for m in self._regex.finditer(text)]
        if hits and self.excludes:
            spans = [m.span() for p in self.excludes for m in p.finditer(text)]
            hits = [h for h in hits if not any(_overlaps(h.start, h.end, s, e) for s, e in spans)]
        if hits and self._kw_excludes:
            cache: Dict[int, List[Tuple[int, int]]] = {}
            kept = []
            for h in hits:
                pats = self._kw_excludes.get(h.kw) if h.kw is not None else None
                if pats:
                    if h.kw not in cache:
                        cache[h.kw] = [m.span() for p in pats for m in p.finditer(text)]
                    if any(_overlaps(h.start, h.end, s, e) for s, e in cache[h.kw]):
                        continue
                kept.append(h)
            hits = kept
        return hits


def load_keywords(path: Optional[str]) -> List[str]:
    """The keywords of a keyword file (first column; load_lexicon gives the other columns too)."""
    return [e.keyword for e in load_lexicon(path)]


# --------------------------------------------------------------------------------------------------
# Stage 1: cheap rules (check 2 without a model)
# --------------------------------------------------------------------------------------------------


class IncidentalRules:
    """
    Marks a hit incidental (hit.rule) when the hit is a language name and
      locale_code     a locale code such as ru-RU / zh-CN is within `locale_distance` characters, or
      language_label  it is in a list directly after "Language:", "言語:", "Язык:", "Subtitles:" ..., or
      language_menu   it is in a run of >= menu_min language names separated by , | / ; "and" ...;
    or when the hit lies inside a listed company name (company_name).
    """

    GAP = re.compile(r"[\s,;|/·•、，&+()\[\]\-–—:]*(?:(?:and|or|und|et|и|y|e)\b[\s,;|/·•、，&+()\[\]\-–—]*)?",
                     re.IGNORECASE)
    LABEL = re.compile(r"(?:\b(?:languages?|lang|display language|interface language|subtitles?|audio|dubbing|"
                       r"captions?|translations?)\b|语言|語言|言語|язык)\s*[:：=]", re.IGNORECASE)
    LOCALE = re.compile(r"(?<![A-Za-z])[a-z]{2,3}[-_](?:[A-Z]{2}|Han[st])(?![A-Za-z])")

    def __init__(self, country_adj: str, menu_min: int = 3, locale_codes: bool = True,
                 language_labels: bool = True, company_names: Iterable[str] = (), locale_distance: int = 80,
                 max_gap: int = 20, margin: int = 300):
        self.menu_min = menu_min
        self.locale_codes = locale_codes
        self.language_labels = language_labels
        self.locale_distance = locale_distance
        self.max_gap = max_gap
        self.margin = margin  # characters around a hit that the rules look at
        self._lang = _phrase_regex(list(LANGUAGE_NAMES) + [country_adj])
        self._company = _phrase_regex(company_names)
        self._company_margin = max((len(c) for c in company_names), default=0)

    @staticmethod
    def _spans(pattern: "re.Pattern[str]", text: str, lo: int, hi: int) -> List[Tuple[int, int]]:
        """Matches inside text[lo:hi], as positions in text. Only a slice is searched: the language-name
        pattern has ~120 alternatives and is far too slow to run over a whole long document."""
        return [(lo + m.start(), lo + m.end()) for m in pattern.finditer(text[lo:hi])]

    def apply(self, text: str, hits: List[Hit]) -> None:
        n = len(text)
        for h in hits:
            if h.rule:
                continue
            if self._company is not None:
                lo, hi = max(0, h.start - self._company_margin), min(n, h.end + self._company_margin)
                if any(s <= h.start and h.end <= e for s, e in self._spans(self._company, text, lo, hi)):
                    h.rule = "company_name"
                    continue
            h.rule = self._language_rule(text, h)

    def _language_rule(self, text: str, h: Hit) -> Optional[str]:
        n = len(text)
        # cheap test first: is the hit itself (part of) a language name? "Russia", "Moscow" ... never are
        near = self._spans(self._lang, text, max(0, h.start - 25), min(n, h.end + 25))
        if not any(_overlaps(h.start, h.end, s, e) for s, e in near):
            return None
        lo, hi = max(0, h.start - self.margin), min(n, h.end + self.margin)
        langs = self._spans(self._lang, text, lo, hi)
        k = next((i for i, (s, e) in enumerate(langs) if _overlaps(h.start, h.end, s, e)), None)
        if k is None:
            return None

        def joined(a: int, b: int) -> bool:  # language names a and b are neighbours in a list
            gap_start, gap_end = langs[a][1], langs[b][0]
            return gap_end - gap_start <= self.max_gap and self.GAP.fullmatch(text, gap_start, gap_end) is not None

        i = k
        while i > 0 and joined(i - 1, i):
            i -= 1
        j = k
        while j + 1 < len(langs) and joined(j, j + 1):
            j += 1
        if self.locale_codes and any(min(abs(h.start - e), abs(s - h.end)) <= self.locale_distance
                                     for s, e in self._spans(self.LOCALE, text, lo, hi)):
            return "locale_code"
        first = langs[i][0]
        if self.language_labels and any(e <= first and first - e <= self.max_gap and self.GAP.fullmatch(text, e, first)
                                        for _, e in self._spans(self.LABEL, text, lo, hi)):
            return "language_label"
        if j - i + 1 >= self.menu_min:
            return "language_menu"
        return None


# --------------------------------------------------------------------------------------------------
# Stage 2: windows
# --------------------------------------------------------------------------------------------------


class WindowBuilder:
    """Character windows: check 1 = ~check1_chars around hits; check 2 = the sentence holding the hit."""

    SENTENCE_END = re.compile(r"[.!?。！？]+[\"'”’)\]]*(?=\s|$)|\n+")

    def __init__(self, check1_chars: int = 1000, check2_chars: int = 300, max_windows: int = 2):
        self.check1_chars = check1_chars
        self.check2_chars = check2_chars
        self.max_windows = max_windows

    @staticmethod
    def _snap(text: str, s: int, e: int, slack: int = 40, lo: int = 0, hi: Optional[int] = None) -> Tuple[int, int]:
        """Move cut points to word boundaries, but never move an edge that already sits on lo / hi
        (text start / end or a sentence boundary)."""
        hi = len(text) if hi is None else hi
        if s > lo:
            j = text.find(" ", s, s + slack)
            s = j + 1 if j >= 0 else s
        if e < hi:
            j = text.rfind(" ", max(s + 1, e - slack), e)
            e = j if j > s else e
        return s, e

    def _around(self, text: str, h: Hit, size: int, lo: int = 0, hi: Optional[int] = None) -> Tuple[int, int]:
        hi = len(text) if hi is None else hi
        center = (h.start + h.end) // 2
        s = max(lo, center - size // 2)
        e = min(hi, s + size)
        s = max(lo, e - size)
        s, e = self._snap(text, s, e, lo=lo, hi=hi)
        return min(s, h.start), max(e, h.end)

    def check1(self, text: str, hits: List[Hit]) -> List[Tuple[int, int]]:
        if len(text) <= self.check1_chars:
            return [(0, len(text))]
        wins: List[Tuple[int, int]] = []
        for h in hits:
            if any(s <= h.start and h.end <= e for s, e in wins):
                continue
            if self.max_windows and len(wins) >= self.max_windows:  # 0 = no limit: a window for every hit
                break
            wins.append(self._around(text, h, self.check1_chars))
        return wins

    def sentence_ends(self, text: str) -> List[int]:
        return [m.end() for m in self.SENTENCE_END.finditer(text)]

    def check2(self, text: str, h: Hit, ends: List[int]) -> Tuple[int, int]:
        i = bisect.bisect_right(ends, h.start)
        s = ends[i - 1] if i else 0
        j = bisect.bisect_left(ends, h.end)
        e = ends[j] if j < len(ends) else len(text)
        if e - s > self.check2_chars:
            s, e = self._around(text, h, self.check2_chars, s, e)
        while s < h.start and text[s].isspace():
            s += 1
        while e > h.end and text[e - 1].isspace():
            e -= 1
        return s, e


# --------------------------------------------------------------------------------------------------
# Stages 3-4: NLI with a fast model and a judge for the uncertain band
# --------------------------------------------------------------------------------------------------


class CascadeScorer:
    """fast model on every pair; the judge re-scores pairs whose fast score lies inside the band."""

    def __init__(self, fast: NLIPool, judge: Optional[NLIPool] = None, band: Tuple[float, float] = (0.6, 0.95)):
        self.fast, self.judge, self.band = fast, judge, band
        self._lock = threading.Lock()
        self.fast_pairs = 0
        self.judge_pairs = 0

    def score(self, premises: List[str], hyps: List[str]) -> List[Tuple[float, Optional[float], float]]:
        """[(fast, judge or None, final)] per pair."""
        if not premises:
            return []
        fast = self.fast.score(premises, hyps)
        judge: List[Optional[float]] = [None] * len(fast)
        idx: List[int] = []
        if self.judge is not None:
            lo, hi = self.band
            idx = [i for i, s in enumerate(fast) if lo <= s <= hi]
            if idx:
                for i, s in zip(idx, self.judge.score([premises[i] for i in idx], [hyps[i] for i in idx])):
                    judge[i] = s
        with self._lock:
            self.fast_pairs += len(fast)
            self.judge_pairs += len(idx)
        return [(f, j, f if j is None else j) for f, j in zip(fast, judge)]


# --------------------------------------------------------------------------------------------------
# One chunk of lines -> decisions
# --------------------------------------------------------------------------------------------------


def _r(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(x, 4)


@dataclass
class FilterSettings:
    country: str
    country_adj: str
    check1: Dict[str, str]          # key -> hypothesis (placeholders filled in)
    check2: Dict[str, str]
    check1_threshold: float = 0.8
    check2_threshold: float = 0.8
    text_field: str = "text"
    id_field: Optional[str] = "id"
    expect_field: Optional[str] = "expect"
    group_field: Optional[str] = "category"
    early_stop: bool = True         # stop scoring a line once its decision is certain (same decisions, fewer pairs)
    # per check (None = as early_stop): check 1 stops at the first window that passes (check 1 is an OR over
    # windows x hypotheses); check 2 stops at the first hit that is not incidental (the line needs ALL hits
    # incidental to be kept). Both are exact shortcuts: turning them off adds scores, never changes a decision.
    check1_early_stop: Optional[bool] = None
    check2_early_stop: Optional[bool] = None
    # level-A (strict) keywords: a line with an A hit is filtered without any model (reason strict_keyword).
    # Absolute by default; strict_rules=True lets the cheap rules (language menu / label / locale / company name)
    # mark an A hit incidental first, and only A hits the rules leave open decide.
    strict_rules: bool = False
    # hypotheses built from the matched keyword (hypothesis file check1_types / check2_types; {country} already
    # filled in, {kw} / {gloss} / {other} filled in per keyword), and how many such hypotheses a window / hit
    # may get at most (cost cap: the global hypotheses always run)
    check1_types: Dict[str, Dict[str, str]] = field(default_factory=dict)
    check2_types: Dict[str, Dict[str, str]] = field(default_factory=dict)
    max_keyword_hyps: int = 4
    # audit of level-A lines: this share (0..1) of the lines an A keyword filters is ALSO run through the rules,
    # check 1 and check 2 as if the A words were B; the result is stored in decision["audit"] and does not
    # change the decision (shows A words that are too broad)
    audit_strict: float = 0.0

    def __post_init__(self) -> None:
        if self.check1_early_stop is None:
            self.check1_early_stop = self.early_stop
        if self.check2_early_stop is None:
            self.check2_early_stop = self.early_stop


@dataclass
class Outcome:
    record: Record
    decision: Dict[str, Any]
    text: Optional[str] = None


class LineFilter:
    """Applies all stages to a list of Records; thread-safe (one call per chunk, many chunks at once)."""

    def __init__(self, settings: FilterSettings, matcher: KeywordMatcher, rules: Optional[IncidentalRules],
                 windows: WindowBuilder, scorer: CascadeScorer):
        self.s, self.matcher, self.rules, self.windows, self.scorer = settings, matcher, rules, windows, scorer
        self._kw_cache: Dict[Tuple[int, int], List[Tuple[str, str]]] = {}

    def keyword_hyps(self, check: int, kw: Optional[int]) -> List[Tuple[str, str]]:
        """(key, hypothesis) built for one keyword from check1_types / check2_types: its type's templates, the
        '*' templates and (check 2) one '@other' hypothesis per other meaning. Key = '<template key>:<keyword>'."""
        types = self.s.check1_types if check == 1 else self.s.check2_types
        if not types or kw is None:
            return []
        ck = (check, kw)
        if ck not in self._kw_cache:
            e = self.matcher.entries[kw]
            out: List[Tuple[str, str]] = []
            for t in ([e.type] if e.type else []) + ["*"]:
                for key, tpl in (types.get(t) or {}).items():
                    if "{gloss}" in tpl and not e.gloss:
                        continue  # a gloss template needs a gloss
                    out.append((f"{key}:{e.keyword}", nli_hypotheses.fill(tpl, e.keyword, e.gloss)))
            for key, tpl in (types.get("@other") or {}).items():
                for i, o in enumerate(e.other, 1):
                    suffix = f"/{i}" if len(e.other) > 1 else ""
                    out.append((f"{key}:{e.keyword}{suffix}", nli_hypotheses.fill(tpl, e.keyword, e.gloss, o)))
            self._kw_cache[ck] = out
        return self._kw_cache[ck]

    def _hyps(self, check: int, kws: Iterable[Optional[int]]) -> List[Tuple[str, str]]:
        """The global hypotheses of a check + those of these keywords (in order, no repeated text, capped)."""
        base = list((self.s.check1 if check == 1 else self.s.check2).items())
        texts = {h for _, h in base}
        extra: List[Tuple[str, str]] = []
        for kw in kws:
            for key, hyp in self.keyword_hyps(check, kw):
                if hyp not in texts and len(extra) < self.s.max_keyword_hyps:
                    texts.add(hyp)
                    extra.append((key, hyp))
        return base + extra

    def process(self, records: Sequence[Record]) -> List[Outcome]:
        s = self.s
        outcomes: List[Outcome] = []
        pending: List[Tuple[Outcome, List[Hit], List[Hit], List[Tuple[int, int]]]] = []
        audited: set = set()  # indexes in pending of level-A lines run only for the audit
        for rec in records:
            d: Dict[str, Any] = {"line": rec.line, "decision": None, "reason": None}  # filled in by _final
            if s.id_field and rec.get(s.id_field) is not None:
                d["id"] = rec.get(s.id_field)
            out = Outcome(rec, d)
            outcomes.append(out)
            if s.expect_field and rec.get(s.expect_field) is not None:
                d["expect"] = rec.get(s.expect_field)
            if rec.error:
                self._final(d, "keep", "blank" if rec.error == "blank" else "bad_json")
                continue
            text = rec.get(s.text_field)
            if not isinstance(text, str) or not text.strip():
                self._final(d, "keep", "no_text")
                continue
            out.text = text
            hits = self.matcher.find(text)
            if not hits:
                self._final(d, "keep", "no_keyword")
                continue
            strict = [h for h in hits if h.kw is not None and self.matcher.entries[h.kw].strict]
            audit = bool(strict) and self._audit_pick(rec)
            if strict and not s.strict_rules and not audit:  # level A: filtered, no rule, no model
                self._final(d, "filter", "strict_keyword", text, hits)
                continue
            if self.rules is not None:
                self.rules.apply(text, hits)
            # the line is a level-A line: always (default) or, with strict_rules, when an A hit is left open
            strict_line = bool(strict) and (not s.strict_rules or any(h.rule is None for h in strict))
            if strict_line and not audit:
                self._final(d, "filter", "strict_keyword", text, hits)
                continue
            open_hits = [h for h in hits if h.rule is None]
            if not open_hits:
                if strict_line:  # audit: the rules alone would have kept it
                    self._audit_final(d, "keep", "rules_incidental", None, text, hits)
                else:
                    self._final(d, "keep", "rules_incidental", text, hits)
                continue
            if strict_line:
                audited.add(len(pending))
            pending.append((out, hits, open_hits, self.windows.check1(text, open_hits)))

        # check 1: window x check-1 hypothesis. Early stop (default): windows are scored in rounds of 1, 2, 4, ...
        # windows per line, and a line leaves as soon as one pair reaches the threshold (the decision is the same
        # as scoring all windows: positive = any pair >= threshold).
        c1_pairs: List[List[Dict[str, Any]]] = [[] for _ in pending]
        c1_done = done = [0] * len(pending)            # windows scored so far per line
        size = 1 if s.check1_early_stop else max((len(p[3]) for p in pending), default=0)
        while True:
            premises, hyps, owners = [], [], []
            for n, (out, _, _, wins) in enumerate(pending):
                if done[n] >= len(wins) or any(p["_final"] >= s.check1_threshold for p in c1_pairs[n]):
                    continue
                for w in range(done[n], min(done[n] + size, len(wins))):
                    a, b = wins[w]
                    kws = list(dict.fromkeys(h.kw for h in pending[n][2] if a <= h.start and h.end <= b)) \
                        if s.check1_types else []
                    for key, hyp in self._hyps(1, kws):
                        premises.append(out.text[a:b])
                        hyps.append(hyp)
                        owners.append((n, w, key, hyp))
                done[n] = min(done[n] + size, len(wins))
            if not premises:
                break
            for (n, w, key, hyp), (f, j, final) in zip(owners, self.scorer.score(premises, hyps)):
                pair = {"window": list(pending[n][3][w]), "hyp": key, "fast": _r(f), "judge": _r(j),
                        "score": _r(final), "_final": final}
                if key not in s.check1:
                    pair["text"] = hyp  # built from a keyword: the hypothesis is not in the run's list
                c1_pairs[n].append(pair)
            size *= 2

        # check 2: per open hit of check-1-positive lines, on the sentence around the hit. Hits in the same
        # sentence share one scoring. Early stop (default): sentences are scored in rounds of 1, 2, 4, ... per
        # line, and a line leaves at its first sentence that is not incidental (the line is filtered then anyway;
        # hits not scored keep check2 = None).
        positive = []
        has_c2 = bool(s.check2 or s.check2_types)
        sentences: List[List[Tuple[Tuple[int, int], List[Hit]]]] = [[] for _ in pending]
        for n, (out, hits, open_hits, _) in enumerate(pending):
            best = max(c1_pairs[n], key=lambda p: p["_final"])
            is_pos = best["_final"] >= s.check1_threshold
            positive.append(is_pos)
            if not is_pos or not has_c2:
                continue
            ends = self.windows.sentence_ends(out.text)
            by_span: Dict[Tuple[Tuple[int, int], Optional[int]], List[Hit]] = {}
            for h in open_hits:
                span = self.windows.check2(out.text, h, ends)
                own = h.kw if self.keyword_hyps(2, h.kw) else None  # own hypotheses: a group of its own
                if (span, own) not in by_span:
                    by_span[(span, own)] = []
                    sentences[n].append((span, by_span[(span, own)]))
                by_span[(span, own)].append(h)
        done = [0] * len(pending)                      # sentences scored so far per line
        stopped = [False] * len(pending)
        size = 1 if s.check2_early_stop else max((len(x) for x in sentences), default=0)
        while True:
            premises, hyps, owners = [], [], []
            for n, sents in enumerate(sentences):
                if stopped[n] or done[n] >= len(sents):
                    continue
                for gi, ((a, b), group) in enumerate(sents[done[n]:done[n] + size], done[n]):
                    for key, hyp in self._hyps(2, [group[0].kw] if s.check2_types else []):
                        premises.append(pending[n][0].text[a:b])
                        hyps.append(hyp)
                        owners.append((n, gi, a, b, group, key, hyp))
                done[n] = min(done[n] + size, len(sents))
            if not premises:
                break
            best2: Dict[Tuple[int, int], Dict[str, Any]] = {}
            all2: Dict[Tuple[int, int], List[Dict[str, Any]]] = {}  # every hypothesis's scores (shown)
            for (n, gi, a, b, group, key, hyp), (f, j, final) in zip(owners, self.scorer.score(premises, hyps)):
                row = {"hyp": key, "fast": _r(f), "judge": _r(j), "score": _r(final)}
                if key not in s.check2:
                    row["text"] = hyp  # built from a keyword
                all2.setdefault((n, gi), []).append(row)
                cur = best2.get((n, gi))
                if cur is None or final > cur["_final"]:
                    best2[(n, gi)] = {"window": [a, b], "hyp": key, "fast": _r(f), "judge": _r(j),
                                      "score": _r(final), "_final": final, "incidental": final >= s.check2_threshold,
                                      "_group": group, **({"text": hyp} if key not in s.check2 else {})}
            for (n, gi), res in best2.items():
                group = res.pop("_group")
                res["pairs"] = all2[(n, gi)]
                for h in group:
                    h.check2 = dict(res)
                if not res["incidental"] and s.check2_early_stop:
                    stopped[n] = True
            size *= 2

        for n, (out, hits, open_hits, _) in enumerate(pending):
            pairs = c1_pairs[n]
            best = max(pairs, key=lambda p: p["_final"])
            out.decision["check1"] = {"score": best["score"], "positive": positive[n], "hyp": best["hyp"],
                                      "window": best["window"],
                                      "pairs": [{k: v for k, v in p.items() if k != "_final"} for p in pairs]}
            if c1_done[n] < len(pending[n][3]):
                out.decision["check1"]["skipped"] = len(pending[n][3]) - c1_done[n]  # windows not scored (early stop)
            if stopped[n] and done[n] < len(sentences[n]):
                out.decision["check2_skipped"] = sum(len(g) for _, g in sentences[n][done[n]:])  # hits not scored
            if not positive[n]:
                verdict = ("keep", "check1_negative")
            elif has_c2 and all(h.incidental for h in open_hits):
                verdict = ("keep", "check2_incidental")
            else:
                verdict = ("filter", "about_country")
            if n in audited:
                self._audit_final(out.decision, verdict[0], verdict[1], out.decision.pop("check1"), out.text, hits)
            else:
                self._final(out.decision, verdict[0], verdict[1], out.text, hits)
        return outcomes

    def _audit_pick(self, rec: Record) -> bool:
        """Is this level-A line in the audit sample? (deterministic: same lines on every run)"""
        rate = self.s.audit_strict
        if rate <= 0:
            return False
        if rate >= 1:
            return True
        return zlib.crc32(f"{rec.source}:{rec.line}".encode("utf-8", "replace")) % 1_000_000 < rate * 1_000_000

    def _audit_final(self, d: Dict[str, Any], decision: str, reason: str, check1: Optional[Dict[str, Any]],
                     text: str, hits: List[Hit]) -> None:
        """A level-A line run for the audit: store what the rules / models would decide, filter it anyway."""
        a: Dict[str, Any] = {"decision": decision, "reason": reason}
        if check1 is not None:
            a["check1"] = check1
        for k in ("check2_skipped",):
            if k in d:
                a[k] = d.pop(k)
        a["hits"] = [{"kw": text[h.start:h.end], "span": [h.start, h.end],
                      **({"rule": h.rule} if h.rule else {}),
                      **({"check2": {k: v for k, v in h.check2.items() if k != "_final"}} if h.check2 else {})}
                     for h in hits]
        for h in hits:  # the real decision: a level-A filter, as without the audit
            h.rule, h.check2 = None, None
        d["audit"] = a
        self._final(d, "filter", "strict_keyword", text, hits)

    def _final(self, d: Dict[str, Any], decision: str, reason: str, text: Optional[str] = None,
               hits: Optional[List[Hit]] = None) -> None:
        d["decision"] = decision
        d["reason"] = reason
        if hits:
            rows = []
            for h in hits:
                row: Dict[str, Any] = {"kw": text[h.start:h.end], "span": [h.start, h.end]}
                e = self.matcher.entries[h.kw] if h.kw is not None else None
                if e is not None:
                    if e.keyword != row["kw"]:
                        row["keyword"] = e.keyword  # as in the keyword file (the text may differ in case)
                    if e.strict:
                        row["level"] = "A"
                if h.rule:
                    row["rule"] = h.rule
                if h.check2:
                    row["check2"] = {k: v for k, v in h.check2.items() if k != "_final"}
                rows.append(row)
            d["hits"] = rows
            if reason == "strict_keyword":
                d["strict"] = sorted({r.get("keyword", r["kw"]) for r in rows if r.get("level") == "A" and "rule" not in r})


# --------------------------------------------------------------------------------------------------
# Statistics and evaluation
# --------------------------------------------------------------------------------------------------

REASONS = ["blank", "bad_json", "no_text", "no_keyword", "rules_incidental", "check1_negative",
           "check2_incidental", "about_country", "strict_keyword"]


class RunStats:
    """Counts per reason / decision, rule counts, and (when lines carry expect labels) a confusion matrix."""

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        d = data or {}
        self.lines = d.get("lines", 0)
        self.reasons = collections.Counter(d.get("reasons", {}))
        self.decisions = collections.Counter(d.get("decisions", {}))
        self.rules = collections.Counter(d.get("rules", {}))
        self.hits = d.get("hits", 0)
        self.check1_windows = d.get("check1_windows", 0)
        self.check2_hits = d.get("check2_hits", 0)
        ev = d.get("eval", {})
        self.confusion = collections.Counter(ev.get("confusion", {}))
        self.by_group: Dict[str, collections.Counter] = {g: collections.Counter(c)
                                                         for g, c in ev.get("by_group", {}).items()}
        self.mistakes: List[Dict[str, Any]] = list(ev.get("mistakes", []))
        self.audit = collections.Counter(d.get("audit", {}))  # level-A audit: lines, would_keep, would_filter

    def add(self, out: Outcome, group_field: Optional[str], max_mistakes: int = 200) -> None:
        d = out.decision
        self.lines += 1
        self.reasons[d["reason"]] += 1
        self.decisions[d["decision"]] += 1
        for h in d.get("hits", []):
            self.hits += 1
            if "rule" in h:
                self.rules[h["rule"]] += 1
            if "check2" in h:
                self.check2_hits += 1
        if "check1" in d:
            self.check1_windows += len({tuple(p["window"]) for p in d["check1"]["pairs"]})
        if "audit" in d:
            self.audit["lines"] += 1
            self.audit["would_" + d["audit"]["decision"]] += 1
        expect = str(d.get("expect", "")).strip().lower()
        if expect not in ("filter", "keep"):
            return
        got = d["decision"]
        cell = {("filter", "filter"): "tp", ("keep", "filter"): "fp",
                ("keep", "keep"): "tn", ("filter", "keep"): "fn"}[(expect, got)]
        self.confusion[cell] += 1
        group = out.record.get(group_field) if group_field else None
        if group is not None:
            self.by_group.setdefault(str(group), collections.Counter())[cell] += 1
        if cell in ("fp", "fn") and len(self.mistakes) < max_mistakes:
            self.mistakes.append({"source": out.record.source, "line": d["line"], "id": d.get("id"),
                                  "group": group, "expect": expect, "got": got, "reason": d["reason"],
                                  "check1": d.get("check1", {}).get("score"),
                                  "text": (out.text or "")[:160]})

    def merge(self, other: "RunStats") -> None:
        self.lines += other.lines
        self.reasons.update(other.reasons)
        self.decisions.update(other.decisions)
        self.rules.update(other.rules)
        self.hits += other.hits
        self.check1_windows += other.check1_windows
        self.check2_hits += other.check2_hits
        self.confusion.update(other.confusion)
        for g, c in other.by_group.items():
            self.by_group.setdefault(g, collections.Counter()).update(c)
        self.mistakes.extend(other.mistakes)
        self.audit.update(other.audit)

    @staticmethod
    def metrics(c: collections.Counter) -> Dict[str, Any]:
        tp, fp, tn, fn = (c.get(k, 0) for k in ("tp", "fp", "tn", "fn"))
        n = tp + fp + tn + fn
        p = tp / (tp + fp) if tp + fp else None
        r = tp / (tp + fn) if tp + fn else None
        f1 = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
        return {"n": n, "tp": tp, "fp": fp, "tn": tn, "fn": fn, "accuracy": (tp + tn) / n if n else None,
                "precision": p, "recall": r, "f1": f1}

    def to_dict(self) -> Dict[str, Any]:
        out = {"lines": self.lines, "decisions": dict(self.decisions),
               "reasons": {k: self.reasons.get(k, 0) for k in REASONS if self.reasons.get(k)},
               "rules": dict(self.rules), "hits": self.hits, "check1_windows": self.check1_windows,
               "check2_hits": self.check2_hits}
        if self.audit:
            out["audit"] = dict(self.audit)
        if self.confusion:
            out["eval"] = {"confusion": dict(self.confusion), "metrics": self.metrics(self.confusion),
                           "by_group": {g: dict(c) for g, c in sorted(self.by_group.items())},
                           "mistakes": self.mistakes}
        return out


# --------------------------------------------------------------------------------------------------
# Runner: files -> chunks -> decisions -> outputs + summary
# --------------------------------------------------------------------------------------------------

_INPUT_SUFFIXES = nli_formats.INPUT_SUFFIXES  # .jsonl .json .ndjson .gz .zst .zstd .zip .rar .parquet .arrow
_stem = nli_formats.stem  # 'shard-00000.jsonl.zst' / 'x.parquet' -> output base name


def _chunks(it: Iterator[Record], size: int) -> Iterator[List[Record]]:
    buf: List[Record] = []
    for x in it:
        buf.append(x)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


def _layout(files: Sequence[str]) -> List[str]:
    """Output path (relative, '/'-separated) of every input file: its path below the common input folder.
    Files of one server input keep their path below the URL that was given (the corpus root for the viewer)."""
    if not files:
        return []
    if all(hasattr(f, "storage") for f in files) and len({id(f.storage) for f in files}) == 1:
        return [f.path for f in files]
    keys = [f.layout_key if hasattr(f, "storage") else os.path.abspath(f).replace("\\", "/") for f in files]
    try:
        root = posixpath.commonpath([posixpath.dirname(k) for k in keys])
    except ValueError:  # e.g. local and server files mixed
        root = ""
    return [posixpath.relpath(k, root) if root else k.replace(":", "").lstrip("/") for k in keys]


class Prefetcher:
    """
    Downloads the server input files (RemoteFile) into a local folder, one file ahead: while file i is
    filtered, file i + 1 is downloaded. get(i) waits for file i and returns its local path; release() deletes
    it. Only files with needed[i] are downloaded (finished files of an earlier run are skipped).
    """

    def __init__(self, files: Sequence[str], needed: Sequence[bool], folder: Path, retries: int = 3, ahead: int = 1):
        self.files, self.needed, self.folder, self.retries, self.ahead = files, needed, Path(folder), retries, ahead
        self.folder.mkdir(parents=True, exist_ok=True)
        self.pool = ThreadPoolExecutor(1, thread_name_prefix="download")
        self.futures: Dict[int, Any] = {}

    def _start(self, i: int) -> None:
        if i < len(self.files) and self.needed[i] and hasattr(self.files[i], "storage") and i not in self.futures:
            self.futures[i] = self.pool.submit(self._fetch, i)

    def _fetch(self, i: int) -> str:
        rf = self.files[i]
        dest = str(self.folder / f"{i:06d}-{posixpath.basename(rf.path)}")
        t0 = time.perf_counter()
        size = download(rf, dest, retries=self.retries)
        log.info("downloaded %s (%.1f MB, %.1fs)", rf, size / 1e6, time.perf_counter() - t0)
        return dest

    def get(self, i: int) -> Optional[str]:
        self._start(i)
        for j in range(i + 1, i + 1 + self.ahead):
            self._start(j)
        fut = self.futures.pop(i, None)
        return fut.result() if fut is not None else None

    def release(self, local: str) -> None:
        with contextlib.suppress(OSError):
            os.remove(local)

    def close(self) -> None:
        for fut in self.futures.values():
            fut.cancel()
        self.pool.shutdown(wait=True)
        for fut in self.futures.values():
            if fut.done() and not fut.cancelled() and fut.exception() is None:
                self.release(fut.result())
        self.futures.clear()
        for p in self.folder.glob("*.part"):
            with contextlib.suppress(OSError):
                p.unlink()
        with contextlib.suppress(OSError):
            self.folder.rmdir()  # only when empty


class ProgressFile:
    """
    <output>/progress/<run id>.json, rewritten every `every` seconds (--progress-every, default 60; only the first
    and the last write are immediate) while a run goes: what it does, how far it is,
    whether it is still alive. The viewer shows these files ("Runs in progress"); every copy of a sharded run writes
    its own. state: running | done | failed | stopped. A run that is killed cannot write "stopped": its file just
    stops being updated (the viewer marks it as stale).
    """

    def __init__(self, output_dir: Path, info: Dict[str, Any], every: float = 60.0):
        import socket
        host = socket.gethostname()
        shard = (info.get("shard") or "").replace("/", "of")
        import uuid
        self.run_id = (f"{time.strftime('%Y%m%d-%H%M%S')}-{host}-{os.getpid()}-{uuid.uuid4().hex[:4]}"
                       + (f"-shard{shard}" if shard else ""))
        self.path = Path(output_dir) / "progress" / f"{self.run_id}.json"
        self.every = every
        self._last = 0.0
        self._t0 = time.time()
        self.data: Dict[str, Any] = {"version": 1, "run_id": self.run_id, "state": "running", "host": host,
                                     "pid": os.getpid(), "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                                     "started_ts": self._t0, "every_seconds": every, **info}
        with contextlib.suppress(OSError):
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def update(self, force: bool = False, **fields: Any) -> None:
        self.data.update(fields)
        now = time.time()
        if not force and now - self._last < self.every:
            return
        self._last = now
        d = self.data
        d["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        d["updated_ts"] = now
        d["seconds"] = round(now - self._t0, 1)
        done, total = d.get("bytes_done", 0), d.get("bytes_total") or 0
        rate = done / d["seconds"] if d["seconds"] > 0 else 0
        d["percent"] = round(100 * done / total, 1) if total else None
        d["eta_seconds"] = round((total - done) / rate) if rate > 0 and total and d["state"] == "running" else None
        d["lines_per_second"] = round(d.get("lines", 0) / d["seconds"], 1) if d["seconds"] > 0 else None
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as exc:  # progress is a nicety: never stop a run for it
            log.debug("cannot write %s: %s", self.path, exc)

    def finish(self, state: str, error: Optional[str] = None) -> None:
        self.update(force=True, state=state, ended=time.strftime("%Y-%m-%d %H:%M:%S"), current=None,
                    **({"error": error} if error else {}))


def _size(f: Any) -> int:
    """Size of an input file in bytes (0 when unknown)."""
    if hasattr(f, "storage"):
        return int(getattr(f, "size", 0) or 0)
    try:
        return os.path.getsize(f)
    except OSError:
        return 0


class FilterRunner:
    def __init__(self, line_filter: LineFilter, output_dir: Path, compress: str = "none", write_split: bool = False,
                 decisions: str = "all", chunk_lines: int = 512, inflight: int = 2, limit: Optional[int] = None,
                 overwrite: bool = False, progress_seconds: float = 10.0, retries: int = 3,
                 download_dir: Optional[Path] = None, progress_file: Optional[ProgressFile] = None):
        self.f = line_filter
        self.output_dir = output_dir
        self.compress = compress
        self.write_split = write_split
        self.decisions = decisions
        self.chunk_lines = chunk_lines
        self.inflight = max(1, inflight)
        self.limit = limit
        self.overwrite = overwrite
        self.progress_seconds = progress_seconds
        self.total = RunStats()
        self.files: List[Dict[str, Any]] = []
        self.failed = 0
        self.retries = retries
        self.download_dir = download_dir or output_dir / ".download"
        self._seen = 0
        self._t0 = time.perf_counter()
        self._last_progress = self._t0
        self.pf = progress_file
        self._bytes_finished = 0  # bytes of the files finished in this run
        self._source: Optional[JsonlSource] = None  # the file being read (its bytes_read = progress inside it)

    def _ext(self, path: str) -> str:
        if self.compress == "auto":
            compressed = path.lower().endswith((".zst", ".zstd", ".gz") + nli_formats.ARCHIVE_SUFFIXES
                                               + nli_formats.TABLE_SUFFIXES)
            return ".zst" if compressed and zstd_available() else ""
        return {"zst": ".zst", "gz": ".gz", "none": ""}[self.compress]

    def run(self, files: List[str]) -> None:
        bases = [self.output_dir / os.path.dirname(rel) / _stem(os.path.basename(rel)) for rel in _layout(files)]
        needed = [self.overwrite or not self._done(b) for b in bases]
        sizes = [_size(f) for f in files]
        if self.pf:
            self.pf.update(force=True, files_total=len(files), files_needed=sum(needed),
                           files_skipped=len(files) - sum(needed), files_done=0, files_failed=0,
                           bytes_total=sum(s for s, n in zip(sizes, needed) if n), bytes_done=0, lines=0)
        fetch = Prefetcher(files, needed, self.download_dir, self.retries) if any(
            hasattr(f, "storage") for f in files) else None
        executor = ThreadPoolExecutor(self.inflight, thread_name_prefix="chunk") if self.inflight > 1 else None
        try:
            for i, (path, base) in enumerate(zip(files, bases)):
                if self.limit is not None and self._seen >= self.limit:
                    break
                local = None
                if fetch is not None and needed[i]:
                    try:
                        local = fetch.get(i)
                    except Exception as exc:  # download failed after the retries: go on with the other files
                        self.failed += 1
                        if self.pf:
                            self._bytes_finished += sizes[i]
                            self.pf.update(files_failed=self.failed, bytes_done=self._bytes_finished)
                        self.files.append({"input": path, "status": f"failed: {exc}", "lines": 0, "filtered": 0,
                                           "seconds": None})
                        log.error("skip %s: %s", path, exc)
                        continue
                if self.pf and needed[i]:
                    self.pf.update(current={"input": mask_uri(str(path)), "size": sizes[i]})
                try:
                    self._run_file(path, base, executor, local)
                finally:
                    if local:
                        fetch.release(local)
                if self.pf and needed[i]:
                    self._bytes_finished += sizes[i]
                    self._source = None
                    self.pf.update(files_done=self.pf.data.get("files_done", 0) + 1,
                                   bytes_done=self._bytes_finished, lines=self._seen)
        finally:
            if executor:
                executor.shutdown(wait=True)
            if fetch:
                fetch.close()

    def _done(self, base: Path) -> bool:
        p = Path(f"{base}.summary.json")
        if not p.exists():
            return False
        try:
            with open(p, encoding="utf-8") as fh:
                return bool(json.load(fh).get("complete", True))
        except (OSError, ValueError):
            return False

    def _run_file(self, path: str, base: Path, executor: Optional[ThreadPoolExecutor],
                  local: Optional[str] = None) -> None:
        summary_path = Path(f"{base}.summary.json")
        if summary_path.exists() and not self.overwrite:
            with open(summary_path, encoding="utf-8") as fh:
                done = json.load(fh)
            if done.get("complete", True):
                self.total.merge(RunStats(done["stats"]))
                self.files.append({"input": path, "status": "skipped (already done)", **_file_row(done)})
                log.warning("skip %s (done: %s; --overwrite to redo)", path, summary_path)
                return
            log.warning("redo %s: the last run stopped inside it (--limit)", path)
        ext = self._ext(path)
        stats = RunStats()
        t0 = time.perf_counter()
        remaining = None if self.limit is None else self.limit - self._seen
        truncated = False

        def limited_records() -> Iterator[Record]:
            """All lines of the file, or the first `remaining`; notes whether the limit cut the file short."""
            nonlocal truncated
            self._source = JsonlSource(path, local=local)
            for i, rec in enumerate(self._source.records()):
                if remaining is not None and i >= remaining:
                    truncated = True
                    return
                yield rec
        with contextlib.ExitStack() as stack:
            dec = stack.enter_context(AtomicOutput(f"{base}.decisions.jsonl{ext}")) if self.decisions != "none" else None
            kept = filt = None
            if self.write_split:
                kept = stack.enter_context(AtomicOutput(f"{base}.kept.jsonl{ext}", binary=True))
                filt = stack.enter_context(AtomicOutput(f"{base}.filtered.jsonl{ext}", binary=True))
            pending: collections.deque = collections.deque()

            def write(outcomes: List[Outcome]) -> None:
                for out in outcomes:
                    stats.add(out, self.f.s.group_field)
                    d = out.decision
                    if out.record.source != path:
                        d = {"source": out.record.source.split("!", 1)[-1], **d}
                    if dec is not None and (self.decisions == "all" or "hits" in d):
                        dec.write(json_dumps(d) + "\n")
                    if self.write_split and out.record.error != "blank":
                        (filt if d["decision"] == "filter" else kept).write(out.record.raw + b"\n")
                self._seen += len(outcomes)
                self._progress(stats)

            for chunk in _chunks(limited_records(), self.chunk_lines):
                if executor is None:
                    write(self.f.process(chunk))
                    continue
                pending.append(executor.submit(self.f.process, chunk))
                while len(pending) >= self.inflight:
                    write(pending.popleft().result())
            while pending:
                write(pending.popleft().result())
        seconds = time.perf_counter() - t0
        # complete = False: --limit stopped inside this file; a later run processes it again
        data = {"input": path, "complete": not truncated, "seconds": round(seconds, 2), "stats": stats.to_dict(),
                "outputs": {"decisions": f"{base}.decisions.jsonl{ext}" if dec is not None else None,
                            "kept": f"{base}.kept.jsonl{ext}" if self.write_split else None,
                            "filtered": f"{base}.filtered.jsonl{ext}" if self.write_split else None}}
        tmp = summary_path.with_name(summary_path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, summary_path)
        self.total.merge(stats)
        self.files.append({"input": path, "status": "partial (--limit)" if truncated else "done", **_file_row(data)})
        log.info("%s: %d lines, %d filtered, %.1fs", path, stats.lines, stats.decisions.get("filter", 0), seconds)

    def _progress(self, stats: RunStats) -> None:
        now = time.perf_counter()
        if now - self._last_progress >= self.progress_seconds:
            self._last_progress = now
            dt = now - self._t0
            log.warning("progress: %d lines (%.0f lines/s), NLI pairs fast %d judge %d",
                        self._seen, self._seen / dt if dt else 0, self.f.scorer.fast_pairs, self.f.scorer.judge_pairs)
        if self.pf:
            src = self._source
            inside = min(src.bytes_read, (self.pf.data.get("current") or {}).get("size") or src.bytes_read) if src else 0
            self.pf.update(bytes_done=self._bytes_finished + inside, lines=self._seen,
                           pairs={"fast": self.f.scorer.fast_pairs, "judge": self.f.scorer.judge_pairs})


def _file_row(data: Dict[str, Any]) -> Dict[str, Any]:
    st = data.get("stats", {})
    return {"lines": st.get("lines", 0), "filtered": st.get("decisions", {}).get("filter", 0),
            "seconds": data.get("seconds")}


# --------------------------------------------------------------------------------------------------
# Summary text
# --------------------------------------------------------------------------------------------------


def _pct(a: float, b: float) -> str:
    return f"{100 * a / b:5.1f}%" if b else "    -"


def _fmt(x: Optional[float]) -> str:
    return "-" if x is None else f"{x:.3f}"


def format_summary(summary: Dict[str, Any], show: int = 20) -> str:
    st = summary["stats"]
    lines = st["lines"]
    t = summary["timing"]
    L = ["", "=" * 78, f" NLI country filter - {summary['country']['name']} "
         f"({summary['country']['adj']}), {len(summary['files'])} file(s)", "=" * 78]
    m = summary["models"]
    L.append(f" models   fast {m['fast']['model']} ({m['fast']['mode']}, {','.join(m['fast']['devices'])}, "
             f"{m['fast']['dtype']})" + (f" | judge {m['judge']['model']} band {summary['settings']['uncertain_band']}"
                                         if m.get("judge") else " | judge none"))
    L.append(f" lines    {lines:,}   filtered {st['decisions'].get('filter', 0):,} "
             f"({_pct(st['decisions'].get('filter', 0), lines).strip()})   kept {st['decisions'].get('keep', 0):,}")
    L.append("")
    L.append(" reason                 lines     share   meaning")
    meaning = {"blank": "empty line", "bad_json": "line is not valid JSON (kept)", "no_text": "text field missing/empty",
               "no_keyword": "no country keyword", "rules_incidental": "all hits resolved by CPU rules",
               "check1_negative": "NLI: not about the country", "check2_incidental": "NLI: all hits incidental",
               "about_country": "FILTERED: about the country",
               "strict_keyword": "FILTERED: a level-A keyword (no model)"}
    for k in REASONS:
        v = st["reasons"].get(k, 0)
        if v:
            L.append(f" {k:<20} {v:>8,}   {_pct(v, lines)}   {meaning[k]}")
    if st.get("rules"):
        L.append(" rule hits: " + ", ".join(f"{k} {v}" for k, v in sorted(st["rules"].items())))
    L.append("")
    L.append(f" NLI pairs  fast {t['fast_pairs']:,}   judge {t['judge_pairs']:,} "
             f"({_pct(t['judge_pairs'], t['fast_pairs']).strip()} of fast)   check-1 windows {st['check1_windows']:,}   "
             f"check-2 hits {st['check2_hits']:,}")
    L.append(f" time       models loaded {t['load_seconds']:.1f}s   filtering {t['run_seconds']:.1f}s   "
             f"{t['lines_per_second']:.1f} lines/s   {t['pairs_per_second']:.1f} pairs/s")
    ev = st.get("eval")
    if ev:
        mt = ev["metrics"]
        L += ["", f" evaluation against '{summary['settings']['expect_field']}' ({mt['n']} labelled lines, "
                  f"positive class = filter)",
              f"   accuracy {_fmt(mt['accuracy'])}   precision {_fmt(mt['precision'])}   recall {_fmt(mt['recall'])}"
              f"   F1 {_fmt(mt['f1'])}",
              f"   TP {mt['tp']}  FP {mt['fp']}  TN {mt['tn']}  FN {mt['fn']}"]
        if ev.get("by_group"):
            L.append(f"   {'group':<22} {'n':>4} {'correct':>8}   TP  FP  TN  FN")
            for g, c in ev["by_group"].items():
                n = sum(c.values())
                ok = c.get("tp", 0) + c.get("tn", 0)
                L.append(f"   {g:<22} {n:>4} {ok:>4} ({_pct(ok, n).strip():>6}) {c.get('tp', 0):>3} {c.get('fp', 0):>3}"
                         f" {c.get('tn', 0):>3} {c.get('fn', 0):>3}")
        if ev["mistakes"] and show:
            L.append(f"   mistakes (first {min(show, len(ev['mistakes']))} of {len(ev['mistakes'])}):")
            for x in ev["mistakes"][:show]:
                text = x["text"].replace("\n", " ")
                L.append(f"   - line {x['line']} {x.get('id') or ''} expect {x['expect']} got {x['got']} "
                         f"({x['reason']}, check1 {_fmt(x['check1'])})")
                L.append(f"       {text[:110]}")
    L.append("")
    L.append(f" outputs  {summary['output_dir']}  (summary.json, *.decisions.jsonl"
             f"{', *.kept/filtered.jsonl' if summary['settings']['write_split'] else ''})")
    L.append("=" * 78)
    return "\n".join(L)


# --------------------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------------------


def _kv(items: Sequence[str], what: str) -> Dict[str, str]:
    out = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not key.strip() or not value.strip():
            raise SystemExit(f"error: {what} must look like KEY=TEXT, got {item!r}")
        out[key.strip()] = value.strip()
    return out


def _render(templates: Dict[str, str], country: str, adj: str, what: str) -> Dict[str, str]:
    out = {}
    for key, tpl in templates.items():
        if "{country}" not in tpl and "{country_adj}" not in tpl:
            log.warning("%s hypothesis '%s' names no {country}/{country_adj}: it is not tied to the country", what, key)
        try:
            out[key] = tpl.format(country=country, country_adj=adj)
        except (KeyError, IndexError, ValueError) as exc:
            raise SystemExit(f"error: {what} hypothesis '{key}': only {{country}} and {{country_adj}} are allowed ({exc})")
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nli_filter.py", description=__doc__.split("\n\n")[0].split(" - ", 1)[1],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__.split("Examples\n--------\n", 1)[1])
    p.add_argument("inputs", nargs="*", help="JSONL files, folders or globs (.jsonl .json .gz .zst .zip .rar .parquet .arrow); "
                                             "default test_russia.jsonl next to this script")
    g = p.add_argument_group("data")
    g.add_argument("--text-field", default="text")
    g.add_argument("--id-field", default="id", help="copied to the decisions (default id; '' = none)")
    g.add_argument("--expect-field", default="expect", help="gold label filter/keep for evaluation, if present")
    g.add_argument("--group-field", default="category", help="field to break the evaluation down by, if present")
    g.add_argument("--limit", type=int, help="stop after this many lines in total")
    g.add_argument("--shard", help="K/N: process only every N-th file starting at K (e.g. 0/4)")
    g = p.add_argument_group("country and keywords")
    g.add_argument("--country", default="Russia", help="country name (default Russia; built-in lists: "
                                                       + ", ".join(c["name"] for c in COUNTRIES.values()) + ")")
    g.add_argument("--country-adj", help="adjective, e.g. Russian (known for built-in countries)")
    g.add_argument("--keywords-file", help="one keyword per line (default: keywords/<country>.txt if it exists, "
                                           "else the built-in list)")
    g.add_argument("--keyword", action="append", default=[], help="extra keyword (repeatable)")
    g.add_argument("--exclude-pattern", action="append", default=[], help="regex; hits inside a match are ignored")
    g = p.add_argument_group("hypotheses and thresholds")
    g.add_argument("--hypotheses-file", help="JSON file with check1 / check2 hypotheses (default: hypotheses/<country>.json "
                                             "if it exists, else the built-in ones = hypotheses/default.json)")
    g.add_argument("--check1-hyp", action="append", default=[], metavar="KEY=TEMPLATE",
                   help="check-1 hypothesis with {country}/{country_adj}; replaces the default (repeatable)")
    g.add_argument("--check2-hyp", action="append", default=[], metavar="KEY=TEMPLATE",
                   help="check-2 hypothesis; replaces the defaults (repeatable)")
    g.add_argument("--no-check2", action="store_true", help="skip check 2 (no NLI rescue of incidental mentions)")
    g.add_argument("--check1-threshold", type=float, default=0.8)
    g.add_argument("--check2-threshold", type=float, default=0.8)
    g.add_argument("--uncertain-band", type=float, nargs=2, default=[0.6, 0.95], metavar=("LOW", "HIGH"),
                   help="fast scores in [LOW, HIGH] go to the judge (default 0.6 0.95)")
    g = p.add_argument_group("rules and windows")
    g.add_argument("--no-rules", action="store_true", help="disable the cheap CPU rules")
    g.add_argument("--max-keyword-hyps", type=int, default=4,
                   help="at most this many hypotheses built from the matched keywords (hypothesis file "
                        "check1_types / check2_types) per check-1 window and per check-2 hit (default 4)")
    g.add_argument("--audit-strict", type=float, default=0.0, metavar="SHARE",
                   help="also run this share (0..1, e.g. 0.05) of the lines a level-A keyword filters through the "
                        "rules and the models, and store what they would decide in the decision's 'audit' (the "
                        "decision stays filter): shows level-A words that are too broad (default 0 = off)")
    g.add_argument("--strict-rules", action="store_true",
                   help="let the cheap rules mark a level-A keyword hit incidental before it filters the line "
                        "(default: a level-A hit filters the line, rules or not)")
    g.add_argument("--language-menu-min", type=int, default=3, help="language names in a row for a menu (default 3)")
    g.add_argument("--company-names-file", help="company/brand names, one per line; hits inside them are incidental")
    g.add_argument("--check1-chars", type=int, default=1000, help="check-1 window size in characters (~250 tokens)")
    g.add_argument("--check2-chars", type=int, default=300, help="max check-2 window (the sentence) in characters")
    g.add_argument("--max-windows", type=int, default=2,
                   help="check-1 windows per line (default 2; 0 = a window around every keyword hit of a long text)")
    g.add_argument("--no-early-stop", action="store_true",
                   help="score every check-1 window and every check-2 sentence even after the decision is certain "
                        "(same decisions, more model calls; for comparing scores) = both options below")
    g.add_argument("--no-check1-early-stop", action="store_true",
                   help="score every check-1 window, also after one passed (same decisions)")
    g.add_argument("--no-check2-early-stop", action="store_true",
                   help="score every hit's check-2 sentence, also after one was not incidental (same decisions)")
    g = p.add_argument_group("models and parallelism")
    g.add_argument("--fast-model", default="modernbert", help="modernbert | deberta | bge-m3 | folder (default modernbert)")
    g.add_argument("--judge-model", default="deberta", help="deberta | modernbert | bge-m3 | folder | none (default deberta)")
    g.add_argument("--models-root", help="folder with the model folders (default ./models)")
    g.add_argument("--device", default="auto", help="auto | cpu | cuda | cuda:0,cuda:1 | cpu*2 (default auto)")
    g.add_argument("--mode", default="auto", choices=["auto", "single", "thread", "process"],
                   help="single: one thread, for tests | thread: worker threads | process: one process per "
                        "device (default auto = single for one device, else thread)")
    g.add_argument("--workers-per-device", type=int, default=1)
    g.add_argument("--dtype", default="auto", help="auto | bf16 | fp16 | fp32")
    g.add_argument("--batch-size", type=int, default=32, help="fast-model pairs per batch (default 32)")
    g.add_argument("--judge-batch-size", type=int, help="judge pairs per batch (default = --batch-size)")
    g.add_argument("--max-batch-tokens", type=int, help="also cap a batch at about this many tokens")
    g.add_argument("--max-length", type=int, default=512, help="tokens per pair (default 512)")
    g.add_argument("--cpu-threads", type=int, help="torch threads per CPU worker")
    g.add_argument("--chunk-lines", type=int, default=512, help="lines per work unit (default 512)")
    g.add_argument("--inflight", type=int, help="work units processed at once (default 1 in single mode, else 2 x workers)")
    g = p.add_argument_group("output")
    g.add_argument("--output-dir", default="nli_filter_out", help="default ./nli_filter_out")
    g.add_argument("--decisions", choices=["all", "candidates", "none"], default="all",
                   help="lines in *.decisions.jsonl: all, only lines with keyword hits, or no file (default all)")
    g.add_argument("--write-split", action="store_true", help="also write the original lines to *.kept / *.filtered")
    g.add_argument("--compress", choices=["auto", "zst", "gz", "none"], default="auto",
                   help="output compression (default auto = .zst if the input was compressed)")
    g.add_argument("--overwrite", action="store_true", help="redo files that already have a .summary.json")
    g.add_argument("--no-progress-file", action="store_true",
                   help="do not write OUTPUT_DIR/progress/<run>.json (the viewer's 'Runs in progress')")
    g.add_argument("--progress-every", type=float, default=60.0, metavar="SECONDS",
                   help="how often the progress file is rewritten (default 60; the viewer warns after 3x this)")
    g.add_argument("--retries", type=int, default=3,
                   help="server input: download attempts after the first one fails (default 3)")
    g.add_argument("--download-dir", help="server input: folder for the downloaded files "
                                          "(default <output-dir>/.download; one or two files at a time)")
    g.add_argument("--show", type=int, default=20, help="mistakes to print (default 20)")
    g.add_argument("--report", action="store_true",
                   help="no filtering: print the summary of --output-dir from its *.summary.json files "
                        "(e.g. after several --shard copies) and save it as summary.report.json")
    g.add_argument("--keywords-report", action="store_true",
                   help="no models: run only the keyword search and the cheap rules over the input (use --limit for "
                        "a sample) and report per keyword how many lines it hits and sends to the models, with "
                        "examples; saves keywords_report.json / .tsv in --output-dir")
    g.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not args.verbose:
        quiet_transformers()
    if args.report:
        return report_main(args)

    # ---- country, keywords, hypotheses ----------------------------------------------------------
    known = COUNTRIES.get(args.country.strip().lower(), {})
    country = known.get("name", args.country.strip())
    adj = args.country_adj or known.get("adj")
    if not adj:
        print(f"error: --country-adj is required for '{country}'", file=sys.stderr)
        return 2
    kw_file = args.keywords_file
    if not kw_file and (HERE / "keywords" / f"{country.lower()}.txt").is_file():
        kw_file = str(HERE / "keywords" / f"{country.lower()}.txt")
    try:
        keywords: List[Any] = load_lexicon(kw_file) if kw_file else list(known.get("keywords", []))
    except (OSError, ValueError) as exc:
        print(f"error: keywords file: {exc}", file=sys.stderr)
        return 2
    keywords += args.keyword
    if not keywords:
        print(f"error: no keywords for '{country}': give --keywords-file or --keyword", file=sys.stderr)
        return 2
    excludes = list(args.exclude_pattern) or list(known.get("exclude", []))
    try:
        matcher = KeywordMatcher(keywords, excludes)
    except re.error as exc:
        print(f"error: bad --exclude-pattern: {exc}", file=sys.stderr)
        return 2
    for w in matcher.warnings:
        log.warning(w)
    hyp_file = args.hypotheses_file or (str(nli_hypotheses.find_file(country)) if nli_hypotheses.find_file(country)
                                        else None)
    base1, base2 = DEFAULT_CHECK1, DEFAULT_CHECK2
    types1: Dict[str, Dict[str, str]] = {}
    types2: Dict[str, Dict[str, str]] = {}
    if hyp_file:
        try:
            data = nli_hypotheses.load(hyp_file)
        except (OSError, ValueError) as exc:
            print(f"error: --hypotheses-file: {exc}", file=sys.stderr)
            return 2
        base1, base2 = data["check1"], data["check2"]
        types1, types2 = data.get("check1_types") or {}, data.get("check2_types") or {}
        log.warning("hypotheses from %s", hyp_file)
    check1 = _render(_kv(args.check1_hyp, "--check1-hyp") or base1, country, adj, "check-1")
    check2 = {} if args.no_check2 else _render(_kv(args.check2_hyp, "--check2-hyp") or base2,
                                               country, adj, "check-2")
    # --check1-hyp / --check2-hyp replace a check's hypotheses: the file's keyword templates of that check too
    check1_types = {} if args.check1_hyp else nli_hypotheses.render_types(types1, country, adj)
    check2_types = {} if (args.no_check2 or args.check2_hyp) else nli_hypotheses.render_types(types2, country, adj)
    if args.max_keyword_hyps < 0:
        print("error: --max-keyword-hyps must be 0 or more", file=sys.stderr)
        return 2
    if not 0 <= args.audit_strict <= 1:
        print("error: --audit-strict must be between 0 and 1", file=sys.stderr)
        return 2
    lo, hi = args.uncertain_band
    if not (0 <= lo < hi <= 1):
        print("error: --uncertain-band needs 0 <= LOW < HIGH <= 1", file=sys.stderr)
        return 2

    # ---- inputs ---------------------------------------------------------------------------------
    inputs = args.inputs or [str(HERE / "test_russia.jsonl")]
    try:
        files = expand_inputs(inputs)
    except FileNotFoundError as exc:
        print(f"error: input not found: {mask_uri(exc)}", file=sys.stderr)
        return 2
    except (StorageError, ValueError, RuntimeError) as exc:
        print(f"error: cannot read the input: {mask_uri(exc)}", file=sys.stderr)
        return 2
    if args.max_windows < 0:
        print("error: --max-windows must be 0 (no limit) or more", file=sys.stderr)
        return 2
    if args.shard:
        k, _, n = args.shard.partition("/")
        k, n = int(k), int(n)
        if not 0 <= k < n:
            print("error: --shard K/N needs 0 <= K < N", file=sys.stderr)
            return 2
        files = files[k::n]
    if not files:
        print("error: no input files", file=sys.stderr)
        return 2
    if not zstd_available() and any(f.lower().endswith((".zst", ".zstd")) for f in files):
        print("error: .zst input needs the 'zstandard' package (pip install zstandard)", file=sys.stderr)
        return 2
    if args.compress == "zst" and not zstd_available():
        print("error: --compress zst needs the 'zstandard' package", file=sys.stderr)
        return 2
    company_names = load_keywords(args.company_names_file) if args.company_names_file else []
    if args.keywords_report:
        rules = None if args.no_rules else IncidentalRules(adj, args.language_menu_min, company_names=company_names)
        return keywords_report(files, matcher, rules,
                               WindowBuilder(args.check1_chars, args.check2_chars, args.max_windows),
                               check1, check2, args, country, kw_file)

    # ---- models ---------------------------------------------------------------------------------
    t_load = time.perf_counter()
    common = dict(devices=args.device, mode=args.mode, workers_per_device=args.workers_per_device, dtype=args.dtype,
                  max_length=args.max_length, models_root=args.models_root, cpu_threads=args.cpu_threads,
                  max_batch_tokens=args.max_batch_tokens)
    try:
        fast = NLIPool(args.fast_model, batch_size=args.batch_size, **common)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: fast model: {exc}", file=sys.stderr)
        return 2
    judge = None
    try:
        if args.judge_model.lower() != "none":
            try:
                judge = NLIPool(args.judge_model, batch_size=args.judge_batch_size or args.batch_size, **common)
            except (FileNotFoundError, ValueError, RuntimeError) as exc:
                print(f"error: judge model: {exc}", file=sys.stderr)
                return 2
        load_seconds = time.perf_counter() - t_load
        if args.inflight:
            inflight = args.inflight
        elif fast.mode == "single":
            inflight = 1
        else:
            inflight = max(2, 2 * len(fast.devices) * args.workers_per_device)

        settings = FilterSettings(country, adj, check1, check2, args.check1_threshold, args.check2_threshold,
                                  args.text_field, args.id_field or None, args.expect_field or None,
                                  args.group_field or None, early_stop=not args.no_early_stop,
                                  check1_early_stop=not (args.no_early_stop or args.no_check1_early_stop),
                                  check2_early_stop=not (args.no_early_stop or args.no_check2_early_stop),
                                  strict_rules=args.strict_rules, check1_types=check1_types,
                                  check2_types=check2_types, max_keyword_hyps=args.max_keyword_hyps,
                                  audit_strict=args.audit_strict)
        rules = None if args.no_rules else IncidentalRules(adj, args.language_menu_min, company_names=company_names)
        scorer = CascadeScorer(fast, judge, (lo, hi))
        line_filter = LineFilter(settings, matcher, rules,
                                 WindowBuilder(args.check1_chars, args.check2_chars, args.max_windows), scorer)
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        pf = None if args.no_progress_file else ProgressFile(out_dir, {
            "command": mask_uri(" ".join([Path(sys.argv[0]).name] + list(argv if argv is not None else sys.argv[1:]))),
            "country": country, "shard": args.shard, "fast_model": fast.name,
            "judge_model": judge.name if judge else None, "devices": list(fast.devices), "mode": fast.mode},
            every=max(1.0, float(args.progress_every)))
        runner = FilterRunner(line_filter, out_dir, args.compress, args.write_split, args.decisions,
                              args.chunk_lines, inflight, args.limit, args.overwrite, retries=args.retries,
                              download_dir=Path(args.download_dir) if args.download_dir else None, progress_file=pf)
        log.warning("filtering %d file(s) for %s: fast %s, judge %s, mode %s, devices %s, inflight %d, keywords %d (%s)",
                    len(files), country, fast.name, judge.name if judge else "none", fast.mode,
                    ",".join(fast.devices), inflight, len(matcher.keywords), matcher.engine)
        t_run = time.perf_counter()
        try:
            runner.run(files)
        except KeyboardInterrupt:
            if pf:
                pf.finish("stopped")
            raise
        except BaseException as exc:
            if pf:
                pf.finish("failed", f"{type(exc).__name__}: {exc}")
            raise
        if pf:
            pf.finish("failed" if runner.failed else "done",
                      f"{runner.failed} file(s) could not be read" if runner.failed else None)
        run_seconds = time.perf_counter() - t_run
    finally:
        fast.close()
        if judge:
            judge.close()

    stats = runner.total.to_dict()
    pairs = scorer.fast_pairs + scorer.judge_pairs
    summary = {
        "country": {"name": country, "adj": adj, "keywords": matcher.keywords, "keywords_file": kw_file,
                    "exclude_patterns": excludes, "lexicon": matcher.counts(),
                    "lexicon_meta": {e.keyword: {k: v for k, v in e.as_dict().items() if k != "keyword"}
                                     for e in matcher.entries if len(e.as_dict()) > 1}},
        "hypotheses": {"check1": check1, "check2": check2, "file": hyp_file,
                       **({"check1_types": check1_types} if check1_types else {}),
                       **({"check2_types": check2_types} if check2_types else {})},
        "settings": {"check1_threshold": args.check1_threshold, "check2_threshold": args.check2_threshold,
                     "uncertain_band": [lo, hi], "rules": not args.no_rules,
                     "language_menu_min": args.language_menu_min, "check1_chars": args.check1_chars,
                     "check2_chars": args.check2_chars, "max_windows": args.max_windows,
                     "early_stop": not args.no_early_stop, "strict_rules": args.strict_rules,
                     "max_keyword_hyps": args.max_keyword_hyps, "audit_strict": args.audit_strict,
                     "check1_early_stop": settings.check1_early_stop, "check2_early_stop": settings.check2_early_stop,
                     "text_field": args.text_field, "id_field": args.id_field, "expect_field": args.expect_field,
                     "chunk_lines": args.chunk_lines, "inflight": inflight, "write_split": args.write_split,
                     "decisions": args.decisions, "limit": args.limit, "shard": args.shard},
        "models": {"fast": fast.info(), "judge": judge.info() if judge else None},
        "timing": {"load_seconds": round(load_seconds, 2), "run_seconds": round(run_seconds, 2),
                   "lines_per_second": round(runner._seen / run_seconds, 2) if run_seconds else 0.0,
                   "fast_pairs": scorer.fast_pairs, "judge_pairs": scorer.judge_pairs,
                   "pairs_per_second": round(pairs / run_seconds, 2) if run_seconds else 0.0},
        "files": runner.files,
        "stats": stats,
        "output_dir": str(out_dir),
        "command": mask_uri(" ".join([Path(sys.argv[0]).name] + list(argv if argv is not None else sys.argv[1:]))),
        "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    # one run summary per shard, so copies running side by side do not overwrite each other
    name = "summary.json" if not args.shard else "summary.shard-{}-of-{}.json".format(*args.shard.split("/"))
    with open(out_dir / name, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)
    print(format_summary(summary, args.show))
    if args.shard:
        print(f" shard summary: {out_dir / name}   (all shards together: python nli_filter.py --report "
              f"--output-dir {out_dir})")
    if runner.failed:
        print(f"error: {runner.failed} file(s) could not be downloaded (see 'files' in {out_dir / name}); "
              f"run the same command again to retry them", file=sys.stderr)
        return 1
    return 0


def build_report(out_dir: Path) -> Optional[Dict[str, Any]]:
    """Whole-run summary rebuilt from the per-file *.summary.json files (and the run summaries for model
    and timing details). Works after several --shard copies, or while a run is still going."""
    run_files = sorted(p for p in out_dir.glob("summary*.json") if p.name != "summary.report.json")
    per_file = sorted(p for p in out_dir.rglob("*.summary.json")
                      if not (p.parent == out_dir and p.name.startswith("summary")))
    if not per_file:
        return None
    total = RunStats()
    files = []
    for p in per_file:
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
        total.merge(RunStats(d["stats"]))
        files.append({"input": d["input"], "status": "done" if d.get("complete", True) else "partial (--limit)",
                      **_file_row(d)})
    runs = []
    for p in run_files:
        with open(p, encoding="utf-8") as fh:
            runs.append(json.load(fh))
    base = runs[0] if runs else {}
    run_seconds = max((r["timing"]["run_seconds"] for r in runs), default=0.0)  # shards ran side by side
    fast_pairs = sum(r["timing"]["fast_pairs"] for r in runs)
    judge_pairs = sum(r["timing"]["judge_pairs"] for r in runs)
    stats = total.to_dict()
    return {
        "country": base.get("country", {"name": "?", "adj": "?"}),
        "hypotheses": base.get("hypotheses"),
        "settings": base.get("settings", {"uncertain_band": None, "expect_field": "expect", "write_split": False}),
        "models": base.get("models") or {"fast": {"model": "?", "mode": "?", "devices": ["?"], "dtype": "?"}},
        "timing": {"load_seconds": max((r["timing"]["load_seconds"] for r in runs), default=0.0),
                   "run_seconds": run_seconds,
                   "lines_per_second": round(stats["lines"] / run_seconds, 2) if run_seconds else 0.0,
                   "fast_pairs": fast_pairs, "judge_pairs": judge_pairs,
                   "pairs_per_second": round((fast_pairs + judge_pairs) / run_seconds, 2) if run_seconds else 0.0},
        "runs": [p.name for p in run_files],
        "files": files,
        "stats": stats,
        "output_dir": str(out_dir),
        "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def keywords_report(files: List[str], matcher: KeywordMatcher, rules: Optional[IncidentalRules],
                    windows: WindowBuilder, check1: Dict[str, str], check2: Dict[str, str], args,
                    country: str, kw_file: Optional[str]) -> int:
    """
    --keywords-report: keyword search + cheap rules only (no model). Per keyword: lines hit, hits the rules
    explain, lines that reach the models, lines that reach them ONLY because of this keyword (what removing it
    would save), examples. Totals estimate the model work of a real run.
    """
    canon = {k.lower(): k for k in matcher.keywords}
    per = {e.keyword: {"keyword": e.keyword, "level": e.level, "type": e.type, "hits": 0, "lines": 0, "rule_hits": 0,
                       "open_hits": 0, "nli_lines": 0, "only_lines": 0, "examples": []} for e in matcher.entries}
    tot = collections.Counter()
    n_examples = 3
    t0 = time.perf_counter()
    last = t0
    out_dir = Path(args.output_dir)
    for path in files:
        if args.limit is not None and tot["lines"] >= args.limit:
            break
        try:
            source = JsonlSource(path)
            for rec in source.records():
                if args.limit is not None and tot["lines"] >= args.limit:
                    break
                tot["lines"] += 1
                tot["bytes"] += len(rec.raw) + 1
                text = rec.get(args.text_field)
                if not isinstance(text, str) or not text.strip():
                    continue
                tot["text_lines"] += 1
                hits = matcher.find(text)
                if not hits:
                    continue
                tot["hit_lines"] += 1
                # level A: the line is filtered without models (with --strict-rules: unless the rules resolve it)
                strict = [h for h in hits if h.kw is not None and matcher.entries[h.kw].strict]
                strict_line = bool(strict) and not args.strict_rules
                if rules is not None and not strict_line:
                    rules.apply(text, hits)
                strict_line = strict_line or any(h.rule is None for h in strict)
                open_hits = [] if strict_line else [h for h in hits if h.rule is None]
                by_kw: Dict[str, List[Hit]] = collections.defaultdict(list)
                for h in hits:
                    by_kw[canon.get(text[h.start:h.end].lower(), text[h.start:h.end])].append(h)
                open_kws = {canon.get(text[h.start:h.end].lower(), text[h.start:h.end]) for h in open_hits}
                for k, hs in by_kw.items():
                    s = per.setdefault(k, {"keyword": k, "hits": 0, "lines": 0, "rule_hits": 0, "open_hits": 0,
                                           "nli_lines": 0, "only_lines": 0, "examples": []})
                    s["hits"] += len(hs)
                    s["lines"] += 1
                    s["rule_hits"] += sum(1 for h in hs if h.rule)
                    s["open_hits"] += sum(1 for h in hs if not h.rule)
                    if k in open_kws:
                        s["nli_lines"] += 1
                        if len(open_kws) == 1:
                            s["only_lines"] += 1
                    if len(s["examples"]) < n_examples:
                        h = hs[0]
                        a, b = max(0, h.start - 50), min(len(text), h.end + 50)
                        snippet = (("..." if a else "") + text[a:h.start] + "[" + text[h.start:h.end] + "]" +
                                   text[h.end:b] + ("..." if b < len(text) else ""))
                        s["examples"].append({"source": str(rec.source), "line": rec.line,
                                              "text": " ".join(snippet.split())})
                if strict_line:
                    tot["strict_lines"] += 1
                    for k in {canon.get(text[h.start:h.end].lower(), text[h.start:h.end]) for h in strict}:
                        per[k]["strict_lines"] = per[k].get("strict_lines", 0) + 1
                    continue
                if not open_hits:
                    tot["rules_lines"] += 1
                    continue
                tot["nli_lines"] += 1
                tot["check1_windows"] += len(windows.check1(text, open_hits))
                tot["open_hits"] += len(open_hits)
                now = time.perf_counter()
                if now - last >= 10:
                    last = now
                    log.warning("keywords report: %d lines (%.0f lines/s)", tot["lines"], tot["lines"] / (now - t0))
        except Exception as exc:  # e.g. a server file that cannot be read: report it, go on
            tot["failed_files"] += 1
            log.error("skip %s: %s", path, mask_uri(exc))
    seconds = time.perf_counter() - t0
    lines = tot["lines"]
    pairs_c1 = tot["check1_windows"] * len(check1)
    rows = sorted(per.values(), key=lambda s: (-s["nli_lines"], -s["lines"], s["keyword"].lower()))
    unused = sorted((s["keyword"] for s in rows if s["lines"] == 0), key=str.lower)
    summary = {
        "country": country, "keywords_file": kw_file, "keywords": len(matcher.keywords), "lexicon": matcher.counts(), "engine": matcher.engine,
        "files": len(files), "failed_files": tot["failed_files"], "limit": args.limit,
        "lines": lines, "text_lines": tot["text_lines"], "bytes": tot["bytes"], "seconds": round(seconds, 2),
        "lines_with_keyword": tot["hit_lines"], "lines_strict": tot["strict_lines"], "lines_rules_only": tot["rules_lines"],
        "lines_to_models": tot["nli_lines"],
        "estimate": {"check1_windows": tot["check1_windows"], "check1_pairs": pairs_c1,
                     "check2_pairs_at_most": tot["open_hits"] * len(check2),
                     "note": "check-2 pairs are only scored for lines that pass check 1, so the real number is lower"},
        "keywords_used": len(rows) - len(unused), "keywords_unused": unused,
        "per_keyword": [s for s in rows if s["lines"]],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "keywords_report.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)
    with open(out_dir / "keywords_report.tsv", "w", encoding="utf-8", newline="\n") as fh:
        fh.write("keyword\tlevel\ttype\tlines\tlines_to_models\tonly_this_keyword\tlevel_a_lines\thits\trule_hits\texample\n")
        for s in rows:
            ex = s["examples"][0]["text"].replace("\t", " ") if s["examples"] else ""
            fh.write(f"{s['keyword']}\t{s.get('level') or 'B'}\t{s.get('type') or ''}\t{s['lines']}\t{s['nli_lines']}\t"
                     f"{s['only_lines']}\t{s.get('strict_lines', 0)}\t{s['hits']}\t{s['rule_hits']}\t{ex}\n")

    def pct(a: float) -> str:
        return _pct(a, lines).strip()

    mb = tot["bytes"] / 1e6
    L = ["", "=" * 78, f" Keywords report - {country}, {len(matcher.keywords)} keywords ({matcher.engine}), "
                       f"{len(files)} file(s), no models", "=" * 78,
         f" lines               {lines:>12,}" + (f"   (sample: --limit {args.limit})" if args.limit else ""),
         f" with a keyword      {tot['hit_lines']:>12,}   {pct(tot['hit_lines'])}",
         f"   level-A keyword   {tot['strict_lines']:>12,}   {pct(tot['strict_lines'])}   (filtered, no model)",
         f"   kept by the rules {tot['rules_lines']:>12,}   {pct(tot['rules_lines'])}   (language menus / labels, no model)",
         f"   go to the models  {tot['nli_lines']:>12,}   {pct(tot['nli_lines'])}",
         f" estimated model work: check 1 {pairs_c1:,} pairs ({tot['check1_windows']:,} windows x {len(check1)} "
         f"hypotheses), check 2 at most {tot['open_hits'] * len(check2):,} pairs",
         f" read {mb:,.1f} MB in {seconds:.1f}s ({mb / seconds if seconds else 0:.1f} MB/s, "
         f"{lines / seconds if seconds else 0:,.0f} lines/s)"
         + (f"   {tot['failed_files']} file(s) could not be read" if tot["failed_files"] else ""),
         "", f" keywords that send the most lines to the models (top {min(args.show, len(summary['per_keyword']))}"
             f" of {summary['keywords_used']} used):",
         f"   {'keyword':<24} {'lines':>9} {'to models':>10} {'only this':>10} {'rule hits':>10}"]
    for s in summary["per_keyword"][:args.show]:
        L.append(f"   {s['keyword'][:24]:<24} {s['lines']:>9,} {s['nli_lines']:>10,} {s['only_lines']:>10,} "
                 f"{s['rule_hits']:>10,}")
        if s["examples"]:
            L.append(f"      e.g. {s['examples'][0]['text'][:100]}")
    L += ["", f" keywords without any hit: {len(unused)}" + (f" ({', '.join(unused[:15])}"
                                                         f"{', ...' if len(unused) > 15 else ''})" if unused else ""),
          " 'only this' = lines that reach the models only because of this keyword: removing it saves them.",
          f" all keywords, with examples: {out_dir / 'keywords_report.tsv'} and keywords_report.json", "=" * 78]
    print("\n".join(L))
    return 1 if tot["failed_files"] else 0


def report_main(args) -> int:
    out_dir = Path(args.output_dir)
    report = build_report(out_dir)
    if report is None:
        print(f"error: no *.summary.json files under {out_dir}", file=sys.stderr)
        return 2
    with open(out_dir / "summary.report.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print(format_summary(report, args.show))
    partial = sum(1 for f in report["files"] if f["status"] != "done")
    print(f" report from {len(report['files'])} file summaries ({partial} partial) and {len(report['runs'])} run "
          f"summaries -> {out_dir / 'summary.report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

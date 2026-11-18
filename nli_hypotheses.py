"""
nli_hypotheses.py - hypothesis files shared by nli_filter.py, nli_playground.py and the viewer.

A hypothesis file is JSON in the folder hypotheses/ of the project:

    {
      "description": "what this set is for (optional)",
      "check1": {"topic": "This text is about {country}."},
      "check2": {"company_name": "This text mentions {country} only as part of a company or brand name."}
    }

check1 = is the text about the country? (every key = one hypothesis, the highest score counts)
check2 = is a keyword hit only incidental? ({} = no check 2)
{country} and {country_adj} are filled in for the chosen country (e.g. Russia / Russian).

Optional: hypotheses built from the matched keyword (keyword lexicon: type, gloss, other meanings):

    "check1_types": {"region": {"place": "This text is about {kw}, {gloss}."}},
    "check2_types": {"*":      {"brand": "In this text, {kw} is part of a company, product or brand name."},
                     "@other": {"sense": "In this text, {kw} means {other}."}}

  type key   a keyword type of the lexicon (region, city, person, ...), "*" = every keyword,
             "@other" (check 2 only) = once per other meaning of the keyword
  {kw}       the keyword (as written in the keyword file); {gloss} its gloss (a template with {gloss} is
             skipped for keywords without one); {other} one of its other meanings (only in "@other")
  check 1: a window gets these for the keywords hit inside it; check 2: a hit gets those of its keyword.

Which file nli_filter.py uses: --hypotheses-file, else hypotheses/<country>.json (e.g. hypotheses/russia.json)
when it exists, else the built-in defaults below (also saved as hypotheses/default.json). --check1-hyp /
--check2-hyp on the command line replace the file's check 1 / check 2.

    from nli_hypotheses import load, find_file, render, DEFAULT
    data = load("hypotheses/russia.json")          # {"description", "check1", "check2"}, validated
    check1 = render(data["check1"], "Russia", "Russian")
"""
from __future__ import annotations

import json
import re
import string
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = ["DEFAULT_CHECK1", "DEFAULT", "HYPOTHESES_DIR", "validate", "load", "dump", "find_file", "render",
           "render_types", "fill", "list_files", "NAME_RE", "TYPE_SECTIONS"]

HERE = Path(__file__).resolve().parent
HYPOTHESES_DIR = HERE / "hypotheses"
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")  # file names the viewer may save (without .json)
TYPE_SECTIONS = {"check1_types": "check1", "check2_types": "check2"}
_TYPE_KEY_RE = re.compile(r"^(\*|@other|[a-z][a-z0-9_-]*)$")
_KEY_RE = re.compile(r"[A-Za-z0-9_.-]{1,60}")

DEFAULT_CHECK1 = {
    "topic": "This text is about {country}, a {country_adj} person, a {country_adj} film, a {country_adj} song, "
             "the lyrics of a {country_adj} song, or the history of {country}.",
}
DEFAULT_CHECK2 = {
    "company_name": "This text mentions {country} or {country_adj} only as part of a company or brand name.",
    "language_setting": "This text mentions the {country_adj} language only as a language option or setting.",
}
DEFAULT = {"description": "built-in default hypotheses of nli_filter.py", "check1": DEFAULT_CHECK1,
           "check2": DEFAULT_CHECK2}


def _placeholders(template: str) -> List[str]:
    try:
        return [f for _, f, _, _ in string.Formatter().parse(template) if f is not None]
    except ValueError as exc:
        raise ValueError(f"bad braces: {exc}") from None


def validate(data: Any) -> Dict[str, Any]:
    """Checked copy {"description", "check1", "check2"}; raises ValueError with a readable message."""
    if not isinstance(data, dict):
        raise ValueError("a hypothesis file must be a JSON object with 'check1' and 'check2'")
    unknown = sorted(set(data) - {"description", "check1", "check2", *TYPE_SECTIONS})
    if unknown:
        raise ValueError(f"unknown key(s) {unknown}: only description, check1, check2, check1_types, check2_types")
    out: Dict[str, Any] = {"description": str(data.get("description") or "")}
    for check in ("check1", "check2"):
        hyps = data.get(check, {} if check == "check2" else None)
        if not isinstance(hyps, dict):
            raise ValueError(f"'{check}' must be an object of key -> hypothesis")
        if check == "check1" and not hyps:
            raise ValueError("'check1' needs at least one hypothesis")
        clean = {}
        for key, tpl in hyps.items():
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,60}", key):
                raise ValueError(f"{check}: key {key!r} may use only letters, digits, _ . - (max 60)")
            if not isinstance(tpl, str) or not tpl.strip():
                raise ValueError(f"{check}.{key}: the hypothesis must be a non-empty text")
            bad = [p for p in _placeholders(tpl) if p not in ("country", "country_adj")]
            if bad:
                raise ValueError(f"{check}.{key}: only {{country}} and {{country_adj}} are allowed, not {bad}")
            clean[key] = tpl.strip()
        out[check] = clean
    for section, check in TYPE_SECTIONS.items():
        types = data.get(section)
        if types is None or types == {}:
            continue
        if not isinstance(types, dict):
            raise ValueError(f"'{section}' must be an object of keyword type -> {{key: hypothesis}}")
        clean_t: Dict[str, Dict[str, str]] = {}
        for typ, hyps in types.items():
            if not isinstance(typ, str) or not _TYPE_KEY_RE.match(typ):
                raise ValueError(f"{section}: type {typ!r}: a keyword type (lowercase word), '*' or '@other'")
            if typ == "@other" and check == "check1":
                raise ValueError(f"{section}: '@other' (other meanings) is for check 2 only")
            if not isinstance(hyps, dict) or not hyps:
                raise ValueError(f"{section}.{typ} must be a non-empty object of key -> hypothesis")
            allowed = {"country", "country_adj", "kw", "gloss"} | ({"other"} if typ == "@other" else set())
            ct = {}
            for key, tpl in hyps.items():
                where = f"{section}.{typ}.{key}"
                if not isinstance(key, str) or not _KEY_RE.fullmatch(key):
                    raise ValueError(f"{where}: the key may use only letters, digits, _ . - (max 60)")
                if not isinstance(tpl, str) or not tpl.strip():
                    raise ValueError(f"{where}: the hypothesis must be a non-empty text")
                ph = _placeholders(tpl)
                bad = [x for x in ph if x not in allowed]
                if bad:
                    raise ValueError(f"{where}: allowed are {{{'}, {'.join(sorted(allowed))}}}, not {bad}")
                if typ == "@other" and "other" not in ph:
                    raise ValueError(f"{where}: an '@other' hypothesis needs {{other}} (the other meaning)")
                ct[key] = tpl.strip()
            clean_t[typ] = ct
        out[section] = clean_t
    return out


def load(path: str) -> Dict[str, Any]:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"{p.name}: not valid JSON: {exc}") from None
    try:
        return validate(data)
    except ValueError as exc:
        raise ValueError(f"{p.name}: {exc}") from None


def dump(data: Dict[str, Any]) -> str:
    """The file text (validated, pretty, UTF-8 kept)."""
    return json.dumps(validate(data), ensure_ascii=False, indent=2) + "\n"


def find_file(country: str, folder: Optional[Path] = None) -> Optional[Path]:
    """hypotheses/<country>.json when it exists (the default for that country), else None."""
    p = (folder or HYPOTHESES_DIR) / f"{country.strip().lower()}.json"
    return p if p.is_file() else None


def render(templates: Dict[str, str], country: str, adj: str) -> Dict[str, str]:
    """Fill in {country} / {country_adj}."""
    return {k: t.format(country=country, country_adj=adj) for k, t in templates.items()}


def render_types(types: Optional[Dict[str, Dict[str, str]]], country: str, adj: str) -> Dict[str, Dict[str, str]]:
    """check*_types with {country} / {country_adj} filled in; {kw}, {gloss}, {other} stay for fill()."""
    keep = {"kw": "{kw}", "gloss": "{gloss}", "other": "{other}"}
    return {typ: {k: t.format(country=country, country_adj=adj, **keep) for k, t in hyps.items()}
            for typ, hyps in (types or {}).items()}


def fill(template: str, kw: str, gloss: Optional[str] = None, other: Optional[str] = None) -> str:
    """A rendered type template for one keyword (plain replace: braces in a gloss stay as they are)."""
    out = template.replace("{kw}", kw)
    if gloss is not None:
        out = out.replace("{gloss}", gloss)
    if other is not None:
        out = out.replace("{other}", other)
    return out


def list_files(folder: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Every hypotheses/*.json with its content, or the error that makes it unusable."""
    out = []
    for p in sorted((folder or HYPOTHESES_DIR).glob("*.json")):
        item: Dict[str, Any] = {"name": p.stem, "file": p.name}
        try:
            item["data"] = load(str(p))
        except (OSError, ValueError) as exc:
            item["error"] = str(exc)
        out.append(item)
    return out

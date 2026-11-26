"""What "same as expected" means for Expected vs result: labels/expected_rules.json.

    {"default": "strict",
     "profiles": {"strict": {"same": [["pass", "untouched", "none"]]},
                  "quick":  {"same": [["keep", "pass", "untouched", "none"]], "note": "text kept = match"}},
     "aliases": {"flag": "remove"}}

- same: groups of actions that count as equal in that profile;
- aliases: an expected value replaced before comparing (flag -> remove);
- default: the profile used when the page does not choose one.

A missing file means the built-in strict rule (pass = untouched = none), which is what the viewer did before the file
existed. The file is re-read when it changes (no restart).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

RULES_FILE = "labels/expected_rules.json"
ACTIONS = ("remove", "review", "keep", "pass", "untouched", "none", "kept", "edited", "removed", "error")
BUILTIN: Dict[str, Any] = {
    "about": "How Expected vs result decides that a result matches the expected action.",
    "default": "strict",
    "profiles": {"strict": {"same": [["pass", "untouched", "none"]]}},
    "aliases": {},
}


def check(data: Any) -> List[str]:
    """Problems that make the file unusable (empty list = fine)."""
    errs: List[str] = []
    if not isinstance(data, dict):
        return ["the rules must be a JSON object"]
    profiles = data.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        return ["profiles: an object of name -> {\"same\": [[action, ...], ...]} with at least one profile"]
    for name, p in profiles.items():
        where = f"profile '{name}'"
        if not str(name).strip() or not all(c.isalnum() or c in "_-" for c in str(name)):
            errs.append(f"{where}: a name of letters, digits, _ and -")
        if not isinstance(p, dict):
            errs.append(f"{where}: must be an object with \"same\"")
            continue
        same = p.get("same", [])
        if not isinstance(same, list) or any(not isinstance(g, list) for g in same):
            errs.append(f"{where}: same must be a list of groups (lists of actions)")
            continue
        seen: Dict[str, int] = {}
        for gi, g in enumerate(same, 1):
            if len(g) < 2:
                errs.append(f"{where}, group {gi}: needs at least two actions")
            for a in g:
                if a not in ACTIONS:
                    errs.append(f"{where}, group {gi}: unknown action '{a}' (one of {', '.join(ACTIONS)})")
                elif a in seen and seen[a] != gi:
                    errs.append(f"{where}: '{a}' is in group {seen[a]} and group {gi} (merge them)")
                else:
                    seen[a] = gi
        if "note" in p and not isinstance(p["note"], str):
            errs.append(f"{where}: note must be text")
    default = data.get("default")
    if default is not None and default not in profiles:
        errs.append(f"default: '{default}' is not one of the profiles ({', '.join(profiles)})")
    aliases = data.get("aliases", {})
    if not isinstance(aliases, dict):
        errs.append("aliases: an object of expected value -> action")
    else:
        for k, v in aliases.items():
            if not str(k).strip():
                errs.append("aliases: an empty name")
            if v not in ACTIONS:
                errs.append(f"aliases: '{k}' -> '{v}': the target must be one of {', '.join(ACTIONS)}")
    return errs


class Rules:
    """The rules file, re-read when it changes. A broken file falls back to the built-in strict rule and reports why."""

    def __init__(self, project: Path):
        self.path = Path(project) / RULES_FILE
        self._key: Optional[Tuple[float, int]] = None
        self.data: Dict[str, Any] = BUILTIN
        self.problem: Optional[str] = None

    def load(self) -> Dict[str, Any]:
        try:
            st = self.path.stat()
            key: Optional[Tuple[float, int]] = (st.st_mtime_ns, st.st_size)
        except OSError:
            key = None
        if key == self._key and (key is not None or self.data is BUILTIN):
            return self.data
        self._key = key
        self.problem = None
        if key is None:
            self.data = BUILTIN
            return self.data
        import json
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            errs = check(data)
        except ValueError as exc:
            data, errs = None, [f"not valid JSON: {exc}"]
        if errs:
            self.problem = f"{RULES_FILE} is not used ({'; '.join(errs[:3])}): the built-in strict rule applies"
            self.data = BUILTIN
        else:
            self.data = data
        return self.data

    def profiles(self) -> List[str]:
        return list(self.load()["profiles"])

    def default(self) -> str:
        d = self.load()
        return d.get("default") or next(iter(d["profiles"]))

    def pick(self, profile: Optional[str]) -> str:
        d = self.load()
        return profile if profile in d["profiles"] else self.default()

    def alias(self, value: Any) -> str:
        v = str(value).strip()
        return str(self.load().get("aliases", {}).get(v, v))

    def same(self, actions: Iterable[Any], profile: Optional[str] = None) -> set:
        """Every action that counts as one of `actions` (after aliases) in the profile."""
        d = self.load()
        groups = d["profiles"][self.pick(profile)].get("same") or []
        out = {self.alias(a) for a in actions if a}
        for g in groups:
            if out & set(g):
                out |= set(g)
        return out

    def why(self, got: Any, expected: Iterable[Any], profile: Optional[str] = None) -> str:
        """How a match was made: "" (exact), "keep ≈ pass (quick)", "flag → remove (alias)"."""
        prof = self.pick(profile)
        exp = [str(a).strip() for a in expected if a]
        if got in exp:
            return ""
        aliased = [self.alias(a) for a in exp]
        parts = [f"{a} → {b} (alias)" for a, b in zip(exp, aliased) if a != b]
        if got not in aliased:
            for g in self.load()["profiles"][prof].get("same") or []:
                if got in g:
                    hit = next((a for a in aliased if a in g), None)
                    if hit:
                        parts.append(f"{got} ≈ {hit} ({prof})")
                        break
        return "; ".join(parts)

    def info(self) -> Dict[str, Any]:
        d = self.load()
        return {"path": RULES_FILE, "exists": self.path.is_file(), "problem": self.problem,
                "default": self.default(), "profiles": {k: {"same": v.get("same") or [], "note": v.get("note") or ""}
                                                         for k, v in d["profiles"].items()},
                "aliases": d.get("aliases") or {}, "actions": list(ACTIONS)}

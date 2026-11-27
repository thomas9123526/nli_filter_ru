// Several level-0 gates are OR-combined (nli_label.py). A run_if that names some gates but not all is refused, so:
// - addGateToRunIf: a new gate is added to every run_if level that names a gate already (and has no @gate);
// - gatesToAt: the quick fix, every gate key in run_if replaced by "@gate" (any gate open).
import type { PolicyData } from "./types";

const gateKeys = (p: PolicyData, except?: string) =>
  Object.entries(p.labels || {}).filter(([k, l]) => l.level === 0 && k !== except).map(([k]) => k);

/** Mutates p: called right after p.labels[key] was added as a level-0 label. Returns the run_if levels changed. */
export function addGateToRunIf(p: PolicyData, key: string): string[] {
  const others = gateKeys(p, key);
  const changed: string[] = [];
  for (const [lv, keys] of Object.entries(p.run_if || {})) {
    if (keys.includes("@gate") || keys.includes(key)) continue;
    if (keys.some((k) => others.includes(k))) {
      p.run_if![lv] = [...keys, key];
      changed.push(lv);
    }
  }
  return changed;
}

/** Does some run_if level name only some of several gates (what nli_label.py refuses)? */
export function partialGates(p: PolicyData): string[] {
  const gates = gateKeys(p);
  if (gates.length < 2) return [];
  return Object.entries(p.run_if || {}).filter(([, keys]) => {
    const named = keys.filter((k) => gates.includes(k));
    return named.length > 0 && named.length < gates.length && !keys.includes("@gate");
  }).map(([lv]) => lv);
}

/** Mutates p: in every run_if level, the gate keys -> one "@gate". */
export function gatesToAt(p: PolicyData): void {
  const gates = gateKeys(p);
  for (const [lv, keys] of Object.entries(p.run_if || {})) {
    if (!keys.some((k) => gates.includes(k))) continue;
    const out: string[] = [];
    for (const k of keys) {
      const v = gates.includes(k) ? "@gate" : k;
      if (!out.includes(v)) out.push(v);
    }
    p.run_if![lv] = out;
  }
}

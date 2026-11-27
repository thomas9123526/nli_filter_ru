// Expected vs got in the browser, with the same rule as the backend (labels/expected_rules.json: aliases on the
// expected values, then the chosen profile's "same" groups) — the Experiment page compares its fresh results.
import type { ExpectedRulesInfo } from "./types";

export type LineExpected = { expected_action: string; acceptable?: string[]; note?: string; clarity?: string;
  clarity_reason?: string; gate_expected?: boolean };

export function sameSet(actions: string[], rules: ExpectedRulesInfo | null | undefined, profile?: string): Set<string> {
  const aliases = rules?.aliases || {};
  const out = new Set(actions.filter(Boolean).map((a) => aliases[a.trim()] ?? a.trim()));
  const prof = profile && rules?.profiles?.[profile] ? profile : rules?.default;
  const groups = (prof && rules?.profiles?.[prof]?.same) || [["pass", "untouched", "none"]];
  for (const g of groups) if (g.some((x) => out.has(x))) g.forEach((x) => out.add(x));
  return out;
}

/** Does `got` (a line's strictest action) match the expected result under the profile? */
export function expectedOk(got: string, e: LineExpected, rules: ExpectedRulesInfo | null | undefined, profile?: string): boolean {
  const exp = [...String(e.expected_action).split(" or "), ...(e.acceptable || [])];
  return sameSet(exp, rules, profile).has(got);
}

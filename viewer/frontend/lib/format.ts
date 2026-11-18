// Formatting helpers and the labels used across pages.

export const REASON_LABEL: Record<string, string> = {
  blank: "Empty line",
  bad_json: "Not valid JSON",
  no_text: "No text",
  no_keyword: "No keyword",
  strict_keyword: "Level-A keyword",
  rules_incidental: "Resolved by rules",
  check1_negative: "Check 1: not about country",
  check2_incidental: "Check 2: only incidental",
  about_country: "About the country",
};

export const REASON_ORDER = Object.keys(REASON_LABEL);

export const RULE_LABEL: Record<string, string> = {
  language_menu: "language menu",
  language_label: "language label",
  locale_code: "locale code",
  company_name: "company name",
};

export const HIT_STATE_LABEL: Record<string, string> = {
  about: "hit: not incidental (check 2)",
  open: "hit: went to check 1 only",
  incidental: "hit: incidental (check 2)",
  rule: "hit: resolved by a rule",
  strict: "hit: level-A keyword (filters the line, no model)",
};

export function score(x: number | null | undefined, digits = 3): string {
  return x === null || x === undefined ? "–" : x.toFixed(digits);
}

export function pct(a: number, b: number, digits = 1): string {
  return b ? `${((100 * a) / b).toFixed(digits)}%` : "–";
}

export function num(x: number | null | undefined): string {
  return x === null || x === undefined ? "–" : x.toLocaleString("en-US");
}

export function seconds(x: number | null | undefined): string {
  if (x === null || x === undefined) return "–";
  if (x < 60) return `${x.toFixed(1)} s`;
  if (x < 3600) return `${(x / 60).toFixed(1)} min`;
  return `${(x / 3600).toFixed(2)} h`;
}

/** Build an in-app link with query parameters (skips empty values). */
export function href(path: string, params: Record<string, string | number | boolean | null | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `${path}?${s}` : path;
}

/** The decision-list filters that travel between the file and record pages. */
export const FILTER_KEYS = ["decision", "reason", "q", "kw", "rule", "min_score", "max_score", "mismatch", "judged"] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];

export function pickFilters(sp: URLSearchParams): Record<FilterKey, string> {
  const out = {} as Record<FilterKey, string>;
  for (const k of FILTER_KEYS) out[k] = sp.get(k) || "";
  return out;
}

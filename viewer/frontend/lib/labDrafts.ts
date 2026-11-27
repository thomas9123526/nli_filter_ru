// The Experiment page's saved drafts (dataset/lab_drafts/, backend nli_viewer/lab_drafts.py) and "carry my changes":
// a draft made on one base policy applied onto another base as its changes only (added / removed labels, changed
// label fields, run_if entries added / removed, other settings changed), so a newer base is not overwritten.
import type { PolicyData } from "./types";

export type DraftInfo = { id: string; name: string | null; auto: boolean; saved: string; saved_ts: number; summary: string;
  run?: string | null; file?: string | null; line?: number | null; policy_path?: string | null; labels: number; texts: number;
  first_text: string };
export type DraftFile = { id: string; name: string | null; auto: boolean; saved: string; summary: string;
  base: { run?: string; file?: string; line?: number; para?: string | null; policy_path?: string; policy_data?: PolicyData;
    settings?: Record<string, unknown> };
  policy: PolicyData; settings: Record<string, unknown>; texts: string[] };

const J = (x: unknown) => JSON.stringify(x ?? null);
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));

/** target + (draft - from), and how many changes were carried. */
export function carryChanges(from: PolicyData, draft: PolicyData, target: PolicyData): { policy: PolicyData; carried: number } {
  const out = clone(target);
  out.labels = out.labels || {};
  let n = 0;
  const lf = from.labels || {}, ld = draft.labels || {};
  for (const k of Object.keys(ld)) {
    if (!(k in lf)) { out.labels[k] = clone(ld[k]); n++; continue; }
    if (J(lf[k]) === J(ld[k])) continue;
    if (!(k in out.labels)) { out.labels[k] = clone(ld[k]); n++; continue; }
    const fields = new Set([...Object.keys(lf[k]), ...Object.keys(ld[k])]);
    for (const f of fields) {
      const a = (lf[k] as Record<string, unknown>)[f], b = (ld[k] as Record<string, unknown>)[f];
      if (J(a) === J(b)) continue;
      if (b === undefined) delete (out.labels[k] as Record<string, unknown>)[f];
      else (out.labels[k] as Record<string, unknown>)[f] = clone(b);
      n++;
    }
  }
  for (const k of Object.keys(lf)) {
    if (!(k in ld) && k in out.labels) {
      delete out.labels[k];
      for (const lv of Object.keys(out.run_if || {})) out.run_if![lv] = out.run_if![lv].filter((x) => x !== k);
      n++;
    }
  }
  const rf = from.run_if || {}, rd = draft.run_if || {};
  for (const lv of new Set([...Object.keys(rf), ...Object.keys(rd)])) {
    const a = rf[lv] || [], b = rd[lv] || [];
    if (J(a) === J(b)) continue;
    const cur = [...((out.run_if || {})[lv] || [])];
    for (const x of b) if (!a.includes(x) && !cur.includes(x)) { cur.push(x); n++; }
    for (const x of a) if (!b.includes(x) && cur.includes(x)) { cur.splice(cur.indexOf(x), 1); n++; }
    out.run_if = { ...(out.run_if || {}), [lv]: cur };
    if (!cur.length) delete out.run_if[lv];
  }
  for (const k of new Set([...Object.keys(from), ...Object.keys(draft)])) {
    if (k === "labels" || k === "run_if") continue;
    if (J(from[k]) === J(draft[k])) continue;
    if (draft[k] === undefined) delete out[k]; else out[k] = clone(draft[k]);
    n++;
  }
  return { policy: out, carried: n };
}

/** The run settings the draft changed against its own base, applied onto `target`. */
export function carrySettings<T extends Record<string, unknown>>(from: Record<string, unknown> | undefined,
  draft: Record<string, unknown>, target: T): T {
  const out = clone(target) as Record<string, unknown>;
  for (const k of Object.keys(draft)) {
    if (!(k in out)) continue;
    if (from && J(from[k]) === J(draft[k])) continue;
    out[k] = clone(draft[k]);
  }
  return out as T;
}

export const samePolicy = (a?: PolicyData, b?: PolicyData) => J(a) === J(b);

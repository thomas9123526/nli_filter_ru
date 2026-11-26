// Fetch functions and types of the keyword-statistics page (/label/kwstats/): backend nli_viewer/kwstats.py.
import { API_BASE, getJSON, postJSON, query, type Params } from "./api";
import type { RunJob } from "./types";

const enc = encodeURIComponent;
const B = "/api/labels/kwstats";

export type KwRunRow = { name: string; path: string; parts: number; complete: boolean; created?: string; policy?: string;
  inputs?: string[]; lines?: number; lines_gated?: number; terms?: number; terms_hit?: number; error?: string };

export type KwReportItem = { key: string; title: string; lines: string[] };

export type KwForecast = {
  pairs_per_paragraph: { gate: number; exceptions: number; level1: number; level2: number; opening: number; low: number; high: number };
  candidate_paragraphs: number; scanned_lines: number; corpus_lines: number; scale: number; paragraphs: number;
  pairs_low: number; pairs_high: number; gpus: number; pairs_per_second: [number, number];
  hours_high: [number, number]; hours_low: [number, number]; paragraphs_per_million_lines: number };

export type KwPair = { a: string; b: string; a_id: number; b_id: number; n: number };

export type KwOverview = {
  name: string; created: string; policy: string; settings: Record<string, unknown> & { inputs?: string[]; group_by?: string; topic_field?: string | null; limit?: number | null };
  totals: Record<string, number>; hist: { hits_per_line: Record<string, number>; terms_per_line: Record<string, number> };
  dims: string[]; units: Record<string, Record<string, Record<string, number>>>;
  concentration: { top10: number; top1pct: number; top1pct_n: number; terms_hit: number; terms: number };
  forecast: KwForecast; n_terms: number; never_hit: number; lists: string[]; kinds: string[];
  duplicates: { term: string; places: string[] }[]; overlaps: { inner: string; outer: string; inner_id: number; outer_id: number }[];
  n_overlaps: number; warnings: string[]; suggest_words: { word: string; gated_lines: number; other_lines: number; lift: number }[];
  pairs: KwPair[]; pairs_total: number; files: number; report: KwReportItem[]; report_md: string; seconds?: number };

export type KwTermRow = { id: number; rank: number; term: string; kind: string; list: string; hits: number; incidental: number;
  incidental_share: number; lines: number; line_share: number; gate_lines: number; paragraphs: number; sentences: number;
  files: number; units_hit: number; co: { id: number; term: string; n: number }[] };

export type KwRankFreq = { terms: string[]; ids: number[]; hits: number[]; kind: string[]; list: number[]; lists: string[] };

export type KwHeatmap = { dim: string; depth: number; norm: string; units: string[]; unit_lines: number[]; unit_gated: number[];
  terms: { id: number; term: string; kind: string; list: string; hits: number; cells: number[] }[] };

export type KwNever = { unit: string | null; total: number; per_unit: Record<string, number>;
  rows: { id: number; term: string; kind: string; list: string; hits: number }[] };

export type KwTerm = KwTermRow & { dim: string; units: Record<string, [number, number]>; pairs: { id: number; term: string; n: number }[] };

export type KwForm = { corpora: { path: string; files: number }[]; policies: string[] };

export const kw = {
  runs: (s?: AbortSignal) => getJSON<{ runs: KwRunRow[] }>(`${B}/runs`, undefined, s),
  form: (s?: AbortSignal) => getJSON<KwForm>(`${B}/form`, undefined, s),
  overview: (run: string, p: Params, s?: AbortSignal) => getJSON<KwOverview>(`${B}/${enc(run)}`, p, s),
  rankfreq: (run: string, s?: AbortSignal) => getJSON<KwRankFreq>(`${B}/${enc(run)}/rankfreq`, undefined, s),
  terms: (run: string, p: Params, s?: AbortSignal) => getJSON<{ total: number; offset: number; rows: KwTermRow[] }>(`${B}/${enc(run)}/terms`, p, s),
  term: (run: string, id: number, p: Params, s?: AbortSignal) => getJSON<KwTerm>(`${B}/${enc(run)}/term/${id}`, p, s),
  heatmap: (run: string, p: Params, s?: AbortSignal) => getJSON<KwHeatmap>(`${B}/${enc(run)}/heatmap`, p, s),
  never: (run: string, p: Params, s?: AbortSignal) => getJSON<KwNever>(`${B}/${enc(run)}/never`, p, s),
  pairs: (run: string, p: Params, s?: AbortSignal) => getJSON<{ total_pairs: number; stored: number; rows: KwPair[] }>(`${B}/${enc(run)}/pairs`, p, s),
  start: (body: { corpus?: string; policy?: string; output_dir?: string; topic_field?: string; group_by?: string; limit?: number | null; args?: string[] }) =>
    postJSON<{ job: RunJob; run: string; args: string[] }>(`${B}/start`, body),
  /** A download link (CSV / report.md) for an <a href>. */
  url: (run: string, path: string, p: Params = {}) => `${API_BASE}${B}/${enc(run)}${path}${query(p)}`,
};

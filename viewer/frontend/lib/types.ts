// Shapes of the nli_viewer API responses (see viewer/backend/nli_viewer/api.py, /docs).

export type DatasetInfo = {
  name: string;
  title: string;
  description: string;
  corpus: string;
  output: string;
  error: string | null;
};

export type Totals = {
  lines: number;
  decisions: Record<string, number>;
  reasons: Record<string, number>;
  rules: Record<string, number>;
  hits: number;
  check1_windows: number;
  check2_hits: number;
};

export type Evaluation = {
  n: number;
  tp: number;
  fp: number;
  tn: number;
  fn: number;
  accuracy: number;
  precision: number | null;
  recall: number | null;
  f1: number | null;
  by_group: Record<string, { tp: number; fp: number; tn: number; fn: number }>;
};

export type ModelInfo = { model: string; mode?: string; devices?: string[]; dtype?: string; max_length?: number };

export type RunInfo = {
  country?: { name: string; adj: string; keywords?: string[]; exclude_patterns?: string[] };
  hypotheses?: { check1: Record<string, string>; check2: Record<string, string> };
  settings?: Record<string, unknown> & {
    check1_threshold?: number;
    check2_threshold?: number;
    uncertain_band?: [number, number];
  };
  models?: { fast?: ModelInfo; judge?: ModelInfo | null };
  timing?: Record<string, number>;
  command?: string;
  finished?: string;
};

export type Overview = {
  name: string;
  title: string;
  description: string;
  corpus: string;
  output: string;
  files: number;
  files_complete: number;
  files_without_corpus: string[];
  totals: Totals;
  evaluation: Evaluation | null;
  run: RunInfo | null;
  runs: { file: string; finished?: string; command?: string; lines?: number }[];
};

export type FileRow = {
  key: string;
  input: string;
  corpus_path: string | null;
  decisions_path: string | null;
  complete: boolean;
  lines: number;
  filtered: number;
  kept: number;
  reasons: Record<string, number>;
  seconds: number | null;
  accuracy: number | null;
  mistakes: number | null;
};

export type DecisionRow = {
  row: number;
  line: number;
  source: string | null;
  id: string | null;
  decision: "filter" | "keep";
  reason: string;
  c1: number | null;
  judged: boolean | null;
  hits: number;
  kws: string[];
  rules: string[];
  c2: number | null;
  expect: string | null;
  ok: boolean | null;
};

export type Facets = {
  total: number;
  decisions: Record<string, number>;
  reasons: Record<string, number>;
  labelled: number;
  mismatches: number;
  judged: number;
  keywords: Record<string, number>;
};

export type DecisionsResp = {
  total: number;
  offset: number;
  limit: number;
  rows: DecisionRow[];
  facets: Facets;
  file: FileRow;
  thresholds: { check1: number; check2: number; band: [number, number] | null };
};

export type Mark = {
  id: number;
  kind: "hit" | "check1_window" | "check2_window";
  start: number;
  end: number;
  hit?: number;
  kw?: string;
  state?: "rule" | "incidental" | "about" | "open";
  rule?: string | null;
  check2?: Check2 | null;
  best?: boolean;
};

export type Check2 = {
  window: [number, number];
  hyp: string;
  fast: number | null;
  judge: number | null;
  score: number | null;
  incidental: boolean;
};

export type Segment = { start: number; end: number; text?: string; marks?: number[]; gap?: number };

export type Check1Row = {
  window: [number, number];
  window_mark: number | null;
  hyp: string;
  hypothesis: string | null;
  fast: number | null;
  judge: number | null;
  score: number | null;
  judged: boolean;
  passed: boolean;
  window_text: string | null;
};

export type Check2Row = {
  hit: number;
  hit_mark: number;
  kw: string;
  span: [number, number];
  window: [number, number];
  hyp: string;
  hypothesis: string | null;
  fast: number | null;
  judge: number | null;
  score: number | null;
  judged: boolean;
  incidental: boolean;
  window_text: string | null;
};

export type Explanation = {
  text_available: boolean;
  text_length: number | null;
  excerpted: boolean;
  marks: Mark[];
  segments: Segment[];
  check1: { threshold: number; positive: boolean; score: number; rows: Check1Row[] } | null;
  check2: { threshold: number; rows: Check2Row[]; all_incidental: boolean } | null;
  verdict: { decision: string; reason: string; summary: string; steps: string[] };
  expect: { value: string; correct: boolean } | null;
  models: {
    fast: string | null;
    judge: string | null;
    band: [number, number] | null;
    check1_threshold: number;
    check2_threshold: number;
    fast_info?: ModelInfo | null;
    judge_info?: ModelInfo | null;
  };
};

export type RecordResp = {
  dataset: string;
  file: string;
  row: number;
  line: number;
  decision: Record<string, unknown> & { id?: string; decision: string; reason: string; source?: string };
  original: {
    available: boolean;
    path: string | null;
    member?: string | null;
    raw?: string;
    raw_truncated?: boolean;
    record?: Record<string, unknown>;
    id?: unknown;
    fields?: string[];
    error?: string;
  };
  text_field: string;
  id_check: { decision_id: unknown; original_id: unknown; match: boolean };
  explanation: Explanation;
  nav: {
    prev: number | null;
    next: number | null;
    prev_match: number | null;
    next_match: number | null;
    position: number | null;
    matches: number | null;
  };
  files: { corpus: string | null; decisions: string | null; summary: string };
};

export type FindMatch = DecisionRow & { file: string };

export type SimMetrics = { tp: number; fp: number; tn: number; fn: number; n: number; accuracy: number; precision: number | null; recall: number | null; f1: number | null } | null;
export type SimCounts = { filter: number; keep: number; to_filter: number; to_keep: number; estimated: number };
export type SimResp = {
  lines: number;
  current: { check1: number; check2: number; counts: SimCounts; metrics: SimMetrics };
  simulated: { check1: number; check2: number; counts: SimCounts; metrics: SimMetrics };
  flips: { file: string; row: number; line: number; id: string | null; from: string; to: string; reason: string; c1: number | null; c2: number | null; estimated: boolean; expect: string | null }[];
  flips_truncated: boolean;
  band: [number, number] | null;
  sweep: { check1: number; check2: number; filter: number; estimated: number; metrics: SimMetrics }[];
};

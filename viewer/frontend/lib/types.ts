// Shapes of the nli_viewer API responses (see viewer/backend/nli_viewer/api.py, /docs).

export type DatasetInfo = {
  name: string;
  title: string;
  description: string;
  corpus: string;
  output: string;
  error: string | null;
  editable?: boolean;
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
  output_ready?: boolean; // false: the output folder does not exist yet (corpus only)
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
  // every check-2 hypothesis on this hit's sentence (decisions written since 2026-11-17; older: empty)
  pairs?: { hyp: string; hypothesis: string | null; fast: number | null; judge: number | null; score: number | null; judged: boolean; best: boolean }[];
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
    line?: number | null;         // where the line is now in the corpus file (null = deleted in the viewer)
    raw?: string;
    raw_truncated?: boolean;
    record?: Record<string, unknown>;
    id?: unknown;
    fields?: string[];
    error?: string;
  };
  text_field: string;
  edit?: EditInfo;
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

// ---- corpus editing ----

export type EditInfo = {
  editable: boolean;
  problem: string | null;
  path: string | null;
  member?: string | null;       // .zip / .rar: the member file the line is in
  line: number | null;
  text: string | null;          // current text of the line
  sha1?: string;                // sha1 of the current line (sent back on save: conflict check)
  edits: number;                // all edits of this line
  edited_after_filter: boolean; // edited after the decisions file was written
  decision_line?: number | null; // the line number in the decisions file
  moved?: boolean;              // lines inserted / deleted above it in the viewer moved it
  edits_after_filter?: number;
  filtered_text: string | null; // the text the filter run saw (highlights and scores belong to it)
  last_edit?: string;
};

export type EditEntry = {
  edit: string;
  kind?: "text" | "insert" | "delete";
  current_line?: number | null; // where the line is now (inserts / deletes move lines); null = deleted
  time: string;
  file: string;
  line: number;
  id: unknown;
  field: string;
  old: string;
  new: string;
  undo_of?: string;
  // other fields changed by this edit: name -> old / new value (added: not there before, removed: dropped)
  fields?: Record<string, { old: unknown; new: unknown; added?: boolean; removed?: boolean }>;
};

/** One line's change in an edit-batch save: new text and / or other fields (the id cannot change). */
export type LineChange = { line: number; sha1: string; text?: string; fields?: Record<string, unknown>; remove?: string[] };

export type LineState = {
  path: string;
  member?: string | null;
  line: number;
  raw: string;
  sha1: string;
  text_field: string;
  text: string | null;
  id: unknown;
  error?: string;
};

export type EditResp = LineState & { changed: boolean; entry?: EditEntry };

export type CorpusLine = {
  line: number;
  sha1: string;
  id: unknown;
  text: string | null;
  text_length?: number;
  truncated?: boolean;
  edits: number;
  row?: number;
  inserted?: boolean;           // added in the viewer after the filter run: no decision
  extra?: Record<string, unknown>; // the other fields (template for a new line)
  error?: string;
  raw?: string;
};

export type CorpusLines = {
  path: string;
  member: string | null;        // .zip / .rar: the member shown
  members: string[] | null;     // .zip / .rar: all readable members; null for other files
  total_lines: number;
  start: number;
  count: number;
  text_field: string;
  id_field: string;
  file_key: string | null;
  editable: boolean;
  problem: string | null;
  decisions_pending?: boolean; // decision links still being prepared (first look at a big file)
  lines: CorpusLine[];
};

export type BatchResp = { changed: number; entries: EditEntry[]; seconds: number; lines: LineState[] };

export type BrowseEntry = { name: string; path: string; is_dir: boolean; size: number | null; mtime: number | null };

export type EditStatus = { editable: boolean; problem: string | null; dataset_editable: boolean };

// ---- try settings (nli_playground.py) ----

export type HypothesesData = { description?: string; check1: Record<string, string>; check2: Record<string, string> };

export type PlaygroundInfo = {
  service: { url: string; running: boolean; fast?: string; judge?: string | null; devices?: string[]; error?: string; start?: string };
  countries: { name: string; adj: string | null }[];
  project_dir: string;
  hypotheses: { name: string; file: string; data?: HypothesesData; error?: string }[];
  builtin_hypotheses: HypothesesData;
  keywords: { name: string; file: string; text: string; count: number }[];
  can_save: boolean;
};

export type TryResult = {
  line: number;
  decision: Record<string, unknown> & { id?: string; decision: string; reason: string };
  explanation: Explanation;
  previous: { decision: string; reason: string; row: number; check1: number | null } | null;
};

export type PlaygroundRun = {
  results: TryResult[];
  seconds: number;
  pairs: { fast: number; judge: number };
  keywords: string[];
  country: { name: string; adj: string };
  hypotheses: { check1: Record<string, string>; check2: Record<string, string> };
  previous_pending: boolean;
};

// ---- run nli_filter.py (started by nli_playground.py) ----

export type RunJob = {
  id: string; label: string; args: string[]; state: "running" | "done" | "failed" | "stopped";
  returncode: number | null; started: string; ended: string | null; seconds: number;
  output: string[]; output_lines: number; log_file: string;
};

export type RunDefaults = {
  args: string[]; command: string; env_names: string[]; notes: string[]; problems: string[];
  output_dir: string | null; last_command: string | null;
  service: { running: boolean; error?: string; python?: string; project_dir?: string; models?: boolean; url: string };
};

// ---- runs in progress (OUTPUT/progress/<run>.json written by nli_filter.py) ----

export type RunProgress = {
  run_id: string; state: "running" | "done" | "failed" | "stopped"; stale: boolean; age_seconds: number | null;
  every_seconds?: number; stale_after?: number;
  host: string; pid: number; shard?: string | null; command?: string; started: string; ended?: string;
  seconds?: number; files_total?: number; files_needed?: number; files_done?: number; files_skipped?: number;
  files_failed?: number; bytes_total?: number; bytes_done?: number; percent?: number | null; lines?: number;
  lines_per_second?: number | null; eta_seconds?: number | null; current?: { input: string; size: number } | null;
  error?: string;
};

export type ProgressResp = {
  runs: RunProgress[];
  combined: { runs: number; percent: number | null; files_done: number; files_needed: number; lines: number;
    lines_per_second: number; eta_seconds: number | null; bytes_total: number; bytes_done: number } | null;
  stale_seconds: number;
};

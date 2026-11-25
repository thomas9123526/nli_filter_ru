// Shapes of the nli_viewer API responses (see viewer/backend/nli_viewer/api.py, /docs).

export type DatasetInfo = {
  auto?: boolean;      // found in auto_datasets (the most recent run for its corpus), not written in the config
  label_run?: string;  // the output is an nli_label.py run: its name on the Labels pages
  modified?: number | null;  // when a local output folder last changed (unix seconds); null for remote outputs
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
  label_run?: string;
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
  audit?: string | null;   // level-A audit: what the rules / models would decide
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
  state?: "rule" | "incidental" | "about" | "open" | "strict";
  level?: "A" | "B";
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
  // level-A line run for the audit: what the rules / models would decide (the decision stays filter)
  audit?: { decision: string; reason: string; check1: number | null; check1_hyp: string | null; check2: number | null; rules: string[] } | null;
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

// ---- review tools ----

export type KeywordFlag = { kind: "unused" | "noisy" | "rules" | "wrong" | "broad" | "no_audit"; text: string };
export type KeywordStat = {
  keyword: string; level: "A" | "B"; type: string | null; gloss: string | null; other: string[]; exclude: string[];
  in_list: boolean; hits: number; lines: number; filter: number; keep: number;
  rule_hits: number; incidental_hits: number; about_hits: number; strict_hits: number; open_hits: number;
  labelled: number; wrong: number; only_lines: number; only_filter: number; audited: number; audit_keep: number;
  reasons: Record<string, number>; flags: KeywordFlag[];
};
export type KeywordStatsResp = { keywords: KeywordStat[]; files: number; pending: number };
export type LineRow = DecisionRow & { file: string; golden?: string | null };
export type LinesResp = {
  total: number; offset: number; limit: number; rows: LineRow[]; pending: number;
  thresholds: { check1: number; check2: number };
};
export type GoldenSummary = { path: string; count: number; expect: Record<string, number>; labels: Record<string, string> };

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

// check1_types / check2_types: hypotheses built from the matched keyword: keyword type ("region", "*", "@other")
// -> key -> template with {kw}, {gloss} (and {other} under "@other")
export type TypeHyps = Record<string, Record<string, string>>;
export type HypothesesData = {
  description?: string; check1: Record<string, string>; check2: Record<string, string>;
  check1_types?: TypeHyps; check2_types?: TypeHyps;
};

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
  hypotheses: { check1: Record<string, string>; check2: Record<string, string>; check1_types?: TypeHyps; check2_types?: TypeHyps };
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

// ---- nli_label.py runs (Labels pages) ----

export type LabelProgress = {
  state: "running" | "done" | "failed" | "stale"; command: string; started: string; updated: string;
  files_total: number; files_done: number; lines_done: number; seconds: number;
  current_file?: string; current_lines?: number; note?: string;
};
export type LabelRunRow = {
  name: string; finished: string | null; command: string | null; policy: string | null; lines: number | null;
  tokens: number | null; tokens_removed: number | null; docs: Record<string, number>; redecided: boolean;
  progress: LabelProgress | null; mode?: "detail" | "simple"; unit?: "paragraph" | "line";
};
export type LabelPolicyLabel = { level: number; decision: string; threshold: number; hypothesis: string; softens?: string[]; note?: string };
export type LabelStats = {
  lines: number; tokens: number; tokens_removed: number; docs: Record<string, number>; doc_tokens: Record<string, number>;
  paragraphs: Record<string, number>; paragraph_tokens: Record<string, number>; reasons: Record<string, number>;
  label_paragraphs: Record<string, number>; label_tokens: Record<string, number>; flags: Record<string, number>;
  rewrites: number; rewrite_names: Record<string, number>;
};
export type LabelRunResp = {
  name: string; progress: LabelProgress | null;
  files: { name: string; input: string | null; lines: number | null; docs: Record<string, number> | null; seconds: number | null }[];
  summary: { finished?: string; command?: string; stats?: LabelStats; settings?: Record<string, unknown>;
             policy?: { path?: string; labels?: Record<string, LabelPolicyLabel>; conflict?: string };
             redecide?: { from?: string; stored: number; missing: number; changed: string[] } };
};
export type ExpectVerdict = {
  kind: "text" | "document"; expected: string; acceptable: string[]; got: string; ok: boolean; note: string;
  paragraphs?: { span: [number, number]; expected: string; acceptable: string[]; note: string; got: string; ok: boolean }[];
};
export type LabelDocRow = {
  line: number; id: string | null; action: string; labels: string[]; flags: string[]; tokens: number;
  tokens_removed: number | null; paragraphs: Record<string, number>; rewrites: number; keywords: string[];
  expect?: ExpectVerdict;
};
export type LabelDocsResp = { rows: LabelDocRow[]; total: number; counts: Record<string, number>; offset: number; limit: number;
  expected?: { n: number; ok: number } };
export type ExpectedSummary = { n: number; ok: number; wrong: { file: string; line: number; id: string | null; expected: string;
  acceptable: string[]; got: string; note: string; paragraphs_wrong: number }[] } | null;
export type LabelParagraph = {
  span: [number, number]; action: string; reason: string; labels: string[]; scores: Record<string, number>;
  tokens: number; marker?: boolean; flags?: string[]; judged?: string[]; levels?: number[]; opened_by?: string[];
  exception?: string; action_before?: string; exception_phrases?: string[]; exception_blocked?: string;
  exception_scores?: Record<string, number>; from_field?: string[];
  non_english?: { term: string; kind: "keyword" | "marker"; script: string }[];
};
export type LabelDocResp = {
  name: string; file: string; input: string | null; text: string | null; problem: string | null;
  row: { line: number; id?: string; gate?: boolean; action: string; hits?: { kw: string; span: [number, number]; rule?: string }[];
         markers?: string[]; paragraphs?: LabelParagraph[]; labels?: string[]; flags?: string[]; tokens: number;
         tokens_removed?: number; rewrites?: number; error?: string;
         decision?: string; reason?: string; decided_by?: number };
  policy: FlowPolicyData;
  policy_path?: string | null;
  settings: Record<string, unknown>;
  expect?: ExpectVerdict;
  clean?: { available: boolean; review_as: string; dropped?: boolean; text?: string | null; problem?: string;
    rewrites?: { start: number; end: number; old: string; new: string }[] };
};

export type PolicyExceptionInfo = { key: string; decision: string; priority: number; scope: string; phrases?: string[];
  hypothesis?: string; threshold?: number; skip_quoted?: boolean; note?: string };
export type FlowPolicyData = { labels: Record<string, LabelPolicyLabel>; run_if: Record<string, string[]>; conflict?: string;
  exceptions?: PolicyExceptionInfo[]; topic?: { field: string | null; mode: string; map: Record<string, string[]> } };

// ---- policy Try page (labels/cases_v1.json, POST /api/labels/try) ----

export type LabelCaseText = { text: string; from: string; labels_yes: string[]; expected_action: string | null; note: string;
  acceptable?: string[]; your_decision?: string; topic?: string };
export type LabelCase = {
  id: string; group: string; label: string | null; title: string; what: string;
  hypothesis?: string; decision?: string; texts: LabelCaseText[];
};
export type LabelCasesResp = { version: number; created: string; about: string; policy: string; file: string; cases: LabelCase[];
  sha?: string; corpus?: string; edited?: string };
export type SaveCasesResp = { file: string; sha: string; backup: string; cases: number; texts: number;
  corpus: { path: string; files: number; lines: number } | null };
export type LabelLineResult = { line: number; text: string; row: LabelDocResp["row"]; clean: string | null;
  rewrites: { start: number; old: string; new: string }[] };
export type LabelLinesResp = { results: LabelLineResult[]; skipped: { line: number; why: string }[]; seconds: number;
  pairs: { fast: number; judge: number }; models: { fast: string; judge: string | null } | null; policy: FlowPolicyData | null };
export type LabelTryResp = {
  rows: LabelDocResp["row"][]; clean: (string | null)[]; rewrites: { start: number; old: string; new: string }[][];
  seconds: number; pairs: { fast: number; judge: number }; models: { fast: string; judge: string | null };
  policy: FlowPolicyData;
};

// ---- policy editor (/label/policy, GET /api/labels/policy/raw, POST …/check, …/save) ----
// The policy JSON as nli_label.py reads it; fields the editor does not know are kept as they are.
export type PolicyLabelData = { level: number; decision: string; threshold?: number; hypothesis: string; softens?: string[];
  protected?: boolean; note?: string; [k: string]: unknown };
export type PolicyExceptionData = { key: string; decision: string; priority?: number; scope?: string; skip_quoted?: boolean;
  match?: { phrases?: string[]; hypothesis?: string; threshold?: number }; note?: string; [k: string]: unknown };
export type PolicyData = { about?: string; version?: number; country?: string; keywords_file?: string | string[] | null;
  company_names_file?: string | null; rewrite_place_names?: boolean; place_names_file?: string | null;
  place_name_exceptions_file?: string | null; markers?: string[]; paragraphs?: { min_chars?: number; max_chars?: number };
  conflict?: string; no_subject?: string; narrative_opens_gate?: boolean; narrative_keywords?: string[];
  exceptions?: PolicyExceptionData[]; topic_field?: string | null; topic_mode?: string; topic_map?: Record<string, string | string[]>;
  labels: Record<string, PolicyLabelData>; run_if?: Record<string, string[]>; [k: string]: unknown };
export type PolicyCheck = { ok: boolean; errors: string[]; warnings: string[]; summary: Record<string, unknown> | null };
export type PolicyRawResp = { path: string; data: PolicyData; sha: string; check: PolicyCheck };

// ---- output modes: config editors (/label/output, /label/non-english), simple-mode runs ----
export type ConfigCheck = { ok: boolean; errors: string[]; info: Record<string, unknown> };
export type ConfigRawResp = { path: string; data: Record<string, unknown>; sha: string; check: ConfigCheck };
export type SchemaField = { name: string; from: string };
export type SchemaData = { about?: string; file?: string; include?: string[]; omit_empty?: boolean; evidence?: string;
  fields: SchemaField[]; reason_text?: Record<string, string>; [k: string]: unknown };
export type NonEnglishData = { about?: string; scripts: Record<string, { enabled: boolean; ranges: string[] }>;
  keywords?: string; markers?: string; score_when_removed?: boolean; [k: string]: unknown };
export type SchemaPreviewResp = { run: string; file: string; files: string[]; rows: Record<string, unknown>[];
  read: number; included: number; evidence_rows: number; unit: string };
export type SimpleRowsResp = { file: string; total: number; offset: number; limit: number;
  rows: { row: Record<string, unknown>; line: number | null; decision: string | null; reason: string | null; keywords: Record<string, number> }[];
  counts: { decision: Record<string, number>; reason: Record<string, number>; keyword: Record<string, number> };
  fields: Record<string, string>; evidence: string; can_open: boolean; unit: string };
export type SimpleLineResp = { name: string; file: string; line: number; input: string | null; text: string | null;
  problem: string | null; row: Record<string, unknown> | null; evidence: (LabelDocResp["row"] & { decision?: string }) | null;
  hits: { start: number; end: number; kw: string | null; marker?: boolean }[]; policy: FlowPolicyData;
  policy_data: PolicyData | null; policy_path: string | null; settings: Record<string, unknown> };

// ---- comparing two runs (/label/compare, GET /api/labels/compare) ----
export type CompareParagraph = { action: string; reason: string; labels: string[]; exception?: string } | null;
export type CompareItem = { file: string; line: number; id?: string | null; doc: { a: string; b: string };
  paragraphs: { span: [number, number]; move: string; a: CompareParagraph; b: CompareParagraph }[] };
export type CompareResp = {
  a: string; b: string; files: number; only_a: string[]; only_b: string[]; notes: string[];
  policy: { a: string | null; b: string | null }; redecide: { a: { from?: string } | null; b: { from?: string } | null };
  lines: number; changed_lines: number;
  totals: { a: { docs: Record<string, number>; paragraphs: Record<string, number> }; b: { docs: Record<string, number>; paragraphs: Record<string, number> } };
  paragraph_moves: Record<string, number>; doc_moves: Record<string, number>;
  total: number; offset: number; items: CompareItem[];
};

"use client";
// "Try settings": run nli_filter.py's decision on the lines of this page with other keywords / hypotheses /
// thresholds, through the model service nli_playground.py. Hypothesis files (hypotheses/*.json) and keyword
// files (keywords/*.txt) are shared with nli_filter.py and can be saved from here.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, useApi } from "@/lib/api";
import type { HypothesesData, PlaygroundInfo, PlaygroundRun, TryResult, TypeHyps } from "@/lib/types";
import { KeywordsEditor } from "./KeywordsEditor";
import { CopyButton, ErrorBox } from "./ui";

export type TrySettings = {
  country: string; adj: string;
  kwFile: string; keywords: string;
  hypFile: string; hyp: HypothesesData;
  useJudge: boolean; check1: number; check2: number; bandLo: number; bandHi: number;
  maxWindows: number; earlyStop1: boolean; earlyStop2: boolean; rules: boolean;
  strictRules: boolean;  // rules may clear a level-A hit (default off: A is absolute)
  auditA: boolean;       // also run level-A lines through the rules / models (shown, decision unchanged)
  // the file text the copy above started from: a copy not edited since follows the file when it changes on disk
  kwBase?: string; hypBase?: string;
};

const STORE = "nli-viewer-try-settings";
export const BUILTIN = "(built-in)";

function load(): Partial<TrySettings> {
  try {
    return JSON.parse(localStorage.getItem(STORE) || "{}");
  } catch {
    return {};
  }
}

/**
 * The "Try settings" of this browser, shared by the corpus page (try on a few lines) and the Run filter page
 * (run on the whole dataset). First use: Russia + keywords/russia.txt + hypotheses/russia.json if they exist.
 */
export function useTrySettings(info: PlaygroundInfo | null | undefined): [TrySettings | null, (p: Partial<TrySettings>) => void] {
  const [st, setSt] = useState<TrySettings | null>(null);
  const set = useCallback((p: Partial<TrySettings>) => setSt((s) => (s ? { ...s, ...p } : s)), []);
  useEffect(() => {
    if (!info || st) return;
    const saved = load();
    const country = saved.country || "Russia";
    const adj = saved.adj || info.countries.find((c) => c.name === country)?.adj || "";
    const kw = info.keywords.find((k) => k.name === (saved.kwFile || country.toLowerCase()));
    const hf = info.hypotheses.find((h) => h.name === (saved.hypFile || country.toLowerCase()) && h.data);
    setSt({
      country, adj,
      kwFile: kw ? kw.name : BUILTIN, keywords: saved.keywords ?? (kw ? kw.text : ""),
      hypFile: hf ? hf.name : BUILTIN, hyp: saved.hyp || (hf?.data as HypothesesData) || info.builtin_hypotheses,
      useJudge: saved.useJudge ?? true, check1: saved.check1 ?? 0.8, check2: saved.check2 ?? 0.8,
      bandLo: saved.bandLo ?? 0.6, bandHi: saved.bandHi ?? 0.95, maxWindows: saved.maxWindows ?? 2,
      // earlyStop: one switch for both checks before 2026-11-17
      earlyStop1: saved.earlyStop1 ?? (saved as { earlyStop?: boolean }).earlyStop ?? true,
      earlyStop2: saved.earlyStop2 ?? (saved as { earlyStop?: boolean }).earlyStop ?? true, rules: saved.rules ?? true,
      strictRules: saved.strictRules ?? false, auditA: saved.auditA ?? false,
      kwBase: saved.kwBase ?? (saved.keywords === undefined && kw ? kw.text : undefined),
      hypBase: saved.hypBase ?? (saved.hyp === undefined && hf ? JSON.stringify(hf.data) : undefined),
    });
  }, [info, st]);
  // the files changed on disk (saved elsewhere, edited in an editor): a copy that was not edited here follows them
  useEffect(() => {
    if (!info || !st) return;
    const p: Partial<TrySettings> = {};
    const kw = info.keywords.find((k) => k.name === st.kwFile);
    if (kw && st.kwBase !== undefined && sameText(st.keywords, st.kwBase) && !sameText(kw.text, st.kwBase)) {
      p.keywords = kw.text; p.kwBase = kw.text;
    }
    const hf = info.hypotheses.find((h) => h.name === st.hypFile && h.data);
    if (hf && st.hypBase !== undefined && JSON.stringify(st.hyp) === st.hypBase && JSON.stringify(hf.data) !== st.hypBase) {
      p.hyp = hf.data as HypothesesData; p.hypBase = JSON.stringify(hf.data);
    }
    if (Object.keys(p).length) set(p);
  }, [info]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!st) return;
    try { localStorage.setItem(STORE, JSON.stringify(st)); } catch { /* storage off: fine */ }
  }, [st]);
  return [st, set];
}

const noEmpty = (t: TypeHyps | undefined) => (t && Object.keys(t).length ? t : undefined);
const sameHyp = (a: HypothesesData | undefined, b: HypothesesData | undefined) =>
  JSON.stringify({ c1: a?.check1, c2: a?.check2, t1: noEmpty(a?.check1_types), t2: noEmpty(a?.check2_types) })
  === JSON.stringify({ c1: b?.check1, c2: b?.check2, t1: noEmpty(b?.check1_types), t2: noEmpty(b?.check2_types) });
const sameText = (a: string, b: string) => a.replace(/\r\n/g, "\n").trim() === b.replace(/\r\n/g, "\n").trim();

/**
 * nli_filter.py options for these settings. A run reads keywords and hypotheses from files, so edits not yet
 * saved with "Save" are not in the run: they come back as warnings. `judge` false = --judge-model none.
 */
export function settingsToArgs(st: TrySettings, info: PlaygroundInfo): { args: string[]; judge: boolean; warnings: string[] } {
  const args = ["--country", st.country];
  if (st.adj) args.push("--country-adj", st.adj);
  const warnings: string[] = [];
  const kw = info.keywords.find((k) => k.name === st.kwFile);
  if (kw) {
    args.push("--keywords-file", `keywords/${kw.file}`);
    if (!sameText(kw.text, st.keywords)) warnings.push(`the keywords were changed but not saved: the run uses keywords/${kw.file} as saved (Save them first)`);
  } else if (st.keywords.trim()) {
    warnings.push("the keyword list is not saved in a file: the run uses the country's default list (Save it first)");
  }
  const hf = info.hypotheses.find((h) => h.name === st.hypFile);
  if (hf) {
    args.push("--hypotheses-file", `hypotheses/${hf.file}`);
    if (!sameHyp(hf.data as HypothesesData, st.hyp)) warnings.push(`the hypotheses were changed but not saved: the run uses hypotheses/${hf.file} as saved (Save them first)`);
  } else {
    args.push("--hypotheses-file", "hypotheses/default.json");
    if (!sameHyp(info.builtin_hypotheses, st.hyp)) warnings.push("the hypotheses were changed but not saved: the run uses hypotheses/default.json (Save them first)");
  }
  args.push("--check1-threshold", String(st.check1), "--check2-threshold", String(st.check2),
    "--uncertain-band", String(st.bandLo), String(st.bandHi), "--max-windows", String(st.maxWindows));
  if (!st.earlyStop1) args.push("--no-check1-early-stop");
  if (!st.earlyStop2) args.push("--no-check2-early-stop");
  if (!st.rules) args.push("--no-rules");
  if (st.rules && st.strictRules) args.push("--strict-rules");
  if (!st.useJudge) args.push("--judge-model", "none");
  return { args, judge: st.useJudge, warnings };
}

export type TryControl = { run: () => void; ready: boolean; running: boolean; count: number };

/** What the page knows about a line (for the copied report). */
export type LineInfo = { id: unknown; text: string | null; length?: number; extra?: Record<string, unknown> };

const f3 = (x: number | null | undefined) => (typeof x === "number" ? x.toFixed(3) : "–");

/**
 * The settings and the results of the last Try run as plain text (Markdown), to paste into a chat or a ticket:
 * everything needed to understand why each line got its decision, without the browser.
 */
export function tryReport(ds: string, path: string, member: string | null, st: TrySettings, info: PlaygroundInfo,
                          run: PlaygroundRun, lines: Record<number, LineInfo>): string {
  const kw = info.keywords.find((k) => k.name === st.kwFile);
  const hf = info.hypotheses.find((h) => h.name === st.hypFile);
  const kwCount = st.keywords.split("\n").filter((l) => l.trim() && !l.trim().startsWith("#")).length;
  const kwState = kw ? (sameText(kw.text, st.keywords) ? "as saved" : "CHANGED, not saved") : st.keywords.trim() ? "typed in, not saved" : "built-in list";
  const hypState = sameHyp(hf ? (hf.data as HypothesesData) : info.builtin_hypotheses, st.hyp) ? "as saved" : "CHANGED, not saved";
  const out: string[] = [];
  out.push(`## Try settings result`, "");
  out.push(`- page: dataset \`${ds}\`, file \`${path}\`${member ? ` (member \`${member}\`)` : ""}, lines ${run.results.map((r) => r.line).join(", ")}`);
  out.push(`- country: ${st.country} / ${st.adj || "(no adjective)"}`);
  out.push(`- keywords: ${kw ? `keywords/${kw.file}` : "(built-in)"}, ${kwCount} keyword(s), ${kwState}`);
  out.push(`- hypotheses: ${hf ? `hypotheses/${hf.file}` : "(built-in) = hypotheses/default.json"}, ${hypState}`);
  out.push(`- judge ${st.useJudge ? "on" : "off"}, band ${st.bandLo}–${st.bandHi}, check 1 ≥ ${st.check1}, check 2 ≥ ${st.check2}, `
    + `windows ${st.maxWindows || "all (0)"}, early stop check 1 ${st.earlyStop1 ? "on" : "off"} / check 2 ${st.earlyStop2 ? "on" : "off"}, rules ${st.rules ? "on" : "off"}${st.rules && st.strictRules ? " (also for level A)" : ""}${st.auditA ? ", audit of level-A lines on" : ""}`);
  const m = run.results[0]?.explanation.models;
  out.push(`- models: fast ${m?.fast || "?"}${st.useJudge ? `, judge ${m?.judge || "?"}` : ""}; ${run.seconds.toFixed(1)} s, `
    + `pairs fast ${run.pairs.fast} / judge ${run.pairs.judge}`);
  if (kw && kwState !== "as saved" || !kw) {
    out.push("", "Keywords used:", "```", st.keywords.trim() || "(empty: the built-in list of the country)", "```");
  }
  out.push("", "Check 1 hypotheses (is the text about the country?):");
  for (const [k, v] of Object.entries(st.hyp.check1)) out.push(`- \`${k}\`: ${v}`);
  out.push("", "Check 2 hypotheses (is a hit only incidental?):");
  const c2 = Object.entries(st.hyp.check2 || {});
  if (!c2.length) out.push("- (none: no check 2)");
  for (const [k, v] of c2) out.push(`- \`${k}\`: ${v}`);
  for (const [label, t] of [["Check 1", st.hyp.check1_types], ["Check 2", st.hyp.check2_types]] as const) {
    const rows = Object.entries(t || {}).flatMap(([typ, h]) => Object.entries(h).map(([k, v]) => `- \`${typ}\` \`${k}\`: ${v}`));
    if (rows.length) out.push("", `${label} hypotheses built from the matched keyword (type → template):`, ...rows);
  }
  for (const r of run.results) {
    const li = lines[r.line];
    const ex = r.explanation;
    const expect = li?.extra?.expect ?? ex.expect?.value;
    out.push("", `### line ${r.line} · id ${li ? JSON.stringify(li.id) : "?"}${expect !== undefined ? ` · expect ${String(expect)}` : ""}`);
    const t = li?.text ?? null;
    if (t !== null) {
      const n = li?.length ?? t.length;
      out.push(`text (${n.toLocaleString("en-US")} chars): "${t.slice(0, 400).replace(/\s+/g, " ")}${n > 400 || t.length > 400 ? " …" : ""}"`);
    }
    const others = Object.entries(li?.extra || {}).filter(([k]) => k !== "expect");
    if (others.length) out.push(`other fields: ${others.map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ")}`);
    out.push(`**try: ${r.decision.decision} (${r.decision.reason})**${r.previous ? ` · saved run: ${r.previous.decision} (${r.previous.reason})${r.previous.decision !== r.decision.decision ? " → CHANGED" : ""}` : " · no saved decision"}`
      + (ex.expect ? ` · ${ex.expect.correct ? "matches" : "does NOT match"} expect` : ""));
    out.push(`why: ${ex.verdict.summary}`);
    for (const s of ex.verdict.steps || []) out.push(`  - ${s}`);
    if (ex.check1) {
      out.push(`check 1 (≥ ${ex.check1.threshold}): best ${f3(ex.check1.score)} → ${ex.check1.positive ? "about the country" : "not about the country"}`);
      for (const c of ex.check1.rows) {
        out.push(`  - \`${c.hyp}\` chars ${c.window[0]}–${c.window[1]}: fast ${f3(c.fast)}${c.judged ? `, judge ${f3(c.judge)}` : ""} → ${f3(c.score)}${c.passed ? " ✓" : ""}`
          + (c.window_text ? ` | "${c.window_text.slice(0, 160).replace(/\s+/g, " ")}${c.window_text.length > 160 ? " …" : ""}"` : ""));
      }
    }
    const hits = ex.marks.filter((k) => k.kind === "hit");
    if (hits.length) {
      out.push(`keyword hits (${hits.length}):`);
      for (const h of hits.slice(0, 30)) {
        const rows = (ex.check2?.rows || []).filter((c) => c.hit_mark === h.id);
        const c2s = rows.map((c) => (c.pairs && c.pairs.length
          ? c.pairs.map((p) => `\`${p.hyp}\` ${p.judged ? `fast ${f3(p.fast)}, judge ${f3(p.judge)} → ` : ""}${f3(p.score)}${p.best ? " (best)" : ""}`).join(", ")
          : `\`${c.hyp}\` fast ${f3(c.fast)}${c.judged ? `, judge ${f3(c.judge)}` : ""} → ${f3(c.score)}`)
          + (c.incidental ? " → incidental" : " → not incidental")).join("; ");
        const state = { about: "not incidental", incidental: "incidental", rule: "incidental by rule",
          strict: "level-A keyword (filters the line, no model)",
          open: r.decision.reason === "strict_keyword" ? "not scored (the line is filtered by a level-A keyword)"
            : ex.check1?.positive ? "not scored (check 2 stopped early)" : "not scored (check 1 negative)" }[h.state || "open"];
        out.push(`  - "${h.kw}" chars ${h.start}–${h.end}: ${state}${h.rule ? ` (rule ${h.rule})` : ""}${c2s ? ` | check 2: ${c2s}` : ""}`);
      }
      if (hits.length > 30) out.push(`  - … ${hits.length - 30} more`);
    }
  }
  return out.join("\n") + "\n";
}

/** "1-3, 7, 9-" -> the page's lines in that selection (in page order) and the numbers / parts not usable. */
export function pickLines(spec: string, page: number[]): { lines: number[]; bad: string[] } {
  const want = new Set<number>();
  const bad: string[] = [];
  const max = page.length ? Math.max(...page) : 0;
  for (const part of spec.split(/[\s,;]+/).filter(Boolean)) {
    const m = part.match(/^(\d*)-(\d*)$/);
    const a = m ? (m[1] ? Number(m[1]) : 1) : Number(part);
    const b = m ? (m[2] ? Number(m[2]) : max) : a;
    if (!Number.isInteger(a) || !Number.isInteger(b) || a < 1 || b < a || (m && !m[1] && !m[2])) { bad.push(part); continue; }
    let found = false;
    for (const n of page) if (n >= a && n <= b) { want.add(n); found = true; }
    if (!found) bad.push(part);
  }
  return { lines: page.filter((n) => want.has(n)), bad };
}

type ScoreCell = { score: number | null; fast?: number | null; judge?: number | null; pass?: boolean };

/** One table of the run: a column per line, a row per hypothesis (best score over windows / hits). */
function scoreTable(run: PlaygroundRun, lineInfo: Record<number, LineInfo>) {
  const cols = run.results.map((r) => {
    const info = lineInfo[r.line];
    const id = info?.id ?? r.decision.id;
    const exp = info?.extra?.expect;
    const e = r.explanation;
    const c1: Record<string, ScoreCell> = {};
    for (const row of e.check1?.rows || []) {
      const old = c1[row.hyp];
      if (!old || (row.score ?? -1) > (old.score ?? -1))
        c1[row.hyp] = { score: row.score, fast: row.fast, judge: row.judged ? row.judge : null, pass: row.passed };
    }
    const c2: Record<string, ScoreCell> = {};
    for (const row of e.check2?.rows || []) {
      const pairs = row.pairs?.length ? row.pairs : [{ hyp: row.hyp, score: row.score, fast: row.fast, judge: row.judge, judged: row.judged }];
      for (const p of pairs) {
        const old = c2[p.hyp];
        if (!old || (p.score ?? -1) > (old.score ?? -1))
          c2[p.hyp] = { score: p.score, fast: p.fast, judge: p.judged ? p.judge : null, pass: (p.score ?? 0) >= (e.check2?.threshold ?? 1) };
      }
    }
    return {
      line: r.line, name: id !== null && id !== undefined && String(id) !== "" ? String(id) : `line ${r.line}`,
      decision: r.decision.decision, reason: r.decision.reason,
      strict: Array.isArray(r.decision.strict) ? (r.decision.strict as string[]) : [],
      audit: r.explanation.audit || null,
      expect: exp === null || exp === undefined || String(exp).trim() === "" ? null : String(exp).trim(),
      c1, c2, best1: e.check1 ? e.check1.score : null,
    };
  });
  // global hypotheses first, then those built from the keywords (e.g. place:Siberia), in the order they appear
  const keys = (base: string[], pick: (c: (typeof cols)[number]) => string[]) =>
    [...new Set([...base, ...cols.flatMap(pick)])];
  return { cols, h1: keys(Object.keys(run.hypotheses.check1), (c) => Object.keys(c.c1)),
    h2: keys(Object.keys(run.hypotheses.check2), (c) => Object.keys(c.c2)) };
}

function TryScores({ run, lineInfo }: { run: PlaygroundRun; lineInfo: Record<number, LineInfo> }) {
  const { cols, h1, h2 } = useMemo(() => scoreTable(run, lineInfo), [run, lineInfo]);
  if (!cols.length) return null;
  const cell = (c: ScoreCell | undefined, key: number) => {
    if (!c || c.score === null) return <td key={key} className="faint" title="not scored">–</td>;
    const tip = `fast ${f3(c.fast)}${c.judge !== null && c.judge !== undefined ? `, judge ${f3(c.judge)}` : ""}`;
    return <td key={key} className="mono" title={tip} style={c.pass ? { fontWeight: 700 } : undefined}>{f3(c.score)}{c.judge !== null && c.judge !== undefined ? <sup className="faint">j</sup> : null}</td>;
  };
  // the same table as text (tab separated: pastes into a spreadsheet or a chat)
  const tsv = [
    ["", ...cols.map((c) => c.name)],
    ["decision", ...cols.map((c) => c.decision + (c.strict.length ? ` (A: ${c.strict.join(", ")})` : ""))],
    ["expect", ...cols.map((c) => c.expect || "")],
    ...h1.map((h) => [`check1 ${h}`, ...cols.map((c) => (c.c1[h]?.score != null ? f3(c.c1[h].score) : "-"))]),
    ...h2.map((h) => [`check2 ${h}`, ...cols.map((c) => (c.c2[h]?.score != null ? f3(c.c2[h].score) : "-"))]),
  ].map((r) => r.join("\t")).join("\n") + "\n";
  return (
    <div data-testid="try-scores">
      <div className="row" style={{ marginBottom: 4 }}>
        <strong>Scores</strong>
        <span className="faint" style={{ fontSize: 12 }}>best score per hypothesis (check 1: over the windows; check 2: over the hits) · <b>bold</b> = at or above the threshold · <sup>j</sup> = decided by the judge · – = not scored</span>
        <span className="spacer" />
        <CopyButton text={tsv} label="Copy table" title="copy this table as tab-separated text" testid="try-scores-copy" />
      </div>
      <div className="table-wrap">
        <table className="try-scores">
          <thead>
            <tr><th></th>{cols.map((c) => <th key={c.line} className="mono" title={`line ${c.line}`}>{c.name}</th>)}</tr>
          </thead>
          <tbody>
            <tr><th>decision</th>{cols.map((c) => <td key={c.line} title={c.reason}><span className={`badge ${c.decision}`}>{c.decision}</span>{c.strict.length ? <div className="faint" title="level-A keyword: filtered without any model">A: {c.strict.join(", ")}</div> : null}{c.audit ? <div className={c.audit.decision === "keep" ? "bad" : "faint"} title={`audit: as B, the rules / models would ${c.audit.decision} it (${c.audit.reason})`}>audit: {c.audit.decision}</div> : null}</td>)}</tr>
            <tr><th>expect</th>{cols.map((c) => <td key={c.line}>{c.expect
              ? <span className={c.expect === c.decision ? "ok" : "bad"} title={c.expect === c.decision ? "matches" : "does not match"}>{c.expect} {c.expect === c.decision ? "✓" : "✗"}</span>
              : <span className="faint">–</span>}</td>)}</tr>
            {h1.map((h, i) => <tr key={`c1-${h}`} className={i === 0 ? "group" : undefined}><th>check 1 <span className="mono">{h}</span></th>{cols.map((c) => cell(c.c1[h], c.line))}</tr>)}
            {h2.map((h, i) => <tr key={`c2-${h}`} className={i === 0 ? "group" : undefined}><th>check 2 <span className="mono">{h}</span></th>{cols.map((c) => cell(c.c2[h], c.line))}</tr>)}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function TryPanel({ ds, path, member, lines: pageLines, onResults, onControl, lineInfo }: {
  ds: string; path: string; member: string | null; lines: number[];
  onResults: (r: PlaygroundRun | null) => void;
  onControl?: (c: TryControl) => void;  // e.g. a second Run button at the bottom of the page
  lineInfo?: Record<number, LineInfo>;  // id / text / fields of the page's lines, for "Copy for chat"
}) {
  const info = useApi("playground", (s) => api.playground(s));
  const [open, setOpen] = useState(false);
  const [st, set] = useTrySettings(info.data);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [last, setLast] = useState<PlaygroundRun | null>(null);
  // which of the page's lines to run: empty = all of them, else e.g. "1-3, 7"
  const [pick, setPick] = useState("");
  const picked = useMemo(() => (pick.trim() ? pickLines(pick, pageLines) : null), [pick, pageLines]);
  const lines = picked ? picked.lines : pageLines;
  useEffect(() => { onResults(null); setLast(null); }, [path, member]);  // eslint-disable-line react-hooks/exhaustive-deps

  async function run() {
    if (!st) return;
    setRunning(true);
    setError(null);
    try {
      const r = await api.playgroundRun(ds, {
        path, member, lines, settings: {
          country: st.country, country_adj: st.adj, keywords: st.keywords,
          check1: st.hyp.check1, check2: st.hyp.check2, use_judge: st.useJudge,
          check1_types: st.hyp.check1_types || {}, check2_types: st.hyp.check2_types || {},
          check1_threshold: st.check1, check2_threshold: st.check2, uncertain_band: [st.bandLo, st.bandHi],
          max_windows: st.maxWindows, check1_early_stop: st.earlyStop1, check2_early_stop: st.earlyStop2, rules: st.rules,
          strict_rules: st.rules && st.strictRules, audit_strict: st.auditA ? 1 : 0,
        },
      });
      setLast(r);
      onResults(r);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError((e as Error).message, 0));
    } finally {
      setRunning(false);
    }
  }

  const svc = info.data?.service;
  const ready = !!st && !!svc?.running && lines.length > 0;
  const runRef = useRef(run);
  runRef.current = run;  // the latest settings; the function handed out stays the same
  const stableRun = useCallback(() => { void runRef.current(); }, []);
  useEffect(() => { onControl?.({ run: stableRun, ready, running, count: lines.length }); },
    [ready, running, lines.length, stableRun]);  // eslint-disable-line react-hooks/exhaustive-deps
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const r of last?.results || []) c[r.decision.decision] = (c[r.decision.decision] || 0) + 1;
    return c;
  }, [last]);
  const changed = (last?.results || []).filter((r) => r.previous && r.previous.decision !== r.decision.decision).length;
  const runButton = (small: boolean) => (
    <span className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
      <button className={`btn primary${small ? " small" : ""}`} onClick={run} disabled={running || !svc?.running || !lines.length}
        title={!svc?.running ? "the model service is not running (open Try settings to see how to start it)" : undefined}
        data-testid={small ? "try-run-collapsed" : "try-run"}>
        {running ? "Running…" : picked
          ? `Run on ${lines.length} of the ${pageLines.length} lines`
          : `Run on the ${lines.length} line${lines.length === 1 ? "" : "s"} of this page`}
      </button>
      <label className="muted" title="line numbers of this page to run, e.g. 1-3, 7 or 5- (from 5 to the end); empty = every line of the page">
        lines <input type="text" className="mono" value={pick} onChange={(e) => setPick(e.target.value)} placeholder="all"
          style={{ width: 110 }} data-testid={small ? "try-lines-collapsed" : "try-lines"} />
      </label>
      {pick ? <button className="btn small ghost" onClick={() => setPick("")} title="run every line of the page">×</button> : null}
      {picked?.bad.length ? <span className="badge warn" title="not lines of this page (or not a number / range)">not on this page: {picked.bad.join(", ")}</span> : null}
    </span>
  );

  return (
    <div className="panel try-panel" data-testid="try-panel">
      <div className="row">
        <button className="btn small" onClick={() => setOpen((o) => !o)}>{open ? "▾" : "▸"} Try settings</button>
        {/* collapsed: the Run button stays reachable, with the settings last used (kept in this browser) */}
        {!open && st ? runButton(true) : null}
        <span className="muted">run the filter on these lines with other keywords / hypotheses</span>
        <span className="spacer" />
        {svc ? (svc.running
          ? <span className="badge keep" title={svc.url}>models: {svc.fast}{svc.judge ? ` + ${svc.judge}` : ""}</span>
          : <span className="badge warn" title={svc.error}>model service not running</span>) : null}
        {last ? <span className="muted">{Object.entries(counts).map(([k, v]) => `${v} ${k}`).join(", ")}{changed ? ` · ${changed} changed vs the run` : ""} · {last.seconds.toFixed(1)} s</span> : null}
        {last && st && info.data ? <CopyButton text={tryReport(ds, path, member, st, info.data, last, lineInfo || {})} label="Copy for chat"
          title="copy the settings and every line's result (scores, hits, why) as text, to paste into a chat" testid="try-copy" /> : null}
        {last ? <button className="btn small ghost" onClick={() => { setLast(null); onResults(null); }}>Clear results</button> : null}
      </div>
      <ErrorBox error={info.error} />
      {open && svc && !svc.running ? (
        <div className="alert warn">The model service is not running. Start it where the models are (in the project folder):<pre className="json">{svc.start}</pre>{svc.error}</div>
      ) : null}
      {open && st && info.data ? <Settings info={info.data} st={st} set={set} onSaved={info.reload} /> : null}
      {open && st ? (
        <div className="row">
          {runButton(false)}
          <span className="faint">results appear on each line; “was” = the decision of the saved filter run</span>
        </div>
      ) : null}
      {error ? <div className="alert warn">{error.message}</div> : null}
      {last ? <TryScores run={last} lineInfo={lineInfo || {}} /> : null}
    </div>
  );
}

export function Settings({ info, st, set, onSaved }: {
  info: PlaygroundInfo; st: TrySettings; set: (p: Partial<TrySettings>) => void; onSaved: () => void;
}) {
  const kwCount = st.keywords.split("\n").filter((l) => l.trim() && !l.trim().startsWith("#")).length;
  return (
    <div className="try-grid">
      <fieldset>
        <legend>Country</legend>
        <div className="row">
          <select value={info.countries.some((c) => c.name === st.country) ? st.country : ""}
            onChange={(e) => { const c = info.countries.find((x) => x.name === e.target.value); if (c) set({ country: c.name, adj: c.adj || "" }); }}>
            <option value="">other…</option>
            {info.countries.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
          </select>
          <input type="text" value={st.country} onChange={(e) => set({ country: e.target.value })} placeholder="country" style={{ width: 120 }} />
          <input type="text" value={st.adj} onChange={(e) => set({ adj: e.target.value })} placeholder="adjective" style={{ width: 120 }} />
        </div>
        <legend style={{ marginTop: 10 }}>Model and thresholds</legend>
        <div className="row">
          <label><input type="checkbox" checked={st.useJudge} onChange={(e) => set({ useJudge: e.target.checked })} /> judge (uncertain scores)</label>
          <label>band <input type="number" step={0.05} min={0} max={1} value={st.bandLo} onChange={(e) => set({ bandLo: Number(e.target.value) })} />–<input type="number" step={0.05} min={0} max={1} value={st.bandHi} onChange={(e) => set({ bandHi: Number(e.target.value) })} /></label>
        </div>
        <div className="row">
          <label>check 1 ≥ <input type="number" step={0.05} min={0} max={1} value={st.check1} onChange={(e) => set({ check1: Number(e.target.value) })} /></label>
          <label>check 2 ≥ <input type="number" step={0.05} min={0} max={1} value={st.check2} onChange={(e) => set({ check2: Number(e.target.value) })} /></label>
        </div>
        <div className="row">
          <label title="check-1 windows per long text (over 1,000 characters); 0 = a window around every keyword hit">windows <input type="number" min={0} max={50} value={st.maxWindows} onChange={(e) => set({ maxWindows: Math.max(0, Number(e.target.value)) })} />{st.maxWindows === 0 ? <span className="faint"> all</span> : null}</label>
        </div>
        <div className="row">
          <span className="faint">early stop:</span>
          <label title="stop at the first check-1 window that passes (same decision; off = score every window)"><input type="checkbox" checked={st.earlyStop1} onChange={(e) => set({ earlyStop1: e.target.checked })} /> check 1</label>
          <label title="stop at the first hit that is not incidental (same decision; off = score every hit's sentence)"><input type="checkbox" checked={st.earlyStop2} onChange={(e) => set({ earlyStop2: e.target.checked })} /> check 2</label>
          <label><input type="checkbox" checked={st.rules} onChange={(e) => set({ rules: e.target.checked })} /> rules</label>
          <label title="off (default): a level-A keyword filters the line, whatever the rules say. On: the rules (language menu / label / locale / company name) may mark an A hit incidental first"><input type="checkbox" checked={st.strictRules} disabled={!st.rules} onChange={(e) => set({ strictRules: e.target.checked })} /> rules apply to A</label>
          <label title="level-A lines stay filtered, but are also run through the rules and the models: shows what they would decide (is the A word too broad?)"><input type="checkbox" checked={st.auditA} onChange={(e) => set({ auditA: e.target.checked })} /> audit A</label>
        </div>
      </fieldset>
      <fieldset>
        <legend>Hypotheses</legend>
        <div className="row">
          <select value={st.hypFile} onChange={(e) => {
            const h = info.hypotheses.find((x) => x.name === e.target.value);
            const hyp = (h?.data as HypothesesData) || info.builtin_hypotheses;
            set({ hypFile: e.target.value, hyp, hypBase: JSON.stringify(hyp) });
          }}>
            <option value={BUILTIN}>{BUILTIN} = hypotheses/default.json</option>
            {info.hypotheses.map((h) => <option key={h.name} value={h.name} disabled={!h.data}>hypotheses/{h.file}{h.error ? " (error)" : ""}</option>)}
          </select>
          {(() => {
            const hf = info.hypotheses.find((h) => h.name === st.hypFile && h.data);
            return hf && !sameHyp(hf.data as HypothesesData, st.hyp) ? (
              <button className="btn small" data-testid="hyp-reload" title={`your copy differs from hypotheses/${hf.file} on disk: load the file (your changes here are dropped)`}
                onClick={() => { if (window.confirm(`Load hypotheses/${hf.file} as it is on disk? Your unsaved changes here are lost.`)) set({ hyp: hf.data as HypothesesData, hypBase: JSON.stringify(hf.data) }); }}>
                ↻ load the file</button>
            ) : null;
          })()}
        </div>
        {info.hypotheses.filter((h) => h.error).map((h) => <div key={h.name} className="alert warn">{h.file}: {h.error}</div>)}
        <input type="text" value={st.hyp.description || ""} placeholder="description" style={{ width: "100%" }}
          onChange={(e) => set({ hyp: { ...st.hyp, description: e.target.value } })} />
        <HypEditor title="Check 1 · is the text about the country?" rows={st.hyp.check1}
          onChange={(check1) => set({ hyp: { ...st.hyp, check1 } })} />
        <HypEditor title="Check 2 · is a hit only incidental? (empty = no check 2)" rows={st.hyp.check2}
          onChange={(check2) => set({ hyp: { ...st.hyp, check2 } })} />
        <TypeHypEditor check={1} types={st.hyp.check1_types || {}} onChange={(check1_types) => set({ hyp: { ...st.hyp, check1_types } })} />
        <TypeHypEditor check={2} types={st.hyp.check2_types || {}} onChange={(check2_types) => set({ hyp: { ...st.hyp, check2_types } })} />
        <div className="faint" style={{ fontSize: 12 }}>Use <span className="mono">{"{country}"}</span> and <span className="mono">{"{country_adj}"}</span>; each key = one hypothesis, the highest score counts.</div>
        <SaveBox kind="hypotheses" defaultName={st.hypFile === BUILTIN ? st.country.toLowerCase() : st.hypFile}
          save={(name, overwrite) => api.saveHypotheses({ name, data: st.hyp, overwrite })}
          onSaved={(name) => { set({ hypFile: name, hypBase: JSON.stringify(st.hyp) }); onSaved(); }} />
      </fieldset>
      <fieldset className="kw-fieldset">
        <legend>Keywords <span className="faint">({kwCount})</span></legend>
        <div className="row">
          <select value={st.kwFile} onChange={(e) => {
            const k = info.keywords.find((x) => x.name === e.target.value);
            set({ kwFile: e.target.value, keywords: k ? k.text : "", kwBase: k ? k.text : undefined });
          }}>
            <option value={BUILTIN}>{BUILTIN} for the country</option>
            {info.keywords.map((k) => <option key={k.name} value={k.name}>keywords/{k.file} ({k.count})</option>)}
          </select>
          {(() => {
            const kf = info.keywords.find((k) => k.name === st.kwFile);
            return kf && !sameText(kf.text, st.keywords) ? (
              <button className="btn small" data-testid="kw-reload" title={`your copy differs from keywords/${kf.file} on disk: load the file (your changes here are dropped)`}
                onClick={() => { if (window.confirm(`Load keywords/${kf.file} as it is on disk? Your unsaved changes here are lost.`)) set({ keywords: kf.text, kwBase: kf.text }); }}>
                ↻ load the file</button>
            ) : null;
          })()}
          <span className="faint" style={{ fontSize: 12 }}>level A = filtered without models (strict_keyword) · B = check 1 / check 2 · plan: cmds/design/keyword_lexicon_plan.md</span>
        </div>
        <KeywordsEditor text={st.keywords} onChange={(keywords) => set({ keywords })} />
        <SaveBox kind="keywords" defaultName={st.kwFile === BUILTIN ? st.country.toLowerCase() : st.kwFile}
          save={(name, overwrite) => api.saveKeywords({ name, text: st.keywords, overwrite })}
          onSaved={(name) => { set({ kwFile: name, kwBase: st.keywords }); onSaved(); }} />
      </fieldset>
    </div>
  );
}

/** Hypotheses built from the matched keyword: one row per (keyword type, key, template). */
function TypeHypEditor({ check, types, onChange }: { check: 1 | 2; types: TypeHyps; onChange: (t: TypeHyps) => void }) {
  const rows = Object.entries(types).flatMap(([typ, h]) => Object.entries(h).map(([k, v]) => ({ typ, k, v })));
  const build = (list: { typ: string; k: string; v: string }[]) => {
    const t: TypeHyps = {};
    for (const r of list) (t[r.typ] = t[r.typ] || {})[r.k] = r.v;
    onChange(t);
  };
  const edit = (i: number, p: Partial<{ typ: string; k: string; v: string }>) => build(rows.map((r, j) => (j === i ? { ...r, ...p } : r)));
  const typeHelp = check === 1
    ? "a keyword type of the lexicon (region, city, person, …) or * = every keyword"
    : "a keyword type, * = every keyword, @other = once per other meaning of the keyword ({other})";
  const example = check === 1
    ? { typ: "region", k: "place", v: "This text is about {kw}, {gloss}." }
    : rows.some((r) => r.typ === "@other")
      ? { typ: "*", k: "brand", v: "In this text, {kw} is part of a company, product or brand name." }
      : { typ: "@other", k: "sense", v: "In this text, {kw} means {other}." };
  return (
    <div className="hyp-editor" data-testid={`type-hyps-${check}`}>
      <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
        Check {check} · built from the matched keyword <span className="faint">({check === 1 ? "a window gets those of the keywords hit in it" : "a hit gets those of its keyword"}; {"{kw}"} {"{gloss}"}{check === 2 ? " {other}" : ""})</span>
      </div>
      {rows.map((r, i) => (
        <div className="row" key={i} style={{ alignItems: "flex-start" }}>
          <input type="text" className="mono" value={r.typ} list={`hyp-types-${check}`} title={typeHelp} style={{ width: 84 }}
            onChange={(e) => edit(i, { typ: e.target.value.trim().toLowerCase() })} />
          <input type="text" className="mono" value={r.k} style={{ width: 90 }} onChange={(e) => edit(i, { k: e.target.value })} />
          <textarea className="hyp-text" rows={2} value={r.v} spellCheck={false} onChange={(e) => edit(i, { v: e.target.value })} />
          <button className="btn small ghost" title="remove" onClick={() => build(rows.filter((_, j) => j !== i))}>✕</button>
        </div>
      ))}
      <datalist id={`hyp-types-${check}`}>
        {["*", ...(check === 2 ? ["@other"] : []), "country", "demonym", "city", "region", "org", "person", "language", "event", "brand"].map((t) => <option key={t} value={t} />)}
      </datalist>
      <button className="btn small ghost" onClick={() => {
        let k = example.k, n = 2;
        while (rows.some((r) => r.typ === example.typ && r.k === k)) k = `${example.k}${n++}`;
        build([...rows, { ...example, k }]);
      }}>+ add keyword hypothesis</button>
    </div>
  );
}

function HypEditor({ title, rows, onChange }: { title: string; rows: Record<string, string>; onChange: (r: Record<string, string>) => void }) {
  const entries = Object.entries(rows);
  const rename = (old: string, key: string) => onChange(Object.fromEntries(entries.map(([k, v]) => [k === old ? key : k, v])));
  return (
    <div className="hyp-editor">
      <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>{title}</div>
      {entries.map(([k, v], i) => (
        <div className="row" key={i} style={{ alignItems: "flex-start" }}>
          <input type="text" className="mono" value={k} style={{ width: 130 }} onChange={(e) => rename(k, e.target.value)} />
          <textarea className="hyp-text" rows={2} value={v} spellCheck={false} onChange={(e) => onChange({ ...rows, [k]: e.target.value })} />
          <button className="btn small ghost" title="remove" onClick={() => onChange(Object.fromEntries(entries.filter(([x]) => x !== k)))}>✕</button>
        </div>
      ))}
      <button className="btn small ghost" onClick={() => {
        let n = entries.length + 1;
        while (`hyp${n}` in rows) n++;
        onChange({ ...rows, [`hyp${n}`]: "This text is about {country}." });
      }}>+ add hypothesis</button>
    </div>
  );
}

function SaveBox({ kind, defaultName, save, onSaved }: {
  kind: string; defaultName: string; save: (name: string, overwrite: boolean) => Promise<{ file: string; backup: string | null }>;
  onSaved: (name: string) => void;
}) {
  const [name, setName] = useState(defaultName);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => setName(defaultName), [defaultName]);
  async function go(overwrite: boolean) {
    setBusy(true);
    setMsg(null);
    try {
      const r = await save(name, overwrite);
      setMsg(`${kind === "keywords" ? "Keywords" : "Hypotheses"} saved to ${r.file}${r.backup ? ` · old version kept in ${r.backup}` : ""}`);
      onSaved(name);
    } catch (e) {
      const m = (e as Error).message;
      if (!overwrite && m.includes("exists") && window.confirm(`${kind}/${name} exists. Overwrite it? (the old file is backed up)`)) {
        setBusy(false);
        return go(true);
      }
      setMsg(`Not saved: ${m}`);  // e.g. "exists" and Cancel in the overwrite question
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="row" style={{ marginTop: 6 }}>
      <span className="faint">{kind}/</span>
      <input type="text" className="mono" value={name} onChange={(e) => setName(e.target.value)} style={{ width: 140 }} />
      <span className="faint">.{kind === "keywords" ? "txt" : "json"}</span>
      <button className="btn small" disabled={busy || !name} onClick={() => go(false)} data-testid={`save-${kind}`}
        title={`write ${kind}/${name || "…"}.${kind === "keywords" ? "txt" : "json"} in the project folder`}>
        {busy ? "Saving…" : `Save ${kind}`}</button>
      {msg ? <span className="faint mono" style={{ fontSize: 12, wordBreak: "break-all" }}>{msg}</span> : null}
    </div>
  );
}

export type { TryResult };

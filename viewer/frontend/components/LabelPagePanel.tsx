"use client";
// Corpus page: "Label with a policy". Runs nli_label.py's policy on the lines of this page through the model service
// (results appear under each line, nothing is written), or saves the whole file as a labelling run (a new folder in the
// project, listed on the Labels pages).
import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiError, api, useApi } from "@/lib/api";
import { href } from "@/lib/format";
import type { LabelLineResult, LabelLinesResp } from "@/lib/types";
import { actionClass } from "./LabelRunView";

const POLICY_KEY = "nli.labelpanel.policy";
const HANDOFF_KEY = "nli.labeltry.handoff";

export function lineAction(r: LabelLineResult): string {
  const ps = r.row.paragraphs || [];
  if (!ps.length) return r.row.action;  // untouched: no keyword in the line
  const order = ["remove", "review", "keep", "pass"];
  return order.find((a) => ps.some((p) => p.action === a)) || r.row.action;
}

/** Open the Try page with this line's text and policy (handed over through this browser's storage). */
export function openInTry(r: LabelLineResult, policy: string, ds: string, path: string) {
  try {
    localStorage.setItem(HANDOFF_KEY, JSON.stringify({ text: r.text, policy, ds, path, line: r.line, at: Date.now() }));
  } catch { /* storage blocked: the Try page opens without the text */ }
  window.open(href("/label/try", { from: "corpus" }), "_blank");
}

export function readTryHandoff(): { text: string; policy: string; ds: string; path: string; line: number } | null {
  try {
    const raw = localStorage.getItem(HANDOFF_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function stem(path: string): string {
  const base = path.split(/[\\/]/).pop() || "file";
  return base.replace(/\.(jsonl|json|ndjson|parquet|zip|rar|txt)(\.(zst|zstd|gz))?$/i, "").replace(/[^A-Za-z0-9_.-]+/g, "_");
}

export function LabelPagePanel({ ds, path, member, lines, onResults }: {
  ds: string; path: string; member: string | null; lines: number[];
  onResults: (r: { policy: string; results: Record<number, LabelLineResult> } | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const policies = useApi("labelpolicies", (s) => api.labelPolicies(s));
  const pg = useApi(open ? "playground" : null, (s) => api.playground(s));
  const [policy, setPolicy] = useState("");
  const [judge, setJudge] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [last, setLast] = useState<LabelLinesResp | null>(null);
  const [outName, setOutName] = useState("");
  const [started, setStarted] = useState<string | null>(null);
  const [saveErr, setSaveErr] = useState<string | null>(null);

  useEffect(() => {  // the policy last used here (this browser), else the newest Russia-side or the first one
    const list = policies.data?.policies || [];
    if (!list.length || policy) return;
    let saved = "";
    try { saved = localStorage.getItem(POLICY_KEY) || ""; } catch { /* no storage */ }
    setPolicy(list.includes(saved) ? saved : (list.filter((p) => p.includes("russia_llm")).pop() || list[list.length - 1]));
  }, [policies.data, policy]);
  useEffect(() => { setOutName(`out_label_${ds}_${stem(path)}`.replace(/[^A-Za-z0-9_.-]+/g, "_")); setStarted(null); }, [ds, path]);
  useEffect(() => { setLast(null); onResults(null); }, [ds, path, member]);  // eslint-disable-line react-hooks/exhaustive-deps

  const svc = pg.data?.service;
  const choose = (p: string) => { setPolicy(p); try { localStorage.setItem(POLICY_KEY, p); } catch { /* no storage */ } };

  const run = async () => {
    if (!policy || !lines.length) return;
    setBusy(true); setErr(null);
    try {
      const r = await api.labelLines(ds, { path, member, lines, policy, use_judge: judge });
      setLast(r);
      onResults({ policy, results: Object.fromEntries(r.results.map((x) => [x.line, x])) });
    } catch (e) {
      const st = e instanceof ApiError ? e.status : 0;
      setErr(st === 502 || st === 503 ? "The model service is not running. Start it in the project folder: py -3.12 nli_playground.py"
        : (e as Error).message);
    }
    setBusy(false);
  };
  const save = async () => {
    setSaveErr(null);
    try {
      const r = await api.labelRunFromDataset(ds, { path, member, policy, output_dir: outName, use_judge: judge });
      setStarted(r.run);
    } catch (e) {
      const st = e instanceof ApiError ? e.status : 0;
      setSaveErr(st === 502 || st === 503 ? "The model service is not running (it starts the run): py -3.12 nli_playground.py"
        : (e as Error).message);
    }
  };
  const counts: Record<string, number> = {};
  (last?.results || []).forEach((r) => { const a = lineAction(r); counts[a] = (counts[a] || 0) + 1; });

  return (
    <div className="panel try-panel" data-testid="label-panel">
      <div className="row">
        <button className="btn small" onClick={() => setOpen((o) => !o)}>{open ? "▾" : "▸"} Label with a policy</button>
        <span className="muted">nli_label.py: remove / review / keep per paragraph, on the lines of this page</span>
        <span className="spacer" />
        {open && svc ? (svc.running
          ? <span className="badge keep" title={svc.url}>models: {svc.fast}{svc.judge ? ` + ${svc.judge}` : ""}</span>
          : <span className="badge warn" title={svc.error}>model service not running</span>) : null}
        {last ? <span className="muted">{Object.entries(counts).map(([k, v]) => `${v} ${k}`).join(", ")} · {last.seconds.toFixed(1)} s</span> : null}
        {last ? <button className="btn small ghost" onClick={() => { setLast(null); onResults(null); }}>Clear results</button> : null}
      </div>
      {open ? (
        <div className="stack" style={{ marginTop: 8 }}>
          {svc && !svc.running ? (
            <div className="alert warn">The model service is not running. Start it in the project folder:<pre className="json">py -3.12 nli_playground.py</pre></div>
          ) : null}
          <div className="row">
            <label className="faint" style={{ fontSize: 13 }}>policy&nbsp;
              <select value={policy} onChange={(e) => choose(e.target.value)} data-testid="label-policy">
                {(policies.data?.policies || []).map((p) => <option key={p} value={p}>{p}</option>)}
              </select></label>
            <label className="faint" style={{ fontSize: 13 }}><input type="checkbox" checked={judge} onChange={(e) => setJudge(e.target.checked)} /> use the judge</label>
          </div>
          <div className="row">
            <button className="btn primary" onClick={run} disabled={busy || !policy || !lines.length} data-testid="label-run-page">
              {busy ? "Labelling… (~1 s per label and line on a CPU)" : `Label the ${lines.length} line${lines.length === 1 ? "" : "s"} of this page`}</button>
            <span className="faint">results appear under each line; nothing is saved</span>
          </div>
          {err ? <div className="alert warn">{err}</div> : null}
          {last?.skipped.length ? <div className="faint" style={{ fontSize: 13 }}>not labelled: {last.skipped.map((s) => `line ${s.line} (${s.why})`).join("; ")}</div> : null}
          <div className="row" style={{ borderTop: "1px solid var(--border, #e3e6ea)", paddingTop: 8 }}>
            <strong style={{ fontSize: 14 }}>Save as a labelling run</strong>
            <span className="faint" style={{ fontSize: 13 }}>the whole file, written to a new folder in dataset/</span>
          </div>
          <div className="row">
            <input className="mono" style={{ minWidth: 320 }} value={outName} onChange={(e) => setOutName(e.target.value)} data-testid="label-out-name" />
            <button className="btn" onClick={save} disabled={!policy || !outName || !!member} data-testid="label-save-run"
              title={member ? "a member of an archive cannot be labelled on its own" : "start nli_label.py run on this file"}>Save as a labelling run</button>
            {started ? <Link className="btn small" href={href("/label/run", { run: started })}>started: open {started} →</Link> : null}
          </div>
          {saveErr ? <div className="alert warn">{saveErr}</div> : null}
          {started ? <div className="faint" style={{ fontSize: 13 }}>It runs in the model service; its progress shows on the Labels pages. Output: {started}\*.labels.jsonl.zst, *.clean.jsonl.zst, *.rewrites.jsonl.zst.</div> : null}
        </div>
      ) : null}
    </div>
  );
}

export function LabelLineBox({ r, policy, ds, path }: { r: LabelLineResult; policy: string; ds: string; path: string }) {
  const a = lineAction(r);
  const ps = r.row.paragraphs || [];
  const labels = Array.from(new Set(ps.flatMap((p) => p.labels)));
  const exc = ps.find((p) => p.exception)?.exception;
  return (
    <div className="try-line-result" data-testid="label-line-result">
      <span className="faint" style={{ fontSize: 12 }}>policy</span>
      <span className={`badge ${actionClass(a)}`}>{a}</span>
      {ps.length > 1 ? <span className="faint" style={{ fontSize: 12 }}>{ps.length} paragraphs: {ps.map((p) => p.action).join(", ")}</span> : null}
      {labels.length ? labels.map((l) => <span key={l} className="chip">{l}</span>) : <span className="faint" style={{ fontSize: 12 }}>{ps.length ? "no label yes" : "no keyword: untouched"}</span>}
      {exc ? <span className="chip" title="decided by an exception of the policy">exception: {exc}</span> : null}
      {r.rewrites.length ? <span className="faint" style={{ fontSize: 12 }}>place names: {r.rewrites.map((x) => `${x.old} → ${x.new}`).join(", ")}</span> : null}
      {ps.length ? <button className="btn small ghost" onClick={() => openInTry(r, policy, ds, path)} title="open this line on the Try page: every score, the whole flow">flow →</button> : null}
    </div>
  );
}

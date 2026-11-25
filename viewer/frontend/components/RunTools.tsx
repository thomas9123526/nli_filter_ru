"use client";
// Run page tools: apply another policy to this run (nli_label.py redecide: no models, the stored scores are reused)
// and compare this run with another run of the same corpus (/label/compare).
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, useApi } from "@/lib/api";
import { href } from "@/lib/format";
import type { RunJob } from "@/lib/types";
import { readPolicyDraft } from "./PolicyEditView";

const DRAFT = "__draft__";

function stamp(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`;
}

export function RunTools({ run, policy }: { run: string; policy?: string | null }) {
  const [open, setOpen] = useState(false);
  const policies = useApi(open ? "labelpolicies" : null, (s) => api.labelPolicies(s));
  const runs = useApi(open ? "labelruns:tools" : null, (s) => api.labelRuns(s));
  const [draft, setDraft] = useState<ReturnType<typeof readPolicyDraft>>(null);
  const [pol, setPol] = useState("");
  const [out, setOut] = useState("");
  const [clean, setClean] = useState(false);
  const [reviewAs, setReviewAs] = useState("");
  const [job, setJob] = useState<RunJob | null>(null);
  const [newRun, setNewRun] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [other, setOther] = useState("");

  useEffect(() => {
    if (!open) return;
    setDraft(readPolicyDraft());
    setOut((o) => o || `${run}_rd_${stamp()}`);
    setPol((p) => p || policy || "");
  }, [open, run, policy]);
  useEffect(() => {  // follow the job
    if (!job || job.state !== "running") return;
    const t = setInterval(() => { api.run(job.id).then(setJob).catch(() => undefined); }, 1500);
    return () => clearInterval(t);
  }, [job]);
  const others = useMemo(() => (runs.data?.runs || []).map((r) => r.name).filter((n) => n !== run), [runs.data, run]);

  const start = async () => {
    setErr(null); setJob(null); setNewRun(null);
    try {
      const body = pol === DRAFT && draft ? { policy_data: draft.data } : { policy: pol };
      const r = await api.labelRedecide(run, { ...body, output_dir: out.trim(), write_clean: clean, review_as: reviewAs || undefined });
      setJob(r.job); setNewRun(r.run);
    } catch (e) { setErr((e as Error).message); }
  };

  return (
    <div className="panel" data-testid="run-tools" style={{ marginBottom: 16 }}>
      <div className="row">
        <button className="btn small ghost" onClick={() => setOpen((o) => !o)} data-testid="run-tools-toggle">{open ? "▾" : "▸"} Apply another policy · compare runs</button>
        {!open ? <span className="faint" style={{ fontSize: 12 }}>redecide this run with an edited policy (no models), then see what changed</span> : null}
      </div>
      {open ? (
        <div className="stack" style={{ marginTop: 10 }}>
          <div>
            <strong>Apply another policy to this run</strong>
            <span className="faint" style={{ fontSize: 12 }}> · nli_label.py redecide: the stored scores are reused (seconds, no GPU); a label whose
              hypothesis is new or reworded counts as not scored. Runs through the model service (<code className="mono">python nli_playground.py --no-models</code>).</span>
            <div className="row" style={{ marginTop: 6, flexWrap: "wrap" }}>
              <label className="faint" style={{ fontSize: 13 }}>policy&nbsp;
                <select value={pol} onChange={(e) => setPol(e.target.value)} data-testid="rd-policy">
                  <option value="">choose…</option>
                  {draft ? <option value={DRAFT}>unsaved edits of {draft.path}</option> : null}
                  {(policies.data?.policies || []).map((p) => <option key={p} value={p}>{p}{p === policy ? " (this run's)" : ""}</option>)}
                </select></label>
              <label className="faint" style={{ fontSize: 13 }}>new run&nbsp;
                <input type="text" className="mono" value={out} onChange={(e) => setOut(e.target.value)} style={{ width: 260 }} data-testid="rd-output" /></label>
              <label className="faint" style={{ fontSize: 13 }}><input type="checkbox" checked={clean} onChange={(e) => setClean(e.target.checked)} /> write the clean copy</label>
              <label className="faint" style={{ fontSize: 13 }}>review&nbsp;
                <select value={reviewAs} onChange={(e) => setReviewAs(e.target.value)}>
                  <option value="">kept (default)</option><option value="remove">cut (--review-as remove)</option>
                </select></label>
              <button className="btn small primary" disabled={!pol || !out.trim() || job?.state === "running"} onClick={start} data-testid="rd-start">
                {job?.state === "running" ? "Redeciding…" : "Redecide"}</button>
            </div>
            {err ? <div className="alert error" style={{ marginTop: 6 }}>{err}</div> : null}
            {job ? (
              <div style={{ marginTop: 6 }}>
                <span className={`badge ${job.state === "done" ? "keep" : job.state === "running" ? "accent" : "filter"}`}>{job.state} · {job.seconds}s</span>
                {job.state === "done" && newRun ? <>
                  {" "}<Link className="btn small" href={href("/label/run", { run: newRun })}>open {newRun} →</Link>
                  {" "}<Link className="btn small primary" href={href("/label/compare", { a: run, b: newRun })} data-testid="rd-compare">compare with this run →</Link></> : null}
                {job.state !== "done" ? <pre className="mono" style={{ maxHeight: 160, overflow: "auto", fontSize: 12, marginTop: 6 }}>{job.output.slice(-20).join("\n") || "(no output yet)"}</pre> : null}
              </div>) : null}
          </div>
          <div>
            <strong>Compare with another run</strong>
            <span className="faint" style={{ fontSize: 12 }}> · of the same corpus: totals side by side and every paragraph whose action changed</span>
            <div className="row" style={{ marginTop: 6 }}>
              <select value={other} onChange={(e) => setOther(e.target.value)} data-testid="cmp-other">
                <option value="">choose a run…</option>
                {others.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
              <Link className={`btn small${other ? "" : " disabled"}`} aria-disabled={!other} href={other ? href("/label/compare", { a: run, b: other }) : "#"}>Compare →</Link>
            </div>
          </div>
        </div>) : null}
    </div>
  );
}

"use client";
// Labels: nli_label.py runs (policy labels per paragraph). List the run folders, start a new run, follow it.
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, useApi } from "@/lib/api";
import { href, num, pct } from "@/lib/format";
import type { LabelProgress, RunJob } from "@/lib/types";
import { Crumbs, ErrorBox, Loading } from "./ui";

const DOC_ACTIONS = ["untouched", "pass", "kept", "review", "edited", "removed", "error"];
const DEFAULT_CMD = "python nli_label.py run corpus_olmo\\seed_docs.jsonl --output-dir out_label_new --judge-model none --limit 20";

export function ProgressBadge({ p }: { p: LabelProgress | null }) {
  if (!p) return null;
  const cls = p.state === "done" ? "keep" : p.state === "running" ? "accent" : p.state === "failed" ? "filter" : "warn";
  return (
    <span className={`badge ${cls}`} title={p.note || p.command}>
      {p.state}{p.state === "running" ? ` · ${num(p.lines_done + (p.current_lines || 0))} lines · file ${p.files_done + 1}/${p.files_total}` : ""}
    </span>
  );
}

export function LabelsView() {
  const [tick, setTick] = useState(0);
  const runs = useApi(`labelruns:${tick}`, (s) => api.labelRuns(s));
  const policies = useApi("labelpolicies", (s) => api.labelPolicies(s));
  const [cmd, setCmd] = useState(DEFAULT_CMD);
  const [job, setJob] = useState<RunJob | null>(null);
  const [err, setErr] = useState<Error | null>(null);
  const anyRunning = (runs.data?.runs || []).some((r) => r.progress?.state === "running") || job?.state === "running";

  useEffect(() => {  // refresh the list while something runs
    if (!anyRunning) return;
    const t = setInterval(() => setTick((x) => x + 1), 4000);
    return () => clearInterval(t);
  }, [anyRunning]);
  useEffect(() => {  // follow the started job's output
    if (!job || job.state !== "running") return;
    const t = setInterval(() => { api.run(job.id).then(setJob).catch(() => undefined); }, 2000);
    return () => clearInterval(t);
  }, [job]);

  const start = async () => {
    setErr(null);
    try { setJob(await api.labelStart(cmd)); setTick((x) => x + 1); } catch (e) { setErr(e as Error); }
  };
  const stop = async () => { if (job) { try { setJob(await api.stopRun(job.id)); } catch (e) { setErr(e as Error); } } };
  const setPolicy = (p: string) => {
    const without = cmd.replace(/\s--policy\s+\S+/, "");
    setCmd(p ? `${without} --policy ${p}` : without);
  };

  return (
    <>
      <div className="page-head">
        <div>
          <Crumbs items={[{ label: "Datasets", href: "/" }, { label: "labels" }]} />
          <h1>Labelling runs</h1>
          <div className="sub">nli_label.py output folders in {runs.data?.project || "the project folder"}: policy labels per paragraph,
            what was removed, kept or sent to review. Guide: cmds\labeling\README.md.</div>
        </div>
      </div>

      <div className="panel" data-testid="label-start">
        <div className="row"><strong>Start a run</strong>
          <span className="faint" style={{ fontSize: 12 }}>Runs through the model service: start it first with
            <code className="mono"> python nli_playground.py --no-models</code> (from the project folder, in the torch environment).</span>
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <input className="mono" style={{ flex: "1 1 600px", padding: "6px 8px" }} value={cmd} onChange={(e) => setCmd(e.target.value)} spellCheck={false} />
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <label className="faint" style={{ fontSize: 13 }}>policy&nbsp;
            <select onChange={(e) => setPolicy(e.target.value)} defaultValue="">
              <option value="">default (policy/russia_policy.json)</option>
              {(policies.data?.policies || []).map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>
          <button className="btn primary small" onClick={start} disabled={job?.state === "running"}>Start</button>
          {job?.state === "running" ? <button className="btn small" onClick={stop}>Stop</button> : null}
          {job ? <span className={`badge ${job.state === "done" ? "keep" : job.state === "running" ? "accent" : "filter"}`}>{job.state} · {job.seconds}s</span> : null}
        </div>
        <ErrorBox error={err} />
        {job ? <pre className="mono" style={{ maxHeight: 220, overflow: "auto", fontSize: 12, marginTop: 8 }}>{job.output.slice(-40).join("\n") || "(no output yet)"}</pre> : null}
      </div>

      <ErrorBox error={runs.error} onRetry={runs.reload} />
      {runs.loading && !runs.data ? <Loading what="Finding runs" /> : null}
      {runs.data ? (
        <div className="panel flush" style={{ marginTop: 16 }}>
          <div className="table-wrap">
            <table data-testid="label-runs">
              <thead><tr><th>Run</th><th>State</th><th className="right">Lines</th><th className="right">Removed tokens</th><th>Documents</th><th>Finished</th></tr></thead>
              <tbody>
                {runs.data.runs.map((r) => (
                  <tr key={r.name}>
                    <td><Link href={href("/labelrun", { run: r.name })}><strong>{r.name}</strong></Link>
                      {r.redecided ? <span className="badge neutral" style={{ marginLeft: 6 }}>redecided</span> : null}
                      <div className="faint mono" style={{ fontSize: 11 }}>{r.policy || ""}</div></td>
                    <td><ProgressBadge p={r.progress} /></td>
                    <td className="right">{num(r.lines)}</td>
                    <td className="right">{r.tokens ? `${num(r.tokens_removed)} (${pct(r.tokens_removed || 0, r.tokens)})` : "–"}</td>
                    <td>{DOC_ACTIONS.filter((a) => r.docs[a]).map((a) => <span key={a} className="chip">{a} {num(r.docs[a])}</span>)}</td>
                    <td className="faint">{r.finished || (r.progress ? `started ${r.progress.started}` : "")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {runs.data.runs.length === 0 ? <div className="empty">No nli_label.py runs in the project folder yet.</div> : null}
        </div>
      ) : null}
    </>
  );
}

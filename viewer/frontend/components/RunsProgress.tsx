"use client";
// "Runs in progress": the progress files nli_filter.py writes into the dataset's output folder
// (OUTPUT/progress/<run>.json), however the run was started (command line, Run filter, run_shards.sh, other PCs).
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ProgressResp, RunProgress } from "@/lib/types";

function dur(s: number | null | undefined): string {
  if (s === null || s === undefined) return "–";
  if (s < 90) return `${Math.round(s)} s`;
  if (s < 5400) return `${Math.round(s / 60)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}

function mb(n: number | null | undefined): string {
  return n ? `${(n / 1048576).toFixed(n > 1e9 ? 0 : 1)} MB` : "0 MB";
}

function Bar({ percent, state }: { percent: number | null | undefined; state: string }) {
  const p = Math.max(0, Math.min(100, percent ?? 0));
  return (
    <div className={`progress-bar ${state}`} title={percent === null || percent === undefined ? "size unknown" : `${p}%`}>
      <div style={{ width: `${p}%` }} />
    </div>
  );
}

export function RunsProgress({ ds, compact }: { ds: string; compact?: boolean }) {
  const [data, setData] = useState<ProgressResp | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    api.progress(ds).then((d) => { if (alive) setData(d); }).catch(() => { /* no output folder yet: nothing to show */ });
    return () => { alive = false; };
  }, [ds, tick]);
  const live = !!data?.runs.some((r) => r.state === "running" && !r.stale);
  useEffect(() => {
    const t = setTimeout(() => setTick((x) => x + 1), live ? 5000 : 30000);
    return () => clearTimeout(t);
  }, [live, tick]);

  if (!data || !data.runs.length) return null;
  const c = data.combined;
  const runs = compact ? data.runs.slice(0, 5) : data.runs;
  return (
    <div className="panel runs-progress" data-testid="runs-progress">
      <div className="row">
        <h2 style={{ margin: 0 }}>Runs {live ? "in progress" : "(recent)"}</h2>
        {c ? <>
          <Bar percent={c.percent} state="running" />
          <span className="mono">{c.percent ?? "–"}%</span>
          <span className="muted">{c.runs} run{c.runs === 1 ? "" : "s"} · {c.files_done}/{c.files_needed} files · {c.lines.toLocaleString("en-US")} lines · {c.lines_per_second} lines/s · {c.eta_seconds !== null ? `about ${dur(c.eta_seconds)} left` : "time left unknown"}</span>
        </> : null}
        <span className="spacer" />
        <span className="faint" style={{ fontSize: 12 }}>from the output folder's progress/ (runs write every {dur(Math.max(...data.runs.map((r) => r.every_seconds || 60)))}) · checked {live ? "every 5 s" : "every 30 s"}</span>
      </div>
      <table>
        <tbody>
          {runs.map((r) => <RunRow key={r.run_id} r={r} stale={r.stale_after ?? data.stale_seconds} />)}
        </tbody>
      </table>
    </div>
  );
}

function RunRow({ r, stale }: { r: RunProgress; stale: number }) {
  const state = r.stale ? "stale" : r.state;
  return (
    <tr className={`run-row ${state}`}>
      <td className="nowrap">
        <span className={`badge ${state === "running" ? "accent" : state === "done" ? "keep" : state === "stale" ? "warn" : "filter"}`}>
          {state === "stale" ? "no update" : state}</span>
      </td>
      <td className="nowrap mono" title={r.command}>{r.host}{r.shard ? ` · shard ${r.shard}` : ""} <span className="faint">pid {r.pid}</span></td>
      <td style={{ minWidth: 160 }}><Bar percent={r.percent} state={state} /></td>
      <td className="nowrap mono">{r.percent ?? "–"}%</td>
      <td className="nowrap muted">{r.files_done ?? 0}/{r.files_needed ?? 0} files{r.files_skipped ? ` (+${r.files_skipped} done before)` : ""}{r.files_failed ? `, ${r.files_failed} failed` : ""}</td>
      <td className="muted">
        {state === "running" ? <>{r.current ? <span className="mono" title={r.current.input}>{short(r.current.input)}</span> : null} · {r.lines_per_second ?? "–"} lines/s · {r.eta_seconds !== null && r.eta_seconds !== undefined ? `about ${dur(r.eta_seconds)} left` : "–"}</> : null}
        {state === "stale" ? <>said “running”, but no update for {dur(r.age_seconds)} (more than {dur(stale)}): stopped, crashed or the machine is gone?</> : null}
        {r.state === "done" || r.state === "failed" || r.state === "stopped" ? <>{(r.lines ?? 0).toLocaleString("en-US")} lines in {dur(r.seconds)}{r.ended ? ` · ended ${r.ended}` : ""}{r.error ? <span className="faint"> · {r.error}</span> : null}</> : null}
      </td>
      <td className="nowrap faint" title={`started ${r.started}`}>{mb(r.bytes_done)} / {mb(r.bytes_total)} · updated {dur(r.age_seconds)} ago</td>
    </tr>
  );
}

function short(p: string, n = 48): string {
  return p.length > n ? `…${p.slice(-n)}` : p;
}

"use client";
// Labels: nli_label.py runs (policy labels per paragraph). List the run folders, start a new run, follow it.
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, useApi } from "@/lib/api";
import { href, num, pct } from "@/lib/format";
import type { LabelProgress } from "@/lib/types";
import { StartRunForm } from "./StartRunForm";
import { KwstatsStartForm } from "./KwstatsView";
import { Crumbs, ErrorBox, Loading } from "./ui";

const DOC_ACTIONS = ["untouched", "pass", "kept", "review", "edited", "removed", "error"];

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
  const anyRunning = (runs.data?.runs || []).some((r) => r.progress?.state === "running");
  const refresh = useCallback(() => setTick((x) => x + 1), []);

  useEffect(() => {  // refresh the list while something runs
    if (!anyRunning) return;
    const t = setInterval(() => setTick((x) => x + 1), 4000);
    return () => clearInterval(t);
  }, [anyRunning]);
  return (
    <>
      <div className="page-head">
        <div>
          <Crumbs items={[{ label: "Labelling" }]} />
          <h1>Labelling runs</h1>
          <div className="sub">nli_label.py output folders in {runs.data?.project || "the project folder"}: policy labels per paragraph,
            what was removed, kept or sent to review. Guide: cmds\labeling\README.md.</div>
        </div>
      </div>

      <div className="row" style={{ marginBottom: 12, flexWrap: "wrap" }}>
        <Link className="btn small primary" href="/label/try" data-testid="labeltry-link">Try the policy, case by case →</Link>
        <Link className="btn small" href="/label/compare" data-testid="compare-link">Compare runs →</Link>
        <Link className="btn small" href="/label/folders" data-testid="folders-link">Clean up run folders →</Link>
        <Link className="btn small" href="/label/kwstats" data-testid="kwstats-link">Keyword statistics →</Link>
        <Link className="btn small" href="/label/lab" data-testid="lab-link">Experiment →</Link>
        <Link className="btn small" href="/label/lab/blank" data-testid="lab-blank-link">Blank experiment →</Link>
        <Link className="btn small" href="/settings" data-testid="settings-link">Settings (policy, keywords, rules, translation …) →</Link>
        <span className="faint" style={{ fontSize: 12 }}>every level-0 / 1 / 2 label and edge case, one text at a time, with its flow</span>
      </div>
      <StartRunForm onChanged={refresh} />
      <div style={{ marginTop: 12 }}><KwstatsStartForm /></div>

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
                    <td><Link href={href("/label/run", { run: r.name })}><strong>{r.name}</strong></Link>
                      {r.redecided ? <span className="badge neutral" style={{ marginLeft: 6 }}>redecided</span> : null}
                      {r.mode === "simple" ? <span className="badge accent" style={{ marginLeft: 6 }}>simple</span> : null}
                      {r.unit === "line" ? <span className="badge neutral" style={{ marginLeft: 6 }}>line unit</span> : null}
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

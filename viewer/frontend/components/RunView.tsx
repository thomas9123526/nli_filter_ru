"use client";
// "Run filter": run nli_filter.py on this dataset with arguments you can see and edit. The run is started by the
// model service nli_playground.py (it has the torch environment); this page shows its output live.
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ApiError, api, useApi } from "@/lib/api";
import { href } from "@/lib/format";
import type { RunJob } from "@/lib/types";
import { RunsProgress } from "./RunsProgress";
import { Crumbs, ErrorBox, Loading } from "./ui";

export function RunView() {
  const sp = useSearchParams();
  const ds = sp.get("ds") || "";
  const defaults = useApi(ds ? `rundefaults:${ds}` : null, (s) => api.runDefaults(ds, s));
  const [command, setCommand] = useState<string | null>(null);
  const [job, setJob] = useState<RunJob | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const outRef = useRef<HTMLPreElement>(null);

  useEffect(() => { if (defaults.data && command === null) setCommand(defaults.data.command); }, [defaults.data, command]);
  // a run of this dataset that is still going (e.g. after reloading the page): show it again
  useEffect(() => {
    if (!ds || job) return;
    api.runs().then((r) => { const j = r.jobs.find((x) => x.label === ds && x.state === "running"); if (j) setJob(j); }).catch(() => {});
  }, [ds, job]);
  // follow the output while the run is going
  useEffect(() => {
    if (!job || job.state !== "running") return;
    const t = setTimeout(() => { api.run(job.id).then(setJob).catch((e) => setError(e)); }, 1500);
    return () => clearTimeout(t);
  }, [job]);
  useEffect(() => { outRef.current?.scrollTo(0, outRef.current.scrollHeight); }, [job?.output.length]);

  async function start() {
    if (!command) return;
    setBusy(true);
    setError(null);
    try {
      setJob(await api.startRun(ds, command));
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError((e as Error).message, 0));
    } finally {
      setBusy(false);
    }
  }
  async function stop() {
    if (!job || !window.confirm("Stop this nli_filter.py run? Files already finished stay done; a rerun continues with the rest.")) return;
    try { setJob(await api.stopRun(job.id)); } catch (e) { setError(e instanceof ApiError ? e : new ApiError((e as Error).message, 0)); }
  }

  if (!ds) return <div className="alert error">Missing ?ds=</div>;
  const d = defaults.data;
  const svc = d?.service;
  const running = job?.state === "running";
  return (
    <>
      <div className="page-head">
        <div>
          <Crumbs items={[{ label: "Datasets", href: "/" }, { label: ds, href: href("/dataset", { ds }) }, { label: "run filter" }]} />
          <h1>Run nli_filter.py on {ds}</h1>
        </div>
      </div>
      <ErrorBox error={defaults.error} onRetry={defaults.reload} />
      {defaults.loading && !d ? <Loading what="Preparing the arguments" /> : null}
      {d ? (
        <div className="stack">
          {svc && !svc.running ? (
            <div className="alert warn">The model service is not running, so no run can start. In the project folder, in the torch environment:
              <pre className="json">python nli_playground.py{"\n"}python nli_playground.py --no-models      (only for runs: no models loaded in the service)</pre>{svc.error}</div>
          ) : svc ? <div className="muted">Runs with <span className="mono">{svc.python || "the service's Python"}</span> in <span className="mono">{svc.project_dir}</span>{svc.models ? " (the service also holds its own models in memory)" : ""}.</div> : null}
          {d.problems.map((p) => <div className="alert warn" key={p}>{p}</div>)}
          <div className="panel">
            <h2>Arguments <span className="faint" style={{ fontWeight: 400, fontSize: 12 }}>python nli_filter.py …</span></h2>
            <div className="editor">
              <textarea className="mono" rows={Math.min(8, Math.max(3, Math.ceil((command || "").length / 110)))} value={command || ""}
                spellCheck={false} disabled={running} onChange={(e) => setCommand(e.target.value)} data-testid="run-command" />
            </div>
            <div className="row" style={{ marginTop: 8 }}>
              <button className="btn primary" onClick={start} disabled={busy || running || !svc?.running || !command}>{busy ? "Starting…" : "Start"}</button>
              <button className="btn" onClick={() => setCommand(d.command)} disabled={running}>Reset</button>
              {running ? <button className="btn danger" onClick={stop}>Stop</button> : null}
              <span className="spacer" />
              <span className="faint">e.g. add <span className="mono">--hypotheses-file hypotheses\russia.json</span>, <span className="mono">--device cuda</span>, <span className="mono">--judge-model none</span>, <span className="mono">--limit 1000</span></span>
            </div>
            {d.notes.length ? <ul className="faint" style={{ fontSize: 12, margin: "8px 0 0" }}>{d.notes.map((n) => <li key={n}>{n}</li>)}</ul> : null}
          </div>
          {error ? <div className="alert warn">{error.message}</div> : null}
          <RunsProgress ds={ds} compact />
          {job ? (
            <div className="panel flush">
              <div className="panel-head">
                <h2>Output</h2>
                <span className={`badge ${job.state === "done" ? "keep" : job.state === "running" ? "accent" : "filter"}`}>{job.state}{job.returncode !== null ? ` (exit ${job.returncode})` : ""}</span>
                <span className="muted">{job.started} · {Math.round(job.seconds)} s · {job.output_lines} lines</span>
                <span className="spacer" />
                {job.state === "done" ? <Link className="btn small primary" href={href("/dataset", { ds })}>Open the results</Link> : null}
              </div>
              <pre ref={outRef} className="json run-output" data-testid="run-output">{job.output.join("\n") || "(no output yet)"}</pre>
              <div className="panel-body faint" style={{ fontSize: 12 }}>Full log: <span className="mono">{job.log_file}</span></div>
            </div>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

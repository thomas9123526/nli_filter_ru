"use client";
// "Run filter": run nli_filter.py on this dataset with arguments you can see and edit. The run is started by the
// model service nli_playground.py (it has the torch environment); this page shows its output live.
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, useApi } from "@/lib/api";
import { href } from "@/lib/format";
import type { RunJob } from "@/lib/types";
import { RunsProgress } from "./RunsProgress";
import { Settings, settingsToArgs, useTrySettings } from "./TryPanel";
import { Crumbs, ErrorBox, Loading } from "./ui";

/** Command line -> tokens. Double quotes group ("D:\my data") and are kept; backslashes stay (Windows paths). */
function tokenize(cmd: string): string[] {
  return cmd.match(/(?:[^\s"]+|"[^"]*")+/g) || [];
}
const quote = (a: string) => (!a || /\s/.test(a) ? `"${a}"` : a);

// options the settings panel sets, with how many values each takes
const MANAGED: Record<string, number> = {
  "--country": 1, "--country-adj": 1, "--keywords-file": 1, "--hypotheses-file": 1, "--check1-hyp": 1, "--check2-hyp": 1,
  "--check1-threshold": 1, "--check2-threshold": 1, "--uncertain-band": 2, "--max-windows": 1,
  "--no-early-stop": 0, "--no-check1-early-stop": 0, "--no-check2-early-stop": 0, "--no-rules": 0,
};

/** The command with the panel's options replaced by `args`; everything else (inputs, --device, ...) is kept.
 *  --judge-model is changed only for on / off: "none" when off, removed when on and it was "none". */
function applySettings(command: string, args: string[], judge: boolean): string {
  const toks = tokenize(command);
  const out: string[] = [];
  for (let i = 0; i < toks.length; i++) {
    const t = toks[i];
    const name = t.split("=", 1)[0];
    const inline = t.includes("=");
    if (name in MANAGED) { i += inline ? 0 : MANAGED[name]; continue; }
    if (name === "--judge-model") {
      const value = inline ? t.slice(t.indexOf("=") + 1) : toks[i + 1] || "";
      if (!inline) i += 1;
      if (judge && value.replace(/"/g, "") !== "none") out.push("--judge-model", value);  // keep another judge model
      continue;
    }
    out.push(t);
  }
  return [...out, ...args.map(quote)].join(" ");
}

/** The panel's options found in a command, normalised (sorted groups, no quotes): to see if they are applied. */
function managedPart(command: string): string {
  const toks = tokenize(command).map((t) => t.replace(/"/g, ""));
  const groups: string[] = [];
  for (let i = 0; i < toks.length; i++) {
    const [name, inl] = toks[i].split(/=(.*)/s, 2);
    if (name in MANAGED || name === "--judge-model") {
      const n = name === "--judge-model" ? 1 : MANAGED[name];
      const vals = inl !== undefined ? [inl] : toks.slice(i + 1, i + 1 + n);
      if (inl === undefined) i += n;
      if (name !== "--judge-model" || vals[0] === "none") groups.push([name, ...vals].join(" "));
    }
  }
  return groups.sort().join(" | ");
}

export function RunView() {
  const sp = useSearchParams();
  const ds = sp.get("ds") || "";
  const defaults = useApi(ds ? `rundefaults:${ds}` : null, (s) => api.runDefaults(ds, s));
  const [command, setCommand] = useState<string | null>(null);
  const [job, setJob] = useState<RunJob | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const outRef = useRef<HTMLPreElement>(null);
  // the "Try settings" of this browser (shared with the corpus pages), turned into nli_filter.py options
  const info = useApi("playground", (s) => api.playground(s));
  const [st, set] = useTrySettings(info.data);
  const [showSettings, setShowSettings] = useState(true);
  const fromSettings = useMemo(() => (st && info.data ? settingsToArgs(st, info.data) : null), [st, info.data]);
  const applied = !!fromSettings && command !== null && managedPart(command) === managedPart(fromSettings.args.map(quote).join(" "));

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
          <div className="panel try-panel" data-testid="run-settings">
            <div className="row">
              <button className="btn small" onClick={() => setShowSettings((o) => !o)}>{showSettings ? "▾" : "▸"} Settings</button>
              <span className="muted">country, keywords, hypotheses, thresholds: the same as “Try settings” on the corpus pages</span>
              <span className="spacer" />
              {fromSettings ? (applied
                ? <span className="badge keep" data-testid="settings-applied">in the arguments</span>
                : <span className="badge warn" data-testid="settings-not-applied">not in the arguments yet</span>) : null}
              {fromSettings ? (
                <button className={`btn small${applied ? "" : " primary"}`} disabled={running || command === null}
                  onClick={() => setCommand(applySettings(command || "", fromSettings.args, fromSettings.judge))} data-testid="apply-settings">
                  Apply to the arguments ↓</button>
              ) : null}
            </div>
            <ErrorBox error={info.error} onRetry={info.reload} />
            {showSettings && st && info.data ? <Settings info={info.data} st={st} set={set} onSaved={info.reload} /> : null}
            {fromSettings?.warnings.map((w) => <div className="alert warn" key={w} style={{ marginTop: 8 }}>{w}</div>)}
            {showSettings && fromSettings ? (
              <div className="faint" style={{ fontSize: 12, marginTop: 6 }}>
                Applying replaces only these options in the arguments: <span className="mono">{fromSettings.args.map(quote).join(" ")}</span>. Inputs, --output-dir, --device and the rest stay as they are.
              </div>
            ) : null}
          </div>
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

"use client";
// "Start a run" on /label/: a form that builds the nli_label.py command (corpus, policy, output folder, options);
// the command stays visible and can be edited before starting. "Run a test set" does what tools/label_test_set.py
// does: rebuilds the test set's corpus from its JSON file, then labels it (the run page then shows expected vs result).
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, getJSON, useApi } from "@/lib/api";
import { href } from "@/lib/format";
import type { RunJob } from "@/lib/types";
import { ErrorBox } from "./ui";

const DEFAULT_POLICY = "policy/russia_llm_policy_v2.json";  // the Russia-side policy

type FormInfo = { corpora: { path: string; files: number }[];
  test_sets: { file: string; kind: string; items: number; corpus: string; policy: string | null; output: string; about: string }[];
  policies: string[] };

function stamp(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`;
}
const q = (s: string) => (/[\s"]/.test(s) ? `"${s.replace(/"/g, '\\"')}"` : s);
const base = (p: string) => p.replace(/[\\/]+$/, "").split(/[\\/]/).pop()?.replace(/\.(jsonl|json|ndjson|zst|gz|zip|rar|parquet)$/gi, "") || "corpus";

function JobBox({ job, run, onStop }: { job: RunJob; run?: string | null; onStop: () => void }) {
  return (
    <div style={{ marginTop: 8 }}>
      <div className="row">
        <span className={`badge ${job.state === "done" ? "keep" : job.state === "running" ? "accent" : "filter"}`}>{job.state} · {job.seconds}s</span>
        {job.state === "running" ? <button className="btn small" onClick={onStop}>Stop</button> : null}
        {job.state === "done" && run ? <Link className="btn small primary" href={href("/label/run", { run })} data-testid="job-open-run">open {run} →</Link> : null}
      </div>
      <pre className="mono" style={{ maxHeight: 220, overflow: "auto", fontSize: 12, marginTop: 6 }}>{job.output.slice(-40).join("\n") || "(no output yet)"}</pre>
    </div>
  );
}

export function StartRunForm({ onChanged }: { onChanged: () => void }) {
  const info = useApi("labelrunform", (s) => getJSON<FormInfo>("/api/labels/forms/run", undefined, s));
  const [corpus, setCorpus] = useState("dataset/test_corpus_cases_ru");
  const [custom, setCustom] = useState("");
  const [policy, setPolicy] = useState(DEFAULT_POLICY);
  const [out, setOut] = useState("");
  const [overwrite, setOverwrite] = useState(true);
  const [clean, setClean] = useState(true);
  const [reviewAs, setReviewAs] = useState("");
  const [maxShare, setMaxShare] = useState("");
  const [firstCut, setFirstCut] = useState(false);
  const [judge, setJudge] = useState(true);
  const [topicField, setTopicField] = useState("");
  const [topicMode, setTopicMode] = useState("");
  const [limit, setLimit] = useState("");
  const [manual, setManual] = useState<string | null>(null);  // the command as edited by hand (null = the form's)
  const [job, setJob] = useState<RunJob | null>(null);
  const [jobRun, setJobRun] = useState<string | null>(null);
  const [err, setErr] = useState<Error | null>(null);
  const [tsJudge, setTsJudge] = useState(true);

  const src = corpus === "__custom__" ? custom.trim() : corpus;
  const outDir = out.trim() || `dataset/out_label_${base(src)}_${stamp()}`;
  const built = useMemo(() => {
    const a = ["python", "nli_label.py", "run", q(src || "<corpus>"), "--policy", q(policy || DEFAULT_POLICY), "--output-dir", q(outDir)];
    if (overwrite) a.push("--overwrite");
    if (clean) a.push("--write-clean");
    if (reviewAs) a.push("--review-as", reviewAs);
    if (maxShare.trim() && Number(maxShare) > 0 && Number(maxShare) <= 1) a.push("--max-removed-share", String(Number(maxShare)));
    if (firstCut) a.push("--drop-if-first-cut");
    if (!judge) a.push("--judge-model", "none");
    if (topicField.trim()) a.push("--topic-field", q(topicField.trim()));
    if (topicMode) a.push("--topic-mode", topicMode);
    if (limit.trim() && Number(limit) > 0) a.push("--limit", String(Math.floor(Number(limit))));
    return a.join(" ");
  }, [src, policy, outDir, overwrite, clean, reviewAs, maxShare, firstCut, judge, topicField, topicMode, limit]);
  const cmd = manual ?? built;

  useEffect(() => {
    if (!job || job.state !== "running") return;
    const t = setInterval(() => { api.run(job.id).then((j) => { setJob(j); if (j.state !== "running") onChanged(); }).catch(() => undefined); }, 2000);
    return () => clearInterval(t);
  }, [job, onChanged]);

  const startCmd = async () => {
    setErr(null);
    try {
      const j = await api.labelStart(cmd);
      const m = /--output-dir\s+("([^"]+)"|(\S+))/.exec(cmd);
      setJob(j); setJobRun(m ? base(m[2] || m[3]) : null); onChanged();
    } catch (e) { setErr(e as Error); }
  };
  const runTestSet = async (file: string) => {
    setErr(null);
    try {
      const r = await api.labelTestSet({ file, use_judge: tsJudge });
      setJob(r.job); setJobRun(r.run); onChanged();
    } catch (e) { setErr(e as Error); }
  };
  const stop = async () => { if (job) { try { setJob(await api.stopRun(job.id)); } catch (e) { setErr(e as Error); } } };
  const policies = info.data?.policies || [];

  return (
    <div className="panel" data-testid="label-start">
      <div className="row"><strong>Start a run</strong>
        <span className="faint" style={{ fontSize: 12 }}>Runs through the model service: start it first with
          <code className="mono"> python nli_playground.py</code> (models needed for a run; <code className="mono">--no-models</code> is enough for redecide).</span>
      </div>

      {info.data?.test_sets.length ? (
        <div className="start-testsets" data-testid="test-sets">
          <span className="faint" style={{ fontSize: 13 }}>Run a test set</span>
          {info.data.test_sets.map((t) => (
            <button key={t.file} className="btn small" disabled={job?.state === "running"} onClick={() => runTestSet(t.file)}
              title={`rebuild ${t.corpus} from ${t.file}, then label it with ${t.policy || "?"} into dataset/${t.output} (--overwrite --write-clean)`}
              data-testid={`run-test-set-${t.file}`}>
              ▶ {t.file.replace(/^labels\//, "")} <span className="faint">({t.items} {t.kind})</span></button>))}
          <label className="faint" style={{ fontSize: 13 }}><input type="checkbox" checked={tsJudge} onChange={(e) => setTsJudge(e.target.checked)} /> judge</label>
          <span className="faint" style={{ fontSize: 12 }}>→ the run page shows expected vs result</span>
          <span className="faint" style={{ fontSize: 12 }}>· edit them: cases on <Link href="/label/try">Try</Link> (Edit cases), documents on <Link href="/label/docs">Documents test set</Link></span>
        </div>) : null}

      <div className="start-grid">
        <label className="pfield"><span className="pfield-label">corpus</span>
          <select value={corpus} onChange={(e) => { setCorpus(e.target.value); setManual(null); }} data-testid="start-corpus">
            {(info.data?.corpora || []).map((c) => <option key={c.path} value={c.path}>{c.path} ({c.files} file{c.files === 1 ? "" : "s"})</option>)}
            {!(info.data?.corpora || []).some((c) => c.path === corpus) && corpus !== "__custom__" ? <option value={corpus}>{corpus}</option> : null}
            <option value="__custom__">another folder / file / server address…</option>
          </select>
          {corpus === "__custom__" ? <input type="text" className="mono" placeholder="D:\data\corpus  or  sftp://user@host/path" value={custom}
            onChange={(e) => { setCustom(e.target.value); setManual(null); }} /> : null}
        </label>
        <label className="pfield"><span className="pfield-label">policy</span>
          <select value={policy} onChange={(e) => { setPolicy(e.target.value); setManual(null); }} data-testid="start-policy">
            {[...new Set([DEFAULT_POLICY, ...policies])].map((p) => <option key={p} value={p}>{p}</option>)}
          </select></label>
        <label className="pfield"><span className="pfield-label">output folder</span>
          <input type="text" className="mono" placeholder={outDir} value={out} onChange={(e) => { setOut(e.target.value); setManual(null); }} data-testid="start-output" />
          <span className="pfield-help">empty = {outDir}</span></label>
        <label className="pfield"><span className="pfield-label">--limit</span>
          <input type="number" min={0} placeholder="all lines" value={limit} onChange={(e) => { setLimit(e.target.value); setManual(null); }} />
          <span className="pfield-help">lines per file, for a quick trial</span></label>
        <label className="pfield"><span className="pfield-label">topic field / mode</span>
          <span className="row" style={{ gap: 4 }}>
            <input type="text" placeholder="(none)" value={topicField} onChange={(e) => { setTopicField(e.target.value); setManual(null); }} style={{ width: 110 }} />
            <select value={topicMode} onChange={(e) => { setTopicMode(e.target.value); setManual(null); }}>
              <option value="">policy default</option><option value="hint">hint</option><option value="trust">trust</option><option value="off">off</option>
            </select></span></label>
      </div>
      <div className="row" style={{ marginTop: 8, flexWrap: "wrap" }}>
        <label className="faint" style={{ fontSize: 13 }} title="label every file again (without it, finished files are skipped)"><input type="checkbox" checked={overwrite} onChange={(e) => { setOverwrite(e.target.checked); setManual(null); }} /> --overwrite</label>
        <label className="faint" style={{ fontSize: 13 }} title="write <file>.clean.jsonl.zst: the training copy"><input type="checkbox" checked={clean} onChange={(e) => { setClean(e.target.checked); setManual(null); }} /> --write-clean</label>
        <label className="faint" style={{ fontSize: 13 }} title="the DeBERTa judge re-checks uncertain scores (slower)"><input type="checkbox" checked={judge} onChange={(e) => { setJudge(e.target.checked); setManual(null); }} /> judge</label>
        <label className="faint" style={{ fontSize: 13 }}>review paragraphs&nbsp;
          <select value={reviewAs} onChange={(e) => { setReviewAs(e.target.value); setManual(null); }}>
            <option value="">kept in the clean copy</option><option value="remove">cut (--review-as remove)</option>
          </select></label>
        <label className="faint" style={{ fontSize: 13 }} title="drop a whole document when more than this share of its tokens is cut (empty = off)">max removed share&nbsp;
          <input type="number" min={0} max={1} step={0.05} placeholder="off" value={maxShare} style={{ width: 70 }} data-testid="start-max-share"
            onChange={(e) => { setMaxShare(e.target.value); setManual(null); }} /></label>
        <label className="faint" style={{ fontSize: 13 }} title="drop a whole document when its first checked paragraph is cut"><input type="checkbox" checked={firstCut}
          onChange={(e) => { setFirstCut(e.target.checked); setManual(null); }} data-testid="start-first-cut" /> --drop-if-first-cut</label>
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        <textarea className="mono" rows={2} style={{ flex: "1 1 600px", fontSize: 12.5 }} value={cmd} spellCheck={false}
          onChange={(e) => setManual(e.target.value)} data-testid="start-command" />
      </div>
      <div className="row" style={{ marginTop: 6 }}>
        <button className="btn primary small" onClick={startCmd} disabled={job?.state === "running" || !src} data-testid="start-run">Start</button>
        {manual !== null ? <><span className="badge warn">edited by hand</span><button className="btn small ghost" onClick={() => setManual(null)}>back to the form</button></> : null}
      </div>
      <ErrorBox error={err} />
      {job ? <JobBox job={job} run={jobRun} onStop={stop} /> : null}
    </div>
  );
}

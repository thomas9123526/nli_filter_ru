"use client";
// Review queue: the lines most worth a human look, across every file of a dataset. Label them filter / keep:
// the labels go to the golden set golden/<dataset>.jsonl (a test file for nli_filter.py), never into the corpus.
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { api, useApi } from "@/lib/api";
import { href, num } from "@/lib/format";
import type { Params } from "@/lib/api";
import { LinesTable } from "./LinesTable";
import { CopyButton, Crumbs, ErrorBox, Loading } from "./ui";

type Queue = { key: string; label: string; help: string; params: Params };

const QUEUES: Queue[] = [
  { key: "close", label: "Close to a threshold",
    help: "Scored lines whose deciding score is nearest to its threshold (check 1, or check 2 when check 1 passed): a small change in the models or hypotheses would flip them. Unlabelled lines only.",
    params: { sort: "review", scored: true, labelled: false } },
  { key: "single", label: "One keyword decides",
    help: "Filtered lines with only one keyword (any number of hits of it), closest to the threshold first: if that keyword is wrong here, the whole decision is wrong.",
    params: { sort: "review", single_kw: true, decision: "filter" } },
  { key: "audit", label: "Level-A audit: models would keep",
    help: "Lines a level-A keyword filtered, where the rules / models (run with --audit-strict) would have kept them: is the A word too broad?",
    params: { audit: "keep" } },
  { key: "judge", label: "Decided by the judge",
    help: "Lines whose best check-1 pair was re-scored by the judge (the fast model was unsure), closest to the threshold first.",
    params: { sort: "review", judged: true } },
  { key: "mistakes", label: "Mistakes",
    help: "Lines with an expect label that the run decided differently.",
    params: { mismatch: true } },
];
const PAGE = 30;

export function ReviewView() {
  const sp = useSearchParams();
  const ds = sp.get("ds") || "";
  const [queue, setQueue] = useState(sp.get("queue") || "close");
  const [offset, setOffset] = useState(0);
  const [tick, setTick] = useState(0);
  const golden = useApi(ds ? `golden:${ds}:${tick}` : null, (s) => api.golden(ds, s));
  const q = QUEUES.find((x) => x.key === queue) || QUEUES[0];
  const params = { ...q.params, offset, limit: PAGE };
  const res = useApi(ds ? `review:${ds}:${queue}:${offset}` : null, (s) => api.lines(ds, params, s));
  if (!ds) return <div className="alert error">Missing ?ds=</div>;
  const d = res.data;
  const g = golden.data;
  const cmd = g ? `python nli_filter.py ${g.path.replace(/^.*[\\/](golden[\\/])/, "$1")} --output-dir out_golden_${ds}` : "";
  return (
    <>
      <div className="page-head">
        <div>
          <Crumbs items={[{ label: "Datasets", href: "/" }, { label: ds, href: href("/dataset", { ds }) }, { label: "review" }]} />
          <h1>Review {ds}</h1>
          <div className="sub">The lines most worth a look. Label them: the labels build a golden set (a test file) without touching the corpus.</div>
        </div>
      </div>
      <div className="panel" data-testid="golden-panel">
        <div className="row">
          <strong>Golden set</strong>
          {g ? <>
            <span className="badge neutral">{num(g.count)} labelled</span>
            {Object.entries(g.expect).map(([e, n]) => <span key={e} className={`badge ${e}`}>{e} {n}</span>)}
            <span className="faint mono" style={{ fontSize: 12 }}>{g.path}</span>
          </> : <Loading what="golden set" />}
        </div>
        {g && g.count ? (
          <div className="row" style={{ marginTop: 6 }}>
            <span className="faint" style={{ fontSize: 12 }}>Test the current keywords / hypotheses on it (from the project folder):</span>
            <code className="mono" style={{ fontSize: 12 }}>{cmd}</code>
            <CopyButton text={cmd} label="Copy" />
          </div>
        ) : null}
      </div>
      <div className="row" style={{ margin: "12px 0" }}>
        <span className="seg" data-testid="review-queues">
          {QUEUES.map((x) => <button key={x.key} className={queue === x.key ? "on" : ""} onClick={() => { setQueue(x.key); setOffset(0); }}>{x.label}</button>)}
        </span>
      </div>
      <div className="faint" style={{ fontSize: 13, marginBottom: 8 }}>{q.help}</div>
      <ErrorBox error={res.error} onRetry={res.reload} />
      {d?.pending ? <div className="alert">Indexing {d.pending} result file(s)… <button className="btn small" onClick={res.reload}>refresh</button></div> : null}
      {d ? (
        <div className="panel flush">
          <LinesTable ds={ds} rows={d.rows} thresholds={d.thresholds} onLabelled={() => setTick((t) => t + 1)} testid="review-lines" />
          <div className="row panel-body">
            <span className="faint">{d.total ? `${offset + 1}–${offset + d.rows.length} of ${num(d.total)}` : "nothing in this queue"}</span>
            <button className="btn small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>‹ prev</button>
            <button className="btn small" disabled={offset + PAGE >= d.total} onClick={() => setOffset(offset + PAGE)}>next ›</button>
            <span className="spacer" />
            <span className="faint" style={{ fontSize: 12 }}>thresholds of the latest run: check 1 ≥ {d.thresholds.check1}, check 2 ≥ {d.thresholds.check2}</span>
          </div>
        </div>
      ) : res.loading ? <Loading what="Finding lines" /> : null}
    </>
  );
}

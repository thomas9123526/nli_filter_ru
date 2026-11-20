"use client";
// One document of an nli_label.py run: the text with its labelled paragraphs, and for the chosen paragraph the flow
// gate → level 1 → level 2 → decision, with every score next to its threshold.
import { useSearchParams } from "next/navigation";
import { useState, type ReactElement } from "react";
import { api, useApi } from "@/lib/api";
import { href, num } from "@/lib/format";
import type { LabelDocResp, LabelParagraph, LabelPolicyLabel } from "@/lib/types";
import { Crumbs, ErrorBox, Loading, ScoreBar } from "./ui";
import { actionClass } from "./LabelRunView";

const REASONS: Record<string, string> = {
  gate_negative: "The gate label is below its threshold and there is no marker term: the keyword was incidental, the paragraph passes untouched.",
  narrative: "A level-2 narrative label is yes and nothing softens it: narratives win over 'keep' subjects.",
  conflict: "A 'remove' label and a 'keep' label are both yes: the policy's conflict rule decides.",
  remove_label: "A 'remove' subject label is yes and no 'keep' label is.",
  review_label: "A 'review' label is yes, or a narrative was softened by reports_or_debunks.",
  keep_label: "A 'keep' subject label is yes.",
  no_subject: "Russia-related (gate yes), but no subject label is yes: kept.",
};

function Level({ title, keys, p, pol, note, used }: { title: string; keys: string[]; p: LabelParagraph; pol: Record<string, LabelPolicyLabel>; note?: string; used: boolean }) {
  const scored = keys.filter((k) => p.scores[k] !== undefined);
  return (
    <div className={`flow-step${used ? "" : " unused"}`}>
      <div className="row"><strong>{title}</strong>{note ? <span className="faint" style={{ fontSize: 12 }}>{note}</span> : null}
        {!used && scored.length ? <span className="badge neutral">does not run for this paragraph: scores shown for information only</span> : null}</div>
      {scored.length === 0 ? <div className="faint" style={{ fontSize: 13 }}>not run for this paragraph</div> : (
        <table className="flow-table"><tbody>{keys.map((k) => {
          const l = pol[k]; const s = p.scores[k];
          const yes = s !== undefined && s >= l.threshold;
          return (
            <tr key={k} className={yes ? "yes" : ""}>
              <td style={{ width: "40%" }}><span className="mono" style={{ fontSize: 12 }}>{k}</span><div className="hyp">{l.hypothesis}</div></td>
              <td><span className={`badge ${actionClass(l.decision)}`}>{l.decision}</span></td>
              <td><ScoreBar value={s} threshold={l.threshold} />{p.judged?.includes(k) ? <span className="chip">judge</span> : null}</td>
              <td>{s === undefined ? <span className="faint">not scored</span> : yes ? <strong>yes</strong> : <span className="faint">no</span>}</td>
            </tr>);
        })}</tbody></table>
      )}
    </div>
  );
}

export type FlowPolicy = { labels: Record<string, LabelPolicyLabel>; run_if: Record<string, string[]> };

export function Flow({ policy, p }: { policy: FlowPolicy; p: LabelParagraph }) {
  const pol = policy.labels;
  const byLevel = (n: number) => Object.keys(pol).filter((k) => pol[k].level === n);
  const runIf = (n: number) => (policy.run_if[String(n)] || []).map((k) => (k === "@marker" ? "a marker term" : k)).join(" or ");
  const used = (n: number) => (p.levels ? p.levels.includes(n) : true);
  return (
    <div className="flow">
      <Level title="Level 0 · gate" keys={byLevel(0)} p={p} pol={pol} used={used(0)} note={p.marker ? "marker term in the paragraph: the gate is skipped" : undefined} />
      <div className="flow-arrow">↓</div>
      <Level title="Level 1 · subject" keys={byLevel(1)} p={p} pol={pol} used={used(1)} note={runIf(1) ? `runs when ${runIf(1)} is yes` : undefined} />
      <div className="flow-arrow">↓</div>
      <Level title="Level 2 · framing" keys={byLevel(2)} p={p} pol={pol} used={used(2)} note={runIf(2) ? `runs when ${runIf(2)} is yes` : undefined} />
      <div className="flow-arrow">↓</div>
      <div className="flow-step">
        <div className="row"><strong>Decision</strong><span className={`badge big ${actionClass(p.action)}`}>{p.action}</span>
          <span className="mono faint" style={{ fontSize: 12 }}>{p.reason}</span></div>
        <div style={{ marginTop: 6 }}>{REASONS[p.reason] || p.reason}</div>
        {p.labels.length ? <div style={{ marginTop: 6 }}>yes: {p.labels.map((l) => <span key={l} className="chip">{l}</span>)}</div> : null}
        {p.flags?.length ? <div style={{ marginTop: 6 }}>flagged (not removed): {p.flags.map((l) => <span key={l} className="chip">⚑ {l}</span>)}</div> : null}
      </div>
    </div>
  );
}

function DocText({ d, sel, onSel }: { d: LabelDocResp; sel: number; onSel: (i: number) => void }) {
  const text = d.text || "";
  const paras = d.row.paragraphs || [];
  const hits = (d.row.hits || []).filter((h) => !h.rule);
  const out: ReactElement[] = [];
  let pos = 0;
  const renderPlain = (a: number, b: number, key: string) => {
    const parts: ReactElement[] = [];
    let p0 = a;
    hits.filter((h) => h.span[0] >= a && h.span[1] <= b).forEach((h, i) => {
      if (h.span[0] > p0) parts.push(<span key={`${key}t${i}`}>{text.slice(p0, h.span[0])}</span>);
      parts.push(<span key={`${key}h${i}`} className="hit open">{text.slice(h.span[0], h.span[1])}</span>);
      p0 = h.span[1];
    });
    if (b > p0) parts.push(<span key={`${key}e`}>{text.slice(p0, b)}</span>);
    return parts;
  };
  paras.forEach((p, i) => {
    if (p.span[0] > pos) out.push(<span key={`g${i}`} className="faint">{renderPlain(pos, p.span[0], `g${i}`)}</span>);
    out.push(
      <span key={`p${i}`} className={`lpara ${p.action}${i === sel ? " sel" : ""}`} onClick={() => onSel(i)} title={`${p.action} (${p.reason}) — click for the flow`}>
        {renderPlain(p.span[0], p.span[1], `p${i}`)}
      </span>);
    pos = p.span[1];
  });
  if (pos < text.length) out.push(<span key="tail" className="faint">{renderPlain(pos, text.length, "tail")}</span>);
  return <div className="doc">{out}</div>;
}

export function LabelDocView() {
  const sp = useSearchParams();
  const run = sp.get("run") || "", file = sp.get("file") || "", line = Number(sp.get("line") || 0);
  const res = useApi(run && file && line ? `labeldoc:${run}:${file}:${line}` : null, (s) => api.labelDoc(run, { file, line }, s));
  const [sel, setSel] = useState(0);
  if (!run || !file || !line) return <div className="alert error">Missing ?run=, ?file= or ?line=</div>;
  const d = res.data;
  const paras = d?.row.paragraphs || [];
  return (
    <>
      <div className="page-head">
        <div>
          <Crumbs items={[{ label: "Datasets", href: "/" }, { label: "labels", href: "/labels" }, { label: run, href: href("/labelrun", { run, file }) }, { label: `line ${line}` }]} />
          <h1>{file} · line {line} {d ? <span className={`badge big ${actionClass(d.row.action)}`}>{d.row.action}</span> : null}</h1>
          {d ? <div className="sub">{num(d.row.tokens)} tokens (est.){d.row.tokens_removed ? `, ${num(d.row.tokens_removed)} removed` : ""}
            {d.row.rewrites ? `, ${d.row.rewrites} place name(s) rewritten` : ""}{d.row.id ? ` · id ${d.row.id}` : ""}</div> : null}
        </div>
      </div>
      <ErrorBox error={res.error} onRetry={res.reload} />
      {res.loading && !d ? <Loading what="Loading document" /> : null}
      {d ? (
        <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1.1fr) minmax(0, 1fr)", alignItems: "start" }}>
          <div className="panel flush">
            <div className="panel-head"><h2>Text</h2>
              <span className="legend"><span><i className="swatch lpara remove" />remove</span><span><i className="swatch lpara review" />review</span>
                <span><i className="swatch lpara keep" />keep</span><span><i className="swatch lpara pass" />pass</span></span></div>
            {d.problem ? <div className="alert" style={{ margin: 12 }}>{d.problem}</div> : null}
            {d.text !== null ? <DocText d={d} sel={sel} onSel={setSel} /> : null}
            {paras.length === 0 ? <div className="empty">No paragraph was labelled: {d.row.gate ? "" : "no keyword or marker hit (untouched)."}</div> : null}
          </div>
          <div className="panel">
            <div className="row" style={{ marginBottom: 8 }}><h2 style={{ margin: 0 }}>Flow</h2>
              {paras.length > 1 ? <span className="seg">{paras.map((p, i) => (
                <button key={i} className={i === sel ? "on" : ""} onClick={() => setSel(i)}>¶{i + 1} <span className={`badge ${actionClass(p.action)}`}>{p.action}</span></button>))}</span> : null}
            </div>
            {paras[sel] ? <Flow policy={d.policy} p={paras[sel]} /> : <div className="faint">Nothing to show.</div>}
          </div>
        </div>
      ) : null}
    </>
  );
}

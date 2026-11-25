"use client";
// The run page of a simple-mode run (nli_label.py run --output-mode simple): totals from the per-file summaries
// (untouched lines included), the decisions file filtered by decision / reason / keyword, and one line opened: its
// source text with the keywords marked, its evidence (paragraphs and scores) when the schema wrote it, and
// "Explain this line": the line checked again through the model service with the policy recorded in this run.
import Link from "next/link";
import { Fragment, useEffect, useState } from "react";
import { api, useApi } from "@/lib/api";
import { href, num, pct } from "@/lib/format";
import type { LabelRunResp, LabelTryResp, SimpleLineResp } from "@/lib/types";
import { Bars, Crumbs, ErrorBox, Loading, Stat } from "./ui";
import { ProgressBadge } from "./LabelsView";
import { actionClass } from "./LabelRunView";
import { TryTrace } from "./TryTrace";

const PAGE = 50;
const DOC_ACTIONS = ["untouched", "pass", "kept", "review", "edited", "removed", "error"];

function Marked({ text, hits }: { text: string; hits: SimpleLineResp["hits"] }) {
  const parts: React.ReactNode[] = [];
  let at = 0;
  hits.forEach((h, i) => {
    if (h.start < at) return;
    parts.push(text.slice(at, h.start));
    parts.push(<mark key={i} className={h.marker ? "mark-marker" : "mark-kw"} title={h.kw || ""}>{text.slice(h.start, h.end)}</mark>);
    at = h.end;
  });
  parts.push(text.slice(at));
  return <div className="doc-text" style={{ whiteSpace: "pre-wrap" }}>{parts}</div>;
}

function LinePanel({ run, file, line, onClose }: { run: string; file: string; line: number; onClose: () => void }) {
  const res = useApi(`simpleline:${run}:${file}:${line}`, (s) => api.simpleLine(run, { file, line }, s));
  const [ex, setEx] = useState<LabelTryResp | null>(null);
  const [exErr, setExErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [para, setPara] = useState<number | null>(null);
  useEffect(() => { setEx(null); setExErr(null); setPara(null); }, [line, file]);
  const d = res.data;
  const st = (d?.settings || {}) as Record<string, unknown>;
  const explain = async () => {
    if (!d?.text) return;
    setBusy(true); setExErr(null);
    try {
      const judge = String(st.judge_model || "deberta");
      const r = await api.labelTry({
        texts: [d.text], ...(d.policy_data ? { policy_data: d.policy_data } : { policy: d.policy_path || undefined }),
        all_labels: !!st.all_labels, use_judge: judge.toLowerCase() !== "none",
        decision_unit: String(st.decision_unit || "paragraph"), review_as: String(st.review_as || "keep"),
        ...(Array.isArray(st.uncertain_band) ? { uncertain_band: st.uncertain_band as number[] } : {}),
      });
      setEx(r);
      const row = r.rows[0];
      setPara(row?.decided_by ?? (row?.paragraphs?.length ? 0 : null));
    } catch (e) { setExErr((e as Error).message); }
    setBusy(false);
  };
  const exRow = ex?.rows[0];
  return (
    <div className="panel" style={{ marginBottom: 16 }} data-testid="simple-line">
      <div className="row" style={{ flexWrap: "wrap" }}>
        <h2 style={{ margin: 0 }}>{file} · line {line}</h2>
        <span className="spacer" />
        <button className="btn small primary" disabled={!d?.text || busy} onClick={explain} data-testid="simple-explain"
          title="check this line again through the model service, with the policy and settings this run recorded">{busy ? "Checking…" : "Explain this line"}</button>
        <button className="btn small ghost" onClick={onClose}>close ✕</button>
      </div>
      <ErrorBox error={res.error} onRetry={res.reload} />
      {res.loading && !d ? <Loading what="Loading the line" /> : null}
      {d ? (<>
        {d.row ? <div className="mono" style={{ fontSize: 12, margin: "6px 0" }}>{JSON.stringify(d.row)}</div> : null}
        {d.problem ? <div className="alert">{d.problem}</div> : null}
        {d.text ? <Marked text={d.text} hits={d.hits} /> : null}
        {d.evidence?.paragraphs?.length ? (
          <div style={{ marginTop: 10 }} data-testid="simple-evidence">
            <strong>Evidence</strong> <span className="faint" style={{ fontSize: 12 }}>stored by the run: every checked paragraph</span>
            <div className="table-wrap"><table>
              <thead><tr><th>Characters</th><th>Action</th><th>Reason</th><th>Labels</th><th>Text</th></tr></thead>
              <tbody>{d.evidence.paragraphs.map((p, i) => (
                <tr key={i} className={d.evidence?.decided_by === i ? "active" : ""}>
                  <td className="mono">{p.span[0]}–{p.span[1]}</td>
                  <td><span className={`badge ${actionClass(p.action)}`}>{p.action}</span></td>
                  <td>{p.reason}{p.exception ? <> · <code>{p.exception}</code></> : null}{p.non_english?.length ? <> · non-English: {p.non_english.map((x) => x.term).join(", ")}</> : null}</td>
                  <td>{p.labels.map((k) => <code key={k} style={{ marginRight: 4 }}>{k}</code>)}</td>
                  <td className="faint" style={{ fontSize: 12, maxWidth: 420 }}>{d.text ? d.text.slice(p.span[0], Math.min(p.span[1], p.span[0] + 220)) + (p.span[1] - p.span[0] > 220 ? "…" : "") : ""}</td>
                </tr>))}</tbody>
            </table></div>
          </div>) : <div className="faint" style={{ fontSize: 12, marginTop: 8 }}>
            No stored evidence for this line{st.evidence === "none" || !st.evidence ? " (the schema's evidence is none)" : ""}: use Explain this line.</div>}
        {exErr ? <div className="alert error" style={{ marginTop: 8 }}>{exErr}</div> : null}
        {ex && exRow && d.text ? (
          <div style={{ marginTop: 12 }} data-testid="simple-explained">
            <div className="row" style={{ flexWrap: "wrap" }}>
              <strong>Checked again</strong>
              <span className={`badge ${actionClass(exRow.decision || exRow.action)}`}>{exRow.decision || exRow.action}</span>
              <span className="faint" style={{ fontSize: 12 }}>policy {d.policy_path || "as recorded"} · {ex.seconds}s · models {ex.models.fast}{ex.models.judge ? ` + ${ex.models.judge}` : ""}</span>
              {(exRow.paragraphs || []).length > 1 ? (
                <span className="seg">{(exRow.paragraphs || []).map((p, i) => (
                  <button key={i} className={para === i ? "on" : ""} onClick={() => setPara(i)}>¶{i + 1} {p.action}</button>))}</span>) : null}
            </div>
            {para !== null && exRow.paragraphs?.[para] ? (
              <TryTrace res={ex} p={exRow.paragraphs[para]} text={d.text} row={exRow} docAction={exRow.action} />
            ) : <div className="faint">No paragraph was checked (no keyword or marker): {exRow.action}.</div>}
          </div>) : null}
      </>) : null}
    </div>
  );
}

export function SimpleRunView({ run, d }: { run: string; d: LabelRunResp }) {
  const st = d.summary.stats;
  const set = (d.summary.settings || {}) as Record<string, unknown>;
  const [file, setFile] = useState(d.files[0]?.name || "");
  const [decision, setDecision] = useState("");
  const [reason, setReason] = useState("");
  const [keyword, setKeyword] = useState("");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  const rows = useApi(file ? `simplerows:${run}:${file}:${decision}:${reason}:${keyword}:${offset}` : null,
    (s) => api.simpleRows(run, { file, decision, reason, keyword, offset, limit: PAGE }, s));
  useEffect(() => { setOpen(null); }, [file, decision, reason, keyword, offset]);
  const r = rows.data;
  const reset = () => setOffset(0);
  return (
    <>
      <div className="page-head"><div>
        <Crumbs items={[{ label: "Labelling", href: "/label" }, { label: run }]} />
        <h1>{run} <ProgressBadge p={d.progress || null} /></h1>
        <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
          <span className="badge accent" data-testid="simple-badge">simple mode</span>
          <span className="badge neutral">decision unit: {String(set.decision_unit || "paragraph")}</span>
          <span className="badge neutral">evidence: {String(set.evidence || "none")}</span>
          <span className="faint" style={{ fontSize: 12 }}>schema {String(set.schema || "output/simple_schema.json")} ·{" "}
            <Link href={href("/label/output", {})}>edit the schema →</Link></span>
        </div>
        <div className="sub mono" style={{ fontSize: 12 }}>{d.summary.command}</div>
      </div></div>
      {st ? (<>
        <div className="stats">
          <Stat label="Lines" value={num(st.lines)} />
          <Stat label="Tokens (est.)" value={num(st.tokens)} />
          <Stat label="Tokens removed" value={num(st.tokens_removed)} note={pct(st.tokens_removed, st.tokens)} />
          <Stat label="Checked paragraphs" value={num(Object.values(st.paragraphs || {}).reduce((a, b) => a + b, 0))} />
        </div>
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))", marginBottom: 16 }}>
          <div className="panel"><h2>Lines by action</h2>
            <Bars items={DOC_ACTIONS.filter((a) => st.docs[a]).map((a) => [a, st.docs[a]] as [string, number])} total={st.lines} /></div>
          <div className="panel"><h2>Paragraph reasons</h2>
            <div className="faint" style={{ fontSize: 12 }}>{Object.entries(st.reasons || {}).map(([k, v]) => `${k} ${v}`).join(", ") || "none"}</div>
            {(st as unknown as { non_english?: Record<string, number> }).non_english ? (
              <div className="faint" style={{ fontSize: 12, marginTop: 6 }}>non-English hits: {Object.entries((st as unknown as { non_english: Record<string, number> }).non_english).map(([k, v]) => `${k} ${v}`).join(", ")}</div>) : null}
          </div>
        </div></>) : null}

      <div className="panel flush">
        <div className="panel-head" style={{ flexWrap: "wrap" }}>
          <h2>Lines</h2>
          <select value={file} onChange={(e) => { setFile(e.target.value); reset(); }} data-testid="simple-file">
            {d.files.map((f) => <option key={f.name} value={f.name}>{f.name} ({num(f.lines || 0)})</option>)}</select>
          <select value={decision} onChange={(e) => { setDecision(e.target.value); reset(); }} data-testid="simple-decision">
            <option value="">every decision</option>
            {Object.entries(r?.counts.decision || {}).map(([k, v]) => <option key={k} value={k}>{k} ({num(v)})</option>)}</select>
          <select value={reason} onChange={(e) => { setReason(e.target.value); reset(); }} data-testid="simple-reason">
            <option value="">every reason</option>
            {Object.entries(r?.counts.reason || {}).map(([k, v]) => <option key={k} value={k}>{k} ({num(v)})</option>)}</select>
          <select value={keyword} onChange={(e) => { setKeyword(e.target.value); reset(); }} data-testid="simple-keyword">
            <option value="">every keyword</option>
            {Object.entries(r?.counts.keyword || {}).map(([k, v]) => <option key={k} value={k}>{k} ({num(v)} lines)</option>)}</select>
          <span className="faint" style={{ fontSize: 12 }}>{r ? `${num(r.total)} rows` : ""}</span>
        </div>
        <ErrorBox error={rows.error} onRetry={rows.reload} />
        {rows.loading && !r ? <Loading what="Loading rows" /> : null}
        {r && !r.can_open ? <div className="panel-body faint">The schema has no &quot;line&quot; field: rows cannot be opened.</div> : null}
        {r ? (
          <div className="table-wrap"><table data-testid="simple-rows">
            <thead><tr><th>Line</th><th>Decision</th><th>Reason</th><th>Keywords</th><th>Row as written</th></tr></thead>
            <tbody>{r.rows.map((x, i) => (
              <Fragment key={i}>
                <tr className={open !== null && open === x.line ? "active" : ""}>
                  <td>{x.line !== null && r.can_open ? <button className="linklike" onClick={() => setOpen(open === x.line ? null : x.line)}>{x.line}</button> : (x.line ?? "–")}</td>
                  <td>{x.decision ? <span className={`badge ${actionClass(x.decision)}`}>{x.decision}</span> : null}</td>
                  <td>{x.reason}</td>
                  <td>{Object.entries(x.keywords).slice(0, 8).map(([k, v]) => <span key={k} className="chip">{k}{v > 1 ? ` ×${v}` : ""}</span>)}</td>
                  <td className="mono faint" style={{ fontSize: 11.5, maxWidth: 420, overflowWrap: "anywhere" }}>{JSON.stringify(x.row)}</td>
                </tr>
                {open !== null && open === x.line ? (
                  <tr><td colSpan={5}><LinePanel run={run} file={file} line={x.line} onClose={() => setOpen(null)} /></td></tr>) : null}
              </Fragment>))}</tbody>
          </table></div>) : null}
        {r && r.total > PAGE ? (
          <div className="row" style={{ padding: "8px 12px" }}>
            <button className="btn small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>← previous</button>
            <span className="faint" style={{ fontSize: 12 }}>{offset + 1}–{Math.min(offset + PAGE, r.total)} of {num(r.total)}</span>
            <button className="btn small" disabled={offset + PAGE >= r.total} onClick={() => setOffset(offset + PAGE)}>next →</button>
          </div>) : null}
      </div>
    </>
  );
}

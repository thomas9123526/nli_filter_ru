"use client";
// One nli_label.py run: token composition, labels, and the documents (filter by action / label) → a document's flow.
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api, useApi } from "@/lib/api";
import { href, num, pct } from "@/lib/format";
import { Bars, Crumbs, ErrorBox, Loading, Stat } from "./ui";
import { ProgressBadge } from "./LabelsView";

const DOC_ACTIONS = ["untouched", "pass", "kept", "review", "edited", "removed", "error"];
const PARA_ACTIONS = ["remove", "review", "keep", "pass"];
const PAGE = 40;
export const actionClass = (a: string) =>
  a === "remove" || a === "removed" || a === "edited" ? "filter" : a === "review" ? "warn" : a === "keep" || a === "kept" ? "keep" : "neutral";

export function LabelRunView() {
  const sp = useSearchParams();
  const run = sp.get("run") || "";
  const res = useApi(run ? `labelrun:${run}` : null, (s) => api.labelRun(run, s));
  const [file, setFile] = useState(sp.get("file") || "");
  const [action, setAction] = useState("");
  const [label, setLabel] = useState("");
  const [paraAction, setParaAction] = useState("");
  const [offset, setOffset] = useState(0);
  const [expect, setExpect] = useState("");  // "" | "wrong" | "right" (test corpora with expected results)
  const [labelsOpen, setLabelsOpen] = useState(true);  // the Labels panel (folded state kept in this browser)
  const [labelQuery, setLabelQuery] = useState("");
  useEffect(() => { try { setLabelsOpen(localStorage.getItem("nli.labelrun.labelsOpen") !== "0"); } catch { /* no storage */ } }, []);
  const toggleLabels = () => setLabelsOpen((o) => {
    try { localStorage.setItem("nli.labelrun.labelsOpen", o ? "0" : "1"); } catch { /* no storage */ }
    return !o;
  });
  const f = file || res.data?.files[0]?.name || "";
  const docs = useApi(run && f ? `labeldocs:${run}:${f}:${action}:${label}:${paraAction}:${offset}:${expect}` : null,
    (s) => api.labelDocs(run, { file: f, action, label, para_action: paraAction, offset, limit: PAGE, ...(expect ? { expect } : {}) }, s));
  const exp = useApi(run ? `labelexp:${run}` : null, (s) => api.labelExpected(run, s));
  const ex = exp.data?.expected;
  if (!run) return <div className="alert error">Missing ?run=</div>;
  const d = res.data;
  const st = d?.summary.stats;
  const pol = d?.summary.policy?.labels || {};
  const reset = () => setOffset(0);

  return (
    <>
      <div className="page-head">
        <div>
          <Crumbs items={[{ label: "Datasets", href: "/" }, { label: "labels", href: "/labels" }, { label: run }]} />
          <h1>{run} <ProgressBadge p={d?.progress || null} /></h1>
          <div className="sub mono" style={{ fontSize: 12 }}>{d?.summary.command}</div>
        </div>
      </div>
      <ErrorBox error={res.error} onRetry={res.reload} />
      {res.loading && !d ? <Loading what="Loading run" /> : null}
      {d?.summary.redecide ? (
        <div className="alert">Redecided from {d.summary.redecide.from}: {num(d.summary.redecide.stored)} stored scores reused,
          {" "}{num(d.summary.redecide.missing)} missing (treated as No){d.summary.redecide.changed?.length ? `; reworded: ${d.summary.redecide.changed.join(", ")}` : ""}.</div>
      ) : null}
      {ex ? (
        <div className="panel flush" style={{ marginBottom: 16 }} data-testid="expected-panel">
          <div className="panel-head"><h2>Expected vs result</h2>
            <span className={`badge ${ex.ok === ex.n ? "keep" : "warn"}`}>{ex.ok} / {ex.n} as expected ({ex.n ? Math.round(100 * ex.ok / ex.n) : 0} %)</span>
            <span className="faint" style={{ fontSize: 12 }}>from the expected actions in the corpus (also fine counted; pass = untouched)</span></div>
          {ex.wrong.length ? (
            <div className="table-wrap"><table>
              <thead><tr><th>File</th><th>Line</th><th>Expected</th><th>Got</th><th>Note</th><th></th></tr></thead>
              <tbody>{ex.wrong.map((w) => (
                <tr key={`${w.file}:${w.line}`}>
                  <td><button className="linklike" onClick={() => { setFile(w.file); setExpect(""); setOffset(0); }}>{w.file}</button></td>
                  <td><Link href={href("/labeldoc", { run, file: w.file, line: w.line })}>{w.line}</Link></td>
                  <td><span className={`badge ${actionClass(w.expected)}`}>{w.expected}</span>{w.acceptable.length ? <span className="faint"> (also {w.acceptable.join(", ")})</span> : null}</td>
                  <td><span className={`badge ${actionClass(w.got)}`}>{w.got}</span>{w.paragraphs_wrong ? <span className="faint"> · {w.paragraphs_wrong} paragraph{w.paragraphs_wrong > 1 ? "s" : ""} not as expected</span> : null}</td>
                  <td className="faint" style={{ fontSize: 12 }}>{w.note}</td>
                  <td><Link className="btn small" href={href("/labeltry", { run, file: w.file, line: w.line, para: 0 })}>Try</Link></td>
                </tr>))}</tbody>
            </table></div>) : <div className="panel-body faint">Every line matches its expected result.</div>}
        </div>) : null}
      {st ? (
        <>
          <div className="stats">
            <Stat label="Documents" value={num(st.lines)} />
            <Stat label="Tokens (est.)" value={num(st.tokens)} />
            <Stat label="Tokens removed" value={num(st.tokens_removed)} note={pct(st.tokens_removed, st.tokens)} />
            <Stat label="Paragraphs labelled" value={num(Object.values(st.paragraphs || {}).reduce((a, b) => a + b, 0))} />
            <Stat label="Place-name rewrites" value={num(st.rewrites)} />
          </div>
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))", marginBottom: 16 }}>
            <div className="panel"><h2>Documents by action (tokens)</h2>
              <Bars items={DOC_ACTIONS.filter((a) => st.doc_tokens[a]).map((a) => [a, st.doc_tokens[a]] as [string, number])} total={st.tokens} />
            </div>
            <div className="panel"><h2>Paragraphs by action</h2>
              <Bars items={PARA_ACTIONS.filter((a) => st.paragraphs[a]).map((a) => [a, st.paragraphs[a]] as [string, number])}
                total={Object.values(st.paragraphs).reduce((a, b) => a + b, 0)} />
              <div className="faint" style={{ fontSize: 12, marginTop: 8 }}>reasons: {Object.entries(st.reasons).map(([k, v]) => `${k} ${v}`).join(", ")}</div>
            </div>
          </div>
          <div className="panel flush" style={{ marginBottom: 16 }} data-testid="labels-panel">
            <div className="panel-head">
              <button className="linklike" onClick={toggleLabels} aria-expanded={labelsOpen} data-testid="labels-toggle"
                title={labelsOpen ? "fold the labels away" : "show the labels"}>
                <h2 style={{ margin: 0 }}>{labelsOpen ? "▾" : "▸"} Labels</h2></button>
              <span className="faint" style={{ fontSize: 12 }}>{Object.keys(pol).length} labels; positive paragraphs; click a label to list its documents</span>
              <span className="spacer" />
              {labelsOpen ? (
                <input type="search" value={labelQuery} onChange={(e) => setLabelQuery(e.target.value)} data-testid="labels-search"
                  placeholder="search label, hypothesis, decision, level…" style={{ minWidth: 260 }} />) : null}
            </div>
            {labelsOpen ? (() => {
              const q = labelQuery.trim().toLowerCase();
              const rows = Object.entries(pol).filter(([k, l]) => !q ||
                [k, l.hypothesis, l.decision, `level ${l.level}`, String(l.level)].some((x) => String(x || "").toLowerCase().includes(q)));
              return (<>
            <div className="table-wrap"><table>
              <thead><tr><th>Label</th><th>Level</th><th>Decision</th><th className="right">Threshold</th><th className="right">Paragraphs</th><th className="right">Tokens</th></tr></thead>
              <tbody>{rows.map(([k, l]) => (
                <tr key={k} className={label === k ? "active" : ""}>
                  <td><button className="linklike" onClick={() => { setLabel(label === k ? "" : k); reset(); }}><strong>{k}</strong></button>
                    <div className="hyp">{l.hypothesis}</div></td>
                  <td>{l.level}</td><td><span className={`badge ${actionClass(l.decision)}`}>{l.decision}</span></td>
                  <td className="right mono">{l.threshold}</td>
                  <td className="right">{num(st.label_paragraphs[k] || 0)}</td><td className="right">{num(st.label_tokens[k] || 0)}</td>
                </tr>))}</tbody>
            </table></div>
            {q && !rows.length ? <div className="panel-body faint">No label matches “{labelQuery}”.</div> : null}
            {q && rows.length ? <div className="panel-body faint" style={{ fontSize: 12 }}>{rows.length} of {Object.keys(pol).length} labels</div> : null}
              </>);
            })() : null}
          </div>
        </>
      ) : null}

      {d ? (
        <div className="panel flush">
          <div className="toolbar">
            {d.files.length > 1 ? (
              <select value={f} onChange={(e) => { setFile(e.target.value); reset(); }}>
                {d.files.map((x) => <option key={x.name} value={x.name}>{x.name} ({num(x.lines)})</option>)}
              </select>
            ) : <strong>{f}</strong>}
            <span className="seg">
              <button className={action === "" ? "on" : ""} onClick={() => { setAction(""); reset(); }}>all</button>
              {DOC_ACTIONS.filter((a) => a !== "untouched" && (docs.data?.counts[a] || st?.docs[a])).map((a) => (
                <button key={a} className={action === a ? "on" : ""} onClick={() => { setAction(a); reset(); }}>{a} {docs.data?.counts[a] ?? ""}</button>))}
            </span>
            <label className="faint" style={{ fontSize: 13 }}>has a paragraph&nbsp;
              <select value={paraAction} onChange={(e) => { setParaAction(e.target.value); reset(); }}>
                <option value="">any</option>{PARA_ACTIONS.map((a) => <option key={a}>{a}</option>)}
              </select></label>
            {label ? <span className="chip">label {label} <button className="linklike" onClick={() => { setLabel(""); reset(); }}>×</button></span> : null}
            {docs.data?.expected || expect ? (
              <span className="seg" data-testid="expect-filter">
                <button className={expect === "" ? "on" : ""} onClick={() => { setExpect(""); reset(); }}>expected: any</button>
                <button className={expect === "wrong" ? "on" : ""} onClick={() => { setExpect("wrong"); reset(); }}>✗ not as expected</button>
                <button className={expect === "right" ? "on" : ""} onClick={() => { setExpect("right"); reset(); }}>✓ as expected</button>
              </span>) : null}
            {docs.data?.expected ? <span className="faint" style={{ fontSize: 12 }}>{docs.data.expected.ok} / {docs.data.expected.n} in this file</span> : null}
          </div>
          <ErrorBox error={docs.error} onRetry={docs.reload} />
          {docs.data ? (
            <>
              <div className="table-wrap"><table data-testid="label-docs">
                <thead><tr><th>Line</th><th>Action</th>{docs.data.expected ? <th>Expected</th> : null}<th>Paragraphs</th><th>Labels</th><th>Keywords</th><th className="right">Tokens removed</th><th></th></tr></thead>
                <tbody>{docs.data.rows.map((r) => (
                  <tr key={r.line}>
                    <td><Link href={href("/labeldoc", { run, file: f, line: r.line })}>{r.line}</Link><div className="faint mono" style={{ fontSize: 11 }}>{r.id || ""}</div></td>
                    <td><span className={`badge ${actionClass(r.action)}`}>{r.action}</span></td>
                    {docs.data!.expected ? (
                      <td>{r.expect ? (<>
                        <span className={r.expect.ok ? "badge keep" : "badge filter"} title={r.expect.note}>{r.expect.ok ? "✓" : "✗"}</span>{" "}
                        <span className={`badge ${actionClass(r.expect.expected)}`}>{r.expect.expected}</span>
                        {r.expect.kind === "text" ? <span className="faint"> got {r.expect.got}</span> : null}
                        {r.expect.paragraphs?.some((p) => !p.ok) ? <span className="faint"> · {r.expect.paragraphs.filter((p) => !p.ok).length} ¶ ✗</span> : null}
                      </>) : <span className="faint">–</span>}</td>) : null}
                    <td>{PARA_ACTIONS.filter((a) => r.paragraphs[a]).map((a) => <span key={a} className={`badge ${actionClass(a)}`} style={{ marginRight: 4 }}>{a} {r.paragraphs[a]}</span>)}</td>
                    <td>{r.labels.map((l) => <span key={l} className="chip">{l}</span>)}{r.flags.map((l) => <span key={l} className="chip">⚑ {l}</span>)}</td>
                    <td className="faint">{r.keywords.join(", ")}</td>
                    <td className="right">{r.tokens_removed ? `${num(r.tokens_removed)} / ${num(r.tokens)}` : "–"}</td>
                    <td className="right"><Link className="btn small" data-testid="row-try" title="open this document's first paragraph on the Try page (its case, the run's policy)"
                      href={href("/labeltry", { run, file: f, line: r.line, para: 0 })}>Try</Link></td>
                  </tr>))}</tbody>
              </table></div>
              <div className="row panel-body">
                <span className="faint">{docs.data.total ? `${offset + 1}–${offset + docs.data.rows.length} of ${num(docs.data.total)} documents with a keyword` : "no documents match"}</span>
                <button className="btn small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>‹ prev</button>
                <button className="btn small" disabled={offset + PAGE >= docs.data.total} onClick={() => setOffset(offset + PAGE)}>next ›</button>
              </div>
            </>
          ) : docs.loading ? <Loading what="Loading documents" /> : null}
        </div>
      ) : null}
    </>
  );
}

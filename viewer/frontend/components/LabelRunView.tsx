"use client";
// One nli_label.py run: token composition, labels, and the documents (filter by action / label) → a document's flow.
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Fragment, useEffect, useState } from "react";
import { api, useApi } from "@/lib/api";
import { formatSet, parseSet, useRestoreScroll, useUrlState } from "@/lib/urlState";
import { href, num, pct } from "@/lib/format";
import { Bars, Crumbs, ErrorBox, Loading, Stat } from "./ui";
import { ProgressBadge } from "./LabelsView";
import { RunTools } from "./RunTools";
import { LineText } from "./LineText";
import { SimpleRunView } from "./SimpleRunView";
import { ExpectBadge, ExpectedPanel } from "./ExpectedPanel";

const DOC_ACTIONS = ["untouched", "pass", "kept", "review", "edited", "removed", "error"];
const PARA_ACTIONS = ["remove", "review", "keep", "pass"];
const PAGE = 40;
export const actionClass = (a: string) =>
  a === "remove" || a === "removed" || a === "edited" ? "filter" : a === "review" ? "warn" : a === "keep" || a === "kept" ? "keep" : "neutral";

export function LabelRunView() {
  const sp = useSearchParams();
  const run = sp.get("run") || "";
  const res = useApi(run ? `labelrun:${run}` : null, (s) => api.labelRun(run, s));
  // the view is kept in the URL (file, filters, page, opened rows, expected profile): Back and copied links show it again
  const [u, setU] = useUrlState({ file: "", action: "", label: "", para_action: "", expect: "", offset: "0", open: "", profile: "" });
  const file = u.file, action = u.action, label = u.label, paraAction = u.para_action, expect = u.expect, profile = u.profile;
  const offset = parseInt(u.offset, 10) || 0;
  const openLines = parseSet(u.open);  // rows whose full text is shown (▸)
  const setFile = (v: string) => setU({ file: v, offset: "0", open: "" });
  const setAction = (v: string) => setU({ action: v, offset: "0", open: "" });
  const setLabel = (v: string) => setU({ label: v, offset: "0", open: "" });
  const setParaAction = (v: string) => setU({ para_action: v, offset: "0", open: "" });
  const setExpect = (v: string) => setU({ expect: v, offset: "0", open: "" });
  const setOffset = (v: number) => setU({ offset: String(v), open: "" });
  const setOpenLines = (x: Set<number> | ((o: Set<number>) => Set<number>)) =>
    setU({ open: formatSet(typeof x === "function" ? x(openLines) : x) });
  const [labelsOpen, setLabelsOpen] = useState(true);  // the Labels panel (folded state kept in this browser)
  const [labelQuery, setLabelQuery] = useState("");
  useEffect(() => { try { setLabelsOpen(localStorage.getItem("nli.labelrun.labelsOpen") !== "0"); } catch { /* no storage */ } }, []);
  const toggleLabels = () => setLabelsOpen((o) => {
    try { localStorage.setItem("nli.labelrun.labelsOpen", o ? "0" : "1"); } catch { /* no storage */ }
    return !o;
  });
  const f = file || res.data?.files[0]?.name || "";
  const simple = res.data?.summary.settings?.output_mode === "simple";  // simple mode: its own page
  const docs = useApi(run && f && res.data && !simple ? `labeldocs:${run}:${f}:${action}:${label}:${paraAction}:${offset}:${expect}:${profile}` : null,
    (s) => api.labelDocs(run, { file: f, action, label, para_action: paraAction, offset, limit: PAGE, ...(expect ? { expect } : {}), profile }, s));
  useEffect(() => {  // ?expand=1: every row's text open
    if (sp.get("expand") === "1" && docs.data) setU({ expand: undefined, open: formatSet(new Set(docs.data.rows.map((r) => r.line))) } as never);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docs.data, sp]);
  useRestoreScroll(!!docs.data && !simple);
  if (!run) return <div className="alert error">Missing ?run=</div>;
  const d = res.data;
  if (d && simple) return <SimpleRunView run={run} d={d} />;
  const st = d?.summary.stats;
  const pol = d?.summary.policy?.labels || {};
  const reset = () => { /* the setters above go back to the first page */ };
  const backUrl = (ln: number) => {  // the document page's "back to the run" returns to this view, at this row
    const q = new URLSearchParams(sp.toString());
    q.set("from_line", String(ln));
    return `/label/run/?${q.toString()}`;
  };
  const toggleLine = (ln: number) => setOpenLines((o) => { const x = new Set(o); if (x.has(ln)) x.delete(ln); else x.add(ln); return x; });

  return (
    <>
      <div className="page-head">
        <div>
          <Crumbs items={[{ label: "Labelling", href: "/label" }, { label: run }]} />
          <h1>{run} <ProgressBadge p={d?.progress || null} /></h1>
          <div className="sub mono" style={{ fontSize: 12 }}>{d?.summary.command}</div>
          {d?.summary.settings?.decision_unit === "line" ? (
            <div className="row" style={{ marginTop: 4 }}><span className="badge accent" data-testid="unit-line">decision unit: line</span>
              <span className="faint" style={{ fontSize: 12 }}>the strictest paragraph decides the whole line (kept whole or removed whole)</span></div>) : null}
        </div>
      </div>
      <ErrorBox error={res.error} onRetry={res.reload} />
      {res.loading && !d ? <Loading what="Loading run" /> : null}
      {d ? <RunTools run={run} policy={d.summary.policy?.path} /> : null}
      {d?.summary.redecide ? (
        <div className="alert">Redecided from {d.summary.redecide.from}: {num(d.summary.redecide.stored)} stored scores reused,
          {" "}{num(d.summary.redecide.missing)} missing (treated as No){d.summary.redecide.changed?.length ? `; reworded: ${d.summary.redecide.changed.join(", ")}` : ""}.</div>
      ) : null}
      {d ? <ExpectedPanel run={run} profile={profile} setProfile={(p) => setU({ profile: p })}
        onFile={(x) => setU({ file: x, expect: "", offset: "0", open: "" })} /> : null}
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
                <thead><tr><th style={{ width: 22 }}><button className="row-toggle" data-testid="toggle-all" title={openLines.size ? "collapse all" : "show every line's text on this page"}
                  onClick={() => setOpenLines(openLines.size ? new Set() : new Set(docs.data!.rows.map((r) => r.line)))}>{openLines.size ? "▾" : "▸"}</button></th>
                  <th>Line</th><th>Action</th>{docs.data.expected ? <th>Expected</th> : null}<th>Paragraphs</th><th>Labels</th><th>Keywords</th><th className="right">Tokens removed</th><th></th></tr></thead>
                <tbody>{docs.data.rows.map((r) => (
                  <Fragment key={r.line}>
                  <tr data-line={r.line} id={`line-${r.line}`}>
                    <td><button className="row-toggle" data-testid={`toggle-${r.line}`} title={openLines.has(r.line) ? "hide the text" : "show the full text"}
                      onClick={() => toggleLine(r.line)}>{openLines.has(r.line) ? "▾" : "▸"}</button></td>
                    <td><Link href={href("/label/doc", { run, file: f, line: r.line, back: backUrl(r.line) })}>{r.line}</Link><div className="faint mono" style={{ fontSize: 11 }}>{r.id || ""}</div></td>
                    <td><span className={`badge ${actionClass(r.action)}`}>{r.action}</span></td>
                    {docs.data!.expected ? (
                      <td>{r.expect ? (<>
                        <ExpectBadge v={r.expect} />
                        {r.expect.paragraphs?.some((p) => !p.ok) ? <span className="faint"> · {r.expect.paragraphs.filter((p) => !p.ok).length} ¶ ✗</span> : null}
                      </>) : <span className="faint">–</span>}</td>) : null}
                    <td>{PARA_ACTIONS.filter((a) => r.paragraphs[a]).map((a) => <span key={a} className={`badge ${actionClass(a)}`} style={{ marginRight: 4 }}>{a} {r.paragraphs[a]}</span>)}</td>
                    <td>{r.labels.map((l) => <span key={l} className="chip">{l}</span>)}{r.flags.map((l) => <span key={l} className="chip">⚑ {l}</span>)}</td>
                    <td className="faint">{r.keywords.join(", ")}</td>
                    <td className="right">{r.tokens_removed ? `${num(r.tokens_removed)} / ${num(r.tokens)}` : "–"}</td>
                    <td className="right"><Link className="btn small" data-testid="row-try" title="open this document's first paragraph on the Try page (its case, the run's policy)"
                      href={href("/label/try", { run, file: f, line: r.line, para: 0 })}>Try</Link>{" "}
                      <Link className="btn small ghost" data-testid="row-lab" title="open this line on the Experiment page (change any setting, compare with the run's policy)"
                      href={href("/label/lab", { run, file: f, line: r.line })}>Experiment</Link></td>
                  </tr>
                  {openLines.has(r.line) ? <tr className="line-text-row"><td colSpan={docs.data!.expected ? 9 : 8}><LineText run={run} file={f} line={r.line} /></td></tr> : null}
                  </Fragment>))}</tbody>
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

"use client";
// Two runs of the same corpus side by side (/label/compare?a=&b=): document and paragraph totals, which actions
// moved (e.g. keep → review), and every changed line with its paragraphs before and after.
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Fragment, useState } from "react";
import { backHere, useRestoreScroll, useUrlState } from "@/lib/urlState";
import { LineText } from "./LineText";
import { api, useApi } from "@/lib/api";
import { href, num } from "@/lib/format";
import type { CompareParagraph } from "@/lib/types";
import { Crumbs, ErrorBox, Loading } from "./ui";
import { actionClass } from "./LabelRunView";
import { LabLink } from "./LabLink";

const DOCS = ["untouched", "pass", "kept", "review", "edited", "removed", "error"];
const PARAS = ["remove", "review", "keep", "pass"];
const PAGE = 50;

function Para({ p }: { p: CompareParagraph }) {
  if (!p) return <span className="faint">not checked</span>;
  return (
    <span>
      <span className={`badge ${actionClass(p.action)}`}>{p.action}</span>{" "}
      <span className="faint mono" style={{ fontSize: 11 }}>{p.reason}</span>{" "}
      {p.labels.map((l) => <span key={l} className="chip">{l}</span>)}
      {p.exception ? <span className="chip">exception {p.exception}</span> : null}
    </span>
  );
}

function delta(a: number, b: number) {
  const d = b - a;
  return d === 0 ? <span className="faint">0</span> : <strong style={{ color: d > 0 ? "var(--filter)" : "var(--keep)" }}>{d > 0 ? `+${num(d)}` : num(d)}</strong>;
}

export function CompareView() {
  const sp = useSearchParams();
  const router = useRouter();
  const a = sp.get("a") || "", b = sp.get("b") || "";
  const change = sp.get("change") || "";
  const [u, setU] = useUrlState({ offset: "0" });  // the page of changed lines is in the URL too (Back returns to it)
  const offset = parseInt(u.offset, 10) || 0;
  const setOffset = (v: number) => setU({ offset: String(v) });
  const [openText, setOpenText] = useState<Set<string>>(new Set());
  const runs = useApi("labelruns:cmp", (s) => api.labelRuns(s));
  const res = useApi(a && b ? `cmp:${a}:${b}:${change}:${offset}` : null,
    (s) => api.labelCompare({ a, b, change: change || null, offset, limit: PAGE }, s));
  const d = res.data;
  const names = (runs.data?.runs || []).map((r) => r.name);
  useRestoreScroll(!!d);
  const go = (p: Record<string, string | null>) => { router.replace(href("/label/compare", { a, b, change: change || null, ...p })); };

  return (
    <>
      <div className="page-head">
        <div>
          <Crumbs items={[{ label: "Labelling", href: "/label" }, { label: "compare runs" }]} />
          <h1>Compare two runs</h1>
          <div className="sub">Same corpus, two policies (or two settings): what changed, paragraph by paragraph.</div>
          <div className="row" style={{ marginTop: 8 }}>
            <label className="faint" style={{ fontSize: 13 }}>A&nbsp;<select value={a} onChange={(e) => go({ a: e.target.value, change: null })} data-testid="cmp-a">
              <option value="">choose…</option>{names.map((n) => <option key={n} value={n}>{n}</option>)}</select></label>
            <button className="btn small ghost" onClick={() => go({ a: b, b: a })} title="swap A and B">⇄</button>
            <label className="faint" style={{ fontSize: 13 }}>B&nbsp;<select value={b} onChange={(e) => go({ b: e.target.value, change: null })} data-testid="cmp-b">
              <option value="">choose…</option>{names.map((n) => <option key={n} value={n}>{n}</option>)}</select></label>
          </div>
        </div>
      </div>
      <ErrorBox error={res.error} onRetry={res.reload} />
      {res.loading && !d ? <Loading what="Comparing" /> : null}
      {d ? (
        <div className="stack">
          {d.notes.map((n) => <div key={n} className="alert warn">{n}</div>)}
          <div className="panel">
            <div className="row" style={{ flexWrap: "wrap" }}>
              <span>A <Link href={href("/label/run", { run: d.a })}><strong>{d.a}</strong></Link> <span className="faint mono" style={{ fontSize: 12 }}>{d.policy.a}</span></span>
              <span>B <Link href={href("/label/run", { run: d.b })}><strong>{d.b}</strong></Link> <span className="faint mono" style={{ fontSize: 12 }}>{d.policy.b}</span>
                {d.redecide.b?.from ? <span className="badge neutral">redecided from {d.redecide.b.from}</span> : null}</span>
            </div>
            <div className="faint" style={{ marginTop: 6, fontSize: 13 }} data-testid="cmp-summary">
              {num(d.files)} file{d.files === 1 ? "" : "s"}, {num(d.lines)} lines compared · <strong>{num(d.changed_lines)}</strong> line{d.changed_lines === 1 ? "" : "s"} changed
              {d.only_a.length ? ` · only in A: ${d.only_a.join(", ")}` : ""}{d.only_b.length ? ` · only in B: ${d.only_b.join(", ")}` : ""}
            </div>
            <div className="row" style={{ marginTop: 10, alignItems: "flex-start", flexWrap: "wrap", gap: 24 }}>
              <table className="cmp-table"><thead><tr><th>documents</th><th className="right">A</th><th className="right">B</th><th className="right">B − A</th></tr></thead>
                <tbody>{DOCS.filter((k) => d.totals.a.docs[k] || d.totals.b.docs[k]).map((k) => (
                  <tr key={k}><td><span className={`badge ${actionClass(k)}`}>{k}</span></td><td className="right mono">{num(d.totals.a.docs[k] || 0)}</td>
                    <td className="right mono">{num(d.totals.b.docs[k] || 0)}</td><td className="right">{delta(d.totals.a.docs[k] || 0, d.totals.b.docs[k] || 0)}</td></tr>))}</tbody></table>
              <table className="cmp-table"><thead><tr><th>paragraphs</th><th className="right">A</th><th className="right">B</th><th className="right">B − A</th></tr></thead>
                <tbody>{PARAS.filter((k) => d.totals.a.paragraphs[k] || d.totals.b.paragraphs[k]).map((k) => (
                  <tr key={k}><td><span className={`badge ${actionClass(k)}`}>{k}</span></td><td className="right mono">{num(d.totals.a.paragraphs[k] || 0)}</td>
                    <td className="right mono">{num(d.totals.b.paragraphs[k] || 0)}</td><td className="right">{delta(d.totals.a.paragraphs[k] || 0, d.totals.b.paragraphs[k] || 0)}</td></tr>))}</tbody></table>
            </div>
            <div style={{ marginTop: 10 }} data-testid="cmp-moves">
              <strong style={{ fontSize: 13 }}>What moved</strong> <span className="faint" style={{ fontSize: 12 }}>(click to show only those)</span>
              <div className="row" style={{ flexWrap: "wrap", gap: 6, marginTop: 4 }}>
                <button className={`btn small${!change ? " primary" : ""}`} onClick={() => go({ change: null })}>all changes</button>
                {Object.entries(d.paragraph_moves).map(([m, n]) => (
                  <button key={m} className={`btn small${change === m ? " primary" : ""}`} onClick={() => go({ change: m })}>¶ {m.replace(">", " → ")} <span className="faint">{num(n)}</span></button>))}
                {Object.entries(d.doc_moves).map(([m, n]) => (
                  <button key={m} className={`btn small${change === `doc:${m}` ? " primary" : ""}`} onClick={() => go({ change: `doc:${m}` })}>doc {m.replace(">", " → ")} <span className="faint">{num(n)}</span></button>))}
                {!Object.keys(d.paragraph_moves).length && !Object.keys(d.doc_moves).length ? <span className="faint">nothing changed</span> : null}
              </div>
            </div>
          </div>
          {d.items.length ? (
            <div className="panel flush">
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Line</th><th>Document</th><th>Paragraph</th><th>A</th><th>B</th></tr></thead>
                  <tbody>
                    {d.items.map((it) => { const key = `${it.file}:${it.line}`; return (<Fragment key={key}>{(it.paragraphs.length ? it.paragraphs : [null]).map((p, k) => (
                      <tr key={`${it.file}:${it.line}:${k}`} data-line={k === 0 ? it.line : undefined}>
                        {k === 0 ? <td rowSpan={Math.max(1, it.paragraphs.length)}>
                          <span className="mono" style={{ fontSize: 12 }}>{it.file}</span> · {it.line}
                          <div className="faint mono" style={{ fontSize: 11 }}>{it.id || ""}</div>
                          <div style={{ fontSize: 12 }}><Link href={href("/label/doc", { run: d.a, file: it.file, line: it.line })}
                            onClick={(e) => { e.preventDefault(); router.push(href("/label/doc", { run: d.a, file: it.file, line: it.line, back: backHere(it.line) })); }}>A</Link>{" · "}
                            <Link href={href("/label/doc", { run: d.b, file: it.file, line: it.line })}
                            onClick={(e) => { e.preventDefault(); router.push(href("/label/doc", { run: d.b, file: it.file, line: it.line, back: backHere(it.line) })); }}>B</Link>{" · "}
                            <button className="linklike" data-testid={`cmp-text-${it.line}`} onClick={() => setOpenText((o) => { const x = new Set(o); if (x.has(key)) x.delete(key); else x.add(key); return x; })}>
                              text {openText.has(key) ? "▾" : "▸"}</button>{" · "}
                            <LabLink params={{ run: d.b, file: it.file, line: it.line }} line={it.line}>Experiment</LabLink></div></td> : null}
                        {k === 0 ? <td rowSpan={Math.max(1, it.paragraphs.length)}>
                          <span className={`badge ${actionClass(it.doc.a)}`}>{it.doc.a}</span> → <span className={`badge ${actionClass(it.doc.b)}`}>{it.doc.b}</span></td> : null}
                        <td className="mono" style={{ fontSize: 12 }}>{p ? `${p.span[0]}–${p.span[1]}` : "–"}</td>
                        <td>{p ? <Para p={p.a} /> : <span className="faint">same paragraphs</span>}</td>
                        <td>{p ? <Para p={p.b} /> : null}</td>
                      </tr>))}
                      {openText.has(key) ? <tr className="line-text-row"><td colSpan={5}><LineText run={d.b} file={it.file} line={it.line} /></td></tr> : null}
                    </Fragment>); })}
                  </tbody>
                </table>
              </div>
              <div className="row" style={{ padding: "10px 16px" }}>
                <span className="faint">{num(d.offset + 1)}–{num(d.offset + d.items.length)} of {num(d.total)} changed lines</span>
                <button className="btn small" disabled={d.offset === 0} onClick={() => setOffset(Math.max(0, d.offset - PAGE))}>‹ prev</button>
                <button className="btn small" disabled={d.offset + d.items.length >= d.total} onClick={() => setOffset(d.offset + PAGE)}>next ›</button>
              </div>
            </div>) : <div className="empty">No changed lines{change ? " for this filter" : ""}.</div>}
        </div>) : null}
      {!a || !b ? <div className="empty">Choose two runs of the same corpus (A and B).</div> : null}
    </>
  );
}

"use client";
// Documents test set editor (/label/docs/?file=labels/russia_llm_docs_v1.json): multi-paragraph test documents, each
// paragraph with its expected action. The document text and its expected document action follow from the
// paragraphs. Checked while editing (as tools/build_russia_llm_docs.py checks: every paragraph must stay a paragraph
// when the document is split); saved with a backup, then the corpus (dataset/test_corpus_docs_ru) is rebuilt.
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { getJSON, postJSON, useApi } from "@/lib/api";
import { href } from "@/lib/format";
import { Crumbs, ErrorBox, Loading } from "./ui";
import { actionClass } from "./LabelRunView";

const ACTIONS = ["remove", "review", "keep", "pass", "none"];
type Para = { text: string; expected_action: string; acceptable?: string[]; note?: string };
type Doc = { id: string; group: string; file: string; title: string; text?: string; paragraphs: Para[]; expected_doc_action?: string; [k: string]: unknown };
type DocsData = { file: string; sha: string; min_chars: number; policy?: string; corpus?: string; about?: string; docs: Doc[]; [k: string]: unknown };
type Check = { ok: boolean; errors: string[]; doc_actions: (string | null)[] };

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40) || "doc";

export function DocsEditView() {
  const sp = useSearchParams();
  const file = sp.get("file") || "labels/russia_llm_docs_v1.json";
  const [tick, setTick] = useState(0);
  const res = useApi(`docsset:${file}:${tick}`, (s) => getJSON<DocsData>("/api/labels/docs", { file }, s));
  const [draft, setDraft] = useState<DocsData | null>(null);
  const [di, setDi] = useState(0);
  const [check, setCheck] = useState<Check | null>(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const data = draft ?? res.data;
  const docs = data?.docs || [];
  const doc = docs[di];
  const minChars = data?.min_chars ?? 200;

  useEffect(() => {
    if (!draft) return;
    const t = setTimeout(() => { postJSON<Check>("/api/labels/docs/check", { file, data: draft }).then(setCheck).catch(() => undefined); }, 400);
    return () => clearTimeout(t);
  }, [draft, file]);
  useEffect(() => {
    if (!draft) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [draft]);

  const edit = (fn: (d: DocsData) => void) => { if (!data) return; const d = clone(data); fn(d); setDraft(d); setMsg(null); setErr(null); };
  const editDoc = (fn: (x: Doc) => void) => edit((d) => fn(d.docs[di]));
  const groups = useMemo(() => {
    const g: [string, { d: Doc; i: number }[]][] = [];
    docs.forEach((d, i) => { const last = g[g.length - 1]; if (last && last[0] === d.group) last[1].push({ d, i }); else g.push([d.group, [{ d, i }]]); });
    return g;
  }, [docs]);
  const addDoc = () => {
    const group = doc?.group || "new_group";
    edit((d) => {
      const n = d.docs.length + 1;
      const id = `doc${String(n).padStart(2, "0")}_new`;
      d.docs.splice(di + 1, 0, { id, group, file: `new_${n}`, title: "New document",
        paragraphs: [{ text: "", expected_action: "keep", note: "" }] });
    });
    setDi(di + 1);
  };
  const save = async () => {
    if (!draft) return;
    setSaving(true); setErr(null); setMsg(null);
    try {
      const r = await postJSON<{ file: string; backup: string; docs: number; paragraphs: number; corpus: string }>("/api/labels/docs/save",
        { file, data: draft, base_sha: res.data?.sha });
      setMsg(`Saved ${r.file}: ${r.docs} documents, ${r.paragraphs} paragraphs (old version: ${r.backup}); ${r.corpus} rebuilt.`);
      setDraft(null); setCheck(null); setTick((t) => t + 1);
    } catch (e) { setErr((e as Error).message); }
    setSaving(false);
  };
  const docAction = (i: number) => (draft && check?.doc_actions[i]) || docs[i]?.expected_doc_action || "?";

  return (
    <>
      <div className="page-head">
        <div>
          <Crumbs items={[{ label: "Labelling", href: "/label" }, { label: "documents test set" }]} />
          <h1>Documents test set</h1>
          <div className="sub">{file}: {docs.length} multi-paragraph documents, an expected action per paragraph; the document&apos;s expected action follows
            from them. Policy {data?.policy || "?"}; corpus <code className="mono">dataset/{data?.corpus || "?"}</code> (rebuilt on Save).
            {" "}<Link href="/label">Run it from the Labelling page →</Link></div>
          <div className="row" style={{ marginTop: 6 }}>
            {draft ? <span className="badge warn">unsaved changes</span> : <span className="faint" style={{ fontSize: 12 }}>no changes</span>}
            {draft && check ? (check.ok ? <span className="badge keep">valid</span> : <span className="badge remove">{check.errors.length} problem{check.errors.length === 1 ? "" : "s"}</span>) : null}
            <button className="btn small primary" disabled={!draft || saving || (check ? !check.ok : false)} onClick={save} data-testid="docs-save">{saving ? "Saving…" : `Save ${file}`}</button>
            <button className="btn small" disabled={!draft} onClick={() => { setDraft(null); setCheck(null); }}>Discard</button>
            {msg ? <span className="faint" style={{ fontSize: 12 }} data-testid="docs-saved">{msg}</span> : null}
          </div>
          {draft && check?.errors.length ? <ul className="policy-errors">{check.errors.map((e) => <li key={e}>{e}</li>)}</ul> : null}
          {err ? <div className="alert error" style={{ marginTop: 6 }}>{err}</div> : null}
        </div>
      </div>
      <ErrorBox error={res.error} onRetry={res.reload} />
      {!data && res.loading ? <Loading what="Loading the documents" /> : null}
      {data ? (
        <div className="try-grid">
          <div className="panel flush case-list" data-testid="docs-list">
            {groups.map(([g, items], gi) => (
              <div key={`${gi}:${g}`}>
                <div className="case-group">{g}</div>
                {items.map(({ d, i }) => (
                  <button key={`${i}:${d.id}`} className={`case-item${i === di ? " on" : ""}`} onClick={() => setDi(i)}>
                    <span>{d.title}<span className="faint mono case-file-name"> {d.file}</span></span>
                    <span className={`badge ${actionClass(docAction(i))}`} style={{ fontSize: 10.5 }}>{docAction(i)}</span>
                  </button>))}
              </div>))}
            <div style={{ padding: 8 }}><button className="btn small" onClick={addDoc} data-testid="docs-add">+ new document after this one</button></div>
          </div>

          {doc ? (
            <div className="panel" data-testid="docs-editor">
              <div className="pgrid">
                <label className="pfield"><span className="pfield-label">id</span><input type="text" className="mono" value={doc.id} onChange={(e) => editDoc((x) => { x.id = e.target.value; })} /></label>
                <label className="pfield"><span className="pfield-label">group</span>
                  <input type="text" className="mono" list="docs-groups" value={doc.group} onChange={(e) => editDoc((x) => { x.group = e.target.value; })} />
                  <datalist id="docs-groups">{[...new Set(docs.map((d) => d.group))].map((g) => <option key={g} value={g} />)}</datalist>
                  <span className="pfield-help">a folder of the corpus</span></label>
                <label className="pfield"><span className="pfield-label">file</span><input type="text" className="mono" value={doc.file} onChange={(e) => editDoc((x) => { x.file = e.target.value; })} />
                  <span className="pfield-help">{doc.group}/{doc.file}.jsonl.zst</span></label>
                <label className="pfield"><span className="pfield-label">title</span><input type="text" value={doc.title}
                  onChange={(e) => editDoc((x) => { const auto = x.file.startsWith("new_"); x.title = e.target.value; if (auto) x.file = slug(e.target.value); })} /></label>
              </div>
              <div className="row" style={{ marginTop: 8 }}>
                <span>Expected document action: <span className={`badge ${actionClass(docAction(di))}`}>{docAction(di)}</span></span>
                <span className="faint" style={{ fontSize: 12 }}>from the paragraphs (a remove paragraph → edited; all removed → removed; a review → review; …)</span>
              </div>
              {doc.paragraphs.map((p, k) => {
                const short = p.text.trim().length > 0 && p.text.trim().length < minChars;
                const setP = (fn: (x: Para) => void) => editDoc((x) => fn(x.paragraphs[k]));
                return (
                  <div key={k} className="docs-para" data-testid={`docs-para-${k}`}>
                    <div className="row">
                      <strong>¶ {k + 1}</strong>
                      <select className={`badge ${actionClass(p.expected_action)}`} value={p.expected_action} onChange={(e) => setP((x) => { x.expected_action = e.target.value; })}>
                        {ACTIONS.map((a) => <option key={a} value={a}>{a}</option>)}</select>
                      <span className="faint" style={{ fontSize: 12 }}>also fine:</span>
                      {ACTIONS.filter((a) => a !== p.expected_action).map((a) => (
                        <label key={a} className="faint" style={{ fontSize: 12 }}><input type="checkbox" checked={(p.acceptable || []).includes(a)}
                          onChange={(e) => setP((x) => { const s = new Set(x.acceptable || []); if (e.target.checked) s.add(a); else s.delete(a); x.acceptable = [...s]; })} /> {a}</label>))}
                      <span className="spacer" />
                      <span className={short ? "badge warn" : "faint"} style={{ fontSize: 11.5 }} title={short ? `shorter than ${minChars}: it would be joined to the next paragraph` : ""}>{p.text.trim().length} chars</span>
                      <button className="btn small ghost" disabled={k === 0} onClick={() => editDoc((x) => { const [m] = x.paragraphs.splice(k, 1); x.paragraphs.splice(k - 1, 0, m); })} title="move up">↑</button>
                      <button className="btn small ghost" disabled={k === doc.paragraphs.length - 1} onClick={() => editDoc((x) => { const [m] = x.paragraphs.splice(k, 1); x.paragraphs.splice(k + 1, 0, m); })} title="move down">↓</button>
                      <button className="btn small ghost danger" disabled={doc.paragraphs.length === 1} onClick={() => editDoc((x) => { x.paragraphs.splice(k, 1); })} title="delete this paragraph">✕</button>
                    </div>
                    <textarea rows={4} value={p.text} onChange={(e) => setP((x) => { x.text = e.target.value; })} style={{ width: "100%", marginTop: 4 }} />
                    <input type="text" placeholder="note (why this action)" value={p.note || ""} onChange={(e) => setP((x) => { x.note = e.target.value; })} style={{ width: "100%" }} />
                    <button className="btn small ghost" style={{ marginTop: 4 }} onClick={() => editDoc((x) => { x.paragraphs.splice(k + 1, 0, { text: "", expected_action: "keep", note: "" }); })}>+ paragraph after this one</button>
                  </div>);
              })}
              <div className="row" style={{ marginTop: 10 }}>
                <span className="faint" style={{ fontSize: 12 }}>Every paragraph needs at least {minChars} characters (the policy&apos;s paragraph size), else it is joined to the next one.</span>
                <span className="spacer" />
                <button className="btn small ghost danger" disabled={docs.length === 1} onClick={() => {
                  if (!window.confirm(`Delete the document “${doc.title}”?`)) return;
                  edit((d) => { d.docs.splice(di, 1); }); setDi(Math.max(0, di - 1));
                }}>Delete document</button>
              </div>
            </div>) : null}
        </div>) : null}
    </>
  );
}

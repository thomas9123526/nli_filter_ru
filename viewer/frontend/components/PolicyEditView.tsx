"use client";
// Policy editor (/label/policy/?file=policy/<name>.json): every setting of a labelling policy as a form, or the raw
// JSON. Checked while you type with nli_label.py's own rules; saved with a backup (policy/.backup/), refused when the
// file changed since it was loaded. "Try these changes" opens the Try page with the unsaved policy.
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, useApi } from "@/lib/api";
import { href } from "@/lib/format";
import type { PolicyCheck, PolicyData, PolicyExceptionData, PolicyLabelData } from "@/lib/types";
import { Crumbs, ErrorBox, Loading } from "./ui";
import { actionClass } from "./LabelRunView";

export const POLICY_DRAFT_KEY = "nli.policy.draft";  // the unsaved policy handed to the Try page
const DECISIONS = ["gate", "keep", "review", "remove", "flag"];
const ACTIONS3 = ["keep", "review", "remove"];
const KEY_RE = /^[a-z][a-z0-9_]*$/;

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const toLines = (t: string) => t.split("\n").map((x) => x.trim()).filter(Boolean);
const toList = (t: string) => t.split(/[,\n]/).map((x) => x.trim()).filter(Boolean);
const asList = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : v ? [String(v)] : []);

export function readPolicyDraft(): { path: string; data: PolicyData; at: number } | null {
  try {
    const v = JSON.parse(localStorage.getItem(POLICY_DRAFT_KEY) || "null");
    return v && v.data && v.path ? v : null;
  } catch { return null; }
}

export function PolicyEditView() {
  const sp = useSearchParams();
  const router = useRouter();
  const policies = useApi("labelpolicies", (s) => api.labelPolicies(s));
  const list = policies.data?.policies || [];
  const file = sp.get("file") || (list.includes("policy/russia_llm_policy_v2.json") ? "policy/russia_llm_policy_v2.json" : list[0] || "");
  const [tick, setTick] = useState(0);
  const raw = useApi(file ? `policyraw:${file}:${tick}` : null, (s) => api.policyRaw(file, s));
  const [draft, setDraft] = useState<PolicyData | null>(null);
  const [tab, setTab] = useState<"form" | "json">("form");
  const [check, setCheck] = useState<PolicyCheck | null>(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [saveAs, setSaveAs] = useState("");
  const data = draft ?? raw.data?.data ?? null;
  const dirty = draft !== null;

  useEffect(() => { setDraft(null); setMsg(null); setErr(null); setCheck(null); }, [file]);
  useEffect(() => { if (raw.data && !draft) setCheck(raw.data.check); }, [raw.data, draft]);
  useEffect(() => {  // check the edited policy as you type (nli_label.py's rules, on the server)
    if (!draft) return;
    const ctl = new AbortController();
    const t = setTimeout(() => { api.policyCheck(draft, ctl.signal).then(setCheck).catch(() => undefined); }, 350);
    return () => { clearTimeout(t); ctl.abort(); };
  }, [draft]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const edit = (fn: (d: PolicyData) => void) => {
    if (!data) return;
    const d = clone(data);
    fn(d);
    setDraft(d); setMsg(null); setErr(null);
  };

  const save = async (as?: string) => {
    if (!data) return;
    setSaving(true); setErr(null); setMsg(null);
    try {
      const target = as ? (as.startsWith("policy/") ? as : `policy/${as}`).replace(/(\.json)?$/, ".json") : undefined;
      const r = await api.policySave({ path: file, data, base_sha: raw.data?.sha, save_as: target });
      setMsg(`Saved ${r.path}${r.backup ? ` (old version: ${r.backup})` : ""}${r.warnings.length ? ` · ${r.warnings.join("; ")}` : ""}`);
      setDraft(null); setSaveAs("");
      if (target) { policies.reload(); router.replace(href("/label/policy", { file: r.path })); } else setTick((n) => n + 1);
    } catch (e) { setErr((e as Error).message); }
    setSaving(false);
  };

  const tryIt = () => {
    if (!data) return;
    try { localStorage.setItem(POLICY_DRAFT_KEY, JSON.stringify({ path: file, data, at: Date.now() })); } catch { /* private window */ }
    window.open(href("/label/try", { policy_draft: 1 }), "_blank");
  };

  return (
    <>
      <div className="page-head">
        <div>
          <Crumbs items={[{ label: "Labelling", href: "/label" }, { label: "policy editor" }]} />
          <h1>Edit a policy</h1>
          <div className="sub">Every setting of the policy file. Checked with nli_label.py&apos;s own rules while you type; a save keeps
            the old file in <code className="mono">policy/.backup/</code>. Runs and Try use the file as soon as it is saved.</div>
          <div className="row" style={{ marginTop: 8 }}>
            <label className="faint" style={{ fontSize: 13 }}>policy&nbsp;
              <select value={file} data-testid="policy-file" onChange={(e) => {
                if (dirty && !window.confirm("Unsaved policy changes will be lost. Switch anyway?")) return;
                router.replace(href("/label/policy", { file: e.target.value }));
              }}>
                {list.map((p) => <option key={p} value={p}>{p}</option>)}
              </select></label>
            <span className="seg">
              <button className={tab === "form" ? "on" : ""} onClick={() => setTab("form")}>Form</button>
              <button className={tab === "json" ? "on" : ""} onClick={() => setTab("json")}>JSON</button>
            </span>
          </div>
        </div>
      </div>

      <div className="panel policy-bar" data-testid="policy-bar">
        <div className="row">
          {dirty ? <span className="badge warn">unsaved changes</span> : <span className="faint" style={{ fontSize: 12 }}>no changes</span>}
          {check ? (check.ok ? <span className="badge keep" data-testid="policy-ok">valid</span>
            : <span className="badge remove" data-testid="policy-invalid">{check.errors.length} problem{check.errors.length === 1 ? "" : "s"}</span>) : null}
          <button className="btn small primary" disabled={!dirty || saving || !check?.ok} onClick={() => save()} data-testid="policy-save">
            {saving ? "Saving…" : `Save ${file}`}</button>
          <button className="btn small" disabled={!dirty || saving} onClick={() => { setDraft(null); setCheck(raw.data?.check || null); }}>Discard</button>
          <span className="faint" style={{ fontSize: 12 }}>or save as</span>
          <input type="text" placeholder="russia_llm_policy_v3.json" value={saveAs} onChange={(e) => setSaveAs(e.target.value)} style={{ width: 210 }} data-testid="policy-save-as" />
          <button className="btn small" disabled={!saveAs.trim() || saving || !check?.ok} onClick={() => save(saveAs.trim())}>Save as new</button>
          <button className="btn small" disabled={!data || !check?.ok} onClick={tryIt} title="open the Try page (new tab) with this policy, saved or not" data-testid="policy-try">Try these changes →</button>
        </div>
        {check?.errors.length ? <ul className="policy-errors" data-testid="policy-errors">{check.errors.map((e) => <li key={e}>{e}</li>)}</ul> : null}
        {check?.warnings.length ? <ul className="policy-warnings">{check.warnings.map((e) => <li key={e}>{e}</li>)}</ul> : null}
        {msg ? <div className="faint" style={{ fontSize: 12, marginTop: 6 }} data-testid="policy-saved">{msg}</div> : null}
        {err ? <div className="alert error" style={{ marginTop: 6 }}>{err}</div> : null}
      </div>

      <ErrorBox error={raw.error} onRetry={raw.reload} />
      {!data && (raw.loading || policies.loading) ? <Loading what="Loading the policy" /> : null}
      {data && tab === "json" ? <JsonTab data={data} onChange={(d) => { setDraft(d); setMsg(null); }} /> : null}
      {data && tab === "form" ? (
        <div className="stack">
          <General d={data} edit={edit} policyPath={file} />
          <Labels d={data} edit={edit} />
          <RunIf d={data} edit={edit} />
          <Exceptions d={data} edit={edit} />
          <Topics d={data} edit={edit} />
          <Other d={data} />
        </div>) : null}
    </>
  );
}

type Ed = { d: PolicyData; edit: (fn: (d: PolicyData) => void) => void };

function Field({ label, help, children }: { label: string; help?: string; children: React.ReactNode }) {
  return (
    <label className="pfield"><span className="pfield-label">{label}</span>{children}{help ? <span className="pfield-help">{help}</span> : null}</label>
  );
}

/** A text box that edits a list (one item per line), kept as typed until it loses focus. */
function ListBox({ value, onChange, rows = 3, placeholder }: { value: string[]; onChange: (v: string[]) => void; rows?: number; placeholder?: string }) {
  const [t, setT] = useState(value.join("\n"));
  useEffect(() => { setT(value.join("\n")); }, [value.join("\n")]);  // eslint-disable-line react-hooks/exhaustive-deps
  return <textarea className="mono" rows={rows} value={t} placeholder={placeholder} onChange={(e) => setT(e.target.value)} onBlur={() => onChange(toLines(t))} />;
}

function General({ d, edit, policyPath }: Ed & { policyPath?: string }) {
  return (
    <section className="panel">
      <h2>General</h2>
      <div className="pgrid">
        <Field label="no_subject" help="the gate is open but no level-1 / level-2 label is positive (plain facts)">
          <select value={d.no_subject || "keep"} onChange={(e) => edit((x) => { x.no_subject = e.target.value; })} data-testid="pol-no-subject">
            {ACTIONS3.map((a) => <option key={a} value={a}>{a}</option>)}</select></Field>
        <Field label="conflict" help="a level-1 'remove' and a 'keep' label are both positive">
          <select value={d.conflict || "review"} onChange={(e) => edit((x) => { x.conflict = e.target.value; })}>
            {ACTIONS3.map((a) => <option key={a} value={a}>{a}</option>)}</select></Field>
        <Field label="narrative_opens_gate" help="a positive level-2 'remove' label opens the gate (hate that names no country)">
          <input type="checkbox" checked={!!d.narrative_opens_gate} onChange={(e) => edit((x) => { x.narrative_opens_gate = e.target.checked; })} /></Field>
        <Field label="country"><input type="text" value={d.country || ""} onChange={(e) => edit((x) => { x.country = e.target.value; })} /></Field>
        <Field label="paragraph min_chars"><input type="number" value={d.paragraphs?.min_chars ?? 200} onChange={(e) => edit((x) => { x.paragraphs = { ...(x.paragraphs || {}), min_chars: Number(e.target.value) }; })} /></Field>
        <Field label="paragraph max_chars"><input type="number" value={d.paragraphs?.max_chars ?? 2000} onChange={(e) => edit((x) => { x.paragraphs = { ...(x.paragraphs || {}), max_chars: Number(e.target.value) }; })} /></Field>
      </div>
      <div className="pgrid" style={{ marginTop: 10 }}>
        <Field label="markers" help="one per line: slurs that open the gate and always get the full check">
          <ListBox value={asList(d.markers)} rows={5} onChange={(v) => edit((x) => { x.markers = v; })} /></Field>
        <Field label="keywords_file" help="one file per line (relative to the project)">
          <ListBox value={asList(d.keywords_file)} rows={3} onChange={(v) => edit((x) => { x.keywords_file = v.length === 1 ? v[0] : v; })} /></Field>
        <Field label="rewrite_place_names" help="clean copy: place names to their Russian form">
          <input type="checkbox" checked={!!d.rewrite_place_names} onChange={(e) => edit((x) => { x.rewrite_place_names = e.target.checked; })} /></Field>
        <Field label="place_names_file"><input type="text" value={d.place_names_file || ""} onChange={(e) => edit((x) => { x.place_names_file = e.target.value || null; })} /></Field>
        <Field label="place_name_exceptions_file"><input type="text" value={d.place_name_exceptions_file || ""} onChange={(e) => edit((x) => { x.place_name_exceptions_file = e.target.value || null; })} /></Field>
        <Field label="non_english_file" help="keywords / markers in other scripts (Arabic …): check as usual or remove. Empty = off">
          <input type="text" placeholder="policy/non_english.json" value={String(d.non_english_file || "")} data-testid="pol-non-english"
            onChange={(e) => edit((x) => { if (e.target.value) x.non_english_file = e.target.value; else delete x.non_english_file; })} /></Field>
      </div>
      <div className="row" style={{ margin: "8px 0", flexWrap: "wrap" }}>
        <Link className="btn small" href={href("/label/files", { policy: policyPath || null })} data-testid="pol-files-link">
          Edit the keyword lists and place-name files →</Link>
        <Link className="btn small" href={href("/label/non-english", { file: (d.non_english_file as string) || null })} data-testid="pol-non-english-link">
          Edit the non-English setting →</Link></div>
      <Field label="about"><textarea rows={3} value={d.about || ""} onChange={(e) => edit((x) => { x.about = e.target.value; })} /></Field>
    </section>
  );
}

function Labels({ d, edit }: Ed) {
  const [newKey, setNewKey] = useState<Record<number, string>>({});
  const keys = Object.keys(d.labels || {});
  const rename = (old: string, nk: string) => edit((x) => {
    if (!KEY_RE.test(nk) || nk === old || x.labels[nk]) return;
    const labels: Record<string, PolicyLabelData> = {};
    for (const [k, v] of Object.entries(x.labels)) labels[k === old ? nk : k] = v;  // keeps the order
    x.labels = labels;
    for (const lv of Object.keys(x.run_if || {})) x.run_if![lv] = x.run_if![lv].map((k) => (k === old ? nk : k));
    for (const v of Object.values(x.labels)) if (v.softens) v.softens = v.softens.map((k) => (k === old ? nk : k));
    for (const t of Object.keys(x.topic_map || {})) {
      const v = x.topic_map![t];
      x.topic_map![t] = Array.isArray(v) ? v.map((k) => (k === old ? nk : k)) : v === old ? nk : v;
    }
  });
  const remove = (k: string) => edit((x) => {
    delete x.labels[k];
    for (const lv of Object.keys(x.run_if || {})) x.run_if![lv] = x.run_if![lv].filter((y) => y !== k);
  });
  const add = (level: number) => {
    const k = (newKey[level] || "").trim();
    if (!KEY_RE.test(k) || d.labels[k]) return;
    edit((x) => { x.labels[k] = { level, decision: level === 0 ? "gate" : "review", threshold: 0.8, hypothesis: "This text …" }; });
    setNewKey((m) => ({ ...m, [level]: "" }));
  };
  return (
    <section className="panel">
      <h2>Labels</h2>
      <p className="faint" style={{ marginTop: 0, fontSize: 13 }}>A label is positive when its score reaches its threshold. Renaming a key also renames it in run_if, softens and the topic map.</p>
      {[0, 1, 2].map((level) => (
        <div key={level} style={{ marginTop: 12 }}>
          <h3 className="plevel">{level === 0 ? "Level 0 · gate" : level === 1 ? "Level 1 · subject" : "Level 2 · framing"}</h3>
          <div className="table-wrap">
            <table className="ptable">
              <thead><tr><th>key</th><th>level</th><th>decision</th><th>threshold</th><th>hypothesis</th><th>softens</th><th>protected</th><th>note</th><th /></tr></thead>
              <tbody>
                {keys.filter((k) => Number(d.labels[k].level ?? 1) === level).map((k) => {
                  const l = d.labels[k];
                  const set = (fn: (v: PolicyLabelData) => void) => edit((x) => fn(x.labels[k]));
                  return (
                    <tr key={k} data-testid={`pol-label-${k}`}>
                      <td><KeyInput value={k} onCommit={(nk) => rename(k, nk)} /></td>
                      <td><select value={l.level} onChange={(e) => set((v) => { v.level = Number(e.target.value); if (v.level === 0) v.decision = "gate"; else if (v.decision === "gate") v.decision = "review"; })}>
                        {[0, 1, 2].map((n) => <option key={n} value={n}>{n}</option>)}</select></td>
                      <td><select className={`badge ${actionClass(l.decision)}`} value={l.decision} onChange={(e) => set((v) => { v.decision = e.target.value; })}>
                        {DECISIONS.map((x) => <option key={x} value={x}>{x}</option>)}</select></td>
                      <td><input type="number" step="0.01" min={0} max={1} value={l.threshold ?? 0.8} onChange={(e) => set((v) => { v.threshold = Number(e.target.value); })} style={{ width: 70 }} /></td>
                      <td style={{ minWidth: 260 }}><textarea rows={2} value={l.hypothesis} onChange={(e) => set((v) => { v.hypothesis = e.target.value; })} /></td>
                      <td><ListInput value={l.softens || []} onCommit={(v) => set((x) => { if (v.length) x.softens = v; else delete x.softens; })} placeholder="hostility_*, …" /></td>
                      <td style={{ textAlign: "center" }}><input type="checkbox" checked={!!l.protected} onChange={(e) => set((v) => { if (e.target.checked) v.protected = true; else delete v.protected; })} /></td>
                      <td style={{ minWidth: 160 }}><textarea rows={2} value={l.note || ""} onChange={(e) => set((v) => { v.note = e.target.value; })} /></td>
                      <td><button className="btn small ghost" title={`delete ${k}`} onClick={() => { if (window.confirm(`Delete the label ${k}?`)) remove(k); }}>✕</button></td>
                    </tr>);
                })}
              </tbody>
            </table>
          </div>
          <div className="row" style={{ marginTop: 6 }}>
            <input type="text" placeholder="new_label_key" value={newKey[level] || ""} onChange={(e) => setNewKey((m) => ({ ...m, [level]: e.target.value }))} style={{ width: 200 }} data-testid={`pol-new-label-${level}`} />
            <button className="btn small" disabled={!KEY_RE.test((newKey[level] || "").trim()) || !!d.labels[(newKey[level] || "").trim()]} onClick={() => add(level)}>+ add a level-{level} label</button>
          </div>
        </div>))}
    </section>
  );
}

function KeyInput({ value, onCommit }: { value: string; onCommit: (v: string) => void }) {
  const [t, setT] = useState(value);
  useEffect(() => setT(value), [value]);
  const bad = !KEY_RE.test(t);
  return <input type="text" className="mono" value={t} style={{ width: 190, borderColor: bad ? "var(--filter)" : undefined }}
    title={bad ? "lower-case letters, digits and _ ; starts with a letter" : "rename: press Enter or leave the box"}
    onChange={(e) => setT(e.target.value)} onBlur={() => (bad ? setT(value) : onCommit(t))} onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />;
}

function ListInput({ value, onCommit, placeholder }: { value: string[]; onCommit: (v: string[]) => void; placeholder?: string }) {
  const [t, setT] = useState(value.join(", "));
  useEffect(() => setT(value.join(", ")), [value.join(", ")]);  // eslint-disable-line react-hooks/exhaustive-deps
  return <input type="text" className="mono" value={t} placeholder={placeholder} style={{ width: 170 }} onChange={(e) => setT(e.target.value)} onBlur={() => onCommit(toList(t))} />;
}

function RunIf({ d, edit }: Ed) {
  const keys = Object.keys(d.labels || {});
  return (
    <section className="panel">
      <h2>run_if</h2>
      <p className="faint" style={{ marginTop: 0, fontSize: 13 }}>A level is scored on a paragraph when <strong>any</strong> ticked item is true (a label positive, or
        <code> @marker</code> = a marker term or a hate label opened the gate; <code>@gate</code> = any level-0 gate label is yes, needed when the
        policy has several gates, which are OR-combined). Nothing ticked = the level always runs. The Try page scores every label anyway.</p>
      {["1", "2"].map((lv) => {
        const on = d.run_if?.[lv];
        return (
          <div key={lv} className="row" style={{ marginTop: 8, alignItems: "flex-start" }} data-testid={`pol-runif-${lv}`}>
            <strong style={{ width: 70 }}>level {lv}</strong>
            <div className="row" style={{ flexWrap: "wrap", gap: 4 }}>
              {[...keys.filter((k) => Number(d.labels[k].level) < Number(lv) + 1), "@gate", "@marker"].map((k) => (
                <label key={k} className="chip" style={{ cursor: "pointer" }}>
                  <input type="checkbox" checked={!!on?.includes(k)} onChange={(e) => edit((x) => {
                    const cur = new Set(x.run_if?.[lv] || []);
                    if (e.target.checked) cur.add(k); else cur.delete(k);
                    x.run_if = { ...(x.run_if || {}) };
                    if (cur.size) x.run_if[lv] = Array.from(cur); else delete x.run_if[lv];
                  })} /> {k}</label>))}
              {!on?.length ? <span className="faint" style={{ fontSize: 12 }}>(always runs)</span> : null}
            </div>
          </div>);
      })}
    </section>
  );
}

function Exceptions({ d, edit }: Ed) {
  const ex = d.exceptions || [];
  const set = (i: number, fn: (e: PolicyExceptionData) => void) => edit((x) => { fn(x.exceptions![i]); });
  return (
    <section className="panel">
      <h2>Exceptions</h2>
      <p className="faint" style={{ marginTop: 0, fontSize: 13 }}>Checked after the cascade; the highest priority that matches sets the decision. A removal by a
        protected label is never lowered. Phrases inside quotation marks are ignored with skip_quoted.</p>
      {ex.map((e, i) => (
        <div key={i} className="pexc" data-testid={`pol-exc-${e.key}`}>
          <div className="pgrid">
            <Field label="key"><input type="text" className="mono" value={e.key} onChange={(v) => set(i, (x) => { x.key = v.target.value; })} /></Field>
            <Field label="decision"><select value={e.decision} onChange={(v) => set(i, (x) => { x.decision = v.target.value; })}>{ACTIONS3.map((a) => <option key={a} value={a}>{a}</option>)}</select></Field>
            <Field label="priority"><input type="number" value={e.priority ?? 0} onChange={(v) => set(i, (x) => { x.priority = Number(v.target.value); })} /></Field>
            <Field label="scope" help="keyword: every paragraph with a hit; gate: only past the gate">
              <select value={e.scope || "keyword"} onChange={(v) => set(i, (x) => { x.scope = v.target.value; })}><option value="keyword">keyword</option><option value="gate">gate</option></select></Field>
            <Field label="skip_quoted"><input type="checkbox" checked={!!e.skip_quoted} onChange={(v) => set(i, (x) => { x.skip_quoted = v.target.checked; })} /></Field>
          </div>
          <div className="pgrid" style={{ marginTop: 8 }}>
            <Field label="phrases" help="one per line, any language, case-insensitive">
              <ListBox value={e.match?.phrases || []} rows={5} onChange={(v) => set(i, (x) => { x.match = { ...(x.match || {}), phrases: v }; if (!v.length) delete x.match.phrases; })} /></Field>
            <Field label="hypothesis (optional)" help="matches when its score reaches the threshold">
              <textarea rows={2} value={e.match?.hypothesis || ""} onChange={(v) => set(i, (x) => { x.match = { ...(x.match || {}), hypothesis: v.target.value }; if (!v.target.value) delete x.match.hypothesis; })} /></Field>
            <Field label="threshold"><input type="number" step="0.01" min={0} max={1} value={e.match?.threshold ?? 0.8} onChange={(v) => set(i, (x) => { x.match = { ...(x.match || {}), threshold: Number(v.target.value) }; })} /></Field>
            <Field label="note"><textarea rows={2} value={e.note || ""} onChange={(v) => set(i, (x) => { x.note = v.target.value; })} /></Field>
          </div>
          <div className="row" style={{ marginTop: 6 }}>
            <button className="btn small ghost" onClick={() => { if (window.confirm(`Delete the exception ${e.key}?`)) edit((x) => { x.exceptions!.splice(i, 1); }); }}>✕ delete this exception</button>
          </div>
        </div>))}
      <button className="btn small" onClick={() => edit((x) => {
        const n = (x.exceptions || []).length + 1;
        x.exceptions = [...(x.exceptions || []), { key: `new_exception_${n}`, decision: "review", priority: 50, scope: "keyword", skip_quoted: true, match: { phrases: ["…"] } }];
      })}>+ add an exception</button>
    </section>
  );
}

function Topics({ d, edit }: Ed) {
  const map = d.topic_map || {};
  const subjects = Object.keys(d.labels || {}).filter((k) => Number(d.labels[k].level) === 1);
  const [newTopic, setNewTopic] = useState("");
  return (
    <section className="panel">
      <h2>Topic field</h2>
      <div className="pgrid">
        <Field label="topic_field" help="the corpus field with a topic (empty = none; --topic-field overrides)">
          <input type="text" value={d.topic_field || ""} onChange={(e) => edit((x) => { x.topic_field = e.target.value || null; })} /></Field>
        <Field label="topic_mode" help="hint: the field helps; trust: the field decides the subjects; off: ignored">
          <select value={d.topic_mode || "hint"} onChange={(e) => edit((x) => { x.topic_mode = e.target.value; })}>
            {["hint", "trust", "off"].map((m) => <option key={m} value={m}>{m}</option>)}</select></Field>
      </div>
      <div className="table-wrap" style={{ marginTop: 10 }}>
        <table className="ptable">
          <thead><tr><th>topic value</th><th>level-1 subjects</th><th /></tr></thead>
          <tbody>
            {Object.entries(map).map(([t, v]) => (
              <tr key={t}>
                <td className="mono">{t}</td>
                <td><div className="row" style={{ flexWrap: "wrap", gap: 4 }}>{subjects.map((s) => (
                  <label key={s} className="chip"><input type="checkbox" checked={asList(v).includes(s)} onChange={(e) => edit((x) => {
                    const cur = new Set(asList(x.topic_map![t]));
                    if (e.target.checked) cur.add(s); else cur.delete(s);
                    const arr = Array.from(cur);
                    x.topic_map![t] = arr.length === 1 ? arr[0] : arr;
                  })} /> {s}</label>))}</div></td>
                <td><button className="btn small ghost" onClick={() => edit((x) => { delete x.topic_map![t]; })}>✕</button></td>
              </tr>))}
          </tbody>
        </table>
      </div>
      <div className="row" style={{ marginTop: 6 }}>
        <input type="text" placeholder="a topic value, e.g. Sports" value={newTopic} onChange={(e) => setNewTopic(e.target.value)} style={{ width: 220 }} />
        <button className="btn small" disabled={!newTopic.trim() || newTopic.trim() in map || !subjects.length}
          onClick={() => { edit((x) => { x.topic_map = { ...(x.topic_map || {}), [newTopic.trim()]: subjects[0] }; }); setNewTopic(""); }}>+ add a topic</button>
      </div>
    </section>
  );
}

/** Settings the form has no box for: shown so nothing is hidden (edit them on the JSON tab). */
function Other({ d }: { d: PolicyData }) {
  const known = new Set(["about", "version", "country", "keywords_file", "company_names_file", "rewrite_place_names", "place_names_file",
    "place_name_exceptions_file", "markers", "paragraphs", "conflict", "no_subject", "narrative_opens_gate", "exceptions", "topic_field",
    "topic_mode", "topic_map", "labels", "run_if", "non_english_file"]);
  const rest = Object.entries(d).filter(([k]) => !known.has(k));
  if (!rest.length) return null;
  return (
    <section className="panel">
      <h2>Other settings</h2>
      <p className="faint" style={{ marginTop: 0, fontSize: 13 }}>Edit these on the JSON tab.</p>
      <pre className="json">{JSON.stringify(Object.fromEntries(rest), null, 2)}</pre>
    </section>
  );
}

function JsonTab({ data, onChange }: { data: PolicyData; onChange: (d: PolicyData) => void }) {
  const text = useMemo(() => JSON.stringify(data, null, 2), [data]);
  const [t, setT] = useState(text);
  const [bad, setBad] = useState<string | null>(null);
  const mine = useRef<string | null>(null);  // the data this box sent: not written back (keeps the cursor and the layout)
  useEffect(() => {
    if (mine.current === text) return;
    setT(text); setBad(null);
  }, [text]);
  return (
    <section className="panel">
      <p className="faint" style={{ marginTop: 0, fontSize: 13 }}>The whole policy file. Changes apply when the text is valid JSON (then checked like the form).</p>
      {bad ? <div className="alert error" style={{ marginBottom: 6 }}>Not valid JSON: {bad}</div> : null}
      <textarea className="mono policy-json" spellCheck={false} value={t} data-testid="policy-json" onChange={(e) => {
        setT(e.target.value);
        try {
          const v = JSON.parse(e.target.value);
          if (!v || typeof v !== "object" || Array.isArray(v)) throw new Error("the policy must be a JSON object");
          setBad(null); mine.current = JSON.stringify(v, null, 2); onChange(v);
        } catch (x) { setBad((x as Error).message); }
      }} />
    </section>
  );
}

export function PolicyLink({ policy }: { policy?: string }) {
  return <Link className="btn small" href={href("/label/policy", { file: policy || null })}>Edit the policy →</Link>;
}

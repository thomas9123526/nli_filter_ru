"use client";
// Config editors of the output modes, like the policy editor: checked with nli_label.py's own rules while typing, saved
// with a backup (<folder>/.backup/), refused when the file changed since it was loaded.
//   /label/output/?file=output/<name>.json        the simple-mode schema (fields, include, omit_empty, evidence,
//                                                 reason vocabulary) with a live preview built from a detail run
//   /label/non-english/?file=policy/<name>.json   which scripts count as non-English, and check / remove
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api, useApi } from "@/lib/api";
import { href } from "@/lib/format";
import type { ConfigCheck, NonEnglishData, SchemaData, SchemaPreviewResp } from "@/lib/types";
import { Crumbs, ErrorBox, Loading } from "./ui";

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));

/** Loading, checking and saving one config file (shared by both editors). */
export function useConfig<T>(kind: string, base: string, fallback: string) {
  const sp = useSearchParams();
  const router = useRouter();
  const list = useApi(`cfgfiles:${kind}`, (s) => api.configFiles(kind, s));
  const file = sp.get("file") || (list.data?.files.includes(fallback) ? fallback : list.data?.files[0]) || "";
  const [tick, setTick] = useState(0);
  const raw = useApi(file ? `cfgraw:${kind}:${file}:${tick}` : null, (s) => api.configRaw(kind, file, s));
  const [draft, setDraft] = useState<T | null>(null);
  const [check, setCheck] = useState<ConfigCheck | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveAs, setSaveAs] = useState("");
  const data = (draft ?? (raw.data?.data as T | undefined)) || null;
  const dirty = draft !== null && JSON.stringify(draft) !== JSON.stringify(raw.data?.data);
  useEffect(() => { setDraft(null); setMsg(null); setErr(null); setCheck(null); }, [file]);
  useEffect(() => { if (raw.data && !draft) setCheck(raw.data.check); }, [raw.data, draft]);
  useEffect(() => {
    if (!draft) return;
    const t = setTimeout(() => { api.configCheck(kind, draft).then(setCheck).catch(() => undefined); }, 300);
    return () => clearTimeout(t);
  }, [draft, kind]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  const edit = (fn: (d: T) => void) => { if (!data) return; const x = clone(data); fn(x); setDraft(x); setMsg(null); };
  const save = async (as?: string) => {
    setSaving(true); setErr(null); setMsg(null);
    try {
      const target = as ? (as.includes("/") ? as : `${base}/${as.endsWith(".json") ? as : as + ".json"}`) : undefined;
      const r = await api.configSave(kind, { path: file, data, base_sha: raw.data?.sha, ...(target ? { save_as: target } : {}) });
      setMsg(`Saved ${r.path}${r.backup ? ` (old version: ${r.backup})` : ""}. Runs use it from their next start.`);
      setDraft(null); setSaveAs("");
      if (target) router.replace(href(base === "output" ? "/label/output" : "/label/non-english", { file: r.path }));
      else setTick((t) => t + 1);
    } catch (e) { setErr((e as Error).message); }
    setSaving(false);
  };
  const pick = (f: string, path: string) => {
    if (dirty && !window.confirm("Unsaved changes will be lost. Switch anyway?")) return;
    router.replace(href(path, { file: f }));
  };
  return { list, file, raw, data, dirty, check, msg, err, saving, saveAs, setSaveAs, edit, save, pick,
    discard: () => { setDraft(null); setCheck(raw.data?.check || null); }, setDraft };
}

export function SaveBar({ c, file, placeholder, testid, noSaveAs }: { c: ReturnType<typeof useConfig<unknown>>; file: string; placeholder: string; testid: string; noSaveAs?: boolean }) {
  return (
    <div className="panel policy-bar" data-testid={`${testid}-bar`}>
      <div className="row" style={{ flexWrap: "wrap" }}>
        {c.dirty ? <span className="badge warn">unsaved changes</span> : <span className="faint" style={{ fontSize: 12 }}>no changes</span>}
        {c.check ? (c.check.ok ? <span className="badge keep" data-testid={`${testid}-ok`}>valid</span>
          : <span className="badge remove">{c.check.errors.length} problem{c.check.errors.length === 1 ? "" : "s"}</span>) : null}
        <button className="btn small primary" disabled={!c.dirty || c.saving || !c.check?.ok} onClick={() => c.save()} data-testid={`${testid}-save`}>
          {c.saving ? "Saving…" : `Save ${file}`}</button>
        <button className="btn small" disabled={!c.dirty || c.saving} onClick={c.discard}>Discard</button>
        {noSaveAs ? null : <>
        <span className="faint" style={{ fontSize: 12 }}>or save as</span>
        <input type="text" placeholder={placeholder} value={c.saveAs} onChange={(e) => c.setSaveAs(e.target.value)} style={{ width: 200 }} />
        <button className="btn small" disabled={!c.saveAs.trim() || c.saving || !c.check?.ok} onClick={() => c.save(c.saveAs.trim())}>Save as new</button></>}
      </div>
      {c.check?.errors.length ? <ul className="policy-errors" data-testid={`${testid}-errors`}>{c.check.errors.map((e, i) => <li key={i}>{e}</li>)}</ul> : null}
      {c.msg ? <div className="faint" style={{ fontSize: 12, marginTop: 6 }} data-testid={`${testid}-saved`}>{c.msg}</div> : null}
      {c.err ? <div className="alert error" style={{ marginTop: 6 }}>{c.err}</div> : null}
    </div>
  );
}

export function JsonBox<T>({ data, onChange }: { data: T; onChange: (d: T) => void }) {
  const [t, setT] = useState(JSON.stringify(data, null, 2));
  const [bad, setBad] = useState<string | null>(null);
  useEffect(() => { setT(JSON.stringify(data, null, 2)); }, [data]);
  return (<>
    {bad ? <div className="alert error">{bad}</div> : null}
    <textarea className="mono policy-json" spellCheck={false} value={t} onChange={(e) => {
      setT(e.target.value);
      try { onChange(JSON.parse(e.target.value)); setBad(null); } catch (x) { setBad(`not valid JSON yet: ${(x as Error).message}`); }
    }} />
  </>);
}

// ------------------------------------------------------------------------------------------------------------------
// the simple-mode schema
// ------------------------------------------------------------------------------------------------------------------
const SOURCES = ["id", "line", "file", "decision", "level", "reason", "reason_text", "labels", "keyword_counts", "markers",
  "tokens", "tokens_removed", "exception", "topic", "paragraphs"];
const SOURCE_HELP: Record<string, string> = {
  id: "the line's id field", line: "line number in the input file", file: "input file name (without extensions)",
  decision: "line unit: remove / review / keep / pass; paragraph unit: the document action (edited, removed …)",
  level: "the strictest decision of the line (remove / review / keep / pass / untouched), in both units",
  reason: "the deciding paragraph's technical reason (remove_label, gate_negative …)",
  reason_text: "what decided, in your words (the vocabulary below)", labels: "positive labels of the line",
  keyword_counts: "every keyword and marker of the line with its count", markers: "marker terms found",
  tokens: "estimated tokens of the line", tokens_removed: "estimated tokens removed", exception: "the deciding paragraph's exception",
  topic: "the corpus' topic field", paragraphs: "[[start, end, action], …] of every checked paragraph",
};
const INCLUDE = ["remove", "review", "keep", "pass", "untouched", "error"];

export function SchemaEditView() {
  const c = useConfig<SchemaData>("schema", "output", "output/simple_schema.json");
  const [tab, setTab] = useState<"form" | "json">("form");
  const runs = useApi("labelruns:schema", (s) => api.labelRuns(s));
  const detailRuns = (runs.data?.runs || []).filter((r) => (r.mode || "detail") === "detail" && r.finished);
  const [run, setRun] = useState("");
  const [prev, setPrev] = useState<SchemaPreviewResp | null>(null);
  const [prevErr, setPrevErr] = useState<string | null>(null);
  const [newKey, setNewKey] = useState("");
  const [newWord, setNewWord] = useState("");
  const d = c.data;
  const runName = run || detailRuns[0]?.name || "";
  useEffect(() => {  // live preview from a detail run
    if (!d || !runName || !c.check?.ok) return;
    const t = setTimeout(() => {
      api.schemaPreview({ data: d, run: runName, limit: 12 }).then((r) => { setPrev(r); setPrevErr(null); })
        .catch((e) => setPrevErr((e as Error).message));
    }, 400);
    return () => clearTimeout(t);
  }, [d, runName, c.check?.ok]);
  const fields = d?.fields || [];
  const vocab = Object.entries(d?.reason_text || {});
  const move = (i: number, by: number) => c.edit((x) => { const f = x.fields; const j = i + by; if (j < 0 || j >= f.length) return; [f[i], f[j]] = [f[j], f[i]]; });

  return (
    <>
      <div className="page-head"><div>
        <Crumbs items={[{ label: "Settings", href: "/settings" }, { label: "simple-mode schema" }]} />
        <h1>Simple-mode output</h1>
        <div className="sub">What <code className="mono">nli_label.py run --output-mode simple</code> writes per line: the fields, which lines get a row,
          the evidence file and your words for the reasons. Used with <code className="mono">--schema {c.file || "output/simple_schema.json"}</code> and by
          {" "}<code className="mono">nli_label.py export</code>.</div>
        <div className="row" style={{ marginTop: 8, flexWrap: "wrap" }}>
          <label className="faint" style={{ fontSize: 13 }}>file&nbsp;
            <select value={c.file} onChange={(e) => c.pick(e.target.value, "/label/output")} data-testid="schema-file">
              {(c.list.data?.files || []).map((f) => <option key={f} value={f}>{f}</option>)}</select></label>
          <span className="seg"><button className={tab === "form" ? "on" : ""} onClick={() => setTab("form")}>Form</button>
            <button className={tab === "json" ? "on" : ""} onClick={() => setTab("json")}>JSON</button></span>
        </div>
      </div></div>
      <SaveBar c={c as never} file={c.file} placeholder="simple_schema_small.json" testid="schema" />
      <ErrorBox error={c.list.error || c.raw.error} onRetry={c.raw.reload} />
      {!d && c.raw.loading ? <Loading what="Loading the schema" /> : null}
      {d && tab === "json" ? <JsonBox data={d} onChange={(x) => c.setDraft(x)} /> : null}
      {d && tab === "form" ? (
        <div className="stack">
          <section className="panel">
            <h2>Rows</h2>
            <div className="pgrid">
              <label className="pfield"><span className="pfield-label">file</span>
                <input type="text" className="mono" value={d.file || "decisions.jsonl.zst"} onChange={(e) => c.edit((x) => { x.file = e.target.value; })} data-testid="schema-name" />
                <span className="pfield-help">per input file: &lt;name&gt;.{(d.file || "decisions").split(".")[0]}.jsonl.zst</span></label>
              <label className="pfield"><span className="pfield-label">omit_empty</span>
                <input type="checkbox" checked={d.omit_empty !== false} onChange={(e) => c.edit((x) => { x.omit_empty = e.target.checked; })} />
                <span className="pfield-help">leave out empty values (no keyword_hint on an untouched line)</span></label>
              <label className="pfield"><span className="pfield-label">evidence</span>
                <select value={d.evidence || "none"} onChange={(e) => c.edit((x) => { x.evidence = e.target.value; })} data-testid="schema-evidence">
                  {["none", "decided", "all"].map((v) => <option key={v} value={v}>{v}</option>)}</select>
                <span className="pfield-help">decided = remove + review lines, all = every checked line: their paragraphs and scores in &lt;name&gt;.evidence.jsonl.zst</span></label>
            </div>
            <div className="pfield" style={{ marginTop: 10 }}><span className="pfield-label">include (which lines get a row)</span>
              <div className="row" style={{ flexWrap: "wrap" }}>{INCLUDE.map((v) => (
                <label key={v} style={{ fontSize: 13 }}><input type="checkbox" checked={(d.include || INCLUDE).includes(v)} data-testid={`schema-inc-${v}`}
                  onChange={(e) => c.edit((x) => { const s = new Set(x.include || INCLUDE); if (e.target.checked) s.add(v); else s.delete(v); x.include = INCLUDE.filter((k) => s.has(k)); })} /> {v}</label>))}
              </div>
              <span className="pfield-help">by the line&apos;s strictest decision; untouched lines are most of a corpus (leave them out to shrink the files; the per-file summaries still count them)</span></div>
          </section>

          <section className="panel flush">
            <div className="panel-head"><h2>Fields</h2><span className="faint" style={{ fontSize: 12 }}>in this order, under these names</span>
              <span className="spacer" />
              <button className="btn small" onClick={() => c.edit((x) => { x.fields.push({ name: `field${x.fields.length + 1}`, from: "labels" }); })} data-testid="schema-add-field">+ add a field</button></div>
            <div className="table-wrap"><table className="ptable" data-testid="schema-fields">
              <thead><tr><th>name</th><th>from</th><th>what it is</th><th /></tr></thead>
              <tbody>{fields.map((f, i) => (
                <tr key={i}>
                  <td><input type="text" className="mono" value={f.name} style={{ width: 140 }} onChange={(e) => c.edit((x) => { x.fields[i].name = e.target.value; })} /></td>
                  <td>{SOURCES.includes(f.from) ? (
                    <select value={f.from} onChange={(e) => c.edit((x) => { x.fields[i].from = e.target.value === "input." ? "input.url" : e.target.value; })}>
                      {SOURCES.map((s) => <option key={s} value={s}>{s}</option>)}<option value="input.">input.&lt;field&gt;</option></select>)
                    : <input type="text" className="mono" value={f.from} style={{ width: 160 }} onChange={(e) => c.edit((x) => { x.fields[i].from = e.target.value; })} />}</td>
                  <td className="faint" style={{ fontSize: 12 }}>{SOURCE_HELP[f.from] || (f.from.startsWith("input.") ? "copied from the input line" : "")}</td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button className="btn small ghost" disabled={i === 0} onClick={() => move(i, -1)} title="up">↑</button>
                    <button className="btn small ghost" disabled={i === fields.length - 1} onClick={() => move(i, 1)} title="down">↓</button>
                    <button className="btn small ghost" onClick={() => c.edit((x) => { x.fields.splice(i, 1); })} title="delete">✕</button></td>
                </tr>))}</tbody>
            </table></div>
          </section>

          <section className="panel flush">
            <div className="panel-head"><h2>Reason vocabulary</h2>
              <span className="faint" style={{ fontSize: 12 }}>label, exception key or technical reason → your word (exact keys first, then * patterns in this order; not listed = the key itself)</span></div>
            <div className="table-wrap"><table className="ptable" data-testid="schema-vocab">
              <thead><tr><th>key or pattern</th><th>word</th><th /></tr></thead>
              <tbody>{vocab.map(([k, w]) => (
                <tr key={k}>
                  <td className="mono">{k}</td>
                  <td><input type="text" value={w} onChange={(e) => c.edit((x) => { x.reason_text = { ...(x.reason_text || {}), [k]: e.target.value }; })} /></td>
                  <td><button className="btn small ghost" onClick={() => c.edit((x) => { const r = { ...(x.reason_text || {}) }; delete r[k]; x.reason_text = r; })}>✕</button></td>
                </tr>))}
                <tr><td><input type="text" className="mono" placeholder="hostility_* or gate_negative" value={newKey} onChange={(e) => setNewKey(e.target.value)} data-testid="schema-vocab-key" /></td>
                  <td><input type="text" placeholder="insult" value={newWord} onChange={(e) => setNewWord(e.target.value)} data-testid="schema-vocab-word" /></td>
                  <td><button className="btn small" disabled={!newKey.trim() || !newWord.trim()} data-testid="schema-vocab-add"
                    onClick={() => { c.edit((x) => { x.reason_text = { ...(x.reason_text || {}), [newKey.trim()]: newWord.trim() }; }); setNewKey(""); setNewWord(""); }}>+ add</button></td></tr>
              </tbody></table></div>
          </section>

          <section className="panel" data-testid="schema-preview">
            <div className="row" style={{ flexWrap: "wrap" }}><h2 style={{ margin: 0 }}>Preview</h2>
              <label className="faint" style={{ fontSize: 13 }}>rows from the detail run&nbsp;
                <select value={runName} onChange={(e) => setRun(e.target.value)}>
                  {detailRuns.map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}</select></label>
              {prev ? <span className="faint" style={{ fontSize: 12 }}>{prev.file}: {prev.included} of the first {prev.read} lines get a row
                {d.evidence && d.evidence !== "none" ? `, ${prev.evidence_rows} evidence rows` : ""} (that run&apos;s unit: {prev.unit}; keyword_hint here counts the hits the run stored)</span> : null}</div>
            {!detailRuns.length ? <div className="faint">No finished detail-mode run to build a preview from.</div> : null}
            {prevErr ? <div className="alert error">{prevErr}</div> : null}
            {prev ? <pre className="mono" style={{ fontSize: 12, whiteSpace: "pre-wrap", margin: "8px 0 0" }} data-testid="schema-preview-rows">
              {prev.rows.map((r) => JSON.stringify(r)).join("\n") || "(no rows: include leaves every line out)"}</pre> : null}
          </section>
        </div>) : null}
    </>
  );
}

// ------------------------------------------------------------------------------------------------------------------
// the non-English setting
// ------------------------------------------------------------------------------------------------------------------
export function NonEnglishEditView() {
  const c = useConfig<NonEnglishData>("non_english", "policy", "policy/non_english.json");
  const [tab, setTab] = useState<"form" | "json">("form");
  const [newName, setNewName] = useState("");
  const d = c.data;
  const scripts = Object.entries(d?.scripts || {});
  const enabled = (c.check?.info?.enabled as string[] | undefined) || [];
  return (
    <>
      <div className="page-head"><div>
        <Crumbs items={[{ label: "Settings", href: "/settings" }, { label: "non-English keywords" }]} />
        <h1>Non-English keywords and markers</h1>
        <div className="sub">A keyword or marker with a letter in an <strong>enabled</strong> script counts as non-English (Cyrillic and Latin never do).
          Such a paragraph is checked as usual (<code>check</code>) or removed (<code>remove</code>, before the gate; exceptions cannot lower it).
          A policy uses this file with <code className="mono">non_english_file</code>{" "}
          (<Link href="/label/policy">set it in the policy editor</Link>); without that line the setting is off.</div>
        <div className="row" style={{ marginTop: 8, flexWrap: "wrap" }}>
          <label className="faint" style={{ fontSize: 13 }}>file&nbsp;
            <select value={c.file} onChange={(e) => c.pick(e.target.value, "/label/non-english")} data-testid="ne-file">
              {(c.list.data?.files || []).map((f) => <option key={f} value={f}>{f}</option>)}</select></label>
          <span className="seg"><button className={tab === "form" ? "on" : ""} onClick={() => setTab("form")}>Form</button>
            <button className={tab === "json" ? "on" : ""} onClick={() => setTab("json")}>JSON</button></span>
          {enabled.length ? <span className="faint" style={{ fontSize: 12 }}>enabled: {enabled.join(", ")}</span> : <span className="badge warn">no script enabled</span>}
        </div>
      </div></div>
      <SaveBar c={c as never} file={c.file} placeholder="non_english_v2.json" testid="ne" />
      <ErrorBox error={c.list.error || c.raw.error} onRetry={c.raw.reload} />
      {!d && c.raw.loading ? <Loading what="Loading the setting" /> : null}
      {!c.list.loading && !(c.list.data?.files || []).length ? <div className="alert">No non-English config in policy/ yet (a JSON file with &quot;scripts&quot;).</div> : null}
      {d && tab === "json" ? <JsonBox data={d} onChange={(x) => c.setDraft(x)} /> : null}
      {d && tab === "form" ? (
        <div className="stack">
          <section className="panel">
            <h2>What a hit does</h2>
            <div className="pgrid">
              {(["keywords", "markers"] as const).map((k) => (
                <label key={k} className="pfield"><span className="pfield-label">{k}</span>
                  <select value={d[k] || "check"} onChange={(e) => c.edit((x) => { x[k] = e.target.value; })} data-testid={`ne-${k}`}>
                    <option value="check">check (the normal check)</option><option value="remove">remove the paragraph</option></select>
                  <span className="pfield-help">reason non_english_{k === "keywords" ? "keyword" : "marker"}</span></label>))}
              <label className="pfield"><span className="pfield-label">score_when_removed</span>
                <input type="checkbox" checked={!!d.score_when_removed} onChange={(e) => c.edit((x) => { x.score_when_removed = e.target.checked; })} data-testid="ne-score" />
                <span className="pfield-help">on: a removed paragraph is still scored (labels and scores kept for the flow view and redecide; slower). The decision stays remove.</span></label>
            </div>
          </section>
          <section className="panel flush">
            <div className="panel-head"><h2>Scripts</h2><span className="faint" style={{ fontSize: 12 }}>Unicode ranges in hex, e.g. 0600-06FF</span></div>
            <div className="table-wrap"><table className="ptable" data-testid="ne-scripts">
              <thead><tr><th>on</th><th>script</th><th>ranges</th><th /></tr></thead>
              <tbody>{scripts.map(([name, v]) => (
                <tr key={name} className={v.enabled ? "" : "row-off"}>
                  <td><input type="checkbox" checked={!!v.enabled} data-testid={`ne-on-${name}`} onChange={(e) => c.edit((x) => { x.scripts[name].enabled = e.target.checked; })} /></td>
                  <td className="mono">{name}</td>
                  <td><RangesBox value={v.ranges || []} onChange={(r) => c.edit((x) => { x.scripts[name].ranges = r; })} /></td>
                  <td><button className="btn small ghost" onClick={() => c.edit((x) => { delete x.scripts[name]; })} title="delete">✕</button></td>
                </tr>))}
                <tr><td /><td><input type="text" className="mono" placeholder="japanese" value={newName} onChange={(e) => setNewName(e.target.value)} data-testid="ne-new-name" /></td>
                  <td className="faint" style={{ fontSize: 12 }}>a new script starts switched off; add its ranges, then tick it</td>
                  <td><button className="btn small" disabled={!/^[a-z][a-z0-9_]*$/.test(newName.trim()) || !!d.scripts[newName.trim()]} data-testid="ne-add"
                    onClick={() => { c.edit((x) => { x.scripts[newName.trim()] = { enabled: false, ranges: ["AC00-D7AF"] }; }); setNewName(""); }}>+ add</button></td></tr>
              </tbody></table></div>
          </section>
          <div className="faint" style={{ fontSize: 12 }}>The keyword lists and markers must contain terms in that script for anything to happen:{" "}
            <Link href="/label/files">keyword lists →</Link></div>
        </div>) : null}
    </>
  );
}

function RangesBox({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const [t, setT] = useState(value.join(", "));
  useEffect(() => { setT(value.join(", ")); }, [value.join(",")]);  // eslint-disable-line react-hooks/exhaustive-deps
  return <input type="text" className="mono" style={{ width: "100%" }} value={t} onChange={(e) => setT(e.target.value)}
    onBlur={() => onChange(t.split(/[,\s]+/).map((x) => x.trim()).filter(Boolean))} />;
}

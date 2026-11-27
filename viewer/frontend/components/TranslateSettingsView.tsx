"use client";
// /label/translate/: the translation providers of viewer_config.json ("translate"), tried in order by "auto", with a
// test button per provider: reachable now?, the models it serves, a sample translation per target with the language
// check. Editable here: add a provider (a model on an OpenAI-compatible server, with a note and a link), remove one,
// the order, on / off (for auto), URL, model, timeout, prompt, thinking off, key variable, note and link of each; saved
// into the "translate" block of viewer_config.json (with a backup) and used at once.
import { useEffect, useState } from "react";
import { getJSON, postJSON, useApi } from "@/lib/api";
import { Crumbs, ErrorBox, Loading } from "./ui";
import { TextTools, loadProviders } from "./TextTools";

type Provider = { name: string; kind: string; base_url?: string; model?: string; timeout?: number; no_think?: boolean;
  prompt?: string; enabled?: boolean; api_key_env?: string | null; has_key?: boolean; note?: string; link?: string };
type Settings = { configured: boolean; source?: string; targets: { code: string; name: string; label: string }[];
  providers: Provider[]; cache_dir?: string; concurrency?: number; down_seconds?: number; editable?: boolean; mtime?: string | null };
type Edit = { name: string; isNew?: boolean; kind: string; enabled: boolean; base_url: string; model: string; timeout: string;
  prompt: string; no_think: boolean; api_key_env: string; note: string; link: string };
const toEdit = (p: Provider): Edit => ({ name: p.name, kind: p.kind || "openai", enabled: p.enabled !== false,
  base_url: p.base_url || "", model: p.model || "", timeout: String(p.timeout ?? ""), prompt: p.prompt || "generic",
  no_think: !!p.no_think, api_key_env: p.api_key_env || "", note: p.note || "", link: p.link || "" });
type Sample = { target: string; ok: boolean; translation: string | null; seconds?: number; error?: string | null;
  language?: { ok: boolean; target_share?: number; main_script?: string }; retry?: { ok: boolean; translation: string | null } };
type TestResp = { text: string; providers: { name: string; model?: string; base_url?: string; enabled?: boolean; reachable: boolean;
  models?: string[]; model_served?: boolean; error?: string | null; seconds?: number; samples: Sample[] }[] };
type ModelsResp = { base_url: string; reachable: boolean; models: string[]; error?: string | null };

// starting points for "Add a model"; every field can be changed before adding
const PRESETS: { key: string; label: string; edit: Partial<Edit>; help: string }[] = [
  { key: "chat", label: "Chat model on an OpenAI-compatible server (Qwen, vLLM, SGLang, llama.cpp, Ollama …)",
    edit: { prompt: "generic", no_think: true, timeout: "60" },
    help: "e.g. Qwen3.6-35B-A3B served by vLLM: URL http://<server>:8000/v1, model = the name the server lists (Find models). " +
      "\"thinking off\" sends enable_thinking=false (Qwen3 / Qwen3.5 / Qwen3.6)." },
  { key: "hunyuan", label: "Hunyuan-MT (vLLM, llama-server, tools/serve_translate_local.py)",
    edit: { prompt: "hunyuan", no_think: false, timeout: "120", model: "Hunyuan-MT-7B", base_url: "http://127.0.0.1:8001/v1",
      link: "https://huggingface.co/tencent/Hunyuan-MT-7B" },
    help: "uses the Hunyuan-MT model card prompt. llama-server: start it with --alias Hunyuan-MT-7B --port 8001 --jinja." },
];
const emptyNew = (): Edit => ({ name: "", isNew: true, kind: "openai", enabled: true, base_url: "http://", model: "", timeout: "60",
  prompt: "generic", no_think: true, api_key_env: "", note: "", link: "" });
const payload = (e: Edit) => ({ ...(e.isNew ? { new: true, kind: e.kind } : {}), name: e.name, enabled: e.enabled,
  base_url: e.base_url, model: e.model, timeout: e.timeout.trim() ? Number(e.timeout) : null, prompt: e.prompt,
  no_think: e.no_think, api_key_env: e.api_key_env, note: e.note, link: e.link });
const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$/;

export function TranslateSettingsView() {
  const st = useApi("translate:settings", (s) => getJSON<Settings>("/api/translate/settings", undefined, s));
  const [busy, setBusy] = useState<string | null>(null);
  const [res, setRes] = useState<Record<string, TestResp["providers"][number]>>({});
  const [err, setErr] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [edits, setEdits] = useState<Edit[] | null>(null);
  const [removed, setRemoved] = useState<string[]>([]);
  const [more, setMore] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  // the "Add a model" form
  const [adding, setAdding] = useState<Edit | null>(null);
  const [preset, setPreset] = useState("chat");
  const [found, setFound] = useState<ModelsResp | null>(null);
  const [finding, setFinding] = useState(false);
  useEffect(() => { if (st.data) { setEdits(st.data.providers.map(toEdit)); setRemoved([]); } }, [st.data]);
  const orig = st.data ? st.data.providers.map(toEdit) : [];
  const changed = !!edits && (removed.length > 0 || JSON.stringify(edits) !== JSON.stringify(orig));
  const setEdit = (i: number, patch: Partial<Edit>) => setEdits((es) => es ? es.map((e, j) => j === i ? { ...e, ...patch } : e) : es);
  const move = (i: number, by: number) => setEdits((es) => {
    if (!es) return es;
    const j = i + by;
    if (j < 0 || j >= es.length) return es;
    const out = es.slice();
    [out[i], out[j]] = [out[j], out[i]];
    return out;
  });
  const undo = () => { setEdits(orig); setRemoved([]); setSaveErr(null); };
  const save = async () => {
    if (!edits || !st.data) return;
    setSaving(true); setSaveErr(null); setSaved(null);
    try {
      const r = await postJSON<{ saved: string; backup: string }>("/api/translate/settings/save", {
        mtime: st.data.mtime ?? null, remove: removed,
        providers: edits.filter((e) => !removed.includes(e.name)).map((e) => {
          if (e.isNew) return payload(e);
          // an existing provider: only what changed (unchanged keys stay exactly as they are in the file)
          const o = orig.find((x) => x.name === e.name);
          const full = payload(e) as Record<string, unknown>;
          const was = o ? payload(o) as Record<string, unknown> : {};
          return Object.fromEntries(Object.entries(full).filter(([k, v]) => k === "name" || JSON.stringify(v) !== JSON.stringify(was[k])));
        }) });
      setSaved(`Saved to ${r.saved} (old file: ${r.backup}). Used at once, no restart needed.`);
      setRes({});
      loadProviders(true);
      st.reload();
    } catch (e) { setSaveErr((e as Error).message); }
    setSaving(false);
  };
  const test = async (name: string) => {
    setBusy(name); setErr(null);
    try {
      const e = edits?.find((x) => x.name === name);
      const o = orig.find((x) => x.name === name);
      const override = e && o && (e.base_url !== o.base_url || e.model !== o.model || e.timeout !== o.timeout ||
        e.prompt !== o.prompt || e.no_think !== o.no_think)
        ? { base_url: e.base_url, model: e.model, timeout: e.timeout.trim() ? Number(e.timeout) : null, prompt: e.prompt,
            no_think: e.no_think } : undefined;
      const r = await postJSON<TestResp>("/api/translate/test", { provider: name, ...(override ? { override } : {}), ...(text.trim() ? { text } : {}) });
      setRes((o) => ({ ...o, ...Object.fromEntries(r.providers.map((p) => [p.name, p])) }));
    } catch (e) { setErr((e as Error).message); }
    setBusy(null);
  };
  const startAdd = (key: string) => {
    setPreset(key);
    setFound(null);
    setAdding({ ...emptyNew(), ...(PRESETS.find((p) => p.key === key)?.edit || {}) });
  };
  const findModels = async () => {
    if (!adding) return;
    setFinding(true); setFound(null);
    try {
      const r = await postJSON<ModelsResp>("/api/translate/models", { base_url: adding.base_url, ...(adding.api_key_env.trim() ? { api_key_env: adding.api_key_env.trim() } : {}) });
      setFound(r);
      if (r.models.length && !adding.model) setAdding({ ...adding, model: r.models[0] });
    } catch (e) { setFound({ base_url: adding.base_url, reachable: false, models: [], error: (e as Error).message }); }
    setFinding(false);
  };
  const names = new Set((edits || []).map((e) => e.name));
  const addProblem = !adding ? null
    : !NAME_RE.test(adding.name) ? "name: 1-40 letters, digits, _ . - (e.g. qwen36)"
    : names.has(adding.name) ? `the name ${adding.name} is used already`
    : !/^https?:\/\/[^\s/]+/.test(adding.base_url.trim()) ? "URL: http://… or https://… (ending in /v1)"
    : !adding.model.trim() ? "model: the name the server serves (Find models)"
    : null;
  const d = st.data;
  const providerOf = (name: string) => d?.providers.find((p) => p.name === name);
  return (
    <>
      <div className="page-head"><div>
        <Crumbs items={[{ label: "Settings", href: "/settings" }, { label: "Translation" }]} />
        <h1>Translation</h1>
        <div className="sub">The translate buttons next to every text (one per language in &quot;targets&quot;): in auto, the providers below
          are tried in order; the page says which one answered. For reading only: labels and decisions always come from the original text.</div>
      </div></div>
      <ErrorBox error={st.error} onRetry={st.reload} />
      {st.loading && !d ? <Loading what="Loading the settings" /> : null}
      {d && !d.configured ? <div className="alert">No &quot;translate&quot; block in viewer_config.json: see cmds/viewer/translate.md.</div> : null}
      {d ? (<>
        <div className="panel">
          <div className="faint" style={{ fontSize: 12 }}>settings from <code>{d.source}</code> · cache <code>{d.cache_dir}</code> · targets {d.targets.map((t) => t.name).join(", ")}</div>
          <label style={{ display: "block", marginTop: 8 }}>test text (empty = a benchmark sentence)
            <textarea className="mono" rows={2} style={{ width: "100%" }} value={text} onChange={(e) => setText(e.target.value)} /></label>
          {err ? <div className="alert error">{err}</div> : null}
        </div>
        {d.editable ? (
          <div className="panel row" style={{ flexWrap: "wrap", position: "sticky", top: 0, zIndex: 2 }} data-testid="translate-savebar">
            <span className="faint" style={{ fontSize: 12 }}>Add or remove a model, change the order (↑ ↓: auto tries them top to bottom), switch one
              off for auto, or change its settings; then save. The translate panel&apos;s &quot;using&quot; choice can still pick any one.</span>
            <span className="spacer" />
            {changed ? <span className="badge warn">not saved</span> : null}
            <button className="btn small ghost" disabled={!changed || saving} onClick={undo}>Undo changes</button>
            <button className="btn small primary" disabled={!changed || saving} onClick={save} data-testid="translate-save">
              {saving ? "Saving…" : "Save to viewer_config.json"}</button>
          </div>) : (
          <div className="alert">These settings are not from a viewer_config.json file, so they cannot be changed here.</div>)}
        {saved ? <div className="alert ok" data-testid="translate-saved">{saved}</div> : null}
        {saveErr ? <div className="alert error" data-testid="translate-save-error">{saveErr}</div> : null}
        {(edits || d.providers.map(toEdit)).map((e, i, all) => {
          const p = providerOf(e.name);
          const r = res[e.name];
          const gone = removed.includes(e.name);
          const ed = !!d.editable && !!edits;
          const open = !!more[e.name] || !!e.isNew;
          return (
            <div key={e.name} className="panel" data-testid={`provider-${e.name}`} style={gone ? { opacity: 0.5 } : undefined}>
              <div className="row" style={{ flexWrap: "wrap" }}>
                <strong style={gone ? { textDecoration: "line-through" } : undefined}>{i + 1}. {e.name}</strong>
                {e.isNew ? <span className="badge warn">new, not saved</span> : null}
                {gone ? <span className="badge filter">will be removed on save</span> : null}
                {ed && !gone ? (<>
                  <button className="btn small ghost" disabled={i === 0} onClick={() => move(i, -1)} title="earlier in auto" data-testid={`up-${e.name}`}>↑</button>
                  <button className="btn small ghost" disabled={i === all.length - 1} onClick={() => move(i, 1)} title="later in auto" data-testid={`down-${e.name}`}>↓</button>
                  <label style={{ fontSize: 12 }}><input type="checkbox" checked={e.enabled} onChange={(ev) => setEdit(i, { enabled: ev.target.checked })} data-testid={`on-${e.name}`} /> used by auto</label>
                </>) : (!ed && e.enabled === false ? <span className="badge neutral">disabled</span> : null)}
                <span className="badge neutral">{e.kind}</span>
                {e.prompt === "hunyuan" ? <span className="badge neutral">Hunyuan-MT prompt</span> : null}
                {p?.api_key_env ? <span className="faint" style={{ fontSize: 12 }}>key from ${p.api_key_env} {p.has_key ? "(set)" : "(not set)"}</span> : null}
                {e.link ? <a href={e.link} target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>model card ↗</a> : null}
                <span className="spacer" />
                {ed ? (gone
                  ? <button className="btn small ghost" onClick={() => setRemoved((rs) => rs.filter((x) => x !== e.name))}>Undo remove</button>
                  : <button className="btn small ghost" data-testid={`remove-${e.name}`} title="remove this provider (on save)"
                      onClick={() => e.isNew ? setEdits((es) => es ? es.filter((x) => x.name !== e.name) : es) : setRemoved((rs) => [...rs, e.name])}>Remove</button>) : null}
                {e.isNew ? <span className="faint" style={{ fontSize: 12 }}>save to test it</span> : (
                  <button className="btn small primary" disabled={!!busy || gone} onClick={() => test(e.name)} data-testid={`test-${e.name}`}
                    title="reachable? served models, a sample translation (with the URL / model / prompt typed here, saved or not)">
                    {busy === e.name ? "Testing…" : "Test"}</button>)}
              </div>
              {e.note && !open ? <div className="faint" style={{ fontSize: 12, marginTop: 4, whiteSpace: "pre-wrap" }} data-testid={`note-${e.name}`}>{e.note}</div> : null}
              {ed && !gone ? (
                <div className="row" style={{ flexWrap: "wrap", marginTop: 6, gap: 8 }}>
                  <label style={{ fontSize: 12 }}>URL <input type="text" className="mono" style={{ width: 300 }} value={e.base_url}
                    onChange={(ev) => setEdit(i, { base_url: ev.target.value })} data-testid={`url-${e.name}`} /></label>
                  <label style={{ fontSize: 12 }}>model <input type="text" className="mono" style={{ width: 200 }} value={e.model}
                    onChange={(ev) => setEdit(i, { model: ev.target.value })} data-testid={`model-${e.name}`} /></label>
                  <label style={{ fontSize: 12 }}>timeout (s) <input type="number" min={1} max={3600} style={{ width: 80 }} value={e.timeout}
                    onChange={(ev) => setEdit(i, { timeout: ev.target.value })} /></label>
                  {!e.isNew ? <button className="btn small ghost" onClick={() => setMore((m) => ({ ...m, [e.name]: !m[e.name] }))}
                    data-testid={`more-${e.name}`}>{open ? "less ▴" : "more ▾"}</button> : null}
                </div>) : (!ed ? <div style={{ marginTop: 6 }}><code>{e.base_url}</code> <span>model <code>{e.model}</code></span></div> : null)}
              {ed && !gone && open ? (
                <div className="row" style={{ flexWrap: "wrap", marginTop: 6, gap: 8, alignItems: "flex-start" }}>
                  <label style={{ fontSize: 12 }}>prompt <select value={e.prompt} onChange={(ev) => setEdit(i, { prompt: ev.target.value })}>
                    <option value="generic">generic (chat models)</option><option value="hunyuan">hunyuan (Hunyuan-MT)</option></select></label>
                  <label style={{ fontSize: 12 }} title="Qwen3 / 3.5 / 3.6: send enable_thinking=false so it answers at once"><input type="checkbox" checked={e.no_think}
                    onChange={(ev) => setEdit(i, { no_think: ev.target.checked })} /> thinking off</label>
                  <label style={{ fontSize: 12 }} title="the NAME of an environment variable that holds the key (never the key itself)">key variable
                    <input type="text" className="mono" style={{ width: 150 }} placeholder="e.g. QWEN_API_KEY" value={e.api_key_env}
                      onChange={(ev) => setEdit(i, { api_key_env: ev.target.value })} /></label>
                  <label style={{ fontSize: 12 }}>link <input type="text" className="mono" style={{ width: 300 }} placeholder="https://huggingface.co/…" value={e.link}
                    onChange={(ev) => setEdit(i, { link: ev.target.value })} data-testid={`link-${e.name}`} /></label>
                  <label style={{ fontSize: 12, flexBasis: "100%" }}>note (what it is, where it runs, how good it is)
                    <textarea rows={2} style={{ width: "100%" }} value={e.note} onChange={(ev) => setEdit(i, { note: ev.target.value })} data-testid={`notebox-${e.name}`} /></label>
                </div>) : null}
              {r ? (<div style={{ marginTop: 8 }}>
                <div className="row" style={{ flexWrap: "wrap" }}>
                  <span className={`badge ${r.reachable ? "keep" : "filter"}`} data-testid={`reach-${e.name}`}>{r.reachable ? "reachable" : "not reachable"}</span>
                  {r.models?.length ? <span>serves {r.models.map((m) => <code key={m} style={{ marginRight: 4 }}>{m}</code>)}</span> : null}
                  {r.reachable && r.model_served === false ? <span className="badge warn">the configured model is not served</span> : null}
                  {r.reachable && r.model_served === false && r.models?.length && ed ? (
                    <button className="btn small ghost" onClick={() => setEdit(i, { model: r.models![0] })} data-testid={`use-served-${e.name}`}>use {r.models[0]}</button>) : null}
                  {r.error ? <span className="faint" style={{ fontSize: 12 }}>{r.error}</span> : null}
                </div>
                {r.samples.map((s) => (
                  <div key={s.target} style={{ marginTop: 6 }}>
                    <span className={`badge ${s.ok ? "keep" : "warn"}`}>{s.target}</span>{" "}
                    {s.seconds !== undefined ? <span className="faint" style={{ fontSize: 12 }}>{s.seconds}s</span> : null}
                    {s.error ? <span className="faint" style={{ fontSize: 12 }}> · {s.error}</span> : null}
                    <div className="doc-text" style={{ whiteSpace: "pre-wrap" }}>{s.translation}</div>
                    {s.retry ? <div className="faint" style={{ fontSize: 12 }}>stricter retry ({s.retry.ok ? "ok" : "still wrong"}): {s.retry.translation}</div> : null}
                  </div>))}
              </div>) : null}
            </div>);
        })}
        {d.editable && edits ? (
          <div className="panel" data-testid="translate-add">
            <h2>Add a translation model</h2>
            {!adding ? (
              <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
                {PRESETS.map((p) => <button key={p.key} className="btn small" onClick={() => startAdd(p.key)} data-testid={`add-${p.key}`}>+ {p.label}</button>)}
              </div>) : (<>
              <div className="faint" style={{ fontSize: 12, marginBottom: 6 }}>{PRESETS.find((p) => p.key === preset)?.help}</div>
              <div className="row" style={{ flexWrap: "wrap", gap: 8 }}>
                <label style={{ fontSize: 12 }}>name <input type="text" className="mono" style={{ width: 140 }} placeholder="e.g. qwen36" value={adding.name}
                  onChange={(ev) => setAdding({ ...adding, name: ev.target.value.trim() })} data-testid="add-name" /></label>
                <label style={{ fontSize: 12 }}>URL <input type="text" className="mono" style={{ width: 300 }} value={adding.base_url}
                  onChange={(ev) => { setAdding({ ...adding, base_url: ev.target.value }); setFound(null); }} data-testid="add-url" /></label>
                <button className="btn small ghost" disabled={finding || !/^https?:\/\/[^\s/]+/.test(adding.base_url.trim())} onClick={findModels}
                  data-testid="add-find">{finding ? "Asking…" : "Find models"}</button>
                <label style={{ fontSize: 12 }}>model <input type="text" className="mono" style={{ width: 220 }} list="tr-found-models" value={adding.model}
                  onChange={(ev) => setAdding({ ...adding, model: ev.target.value })} data-testid="add-model" /></label>
                <datalist id="tr-found-models">{(found?.models || []).map((m) => <option key={m} value={m} />)}</datalist>
                <label style={{ fontSize: 12 }}>timeout (s) <input type="number" min={1} max={3600} style={{ width: 80 }} value={adding.timeout}
                  onChange={(ev) => setAdding({ ...adding, timeout: ev.target.value })} /></label>
              </div>
              {found ? (
                <div style={{ fontSize: 12, marginTop: 4 }} data-testid="add-found">
                  {found.reachable
                    ? (found.models.length ? <>the server serves {found.models.map((m) => (
                        <button key={m} className="btn small ghost" onClick={() => setAdding({ ...adding, model: m })}>{m}</button>))}</>
                      : "reachable, but it lists no models")
                    : <span className="badge filter">not reachable</span>} {found.error ? <span className="faint">{found.error}</span> : null}
                </div>) : null}
              <div className="row" style={{ flexWrap: "wrap", gap: 8, marginTop: 6, alignItems: "flex-start" }}>
                <label style={{ fontSize: 12 }}>kind <select value={adding.kind} onChange={(ev) => setAdding({ ...adding, kind: ev.target.value })}>
                  <option value="openai">openai (any OpenAI-compatible server)</option><option value="local">local (tools/serve_translate_local.py)</option></select></label>
                <label style={{ fontSize: 12 }}>prompt <select value={adding.prompt} onChange={(ev) => setAdding({ ...adding, prompt: ev.target.value })}>
                  <option value="generic">generic (chat models)</option><option value="hunyuan">hunyuan (Hunyuan-MT)</option></select></label>
                <label style={{ fontSize: 12 }}><input type="checkbox" checked={adding.no_think} onChange={(ev) => setAdding({ ...adding, no_think: ev.target.checked })} /> thinking off</label>
                <label style={{ fontSize: 12 }}>key variable <input type="text" className="mono" style={{ width: 150 }} placeholder="none, or e.g. QWEN36_KEY"
                  value={adding.api_key_env} onChange={(ev) => setAdding({ ...adding, api_key_env: ev.target.value })} /></label>
                <label style={{ fontSize: 12 }}>link <input type="text" className="mono" style={{ width: 320 }} placeholder="https://huggingface.co/Qwen/Qwen3.6-35B-A3B"
                  value={adding.link} onChange={(ev) => setAdding({ ...adding, link: ev.target.value })} data-testid="add-link" /></label>
                <label style={{ fontSize: 12, flexBasis: "100%" }}>note (what it is, where it runs, how good it is)
                  <textarea rows={2} style={{ width: "100%" }} value={adding.note} onChange={(ev) => setAdding({ ...adding, note: ev.target.value })} data-testid="add-note" /></label>
              </div>
              <div className="row" style={{ gap: 8, marginTop: 6 }}>
                {addProblem ? <span className="faint" style={{ fontSize: 12 }} data-testid="add-problem">{addProblem}</span> : null}
                <span className="spacer" />
                <button className="btn small ghost" onClick={() => { setAdding(null); setFound(null); }}>Cancel</button>
                <button className="btn small primary" disabled={!!addProblem} data-testid="add-confirm"
                  onClick={() => { setEdits((es) => [...(es || []), { ...adding, base_url: adding.base_url.trim(), model: adding.model.trim() }]); setAdding(null); setFound(null); }}>
                  Add to the list</button>
              </div>
              <div className="faint" style={{ fontSize: 12, marginTop: 4 }}>Added at the end (last in auto); then &quot;Save to viewer_config.json&quot;.</div>
            </>)}
          </div>) : null}
        <div className="panel">
          <h2>Try it</h2>
          <div className="faint" style={{ fontSize: 12, marginBottom: 6 }}>the same buttons as next to every text (with the &quot;using&quot; choice)</div>
          <TextTools text={text.trim() || "Shchi is a traditional Russian cabbage soup, often served with sour cream and dark rye bread."} testid="translate-try" />
        </div>
      </>) : null}
    </>
  );
}

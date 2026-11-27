"use client";
// /label/translate/: the translation providers of viewer_config.json ("translate"), tried in order (Qwen endpoint first,
// Hunyuan-MT-7B when it fails), with a test button per provider: reachable now?, the models it serves, a sample
// translation per target with the language check. Editable here: the order, on / off (for auto), URL, model and timeout
// of each provider, saved into the "translate" block of viewer_config.json (with a backup) and used at once.
import { useEffect, useState } from "react";
import { getJSON, postJSON, useApi } from "@/lib/api";
import { Crumbs, ErrorBox, Loading } from "./ui";
import { TextTools, loadProviders } from "./TextTools";

type Provider = { name: string; kind: string; base_url?: string; model?: string; timeout?: number; no_think?: boolean;
  prompt?: string; enabled?: boolean; api_key_env?: string | null; has_key?: boolean };
type Settings = { configured: boolean; source?: string; targets: { code: string; name: string; label: string }[];
  providers: Provider[]; cache_dir?: string; concurrency?: number; down_seconds?: number; editable?: boolean; mtime?: string | null };
type Edit = { name: string; enabled: boolean; base_url: string; model: string; timeout: string };
const toEdits = (ps: Provider[]): Edit[] => ps.map((p) => ({ name: p.name, enabled: p.enabled !== false,
  base_url: p.base_url || "", model: p.model || "", timeout: String(p.timeout ?? "") }));
type Sample = { target: string; ok: boolean; translation: string | null; seconds?: number; error?: string | null;
  language?: { ok: boolean; target_share?: number; main_script?: string }; retry?: { ok: boolean; translation: string | null } };
type TestResp = { text: string; providers: { name: string; model?: string; base_url?: string; enabled?: boolean; reachable: boolean;
  models?: string[]; model_served?: boolean; error?: string | null; seconds?: number; samples: Sample[] }[] };

export function TranslateSettingsView() {
  const st = useApi("translate:settings", (s) => getJSON<Settings>("/api/translate/settings", undefined, s));
  const [busy, setBusy] = useState<string | null>(null);
  const [res, setRes] = useState<Record<string, TestResp["providers"][number]>>({});
  const [err, setErr] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [edits, setEdits] = useState<Edit[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  useEffect(() => { if (st.data) setEdits(toEdits(st.data.providers)); }, [st.data]);
  const orig = st.data ? toEdits(st.data.providers) : [];
  const changed = !!edits && JSON.stringify(edits) !== JSON.stringify(orig);
  const setEdit = (i: number, patch: Partial<Edit>) => setEdits((es) => es ? es.map((e, j) => j === i ? { ...e, ...patch } : e) : es);
  const move = (i: number, by: number) => setEdits((es) => {
    if (!es) return es;
    const j = i + by;
    if (j < 0 || j >= es.length) return es;
    const out = es.slice();
    [out[i], out[j]] = [out[j], out[i]];
    return out;
  });
  const save = async () => {
    if (!edits || !st.data) return;
    setSaving(true); setSaveErr(null); setSaved(null);
    try {
      const r = await postJSON<{ saved: string; backup: string }>("/api/translate/settings/save", {
        mtime: st.data.mtime ?? null,
        providers: edits.map((e) => ({ name: e.name, enabled: e.enabled, base_url: e.base_url, model: e.model,
          timeout: e.timeout.trim() ? Number(e.timeout) : null })) });
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
      const override = e && o && (e.base_url !== o.base_url || e.model !== o.model || e.timeout !== o.timeout)
        ? { base_url: e.base_url, model: e.model, timeout: e.timeout.trim() ? Number(e.timeout) : null } : undefined;
      const r = await postJSON<TestResp>("/api/translate/test", { provider: name, ...(override ? { override } : {}), ...(text.trim() ? { text } : {}) });
      setRes((o) => ({ ...o, ...Object.fromEntries(r.providers.map((p) => [p.name, p])) }));
    } catch (e) { setErr((e as Error).message); }
    setBusy(null);
  };
  const d = st.data;
  return (
    <>
      <div className="page-head"><div>
        <Crumbs items={[{ label: "Labelling", href: "/label" }, { label: "Translation" }]} />
        <h1>Translation</h1>
        <div className="sub">The Korean / Russian buttons next to every text: the providers below are tried in order; the page says which one
          answered. For reading only: labels and decisions always come from the original text.</div>
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
            <span className="faint" style={{ fontSize: 12 }}>Change the order (↑ ↓: auto tries them top to bottom), switch one off for auto,
              or change its URL / model / timeout; then save. The translate panel&apos;s &quot;using&quot; choice can still pick any one.</span>
            <span className="spacer" />
            {changed ? <span className="badge warn">not saved</span> : null}
            <button className="btn small ghost" disabled={!changed || saving} onClick={() => { setEdits(orig); setSaveErr(null); }}>Undo changes</button>
            <button className="btn small primary" disabled={!changed || saving} onClick={save} data-testid="translate-save">
              {saving ? "Saving…" : "Save to viewer_config.json"}</button>
          </div>) : (
          <div className="alert">These settings are not from a viewer_config.json file, so they cannot be changed here.</div>)}
        {saved ? <div className="alert ok" data-testid="translate-saved">{saved}</div> : null}
        {saveErr ? <div className="alert error" data-testid="translate-save-error">{saveErr}</div> : null}
        {(edits && edits.length === d.providers.length ? edits.map((x) => d.providers.find((p) => p.name === x.name)!) : d.providers).map((p, i) => {
          const r = res[p.name];
          const e = edits && edits.length === d.providers.length ? edits[i] : undefined;
          return (
            <div key={p.name} className="panel" data-testid={`provider-${p.name}`}>
              <div className="row" style={{ flexWrap: "wrap" }}>
                <strong>{i + 1}. {p.name}</strong>
                {d.editable && e ? (<>
                  <button className="btn small ghost" disabled={i === 0} onClick={() => move(i, -1)} title="earlier in auto" data-testid={`up-${p.name}`}>↑</button>
                  <button className="btn small ghost" disabled={!edits || i === edits.length - 1} onClick={() => move(i, 1)} title="later in auto" data-testid={`down-${p.name}`}>↓</button>
                  <label style={{ fontSize: 12 }}><input type="checkbox" checked={e.enabled} onChange={(ev) => setEdit(i, { enabled: ev.target.checked })} data-testid={`on-${p.name}`} /> used by auto</label>
                </>) : (p.enabled === false ? <span className="badge neutral">disabled</span> : null)}
                <span className="badge neutral">{p.kind}</span>
                {p.api_key_env ? <span className="faint" style={{ fontSize: 12 }}>key from ${p.api_key_env} {p.has_key ? "(set)" : "(not set)"}</span> : null}
                <span className="spacer" />
                <button className="btn small primary" disabled={!!busy} onClick={() => test(p.name)} data-testid={`test-${p.name}`}
                  title="reachable? served models, a sample translation (with the URL / model / timeout typed here, saved or not)">
                  {busy === p.name ? "Testing…" : "Test"}</button>
              </div>
              {d.editable && e ? (
                <div className="row" style={{ flexWrap: "wrap", marginTop: 6, gap: 8 }}>
                  <label style={{ fontSize: 12 }}>URL <input type="text" className="mono" style={{ width: 300 }} value={e.base_url}
                    onChange={(ev) => setEdit(i, { base_url: ev.target.value })} data-testid={`url-${p.name}`} /></label>
                  <label style={{ fontSize: 12 }}>model <input type="text" className="mono" style={{ width: 180 }} value={e.model}
                    onChange={(ev) => setEdit(i, { model: ev.target.value })} data-testid={`model-${p.name}`} /></label>
                  <label style={{ fontSize: 12 }}>timeout (s) <input type="number" min={1} max={3600} style={{ width: 80 }} value={e.timeout}
                    onChange={(ev) => setEdit(i, { timeout: ev.target.value })} /></label>
                </div>) : (
                <div style={{ marginTop: 6 }}><code>{p.base_url}</code> <span>model <code>{p.model}</code></span></div>)}
              {r ? (<div style={{ marginTop: 8 }}>
                <div className="row" style={{ flexWrap: "wrap" }}>
                  <span className={`badge ${r.reachable ? "keep" : "filter"}`} data-testid={`reach-${p.name}`}>{r.reachable ? "reachable" : "not reachable"}</span>
                  {r.models?.length ? <span>serves {r.models.map((m) => <code key={m} style={{ marginRight: 4 }}>{m}</code>)}</span> : null}
                  {r.reachable && r.model_served === false ? <span className="badge warn">the configured model is not served</span> : null}
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
        <div className="panel">
          <h2>Try it</h2>
          <div className="faint" style={{ fontSize: 12, marginBottom: 6 }}>the same buttons as next to every text (with the fallback)</div>
          <TextTools text={text.trim() || "Shchi is a traditional Russian cabbage soup, often served with sour cream and dark rye bread."} testid="translate-try" />
        </div>
      </>) : null}
    </>
  );
}

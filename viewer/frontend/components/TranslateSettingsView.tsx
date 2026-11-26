"use client";
// /label/translate/: the translation providers of viewer_config.json ("translate"), tried in order (Qwen endpoint first,
// Hunyuan-MT-7B when it fails), with a test button per provider: reachable now?, the models it serves, a sample
// translation per target with the language check. The settings are edited in viewer_config.json (cmds/viewer/translate.md).
import { useState } from "react";
import { getJSON, postJSON, useApi } from "@/lib/api";
import { Crumbs, ErrorBox, Loading } from "./ui";
import { TextTools } from "./TextTools";

type Provider = { name: string; kind: string; base_url?: string; model?: string; timeout?: number; no_think?: boolean;
  prompt?: string; enabled?: boolean; api_key_env?: string | null; has_key?: boolean };
type Settings = { configured: boolean; source?: string; targets: { code: string; name: string; label: string }[];
  providers: Provider[]; cache_dir?: string; concurrency?: number; down_seconds?: number };
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
  const test = async (name: string) => {
    setBusy(name); setErr(null);
    try {
      const r = await postJSON<TestResp>("/api/translate/test", { provider: name, ...(text.trim() ? { text } : {}) });
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
        <div className="sub">The 中文 / Русский buttons next to every text: the providers below are tried in order; the page says which one
          answered. For reading only: labels and decisions always come from the original text.</div>
      </div></div>
      <ErrorBox error={st.error} onRetry={st.reload} />
      {st.loading && !d ? <Loading what="Loading the settings" /> : null}
      {d && !d.configured ? <div className="alert">No &quot;translate&quot; block in viewer_config.json: see cmds/viewer/translate.md.</div> : null}
      {d ? (<>
        <div className="panel">
          <div className="faint" style={{ fontSize: 12 }}>settings from <code>{d.source}</code> · cache <code>{d.cache_dir}</code> · targets {d.targets.map((t) => t.label).join(", ")}</div>
          <label style={{ display: "block", marginTop: 8 }}>test text (empty = a benchmark sentence)
            <textarea className="mono" rows={2} style={{ width: "100%" }} value={text} onChange={(e) => setText(e.target.value)} /></label>
          {err ? <div className="alert error">{err}</div> : null}
        </div>
        {d.providers.map((p, i) => {
          const r = res[p.name];
          return (
            <div key={p.name} className="panel" data-testid={`provider-${p.name}`}>
              <div className="row" style={{ flexWrap: "wrap" }}>
                <strong>{i + 1}. {p.name}</strong>
                {p.enabled === false ? <span className="badge neutral">disabled</span> : null}
                <span className="badge neutral">{p.kind}</span>
                <code>{p.base_url}</code> <span>model <code>{p.model}</code></span>
                {p.api_key_env ? <span className="faint" style={{ fontSize: 12 }}>key from ${p.api_key_env} {p.has_key ? "(set)" : "(not set)"}</span> : null}
                <span className="spacer" />
                <button className="btn small primary" disabled={!!busy} onClick={() => test(p.name)} data-testid={`test-${p.name}`}>
                  {busy === p.name ? "Testing…" : "Test"}</button>
              </div>
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

"use client";
// "Try settings": run nli_filter.py's decision on the lines of this page with other keywords / hypotheses /
// thresholds, through the model service nli_playground.py. Hypothesis files (hypotheses/*.json) and keyword
// files (keywords/*.txt) are shared with nli_filter.py and can be saved from here.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, useApi } from "@/lib/api";
import type { HypothesesData, PlaygroundInfo, PlaygroundRun, TryResult } from "@/lib/types";
import { ErrorBox } from "./ui";

export type TrySettings = {
  country: string; adj: string;
  kwFile: string; keywords: string;
  hypFile: string; hyp: HypothesesData;
  useJudge: boolean; check1: number; check2: number; bandLo: number; bandHi: number;
  maxWindows: number; earlyStop: boolean; rules: boolean;
};

const STORE = "nli-viewer-try-settings";
const BUILTIN = "(built-in)";

function load(): Partial<TrySettings> {
  try {
    return JSON.parse(localStorage.getItem(STORE) || "{}");
  } catch {
    return {};
  }
}

export type TryControl = { run: () => void; ready: boolean; running: boolean; count: number };

export function TryPanel({ ds, path, member, lines, onResults, onControl }: {
  ds: string; path: string; member: string | null; lines: number[];
  onResults: (r: PlaygroundRun | null) => void;
  onControl?: (c: TryControl) => void;  // e.g. a second Run button at the bottom of the page
}) {
  const info = useApi("playground", (s) => api.playground(s));
  const [open, setOpen] = useState(false);
  const [st, setSt] = useState<TrySettings | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [last, setLast] = useState<PlaygroundRun | null>(null);
  const set = (p: Partial<TrySettings>) => setSt((s) => (s ? { ...s, ...p } : s));

  // first settings: what this browser used last, else Russia + keywords/russia.txt + hypotheses/russia.json
  useEffect(() => {
    if (!info.data || st) return;
    const d = info.data;
    const saved = load();
    const country = saved.country || "Russia";
    const adj = saved.adj || d.countries.find((c) => c.name === country)?.adj || "";
    const kw = d.keywords.find((k) => k.name === (saved.kwFile || country.toLowerCase()));
    const hf = d.hypotheses.find((h) => h.name === (saved.hypFile || country.toLowerCase()) && h.data);
    setSt({
      country, adj,
      kwFile: kw ? kw.name : BUILTIN, keywords: saved.keywords ?? (kw ? kw.text : ""),
      hypFile: hf ? hf.name : BUILTIN, hyp: saved.hyp || (hf?.data as HypothesesData) || d.builtin_hypotheses,
      useJudge: saved.useJudge ?? true, check1: saved.check1 ?? 0.8, check2: saved.check2 ?? 0.8,
      bandLo: saved.bandLo ?? 0.6, bandHi: saved.bandHi ?? 0.95, maxWindows: saved.maxWindows ?? 2,
      earlyStop: saved.earlyStop ?? true, rules: saved.rules ?? true,
    });
  }, [info.data, st]);
  useEffect(() => {
    if (!st) return;
    try { localStorage.setItem(STORE, JSON.stringify(st)); } catch { /* storage off: fine */ }
  }, [st]);
  useEffect(() => { onResults(null); setLast(null); }, [path, member]);  // eslint-disable-line react-hooks/exhaustive-deps

  async function run() {
    if (!st) return;
    setRunning(true);
    setError(null);
    try {
      const r = await api.playgroundRun(ds, {
        path, member, lines, settings: {
          country: st.country, country_adj: st.adj, keywords: st.keywords,
          check1: st.hyp.check1, check2: st.hyp.check2, use_judge: st.useJudge,
          check1_threshold: st.check1, check2_threshold: st.check2, uncertain_band: [st.bandLo, st.bandHi],
          max_windows: st.maxWindows, early_stop: st.earlyStop, rules: st.rules,
        },
      });
      setLast(r);
      onResults(r);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError((e as Error).message, 0));
    } finally {
      setRunning(false);
    }
  }

  const svc = info.data?.service;
  const ready = !!st && !!svc?.running && lines.length > 0;
  const runRef = useRef(run);
  runRef.current = run;  // the latest settings; the function handed out stays the same
  const stableRun = useCallback(() => { void runRef.current(); }, []);
  useEffect(() => { onControl?.({ run: stableRun, ready, running, count: lines.length }); },
    [ready, running, lines.length, stableRun]);  // eslint-disable-line react-hooks/exhaustive-deps
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const r of last?.results || []) c[r.decision.decision] = (c[r.decision.decision] || 0) + 1;
    return c;
  }, [last]);
  const changed = (last?.results || []).filter((r) => r.previous && r.previous.decision !== r.decision.decision).length;

  return (
    <div className="panel try-panel" data-testid="try-panel">
      <div className="row">
        <button className="btn small" onClick={() => setOpen((o) => !o)}>{open ? "▾" : "▸"} Try settings</button>
        <span className="muted">run the filter on these lines with other keywords / hypotheses</span>
        <span className="spacer" />
        {svc ? (svc.running
          ? <span className="badge keep" title={svc.url}>models: {svc.fast}{svc.judge ? ` + ${svc.judge}` : ""}</span>
          : <span className="badge warn" title={svc.error}>model service not running</span>) : null}
        {last ? <span className="muted">{Object.entries(counts).map(([k, v]) => `${v} ${k}`).join(", ")}{changed ? ` · ${changed} changed vs the run` : ""} · {last.seconds.toFixed(1)} s</span> : null}
        {last ? <button className="btn small ghost" onClick={() => { setLast(null); onResults(null); }}>Clear results</button> : null}
      </div>
      <ErrorBox error={info.error} />
      {open && svc && !svc.running ? (
        <div className="alert warn">The model service is not running. Start it where the models are (in the project folder):<pre className="json">{svc.start}</pre>{svc.error}</div>
      ) : null}
      {open && st && info.data ? <Settings info={info.data} st={st} set={set} onSaved={info.reload} /> : null}
      {open && st ? (
        <div className="row">
          <button className="btn primary" onClick={run} disabled={running || !svc?.running || !lines.length}>
            {running ? "Running…" : `Run on the ${lines.length} line${lines.length === 1 ? "" : "s"} of this page`}
          </button>
          <span className="faint">results appear on each line; “was” = the decision of the saved filter run</span>
        </div>
      ) : null}
      {error ? <div className="alert warn">{error.message}</div> : null}
    </div>
  );
}

function Settings({ info, st, set, onSaved }: {
  info: PlaygroundInfo; st: TrySettings; set: (p: Partial<TrySettings>) => void; onSaved: () => void;
}) {
  const kwCount = st.keywords.split("\n").filter((l) => l.trim() && !l.trim().startsWith("#")).length;
  return (
    <div className="try-grid">
      <fieldset>
        <legend>Country</legend>
        <div className="row">
          <select value={info.countries.some((c) => c.name === st.country) ? st.country : ""}
            onChange={(e) => { const c = info.countries.find((x) => x.name === e.target.value); if (c) set({ country: c.name, adj: c.adj || "" }); }}>
            <option value="">other…</option>
            {info.countries.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
          </select>
          <input type="text" value={st.country} onChange={(e) => set({ country: e.target.value })} placeholder="country" style={{ width: 120 }} />
          <input type="text" value={st.adj} onChange={(e) => set({ adj: e.target.value })} placeholder="adjective" style={{ width: 120 }} />
        </div>
        <legend style={{ marginTop: 10 }}>Model and thresholds</legend>
        <div className="row">
          <label><input type="checkbox" checked={st.useJudge} onChange={(e) => set({ useJudge: e.target.checked })} /> judge (uncertain scores)</label>
          <label>band <input type="number" step={0.05} min={0} max={1} value={st.bandLo} onChange={(e) => set({ bandLo: Number(e.target.value) })} />–<input type="number" step={0.05} min={0} max={1} value={st.bandHi} onChange={(e) => set({ bandHi: Number(e.target.value) })} /></label>
        </div>
        <div className="row">
          <label>check 1 ≥ <input type="number" step={0.05} min={0} max={1} value={st.check1} onChange={(e) => set({ check1: Number(e.target.value) })} /></label>
          <label>check 2 ≥ <input type="number" step={0.05} min={0} max={1} value={st.check2} onChange={(e) => set({ check2: Number(e.target.value) })} /></label>
        </div>
        <div className="row">
          <label>windows <input type="number" min={1} max={20} value={st.maxWindows} onChange={(e) => set({ maxWindows: Number(e.target.value) })} /></label>
          <label><input type="checkbox" checked={st.earlyStop} onChange={(e) => set({ earlyStop: e.target.checked })} /> early stop</label>
          <label><input type="checkbox" checked={st.rules} onChange={(e) => set({ rules: e.target.checked })} /> rules</label>
        </div>
        <legend style={{ marginTop: 10 }}>Keywords <span className="faint">({kwCount})</span></legend>
        <div className="row">
          <select value={st.kwFile} onChange={(e) => {
            const k = info.keywords.find((x) => x.name === e.target.value);
            set({ kwFile: e.target.value, keywords: k ? k.text : "" });
          }}>
            <option value={BUILTIN}>{BUILTIN} for the country</option>
            {info.keywords.map((k) => <option key={k.name} value={k.name}>keywords/{k.file} ({k.count})</option>)}
          </select>
        </div>
        <div className="editor"><textarea className="mono" rows={8} value={st.keywords} spellCheck={false}
          placeholder="one keyword per line; empty = the built-in list of the country" onChange={(e) => set({ keywords: e.target.value })} /></div>
        <SaveBox kind="keywords" defaultName={st.kwFile === BUILTIN ? st.country.toLowerCase() : st.kwFile}
          save={(name, overwrite) => api.saveKeywords({ name, text: st.keywords, overwrite })}
          onSaved={(name) => { set({ kwFile: name }); onSaved(); }} />
      </fieldset>
      <fieldset>
        <legend>Hypotheses</legend>
        <div className="row">
          <select value={st.hypFile} onChange={(e) => {
            const h = info.hypotheses.find((x) => x.name === e.target.value);
            set({ hypFile: e.target.value, hyp: (h?.data as HypothesesData) || info.builtin_hypotheses });
          }}>
            <option value={BUILTIN}>{BUILTIN} = hypotheses/default.json</option>
            {info.hypotheses.map((h) => <option key={h.name} value={h.name} disabled={!h.data}>hypotheses/{h.file}{h.error ? " (error)" : ""}</option>)}
          </select>
        </div>
        {info.hypotheses.filter((h) => h.error).map((h) => <div key={h.name} className="alert warn">{h.file}: {h.error}</div>)}
        <input type="text" value={st.hyp.description || ""} placeholder="description" style={{ width: "100%" }}
          onChange={(e) => set({ hyp: { ...st.hyp, description: e.target.value } })} />
        <HypEditor title="Check 1 · is the text about the country?" rows={st.hyp.check1}
          onChange={(check1) => set({ hyp: { ...st.hyp, check1 } })} />
        <HypEditor title="Check 2 · is a hit only incidental? (empty = no check 2)" rows={st.hyp.check2}
          onChange={(check2) => set({ hyp: { ...st.hyp, check2 } })} />
        <div className="faint" style={{ fontSize: 12 }}>Use <span className="mono">{"{country}"}</span> and <span className="mono">{"{country_adj}"}</span>; each key = one hypothesis, the highest score counts.</div>
        <SaveBox kind="hypotheses" defaultName={st.hypFile === BUILTIN ? st.country.toLowerCase() : st.hypFile}
          save={(name, overwrite) => api.saveHypotheses({ name, data: st.hyp, overwrite })}
          onSaved={(name) => { set({ hypFile: name }); onSaved(); }} />
      </fieldset>
    </div>
  );
}

function HypEditor({ title, rows, onChange }: { title: string; rows: Record<string, string>; onChange: (r: Record<string, string>) => void }) {
  const entries = Object.entries(rows);
  const rename = (old: string, key: string) => onChange(Object.fromEntries(entries.map(([k, v]) => [k === old ? key : k, v])));
  return (
    <div className="hyp-editor">
      <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>{title}</div>
      {entries.map(([k, v], i) => (
        <div className="row" key={i} style={{ alignItems: "flex-start" }}>
          <input type="text" className="mono" value={k} style={{ width: 130 }} onChange={(e) => rename(k, e.target.value)} />
          <textarea className="hyp-text" rows={2} value={v} spellCheck={false} onChange={(e) => onChange({ ...rows, [k]: e.target.value })} />
          <button className="btn small ghost" title="remove" onClick={() => onChange(Object.fromEntries(entries.filter(([x]) => x !== k)))}>✕</button>
        </div>
      ))}
      <button className="btn small ghost" onClick={() => {
        let n = entries.length + 1;
        while (`hyp${n}` in rows) n++;
        onChange({ ...rows, [`hyp${n}`]: "This text is about {country}." });
      }}>+ add hypothesis</button>
    </div>
  );
}

function SaveBox({ kind, defaultName, save, onSaved }: {
  kind: string; defaultName: string; save: (name: string, overwrite: boolean) => Promise<{ file: string; backup: string | null }>;
  onSaved: (name: string) => void;
}) {
  const [name, setName] = useState(defaultName);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => setName(defaultName), [defaultName]);
  async function go(overwrite: boolean) {
    setBusy(true);
    setMsg(null);
    try {
      const r = await save(name, overwrite);
      setMsg(`saved ${r.file}${r.backup ? ` (old version: ${r.backup})` : ""}`);
      onSaved(name);
    } catch (e) {
      const m = (e as Error).message;
      if (!overwrite && m.includes("exists") && window.confirm(`${kind}/${name} exists. Overwrite it? (the old file is backed up)`)) {
        setBusy(false);
        return go(true);
      }
      setMsg(m);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="row" style={{ marginTop: 6 }}>
      <span className="faint">{kind}/</span>
      <input type="text" className="mono" value={name} onChange={(e) => setName(e.target.value)} style={{ width: 140 }} />
      <button className="btn small" disabled={busy || !name} onClick={() => go(false)}>Save</button>
      {msg ? <span className="faint" style={{ fontSize: 12 }}>{msg}</span> : null}
    </div>
  );
}

export type { TryResult };

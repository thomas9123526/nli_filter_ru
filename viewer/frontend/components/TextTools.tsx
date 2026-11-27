"use client";
// [Copy ▾] [Korean] [Russian] next to every text the Labelling pages show. Copy: the text, the selected paragraph, the
// text with its source (file · line · id), the row as JSON, the translation. Translate: POST /api/translate (the
// providers of viewer_config.json "translate", tried in order: Qwen endpoint first, Hunyuan-MT-7B when it fails),
// shown in a side panel with the provider that answered; for reading only, labels always come from the original.
// The panel's "using" choice: auto (in order, with the fallback) or one provider only; remembered in this browser.
import { useEffect, useRef, useState } from "react";
import { getJSON, postJSON } from "@/lib/api";

export type TextSource = { run?: string; file?: string | null; line?: number | null; id?: string | null };

/** "text\n\n— file · line N · id X · run R" (for notes and questions). */
export function withSource(text: string, src: TextSource): string {
  const bits = [src.file, src.line !== undefined && src.line !== null ? `line ${src.line}` : null,
    src.id ? `id ${src.id}` : null, src.run ? `run ${src.run}` : null].filter(Boolean);
  return bits.length ? `${text}\n\n— ${bits.join(" · ")}` : text;
}

/** Copy to the clipboard: navigator.clipboard where the browser allows it (localhost / https), else a hidden textarea +
 * the copy command (the viewer opened from another computer by a plain http:// address). */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch { /* fall back */ }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "-1000px";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, text.length);
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

export type TranslateResult = { translation: string | null; provider: string | null; model?: string | null;
  fallback?: boolean; cached?: boolean; error?: string | null; errors?: { provider: string; error: string }[] };
export type TranslateResp = { target: string; results: TranslateResult[] };

// the buttons until the settings arrive; then the "targets" of viewer_config.json (English names)
const TARGETS: [string, string][] = [["ko", "Korean"], ["ru", "Russian"]];
const tcache = new Map<string, TranslateResp>();  // this page view: the same text again is instant

export async function translate(texts: string[], target: string, provider?: string): Promise<TranslateResp> {
  const key = `${target}\u0000${provider || ""}\u0000${texts.join("\u0001")}`;
  const hit = tcache.get(key);
  if (hit) return hit;
  const r = await postJSON<TranslateResp>("/api/translate", { texts, target, ...(provider ? { provider } : {}) });
  tcache.set(key, r);
  return r;
}

// ---- the provider choice ("" = auto: in order, with the fallback), shared by every TextTools on the page
export type ProviderInfo = { name: string; enabled?: boolean; model?: string };
const PROVIDER_KEY = "nli.translate.provider";
type TrSettings = { providers: ProviderInfo[]; targets: { code: string; name: string }[] };
let settingsP: Promise<TrSettings> | null = null;
function loadSettings(fresh = false): Promise<TrSettings> {
  if (!settingsP || fresh) {
    settingsP = getJSON<TrSettings>("/api/translate/settings")
      .then((r) => ({ providers: r.providers || [], targets: r.targets || [] }))
      .catch(() => { settingsP = null; return { providers: [], targets: [] }; });
  }
  return settingsP;
}
export function loadProviders(fresh = false): Promise<ProviderInfo[]> {
  return loadSettings(fresh).then((s) => s.providers);
}
export function savedProvider(): string {
  try { return localStorage.getItem(PROVIDER_KEY) || ""; } catch { return ""; }
}
function storeProvider(name: string) {
  try { if (name) localStorage.setItem(PROVIDER_KEY, name); else localStorage.removeItem(PROVIDER_KEY); } catch { /* private mode */ }
}

type Para = { span: [number, number]; action: string };

export function TextTools({ text: shown, source, row, paragraph, paragraphs, testid, full }: {
  text: string; source?: TextSource; row?: unknown; paragraph?: string; paragraphs?: Para[]; testid?: string;
  /** the whole text when `text` is only a preview (copied and translated whole) */
  full?: () => Promise<string>;
}) {
  const [whole, setWhole] = useState<string | null>(null);
  const text = whole ?? shown;
  const getText = async () => {
    if (!full || whole !== null) return text;
    const t = await full();
    setWhole(t);
    return t;
  };
  const [menu, setMenu] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const [tr, setTr] = useState<{ target: string; resp: TranslateResp | null; error: string | null; busy: boolean } | null>(null);
  const [showOrig, setShowOrig] = useState(true);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [using, setUsing] = useState("");
  const [targets, setTargets] = useState<[string, string][]>(TARGETS);
  useEffect(() => {
    let live = true;
    loadSettings().then((s) => { if (live && s.targets.length) setTargets(s.targets.map((t) => [t.code, t.name])); });
    return () => { live = false; };
  }, []);
  const box = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!menu) return;
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setMenu(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menu]);
  const doCopy = async (what: string, s: string | (() => Promise<string>)) => {
    setMenu(false);
    if (typeof s !== "string") s = await s();
    const ok = await copyText(s);
    setFlash(ok ? `Copied ${what} (${s.length.toLocaleString()} characters)` : "Copy failed: select the text and press Ctrl+C");
    setTimeout(() => setFlash(null), 2200);
  };
  // the parts translated one by one (alignment): the coloured paragraphs and the text between them, else blank-line blocks
  const partsOf = (text: string): { text: string; action: string | null }[] => {
    if (paragraphs && paragraphs.length) {
      const out: { text: string; action: string | null }[] = [];
      let pos = 0;
      for (const p of paragraphs) {
        if (p.span[0] > pos && text.slice(pos, p.span[0]).trim()) out.push({ text: text.slice(pos, p.span[0]), action: null });
        out.push({ text: text.slice(p.span[0], p.span[1]), action: p.action });
        pos = p.span[1];
      }
      if (text.slice(pos).trim()) out.push({ text: text.slice(pos), action: null });
      return out;
    }
    return [{ text, action: null }];
  };
  const parts = partsOf(text);
  const run = async (target: string, choice?: string) => {
    setTr({ target, resp: null, error: null, busy: true });
    try {
      let use = choice ?? savedProvider();
      const provs = await loadProviders();
      setProviders(provs);
      if (use && !provs.some((p) => p.name === use)) use = "";   // a provider that is gone: auto
      setUsing(use);
      const t = await getText();
      const resp = await translate(partsOf(t).map((p) => p.text.trim()), target, use || undefined);
      setTr({ target, resp, error: null, busy: false });
    } catch (e) {
      setTr({ target, resp: null, error: (e as Error).message, busy: false });
    }
  };
  const translation = tr?.resp?.results.map((r) => r.translation || "").join("\n\n") || "";
  const used = Array.from(new Set((tr?.resp?.results || []).map((r) => r.provider).filter(Boolean)));
  const fallback = (tr?.resp?.results || []).some((r) => r.fallback);
  const failed = (tr?.resp?.results || []).filter((r) => !r.translation);
  return (
    <span className="text-tools" ref={box} data-testid={testid || "text-tools"} onClick={(e) => e.stopPropagation()}>
      <span className="tt-copy">
        <button className="btn small ghost" title="copy the text" data-testid="copy-text" onClick={() => doCopy("the text", getText)}>Copy</button>
        <button className="btn small ghost tt-more" title="more ways to copy" data-testid="copy-menu" onClick={() => setMenu(!menu)}>▾</button>
        {menu ? (
          <span className="tt-menu" role="menu">
            <button onClick={() => doCopy("the text", getText)}>text</button>
            {paragraph ? <button onClick={() => doCopy("the paragraph", paragraph)}>selected paragraph</button> : null}
            {source ? <button data-testid="copy-source" onClick={() => doCopy("the text with its source", async () => withSource(await getText(), source))}>with source (file · line · id)</button> : null}
            {row !== undefined && row !== null ? <button onClick={() => doCopy("the row", JSON.stringify(row, null, 2))}>row (JSON)</button> : null}
            {translation ? <button onClick={() => doCopy("the translation", translation)}>translation</button> : null}
          </span>) : null}
      </span>
      {targets.map(([t, name]) => (
        <button key={t} className={`btn small ghost${tr?.target === t ? " on" : ""}`} data-testid={`translate-${t}`}
          title={`translate to ${name} (for reading only)`} onClick={() => run(t)}>{name}</button>))}
      {flash ? <span className="tt-flash" data-testid="copy-flash">{flash}</span> : null}
      {tr ? (
        <div className="tt-drawer" data-testid="translation">
          <div className="row" style={{ flexWrap: "wrap" }}>
            <strong>{targets.find(([t]) => t === tr.target)?.[1] || tr.target}</strong>
            {tr.busy ? <span className="faint">translating…</span> : null}
            {used.length ? <span className="faint" style={{ fontSize: 12 }} data-testid="translated-by">translated by {used.join(", ")}{fallback ? " (fallback)" : ""}{using ? " (chosen)" : ""}
              {tr.resp?.results.some((r) => r.cached) ? " · cached" : ""}</span> : null}
            <span className="spacer" />
            {providers.length ? (
              <label className="faint" style={{ fontSize: 12 }} title="auto: the providers in their order, the next one when one fails; or only one (remembered in this browser)">using{" "}
                <select value={using} data-testid="translate-provider" disabled={tr.busy}
                  onChange={(e) => { storeProvider(e.target.value); run(tr.target, e.target.value); }}>
                  <option value="">auto (in order)</option>
                  {providers.map((p) => <option key={p.name} value={p.name}>{p.name}{p.enabled === false ? " (disabled in auto)" : ""}</option>)}
                </select></label>) : null}
            <label className="faint" style={{ fontSize: 12 }}><input type="checkbox" checked={showOrig} onChange={(e) => setShowOrig(e.target.checked)} /> show original</label>
            {translation ? <button className="btn small ghost" onClick={() => doCopy("the translation", translation)}>Copy</button> : null}
            <button className="btn small ghost" onClick={() => setTr(null)}>close ✕</button>
          </div>
          {tr.error ? <div className="alert error">{tr.error}</div> : null}
          {failed.length && !tr.busy ? <div className="alert error">{failed.length} of {parts.length} part(s) not translated: {failed.map((f) => f.error || (f.errors || []).map((e) => `${e.provider}: ${e.error}`).join("; ")).filter(Boolean)[0]}</div> : null}
          <div className={`tt-body${showOrig ? " side" : ""}`}>
            {parts.map((p, i) => (
              <div key={i} className="tt-pair">
                {showOrig ? <div className={`tt-orig${p.action ? ` lpara ${p.action}` : ""}`}>{p.text.trim()}</div> : null}
                <div className={`tt-tr${p.action ? ` lpara ${p.action}` : ""}`} lang={tr.target}>{tr.resp?.results[i]?.translation ?? (tr.busy ? "…" : "")}</div>
              </div>))}
          </div>
        </div>) : null}
    </span>
  );
}

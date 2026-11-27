"use client";
// /label/lab/ ("Experiment"): change any setting of the policy and of the run on a working copy (the draft), and see
// each text's result with the draft and with the base side by side, with what changed marked. The base is the policy
// the run recorded (policy_data), else the policy file. The draft lives only in this browser (it survives a reload;
// "Discard draft" starts again). Nothing reaches policy/ unless "Save as new policy" or a replace confirmed by typing
// the file name. Different from /label/try/: no case sets, real lines, the whole policy.
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, getJSON, postJSON, useApi } from "@/lib/api";
import { href } from "@/lib/format";
import type { LabelTryResp, PolicyCheck, PolicyData, PolicyLabelData } from "@/lib/types";
import { Crumbs, ErrorBox, Loading } from "./ui";
import { actionClass } from "./LabelRunView";
import { ClarityBadge } from "./ExpectedPanel";
import { expectedOk, type LineExpected } from "@/lib/expected";
import { TryTrace } from "./TryTrace";
import { TextTools } from "./TextTools";
import { addGateToRunIf, gatesToAt, partialGates } from "@/lib/policyGates";
import { carryChanges, carrySettings, samePolicy, type DraftFile, type DraftInfo } from "@/lib/labDrafts";
import { safeBack } from "@/lib/urlState";
import { backTarget } from "./LabLink";
import { WholeLine, decidingParagraph } from "./WholeLine";

type Base = { text: string | null; paragraph: string | null; problem: string | null; settings: Record<string, unknown>;
  source?: { run: string; file: string; line: number; input: string | null }; policy_data: PolicyData; policy_from: string;
  policy_path?: string; policy_sha?: string; file_differs?: boolean; policies: string[]; expected?: LineExpected };
type Settings = { use_judge: boolean; band: [number, number]; unit: string; review_as: string; all_labels: boolean };
// sources[i]: where texts[i] came from (a run line, with its expected result and the text as it was), null = typed
type TextSource = { run: string; file: string; line: number; text: string; expected?: LineExpected | null };
type Draft = { policy: PolicyData; settings: Settings; texts: string[]; sources?: (TextSource | null)[] };
type Result = { draft: LabelTryResp | null; base: LabelTryResp | null; error: string | null };
type NavPos = { file: string; line: number; file_index: number; files: number; line_index: number | null; lines_in_file: number;
  lines_total: number; match_index: number | null; matches_in_file: number; matches_total: number; action: string | null;
  expected: Record<string, boolean> | null; clarity?: string | null };
type NavResp = { target: { file: string; line: number } | null; pos: NavPos; profiles: string[]; has_expected: boolean;
  clarities?: string[] };
const NAV_CRIT_KEY = "nli.lab.navCrit", NAV_RUN_KEY = "nli.lab.navAutoRun";

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const LEVELS = [0, 1, 2];
const DECISIONS: Record<number, string[]> = { 0: ["gate"], 1: ["remove", "keep", "review", "flag"], 2: ["remove", "keep", "review", "flag"] };
const STRICT: Record<string, number> = { pass: 0, keep: 1, review: 2, remove: 3 };

/** The draft against the base, as a readable list. */
export function policyDiff(a: PolicyData, b: PolicyData): string[] {
  const out: string[] = [];
  const la = a.labels || {}, lb = b.labels || {};
  for (const k of Object.keys(lb)) if (!(k in la)) out.push(`added label ${k} (level ${lb[k].level}, ${lb[k].decision}, threshold ${lb[k].threshold ?? 0.8}): “${lb[k].hypothesis}”`);
  for (const k of Object.keys(la)) if (!(k in lb)) out.push(`removed label ${k}`);
  for (const k of Object.keys(la)) {
    if (!(k in lb)) continue;
    for (const f of ["level", "decision", "threshold", "hypothesis", "softens", "protected"] as const) {
      const x = JSON.stringify(la[k][f] ?? null), y = JSON.stringify(lb[k][f] ?? null);
      if (x !== y) out.push(f === "hypothesis" ? `reworded ${k}: “${la[k].hypothesis}” → “${lb[k].hypothesis}”` : `${f} of ${k}: ${x} → ${y}`);
    }
  }
  const ra = a.run_if || {}, rb = b.run_if || {};
  for (const lv of new Set([...Object.keys(ra), ...Object.keys(rb)])) {
    if (JSON.stringify(ra[lv] || []) !== JSON.stringify(rb[lv] || [])) out.push(`run_if ${lv}: [${(ra[lv] || []).join(", ")}] → [${(rb[lv] || []).join(", ")}]`);
  }
  const skip = new Set(["labels", "run_if"]);
  for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) {
    if (skip.has(k)) continue;
    const x = JSON.stringify(a[k] ?? null), y = JSON.stringify(b[k] ?? null);
    if (x !== y) out.push(`${k}: ${x.length > 80 ? x.slice(0, 80) + "…" : x} → ${y.length > 80 ? y.slice(0, 80) + "…" : y}`);
  }
  return out;
}

function settingsDiff(a: Settings, b: Settings): string[] {
  const out: string[] = [];
  for (const k of Object.keys(a) as (keyof Settings)[]) if (JSON.stringify(a[k]) !== JSON.stringify(b[k])) out.push(`run setting ${k}: ${JSON.stringify(a[k])} → ${JSON.stringify(b[k])}`);
  return out;
}

function strictest(row: LabelTryResp["rows"][number] | undefined): string {
  if (!row) return "?";
  if (row.decision) return row.decision;
  const acts = (row.paragraphs || []).map((p) => p.action);
  return acts.sort((x, y) => (STRICT[y] ?? 0) - (STRICT[x] ?? 0))[0] || row.action;
}

export function LabView({ blank = false }: { blank?: boolean } = {}) {
  // blank (/label/lab/blank/): no run, no corpus line — one empty text box, a policy picker; everything else the same
  const sp = useSearchParams();
  const router = useRouter();
  const run = blank ? "" : sp.get("run") || "", file = blank ? "" : sp.get("file") || "", line = blank ? 0 : Number(sp.get("line") || 0);
  const para = blank ? null : sp.get("para"), ds = blank ? "" : sp.get("ds") || "", path = blank ? "" : sp.get("path") || "";
  const member = blank ? "" : sp.get("member") || "";
  const policyQ = sp.get("policy") || "";
  const back = safeBack(sp.get("back"));   // where the page was opened from (kept through Prev / Next)
  const baseKey = blank ? `blank|${policyQ}` : `${run}|${file}|${line}|${para ?? ""}|${ds}|${path}|${policyQ}`;
  const base = useApi(`labbase:${baseKey}`, (s) => getJSON<Base>("/api/labels/lab/base",
    { run: run || undefined, file: file || undefined, line: line || undefined, para: para ?? undefined, policy: policyQ || undefined }, s));
  const corpus = useApi(ds && path && line ? `labcorpus:${ds}:${path}:${line}` : null,
    (s) => api.corpusLines(ds, { path, member: member || undefined, start: line, count: 1 }, s));
  const b = base.data;
  const baseSettings: Settings | null = useMemo(() => {
    if (!b) return null;
    const st = b.settings || {};
    const band = Array.isArray(st.uncertain_band) ? st.uncertain_band as [number, number] : [0.6, 0.95] as [number, number];
    return { use_judge: String(st.judge_model || "deberta").toLowerCase() !== "none", band, unit: String(st.decision_unit || "paragraph"),
      review_as: String(st.review_as || "keep"), all_labels: !!st.all_labels };
  }, [b]);
  const firstText = b ? (b.paragraph || b.text || corpus.data?.lines[0]?.text || "") : "";
  const firstSource: TextSource | null = b && run && file && line && firstText
    ? { run, file, line, text: firstText, expected: b.expected || null } : null;
  const storeKey = `nli.lab.draft:${baseKey}`;
  const [draft, setDraftState] = useState<Draft | null>(null);
  const [restored, setRestored] = useState(false);
  useEffect(() => {  // the draft of this page, kept in this browser
    if (!b || !baseSettings || draft) return;
    if (ds && !corpus.data) return;
    let d: Draft | null = null;
    try { const v = localStorage.getItem(storeKey); if (v) { d = JSON.parse(v); setRestored(true); } } catch { /* no storage */ }
    setDraftState(d || { policy: clone(b.policy_data), settings: clone(baseSettings), texts: firstText ? [firstText] : (blank ? [""] : []),
      sources: firstText ? [firstSource] : (blank ? [null] : []) });
  }, [b, baseSettings, corpus.data, ds, draft, firstText, storeKey]);
  const setDraft = (fn: (d: Draft) => void) => setDraftState((o) => {
    if (!o) return o;
    const x = clone(o); fn(x);
    try { localStorage.setItem(storeKey, JSON.stringify(x)); } catch { /* no storage */ }
    return x;
  });
  const discard = () => {
    if (!b || !baseSettings) return;
    if (!window.confirm("Discard the draft and start again from the base?")) return;
    try { localStorage.removeItem(storeKey); sessionStorage.removeItem(autoIdKey); } catch { /* no storage */ }
    lastSaved.current = null;
    setRestored(false);
    setDraftState({ policy: clone(b.policy_data), settings: clone(baseSettings), texts: firstText ? [firstText] : (blank ? [""] : []),
      sources: firstText ? [firstSource] : (blank ? [null] : []) });
    setResults([]);
  };
  // checked while typing
  const [check, setCheck] = useState<PolicyCheck | null>(null);
  useEffect(() => {
    if (!draft) return;
    const t = setTimeout(() => { postJSON<PolicyCheck>("/api/labels/lab/check", { data: draft.policy }).then(setCheck).catch(() => undefined); }, 350);
    return () => clearTimeout(t);
  }, [draft]);
  const diff = useMemo(() => (b && draft && baseSettings ? [...policyDiff(b.policy_data, draft.policy), ...settingsDiff(baseSettings, draft.settings)] : []), [b, draft, baseSettings]);
  // ---- drafts kept as files (dataset/lab_drafts/): saved by themselves a moment after a change, loadable elsewhere
  const lastSaved = useRef<string | null>(null);
  const autoIdKey = `nli.lab.autoId:${baseKey}`;
  const [autoMsg, setAutoMsg] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<DraftInfo[] | null>(null);
  const [draftsOpen, setDraftsOpen] = useState(false);
  const [draftsMsg, setDraftsMsg] = useState<string | null>(null);
  const [draftsErr, setDraftsErr] = useState<string | null>(null);
  const [draftName, setDraftName] = useState("");
  const snapshot = (d: Draft) => JSON.stringify([d.policy, d.settings, d.texts]);
  const draftBody = (d: Draft) => ({
    summary: diff.slice(0, 8).join("; ") + (diff.length > 8 ? ` … (${diff.length} changes)` : ""),
    base: { run: run || undefined, file: file || undefined, line: line || undefined, para, policy_path: b?.policy_path,
      policy_data: b?.policy_data, settings: baseSettings },
    policy: d.policy, settings: d.settings, texts: d.texts, sources: d.sources || [] });
  useEffect(() => {
    if (!draft || !b) return;
    const snap = snapshot(draft);
    if (lastSaved.current === null) { lastSaved.current = snap; return; }   // as loaded / restored: nothing new
    if (snap === lastSaved.current || !diff.length) return;               // no change against the base: not kept
    const t = setTimeout(async () => {
      let id: string | undefined;
      try { id = sessionStorage.getItem(autoIdKey) || undefined; } catch { /* private mode */ }
      try {
        const r = await postJSON<{ id: string; saved: string; same_as?: string | null; replaced?: string[] }>(
          "/api/labels/lab/drafts/save", { auto: true, id, ...draftBody(draft) });
        try { sessionStorage.setItem(autoIdKey, r.id); } catch { /* private mode */ }
        lastSaved.current = snap;
        setAutoMsg(r.same_as ? `same as your draft ${r.same_as} (not kept twice)`
          : `kept as ${r.id} (${r.saved.slice(11)})${r.replaced?.length ? `, replacing ${r.replaced.length} identical one${r.replaced.length > 1 ? "s" : ""}` : ""}`);
      } catch (e) { setAutoMsg(`not kept: ${(e as Error).message}`); }
    }, 1500);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft]);
  const loadList = async () => {
    setDraftsErr(null);
    try { setDrafts((await getJSON<{ drafts: DraftInfo[] }>("/api/labels/lab/drafts")).drafts); }
    catch (e) { setDraftsErr((e as Error).message); }
  };
  const loadDraft = async (id: string, withTexts: boolean, mode: "carry" | "replace") => {
    if (!b || !baseSettings) return;
    setDraftsErr(null); setDraftsMsg(null);
    try {
      const d = await getJSON<DraftFile>(`/api/labels/lab/drafts/${encodeURIComponent(id)}`);
      const same = samePolicy(d.base?.policy_data, b.policy_data);
      let policy: PolicyData, how: string;
      if (same || mode === "replace" || !d.base?.policy_data) {
        policy = clone(d.policy);
        how = same ? "same base: its policy as it was" : "its whole policy (replacing this base)";
      } else {
        const c = carryChanges(d.base.policy_data, d.policy, b.policy_data);
        policy = c.policy;
        how = `${c.carried} change(s) carried onto this base`;
      }
      const settings = carrySettings(d.base?.settings, d.settings || {}, baseSettings as unknown as Record<string, unknown>) as unknown as Settings;
      setDraft((x) => {
        x.policy = policy;
        x.settings = settings;
        if (withTexts) (d.texts || []).forEach((t, k) => {
          if (!t.trim() || x.texts.includes(t)) return;
          x.sources = [...(x.sources || x.texts.map(() => null))];
          x.texts.push(t);
          x.sources.push((d.sources || [])[k] || null);
        });
      });
      setResults([]);
      setDraftsMsg(`Loaded ${d.name || d.id}: ${how}${withTexts ? `, with its ${d.texts.length} text(s)` : ""}. Run draft and base to see it.`);
    } catch (e) { setDraftsErr((e as Error).message); }
  };
  const saveDraftAs = async (overwrite = false) => {
    if (!draft) return;
    setDraftsErr(null); setDraftsMsg(null);
    const name = draftName.trim();
    try {
      const r = await postJSON<{ id: string }>("/api/labels/lab/drafts/save", { auto: false, name, overwrite, ...draftBody(draft) });
      setDraftsMsg(`Saved as ${r.id}.`); setDraftName("");
      if (draftsOpen) loadList();
    } catch (e) {
      const m = (e as Error).message;
      if (!overwrite && m.includes("exists already") && window.confirm(`A draft named ${name} exists. Replace it?`)) return saveDraftAs(true);
      setDraftsErr(m);
    }
  };
  const deleteDraft = async (x: DraftInfo) => {
    if (!window.confirm(`Delete the draft ${x.name || x.id}?`)) return;
    try { await postJSON("/api/labels/lab/drafts/delete", { id: x.id }); loadList(); }
    catch (e) { setDraftsErr((e as Error).message); }
  };
  // ---- Prev / Next through the run's lines; the draft goes along (only the text changes)
  const [crit, setCrit] = useState<string[]>(["all"]);
  const [autoRun, setAutoRun] = useState(false);
  useEffect(() => {
    try {
      const c = JSON.parse(localStorage.getItem(NAV_CRIT_KEY) || "null");
      if (Array.isArray(c) && c.length) setCrit(c);
      setAutoRun(localStorage.getItem(NAV_RUN_KEY) === "1");
    } catch { /* private mode */ }
  }, []);
  const setCritKeep = (c: string[]) => { setCrit(c); try { localStorage.setItem(NAV_CRIT_KEY, JSON.stringify(c)); } catch { /* private mode */ } };
  const toggleCrit = (c: string) => {
    if (c === "all") return setCritKeep(["all"]);
    const rest = crit.filter((x) => x !== "all");
    const next = rest.includes(c) ? rest.filter((x) => x !== c) : [...rest, c];
    setCritKeep(next.length ? next : ["all"]);
  };
  const nav = useApi(run && file && line ? `labnav:${run}:${file}:${line}:${crit.join(",")}` : null,
    (s) => getJSON<NavResp>(`/api/labels/${encodeURIComponent(run)}/nav`, { file, line, crit: crit.join(","), dir: "none" }, s));
  const [navBusy, setNavBusy] = useState(false);
  const [navMsg, setNavMsg] = useState<string | null>(null);
  const pendingRun = useRef(false);
  const step = async (dir: "next" | "prev") => {
    if (!run || !file || !line || !draft || navBusy) return;
    setNavBusy(true); setNavMsg(null);
    try {
      const r = await getJSON<NavResp>(`/api/labels/${encodeURIComponent(run)}/nav`, { file, line, crit: crit.join(","), dir });
      if (!r.target) { setNavMsg(dir === "next" ? "no further matching line in this run" : "no earlier matching line in this run"); return; }
      const nb = await getJSON<Base>("/api/labels/lab/base", { run, file: r.target.file, line: r.target.line });
      const text = nb.text || "";
      const moved: Draft = { ...draft, texts: text ? [text] : [],
        sources: text ? [{ run, file: r.target.file, line: r.target.line, text, expected: nb.expected || null }] : [] };
      const newKey = `${run}|${r.target.file}|${r.target.line}||${ds}|${path}|${policyQ}`;
      try {
        localStorage.setItem(`nli.lab.draft:${newKey}`, JSON.stringify(moved));
        const aid = sessionStorage.getItem(autoIdKey);
        if (aid) sessionStorage.setItem(`nli.lab.autoId:${newKey}`, aid);   // the same automatic draft file goes on
      } catch { /* private mode */ }
      lastSaved.current = snapshot(moved);
      setDraftState(moved);
      setResults([]);
      setSel({});
      pendingRun.current = autoRun && !!text;
      router.push(href("/label/lab", { run, file: r.target.file, line: r.target.line, back: back || undefined }));
    } catch (e) { setNavMsg((e as Error).message); }
    finally { setNavBusy(false); }
  };
  useEffect(() => {   // "[" / "]" outside text fields: Prev / Next
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === "]") { e.preventDefault(); step("next"); }
      else if (e.key === "[") { e.preventDefault(); step("prev"); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  // blank page: switching the base policy carries the draft's changes onto the new one (once it is loaded)
  const pendingCarry = useRef<{ from: PolicyData; draft: PolicyData } | null>(null);
  const pickPolicy = (p: string) => {
    if (!b || !draft || p === b.policy_path) return;
    if (diff.length && !window.confirm(`Switch the base policy to ${p}? Your ${diff.length} change(s) are carried onto it where they apply.`)) return;
    pendingCarry.current = { from: clone(b.policy_data), draft: clone(draft.policy) };
    router.replace(href("/label/lab/blank", { policy: p, back: back || undefined }));
  };
  useEffect(() => {
    const pc = pendingCarry.current;
    if (!pc || !b || !draft || samePolicy(pc.from, b.policy_data)) return;
    pendingCarry.current = null;
    const c = carryChanges(pc.from, pc.draft, b.policy_data);
    setDraftState((o) => {
      if (!o) return o;
      const x = { ...o, policy: c.policy };
      try { localStorage.setItem(storeKey, JSON.stringify(x)); } catch { /* no storage */ }   // kept under the new address
      return x;
    });
    setResults([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [b]);
  const newBlank = () => {
    if (!b || !baseSettings) return;
    if ((diff.length || draft?.texts.some((t) => t.trim())) && !window.confirm("Clear the texts and the draft and start again?")) return;
    try { localStorage.removeItem(storeKey); sessionStorage.removeItem(autoIdKey); } catch { /* no storage */ }
    lastSaved.current = null;
    setRestored(false);
    setDraftState({ policy: clone(b.policy_data), settings: clone(baseSettings), texts: [""], sources: [null] });
    setResults([]);
  };
  // running
  const [results, setResults] = useState<Result[]>([]);
  const [busy, setBusy] = useState(false);
  // "Hide" on the Draft policy panel: the texts and traces get the whole width (remembered in this browser)
  const [hidden, setHidden] = useState(false);
  useEffect(() => { try { setHidden(localStorage.getItem("nli.lab.draftHidden") === "1"); } catch { /* private mode */ } }, []);
  const toggleHidden = (v: boolean) => {
    setHidden(v);
    try { if (v) localStorage.setItem("nli.lab.draftHidden", "1"); else localStorage.removeItem("nli.lab.draftHidden"); } catch { /* private mode */ }
  };
  const [sel, setSel] = useState<Record<string, number>>({});
  // "score again (no cache)": the model service forgets its scored pairs first, so the base run scores everything
  // with the models (the draft then reuses the base's fresh scores for unchanged hypotheses)
  const [fresh, setFresh] = useState(false);
  const rules = useApi("expected-rules", (s2) => api.expectedRules(undefined, s2));
  const [expProfile, setExpProfile] = useState("");
  const [cacheMsg, setCacheMsg] = useState<string | null>(null);
  const clearCache = async () => {
    try {
      const r = await postJSON<{ cleared: number }>("/api/labels/cache/clear", {});
      setCacheMsg(`score cache cleared (${r.cleared} scored pairs forgotten)`);
      return true;
    } catch (e) { setCacheMsg(`could not clear the score cache: ${(e as Error).message}`); return false; }
  };
  const runAll = async () => {
    if (!draft || !b || !baseSettings) return;
    setBusy(true);
    if (fresh) await clearCache();
    const texts = draft.texts.filter((t) => t.trim());
    const call = (pd: PolicyData, st: Settings) => api.labelTry({ texts, policy_data: pd, all_labels: st.all_labels, use_judge: st.use_judge,
      decision_unit: st.unit, review_as: st.review_as, uncertain_band: st.band, reuse_scores: true });
    let out: Result[];
    try {
      const rb = await call(b.policy_data, baseSettings);
      let rd: LabelTryResp | null = null, err: string | null = null;
      try { rd = await call(draft.policy, draft.settings); } catch (e) { err = `draft: ${(e as Error).message}`; }
      out = texts.map(() => ({ draft: rd, base: rb, error: err }));
    } catch (e) {
      out = texts.map(() => ({ draft: null, base: null, error: (e as Error).message }));
    }
    setResults(out);
    setBusy(false);
  };
  useEffect(() => {
    if (pendingRun.current && b && draft && baseSettings && !busy) { pendingRun.current = false; runAll(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [b, draft, baseSettings]);
  // saving (only on explicit confirm)
  const [saveName, setSaveName] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmName, setConfirmName] = useState("");
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const saveAs = async () => {
    setSaveErr(null); setSaveMsg(null);
    const n = saveName.trim().replace(/^policy\//, "");
    try {
      const r = await postJSON<{ path: string }>("/api/labels/lab/save", { data: draft!.policy, save_as: `policy/${n.endsWith(".json") ? n : n + ".json"}` });
      setSaveMsg(`Saved as ${r.path} (a new file; the base is unchanged).`); setSaveName("");
    } catch (e) { setSaveErr((e as Error).message); }
  };
  const replace = async () => {
    setSaveErr(null); setSaveMsg(null);
    try {
      const r = await postJSON<{ path: string; backup: string | null }>("/api/labels/lab/save",
        { data: draft!.policy, replace: b!.policy_path, confirm: confirmName, base_sha: b!.policy_sha });
      setSaveMsg(`Replaced ${r.path}; the old version is in ${r.backup}.`); setConfirmOpen(false); setConfirmName("");
    } catch (e) { setSaveErr((e as Error).message); }
  };
  // applying to the whole run (redecide into a new folder, then compare)
  const [applyName, setApplyName] = useState("");
  const [applied, setApplied] = useState<string | null>(null);
  const apply = async () => {
    setSaveErr(null);
    try {
      const r = await api.labelRedecide(run, { policy_data: draft!.policy, output_dir: applyName.trim(), review_as: draft!.settings.review_as });
      setApplied(r.run);
    } catch (e) { setSaveErr((e as Error).message); }
  };
  // adding texts from a run's wrong lines
  const exp = useApi(run ? `labexp:${run}:` : null, (s) => api.labelExpected(run, s));
  const addLine = async (f: string, ln: number) => {
    try {
      const r = await getJSON<Base>("/api/labels/lab/base", { run, file: f, line: ln });
      if (r.text) setDraft((d) => {
        d.sources = [...(d.sources || d.texts.map(() => null))];
        d.texts.push(r.text!);
        d.sources.push({ run, file: f, line: ln, text: r.text!, expected: r.expected || null });
      });
    } catch { /* shown nowhere: the line is simply not added */ }
  };
  const [paste, setPaste] = useState("");

  const pol = draft?.policy;
  const labelsOf = pol ? Object.entries(pol.labels || {}) : [];
  return (
    <>
      <div className="page-head"><div>
        <Crumbs items={[{ label: "Labelling", href: "/label" }, ...(run ? [{ label: run, href: href("/label/run", { run, file: file || undefined }) }] : []),
          ...(run && line ? [{ label: `line ${line}`, href: href("/label/doc", { run, file, line }) }] : []), { label: blank ? "Experiment (blank)" : "Experiment" }]} />
        <div className="row" style={{ alignItems: "baseline", flexWrap: "wrap" }}><h1 style={{ marginRight: 8 }}>{blank ? "Experiment (blank)" : "Experiment"}</h1>
          {(() => { const t = backTarget(back, run); return (
            <Link className="btn small" href={t.url} data-testid="lab-back"
              title="back to the page this Experiment was opened from, as you left it (the browser's Back goes line by line through Prev / Next)">◂ Back to {t.label}</Link>); })()}
          {blank && b ? (
            <label style={{ fontSize: 13 }} title="the base policy of this blank experiment">policy{" "}
              <select value={b.policy_path || ""} data-testid="lab-policy-pick" onChange={(e) => pickPolicy(e.target.value)}>
                {(b.policies || []).map((p) => <option key={p} value={p}>{p}</option>)}
              </select></label>) : null}
          {blank ? <button className="btn small ghost" onClick={newBlank} data-testid="lab-new-blank" title="clear the texts and the draft, start again">New blank</button>
            : <Link className="btn small ghost" href={href("/label/lab/blank", { back: back || undefined })} data-testid="lab-open-blank"
                title="an Experiment page with no line: type any text">Open blank →</Link>}
        </div>
        {blank ? <div className="sub">Type any text and compare the draft with the chosen policy. Nothing is loaded from a dataset; everything
          else works as on the Experiment page.</div> : null}
        <div className="sub">Change anything in a working copy (the draft) and compare with the base on real lines. Nothing is saved
          unless you confirm below. For case sets and their expected actions use <Link href="/label/try">Try</Link>.</div>
      </div></div>
      <ErrorBox error={base.error} onRetry={base.reload} />
      {base.loading && !b ? <Loading what="Loading the base" /> : null}
      {b && draft && pol && baseSettings ? (<>
        {run && file && line ? (() => {
          const p = nav.data?.pos;
          const profiles = nav.data?.profiles || [];
          const hasExp = !!nav.data?.has_expected;
          const options: [string, string, boolean][] = [["all", "every line", true], ["remove", "remove", true], ["review", "review", true],
            ["keep", "keep", true], ...profiles.map((pr) => [`wrong:${pr}`, `not as expected (${pr})`, hasExp] as [string, string, boolean]),
            ...(nav.data?.clarities || []).map((c) => [`clarity:${c}`, c, true] as [string, string, boolean])];
          const onlyAll = crit.length === 1 && crit[0] === "all";
          return (
            <div className="panel lab-nav" data-testid="lab-nav">
              <div className="row" style={{ flexWrap: "wrap" }}>
                <button className="btn small" disabled={navBusy} onClick={() => step("prev")} data-testid="lab-prev" title="previous matching line ( [ )">◂ Prev</button>
                <button className="btn small primary" disabled={navBusy} onClick={() => step("next")} data-testid="lab-next" title="next matching line ( ] )">Next ▸</button>
                {p ? (
                  <span style={{ fontSize: 13 }} data-testid="lab-nav-pos">
                    file <strong>{p.file_index}</strong> of {p.files}: <code>{p.file}</code> · line <strong>{p.line}</strong>
                    {p.line_index ? <> ({p.line_index} of {p.lines_in_file})</> : <> (of {p.lines_in_file})</>}
                    {!onlyAll ? <> · match <strong>{p.match_index ?? "–"}</strong> of {p.matches_in_file} in this file · {p.matches_total} in the run</> : null}
                    {p.action ? <> · run: <span className={`badge ${actionClass(p.action)}`}>{p.action}</span></> : null}
                    {p.clarity ? <> <ClarityBadge c={p.clarity} /></> : null}
                    {p.expected ? Object.entries(p.expected).map(([pr, ok]) => (
                      <span key={pr} className={`badge ${ok ? "keep" : "warn"}`} style={{ marginLeft: 4 }}>{pr} {ok ? "✓" : "✗"}</span>)) : null}
                  </span>) : nav.loading ? <span className="faint">…</span> : null}
              </div>
              <div className="row" style={{ flexWrap: "wrap", marginTop: 6, fontSize: 12.5 }} data-testid="lab-nav-crit">
                <span className="faint">Next / Prev stop at:</span>
                {options.map(([k, label, usable]) => (
                  <label key={k} className={usable ? "" : "faint"} title={usable ? "" : "this run has no expected results"}>
                    <input type="checkbox" disabled={!usable} checked={crit.includes(k)} onChange={() => toggleCrit(k)} data-testid={`lab-crit-${k}`} /> {label}</label>))}
                <span className="spacer" />
                <label title="run draft and base right after each step"><input type="checkbox" checked={autoRun} data-testid="lab-nav-autorun"
                  onChange={(e) => { setAutoRun(e.target.checked); try { if (e.target.checked) localStorage.setItem(NAV_RUN_KEY, "1"); else localStorage.removeItem(NAV_RUN_KEY); } catch { /* private mode */ } }} /> run draft and base on each step</label>
              </div>
              <div className="faint" style={{ fontSize: 11.5, marginTop: 2 }}>Your draft policy and settings go along; only the text changes to the new line.
                Keys: <code>[</code> / <code>]</code> (outside text boxes).</div>
              {navMsg ? <div className="alert" style={{ marginTop: 6 }} data-testid="lab-nav-msg">{navMsg}</div> : null}
            </div>);
        })() : null}
        <div className="panel">
          <div className="row" style={{ flexWrap: "wrap" }}>
            <span>base: <strong>{b.policy_from}</strong>{b.policy_path ? <> · file <code>{b.policy_path}</code></> : null}</span>
            {b.file_differs ? <span className="badge warn" title="the run recorded its whole policy; the file was changed since">the file differs from what the run used</span> : null}
            {restored ? <span className="badge accent" data-testid="lab-restored">draft restored from this browser</span> : null}
            <span className="spacer" />
            {check ? (check.ok ? <span className="badge keep" data-testid="lab-valid">draft valid</span>
              : <span className="badge filter">{check.errors.length} problem(s)</span>) : null}
            <button className="btn small ghost danger" onClick={discard} data-testid="lab-discard">Discard draft</button>
          </div>
          {pol && partialGates(pol).length ? (
            <div className="alert" data-testid="lab-gate-fix">Run if level {partialGates(pol).join(", ")} names some gates but not all. The gates
              are OR-combined, so name every gate, or use <code>@gate</code> (any gate open).{" "}
              <button className="btn small" onClick={() => setDraft((d) => { gatesToAt(d.policy); })} data-testid="lab-gate-fix-button">Use @gate in Run if</button></div>) : null}
          {check?.errors.length ? <ul className="policy-errors">{check.errors.map((e, i) => <li key={i}>{e}</li>)}</ul> : null}
          {check?.warnings.length ? <div className="faint" style={{ fontSize: 12 }}>{check.warnings.join("; ")}</div> : null}
          {b.problem ? <div className="alert">{b.problem}</div> : null}
          <div className="row" style={{ flexWrap: "wrap", marginTop: 8 }} data-testid="lab-drafts-bar">
            <button className="btn small" onClick={() => { const o = !draftsOpen; setDraftsOpen(o); if (o) loadList(); }} data-testid="lab-drafts-open">
              {draftsOpen ? "Close saved drafts ▴" : "Load a draft… ▾"}</button>
            <input type="text" placeholder="name, e.g. ukraine_gate_try" value={draftName} onChange={(e) => setDraftName(e.target.value)}
              style={{ width: 210 }} data-testid="lab-draft-name" />
            <button className="btn small" disabled={!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$/.test(draftName.trim()) || draftName.trim().startsWith("auto-")}
              onClick={() => saveDraftAs()} data-testid="lab-draft-save">Save draft as…</button>
            <span className="faint" style={{ fontSize: 12 }} data-testid="lab-autosave">{autoMsg
              ? `automatic copy: ${autoMsg}` : "changes are kept automatically as a draft file (dataset/lab_drafts/)"}</span>
          </div>
          {draftsMsg ? <div className="alert ok" style={{ marginTop: 6 }} data-testid="lab-drafts-msg">{draftsMsg}</div> : null}
          {draftsErr ? <div className="alert error" style={{ marginTop: 6 }}>{draftsErr}</div> : null}
          {draftsOpen ? (
            <div style={{ marginTop: 8 }} data-testid="lab-drafts">
              {drafts === null ? <span className="faint">loading…</span> : !drafts.length ? <span className="faint">no saved drafts yet</span> : (
                <div className="table-wrap"><table>
                  <thead><tr><th>Draft</th><th>Changes</th><th>From</th><th>Texts</th><th></th></tr></thead>
                  <tbody>{drafts.map((x) => (
                    <tr key={x.id} data-testid={`lab-draft-${x.id}`}>
                      <td style={{ whiteSpace: "nowrap" }}>{x.name ? <strong>{x.name}</strong> : <span className="faint">automatic</span>}
                        <div className="faint" style={{ fontSize: 11.5 }}>{x.saved}</div></td>
                      <td style={{ fontSize: 12, maxWidth: 520 }}>{x.summary || <span className="faint">–</span>}</td>
                      <td style={{ fontSize: 12 }}>{x.run ? <>{x.run}{x.line ? ` · line ${x.line}` : ""}</> : (x.policy_path || "–")}</td>
                      <td style={{ fontSize: 12 }} title={x.first_text}>{x.texts}</td>
                      <td style={{ whiteSpace: "nowrap" }}>
                        <button className="btn small primary" onClick={() => loadDraft(x.id, false, "carry")} data-testid={`lab-draft-load-${x.id}`}
                          title="its policy changes and run settings; this page's texts stay">Load</button>{" "}
                        <button className="btn small" onClick={() => loadDraft(x.id, true, "carry")} title="also add its texts">+ texts</button>{" "}
                        <button className="btn small ghost" onClick={() => loadDraft(x.id, false, "replace")}
                          title="its whole policy as it was, instead of carrying its changes onto this base">whole policy</button>{" "}
                        <button className="btn small ghost danger" onClick={() => deleteDraft(x)} title="delete this draft file">✕</button></td>
                    </tr>))}</tbody>
                </table></div>)}
              <div className="faint" style={{ fontSize: 11.5, marginTop: 4 }}>Load = the draft&apos;s changes carried onto this page&apos;s base (added labels,
                changed thresholds / hypotheses, run_if, settings), so a newer base is kept; &quot;whole policy&quot; = its policy as it was.
                Automatic drafts: the newest 50 are kept; named ones until deleted.</div>
            </div>) : null}
        </div>

        {hidden ? (
          <div className="panel row" style={{ flexWrap: "wrap" }} data-testid="lab-draft-hidden">
            <strong>Draft policy</strong>
            <span className="faint" style={{ fontSize: 12 }}>hidden · {labelsOf.length} labels · {diff.length ? `${diff.length} change(s) vs base` : "no change yet"}
              {check && !check.ok ? ` · ${check.errors.length} problem(s)` : ""} · Draft vs base and Save are below the texts</span>
            <span className="spacer" />
            <button className="btn small" onClick={() => toggleHidden(false)} data-testid="lab-draft-show">Show draft policy ▸</button>
          </div>) : null}
        <div className="grid" style={{ gridTemplateColumns: hidden ? "minmax(0, 1fr)" : "minmax(0, 1fr) minmax(0, 1.1fr)", alignItems: "start" }}>
          <div style={hidden ? { order: 2 } : undefined}>
            {!hidden ? (
            <div className="panel" data-testid="lab-draft">
              <div className="row"><h2 style={{ margin: 0 }}>Draft policy</h2><span className="spacer" />
                <button className="btn small ghost" onClick={() => toggleHidden(true)} title="hide the draft: the texts and traces get the whole width"
                  data-testid="lab-draft-hide">◂ Hide</button></div>
              <div className="table-wrap"><table>
                <thead><tr><th>Label</th><th>Lvl</th><th>Decision</th><th>Thr.</th><th>Hypothesis</th><th></th></tr></thead>
                <tbody>{labelsOf.map(([k, l]) => (
                  <tr key={k} className={!(k in (b.policy_data.labels || {})) ? "active" : ""}>
                    <td><code>{k}</code></td>
                    <td><select value={l.level} onChange={(e) => setDraft((d) => { const x = d.policy.labels[k]; x.level = Number(e.target.value); if (x.level === 0) x.decision = "gate"; else if (x.decision === "gate") x.decision = "keep"; })}>
                      {LEVELS.map((v) => <option key={v}>{v}</option>)}</select></td>
                    <td><select value={l.decision} onChange={(e) => setDraft((d) => { d.policy.labels[k].decision = e.target.value; })}>
                      {(DECISIONS[l.level] || DECISIONS[1]).map((v) => <option key={v}>{v}</option>)}</select></td>
                    <td><input type="number" step="0.01" min={0} max={1} style={{ width: 64 }} value={l.threshold ?? 0.8}
                      onChange={(e) => setDraft((d) => { d.policy.labels[k].threshold = Number(e.target.value); })} data-testid={`thr-${k}`} /></td>
                    <td><textarea rows={2} style={{ width: "100%", minWidth: 180, fontSize: 12 }} value={l.hypothesis}
                      onChange={(e) => setDraft((d) => { d.policy.labels[k].hypothesis = e.target.value; })} />
                      <div className="row" style={{ fontSize: 11, gap: 6 }}>
                        <label>softens <input type="text" style={{ width: 110 }} value={(l.softens || []).join(", ")}
                          onChange={(e) => setDraft((d) => { const v = e.target.value.split(",").map((x) => x.trim()).filter(Boolean); if (v.length) d.policy.labels[k].softens = v; else delete d.policy.labels[k].softens; })} /></label>
                        <label><input type="checkbox" checked={!!l.protected} onChange={(e) => setDraft((d) => { if (e.target.checked) d.policy.labels[k].protected = true; else delete d.policy.labels[k].protected; })} /> protected</label>
                      </div></td>
                    <td><button className="btn small ghost danger" title="remove this label" onClick={() => setDraft((d) => {
                      delete d.policy.labels[k];
                      for (const lv of Object.keys(d.policy.run_if || {})) d.policy.run_if![lv] = d.policy.run_if![lv].filter((x) => x !== k);
                    })}>✕</button></td>
                  </tr>))}</tbody>
              </table></div>
              <NewLabel onAdd={(k, l) => setDraft((d) => { d.policy.labels[k] = l; if (l.level === 0) addGateToRunIf(d.policy, k); })} existing={Object.keys(pol.labels || {})} />
              <h3 style={{ marginTop: 12 }}>Run if</h3>
              <div className="faint" style={{ fontSize: 12 }}>per level: the labels (or @gate = any gate open, @marker = a marker term) that let the level run</div>
              {["1", "2"].map((lv) => (
                <div key={lv} className="row"><span>level {lv}</span>
                  <input type="text" style={{ flex: 1 }} value={(pol.run_if?.[lv] || []).join(", ")} data-testid={`runif-${lv}`}
                    onChange={(e) => setDraft((d) => { const v = e.target.value.split(",").map((x) => x.trim()).filter(Boolean); d.policy.run_if = { ...(d.policy.run_if || {}), [lv]: v }; if (!v.length) delete d.policy.run_if[lv]; })} /></div>))}
              <h3 style={{ marginTop: 12 }}>Decisions</h3>
              <div className="row" style={{ flexWrap: "wrap" }}>
                <label>no_subject <select value={pol.no_subject || "keep"} onChange={(e) => setDraft((d) => { d.policy.no_subject = e.target.value; })}>
                  {["keep", "review", "remove"].map((v) => <option key={v}>{v}</option>)}</select></label>
                <label>conflict <select value={pol.conflict || "review"} onChange={(e) => setDraft((d) => { d.policy.conflict = e.target.value; })}>
                  {["review", "remove", "keep"].map((v) => <option key={v}>{v}</option>)}</select></label>
                <label><input type="checkbox" checked={!!pol.narrative_opens_gate} onChange={(e) => setDraft((d) => { d.policy.narrative_opens_gate = e.target.checked; })} /> narrative_opens_gate</label>
                <label>non_english_file <select value={String(pol.non_english_file || "")} onChange={(e) => setDraft((d) => { if (e.target.value) d.policy.non_english_file = e.target.value; else delete d.policy.non_english_file; })}>
                  <option value="">(off)</option><option value="policy/non_english.json">policy/non_english.json</option></select></label>
              </div>
              <label style={{ display: "block", marginTop: 8 }}>markers (one per line)
                <textarea rows={3} style={{ width: "100%" }} value={(pol.markers || []).join("\n")}
                  onChange={(e) => setDraft((d) => { d.policy.markers = e.target.value.split("\n").map((x) => x.trim()).filter(Boolean); })} /></label>
              <details style={{ marginTop: 8 }}><summary>Exceptions and everything else (JSON)</summary>
                <JsonField value={pol} onChange={(v) => setDraft((d) => { d.policy = v; })} /></details>
              <h3 style={{ marginTop: 12 }}>Run settings</h3>
              <div className="row" style={{ flexWrap: "wrap" }}>
                <label><input type="checkbox" checked={draft.settings.use_judge} onChange={(e) => setDraft((d) => { d.settings.use_judge = e.target.checked; })} /> judge model</label>
                <label>uncertain band <input type="number" step="0.01" style={{ width: 60 }} value={draft.settings.band[0]} onChange={(e) => setDraft((d) => { d.settings.band[0] = Number(e.target.value); })} />
                  – <input type="number" step="0.01" style={{ width: 60 }} value={draft.settings.band[1]} onChange={(e) => setDraft((d) => { d.settings.band[1] = Number(e.target.value); })} /></label>
                <label>decision unit <select value={draft.settings.unit} onChange={(e) => setDraft((d) => { d.settings.unit = e.target.value; })}><option>paragraph</option><option>line</option></select></label>
                <label>review as <select value={draft.settings.review_as} onChange={(e) => setDraft((d) => { d.settings.review_as = e.target.value; })}><option>keep</option><option>remove</option></select></label>
                <label><input type="checkbox" checked={draft.settings.all_labels} onChange={(e) => setDraft((d) => { d.settings.all_labels = e.target.checked; })} /> all labels</label>
              </div>
              <div className="faint" style={{ fontSize: 11.5 }}>the fast model is the one the model service has loaded (restart it with another to compare models)</div>
            </div>) : null}

            <div className="panel" data-testid="lab-diff">
              <h2>Draft vs base</h2>
              {diff.length ? <ul style={{ margin: 0, paddingLeft: 18 }}>{diff.map((x) => <li key={x} style={{ fontSize: 13 }}>{x}</li>)}</ul>
                : <div className="faint">no change yet</div>}
            </div>

            <div className="panel" data-testid="lab-save">
              <h2>Save (only when you confirm)</h2>
              <div className="row" style={{ flexWrap: "wrap" }}>
                <input type="text" placeholder="new policy name, e.g. russia_llm_policy_v3" value={saveName} onChange={(e) => setSaveName(e.target.value)} style={{ minWidth: 260 }} data-testid="lab-save-name" />
                <button className="btn small primary" disabled={!saveName.trim() || !check?.ok || !diff.length} onClick={saveAs} data-testid="lab-save-as">Save as new policy…</button>
              </div>
              {b.policy_path ? (
                <div style={{ marginTop: 8 }}>
                  {!confirmOpen ? <button className="btn small ghost danger" disabled={!check?.ok || !diff.length} onClick={() => setConfirmOpen(true)} data-testid="lab-replace">Replace {b.policy_path}…</button> : (
                    <div className="alert" data-testid="lab-confirm">
                      <strong>Replace {b.policy_path}?</strong> The old file goes to policy/.backup/. Changes:
                      <ul style={{ margin: "4px 0", paddingLeft: 18 }}>{policyDiff(b.policy_data, draft.policy).map((x) => <li key={x} style={{ fontSize: 12.5 }}>{x}</li>)}</ul>
                      {b.file_differs ? <div className="faint" style={{ fontSize: 12 }}>note: the file is not the base (the run recorded another version); the list above is against the base</div> : null}
                      <div className="row">type <code>{b.policy_path.split("/").pop()}</code> to confirm
                        <input type="text" value={confirmName} onChange={(e) => setConfirmName(e.target.value)} data-testid="lab-confirm-name" />
                        <button className="btn small danger" disabled={confirmName.trim() !== b.policy_path.split("/").pop()} onClick={replace} data-testid="lab-confirm-go">Replace</button>
                        <button className="btn small ghost" onClick={() => { setConfirmOpen(false); setConfirmName(""); }}>Cancel</button></div>
                    </div>)}
                </div>) : null}
              {saveMsg ? <div className="faint" style={{ marginTop: 6 }} data-testid="lab-saved">{saveMsg}</div> : null}
              {saveErr ? <div className="alert error" style={{ marginTop: 6 }}>{saveErr}</div> : null}
              {run ? (
                <div style={{ marginTop: 10 }}>
                  <div className="faint" style={{ fontSize: 12 }}>Apply the draft to the whole run: <code>redecide</code> into a new folder (stored scores; new or reworded
                    hypotheses count as not scored), then compare. Nothing in policy/ changes.</div>
                  <div className="row"><input type="text" placeholder="new folder, e.g. out_label_lab_1" value={applyName} onChange={(e) => setApplyName(e.target.value)} />
                    <button className="btn small" disabled={!applyName.trim() || !check?.ok} onClick={apply} data-testid="lab-apply">Apply to run {run}</button>
                    {applied ? <Link href={href("/label/compare", { a: run, b: applied })}>compare {run} → {applied} (when the job is done) →</Link> : null}</div>
                </div>) : null}
            </div>
          </div>

          <div>
            <div className="panel" data-testid="lab-texts">
              <div className="row"><h2 style={{ margin: 0 }}>Texts</h2>
                {(draft.sources || []).some((x) => x?.expected) && rules.data ? (
                  <span className="seg" title="which actions count as the same (labels/expected_rules.json)" data-testid="lab-exp-profile">
                    {Object.keys(rules.data.profiles || {}).map((p) => (
                      <button key={p} className={p === (expProfile || rules.data!.default) ? "on" : ""} onClick={() => setExpProfile(p)}>{p}</button>))}
                  </span>) : null}
                <span className="spacer" />
                <label className="faint" style={{ fontSize: 12 }} title="forget every scored pair first, so the base is scored with the models again (slower)">
                  <input type="checkbox" checked={fresh} onChange={(e) => setFresh(e.target.checked)} data-testid="lab-fresh" /> score again (no cache)</label>
                <button className="btn small ghost" onClick={clearCache} title="the model service keeps scored pairs in memory until it restarts; a cached score equals a fresh one for the same models"
                  data-testid="lab-clear-cache">Clear score cache</button>
                <button className="btn small primary" disabled={busy || !draft.texts.some((t) => t.trim()) || (check !== null && !check.ok)} onClick={runAll} data-testid="lab-run">
                  {busy ? "Running…" : "Run draft and base"}</button></div>
              {cacheMsg ? <div className="faint" style={{ fontSize: 12 }} data-testid="lab-cache-msg">{cacheMsg}</div> : null}
              {draft.texts.map((t, i) => {
                const r = results[i];
                const rd = r?.draft?.rows[i], rb = r?.base?.rows[i];
                const changed = rd && rb && strictest(rd) !== strictest(rb);
                const src = (draft.sources || [])[i] || null;
                const ex = src?.expected || null;
                const okB = ex && rb ? expectedOk(strictest(rb), ex, rules.data, expProfile) : null;
                const okD = ex && rd ? expectedOk(strictest(rd), ex, rules.data, expProfile) : null;
                const pi = sel[i] ?? rd?.decided_by ?? 0;
                return (
                  <div key={i} className="panel" style={{ marginTop: 10 }} data-testid={`lab-text-${i}`}>
                    <div className="row" style={{ flexWrap: "wrap" }}><strong>text {i + 1}</strong>
                      {rd && rb ? <span data-testid={`lab-result-${i}`}>base <span className={`badge ${actionClass(strictest(rb))}`}>{strictest(rb)}</span> → draft{" "}
                        <span className={`badge ${actionClass(strictest(rd))}`}>{strictest(rd)}</span>
                        {(() => { const k = decidingParagraph(rd.paragraphs || []); return k !== null && (rd.paragraphs || []).length > 1
                          ? <span className="faint" style={{ fontSize: 11.5 }} data-testid={`lab-from-${i}`}> (from ¶{k + 1})</span> : null; })()}
                        {changed ? <span className="badge warn" style={{ marginLeft: 4 }}>changed</span> : null}</span> : null}
                      {ex ? (
                        <span data-testid={`lab-expected-${i}`} title={ex.note || ""}>
                          · expected <span className={`badge ${actionClass(ex.expected_action)}`}>{ex.expected_action}</span>
                          {ex.acceptable?.length ? <span className="faint"> (also {ex.acceptable.join(", ")})</span> : null}
                          {okB !== null ? <> base <span className={`badge ${okB ? "keep" : "filter"}`}>{okB ? "✓" : "✗"}</span></> : null}
                          {okD !== null ? <> draft <span className={`badge ${okD ? "keep" : "filter"}`}>{okD ? "✓" : "✗"}</span></> : null}
                          {okB === false && okD ? <span className="badge keep" style={{ marginLeft: 4 }} data-testid={`lab-fixed-${i}`}>fixed</span> : null}
                          {okB && okD === false ? <span className="badge filter" style={{ marginLeft: 4 }} data-testid={`lab-broken-${i}`}>broken</span> : null}
                          {" "}<ClarityBadge c={ex.clarity} reason={ex.clarity_reason} gate={ex.gate_expected} />
                          {src && src.text !== t ? <span className="faint" style={{ fontSize: 11.5 }} data-testid={`lab-edited-${i}`}> · text edited</span> : null}
                          <span className="faint" style={{ fontSize: 11.5 }}> · {src!.file} line {src!.line}</span>
                        </span>) : null}
                      <span className="spacer" />
                      <TextTools text={t} testid={`lab-tools-${i}`} />
                      <button className="btn small ghost danger" onClick={() => { setDraft((d) => { d.texts.splice(i, 1); if (d.sources) d.sources.splice(i, 1); }); setResults([]); }}>✕</button></div>
                    <textarea rows={4} style={{ width: "100%" }} value={t} onChange={(e) => setDraft((d) => { d.texts[i] = e.target.value; })} />
                    {r?.error ? <div className="alert error">{r.error}</div> : null}
                    {rd && rb ? (<>
                      <div className="table-wrap"><table>
                        <thead><tr><th>¶</th><th>Base</th><th>Draft</th><th>Labels (draft)</th></tr></thead>
                        <tbody>{(rd.paragraphs || []).map((p, k) => {
                          const q = (rb.paragraphs || []).find((x) => x.span[0] === p.span[0] && x.span[1] === p.span[1]);
                          return (<tr key={k} className={k === pi ? "active" : ""} onClick={() => setSel((o) => ({ ...o, [i]: k }))} style={{ cursor: "pointer" }}>
                            <td>¶{k + 1}</td><td>{q ? <span className={`badge ${actionClass(q.action)}`}>{q.action}</span> : "–"} <span className="faint" style={{ fontSize: 11 }}>{q?.reason}</span></td>
                            <td><span className={`badge ${actionClass(p.action)}`}>{p.action}</span> <span className="faint" style={{ fontSize: 11 }}>{p.reason}</span>
                              {q && q.action !== p.action ? <span className="badge warn" style={{ marginLeft: 4 }}>{q.action} → {p.action}</span> : null}</td>
                            <td>{p.labels.map((x) => <code key={x} style={{ marginRight: 4 }}>{x}</code>)}</td></tr>);
                        })}</tbody>
                      </table></div>
                      {!(rd.paragraphs || []).length ? <div className="faint">no paragraph checked (no keyword or marker): {rd.action}</div> : null}
                      {rd.paragraphs?.[pi] ? (
                        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", marginTop: 8 }}>
                          <div><strong>Base</strong>{rb.paragraphs?.[pi] ? <TryTrace res={r!.base!} p={rb.paragraphs[pi]} text={t} row={rb} docAction={rb.action} /> : <div className="faint">–</div>}
                            <WholeLine text={t} row={rb} policy={r!.base!.policy} unit={baseSettings.unit} reviewAs={baseSettings.review_as} sel={pi}
                              onSel={(k) => setSel((o) => ({ ...o, [i]: k }))} expected={ex ? { action: ex.expected_action, ok: okB } : null} testid={`whole-base-${i}`} /></div>
                          <div><strong>Draft</strong><TryTrace res={r!.draft!} p={rd.paragraphs[pi]} text={t} row={rd} docAction={rd.action} />
                            <WholeLine text={t} row={rd} policy={r!.draft!.policy} unit={draft.settings.unit} reviewAs={draft.settings.review_as} sel={pi}
                              onSel={(k) => setSel((o) => ({ ...o, [i]: k }))} expected={ex ? { action: ex.expected_action, ok: okD } : null} testid={`whole-draft-${i}`} /></div>
                        </div>) : null}
                    </>) : null}
                  </div>);
              })}
              {results[0]?.draft ? <div className="faint" style={{ fontSize: 12, marginTop: 6 }} data-testid="lab-timing">
                {results[0].base ? <>base {results[0].base.seconds}s · {results[0].base.pairs.fast} scored by the model{results[0].base.pairs.reused ? `, ${results[0].base.pairs.reused} from the cache` : ""} · </> : null}
                draft {results[0].draft.seconds}s · {results[0].draft.pairs.fast} scored by the model{results[0].draft.pairs.reused ? `, ${results[0].draft.pairs.reused} from the cache` : ""}</div> : null}
              <div style={{ marginTop: 10 }}>
                <textarea rows={3} style={{ width: "100%" }} placeholder="paste another text" value={paste} onChange={(e) => setPaste(e.target.value)} data-testid="lab-paste" />
                <button className="btn small" disabled={!paste.trim()} onClick={() => { setDraft((d) => { d.sources = [...(d.sources || d.texts.map(() => null)), null]; d.texts.push(paste); }); setPaste(""); }} data-testid="lab-add">+ add text</button>
              </div>
              {exp.data?.expected?.wrong.length ? (
                <details style={{ marginTop: 8 }}><summary>add a line {run} did not get as expected ({exp.data.expected.wrong.length})</summary>
                  <div className="row" style={{ flexWrap: "wrap", gap: 4, marginTop: 6 }}>
                    {exp.data.expected.wrong.slice(0, 60).map((w) => (
                      <button key={`${w.file}:${w.line}`} className="btn small ghost" onClick={() => addLine(w.file, w.line)}
                        title={`expected ${w.expected}, got ${w.got}`}>{w.file}:{w.line}</button>))}</div></details>) : null}
            </div>
          </div>
        </div>
      </>) : null}
    </>
  );
}

function NewLabel({ onAdd, existing }: { onAdd: (k: string, l: PolicyLabelData) => void; existing: string[] }) {
  const [k, setK] = useState("");
  const [level, setLevel] = useState(1);
  const [decision, setDecision] = useState("remove");
  const [thr, setThr] = useState(0.8);
  const [hyp, setHyp] = useState("");
  const bad = !/^[a-z][a-z0-9_]*$/.test(k) || existing.includes(k) || !hyp.trim();
  return (
    <div className="row" style={{ flexWrap: "wrap", marginTop: 8 }} data-testid="lab-new-label">
      <input type="text" placeholder="new_label_key" value={k} onChange={(e) => setK(e.target.value)} style={{ width: 150 }} data-testid="lab-new-key" />
      <select value={level} onChange={(e) => { const v = Number(e.target.value); setLevel(v); setDecision(v === 0 ? "gate" : "remove"); }}>
        {LEVELS.map((v) => <option key={v} value={v}>level {v}{v === 0 ? " (gate)" : ""}</option>)}</select>
      <select value={decision} onChange={(e) => setDecision(e.target.value)}>{(DECISIONS[level] || []).map((v) => <option key={v}>{v}</option>)}</select>
      <input type="number" step="0.01" style={{ width: 64 }} value={thr} onChange={(e) => setThr(Number(e.target.value))} />
      <input type="text" placeholder="hypothesis: This text …" value={hyp} onChange={(e) => setHyp(e.target.value)} style={{ flex: 1, minWidth: 200 }} data-testid="lab-new-hyp" />
      <button className="btn small" disabled={bad} onClick={() => { onAdd(k, { level, decision, threshold: thr, hypothesis: hyp.trim() }); setK(""); setHyp(""); }}
        data-testid="lab-new-add">+ label</button>
      {level === 0 ? <span className="faint" style={{ fontSize: 11.5 }}>gates are OR-combined: a new gate is added to every Run if level that names a gate</span> : null}
    </div>);
}

function JsonField({ value, onChange }: { value: PolicyData; onChange: (v: PolicyData) => void }) {
  const [t, setT] = useState(JSON.stringify(value, null, 2));
  const [bad, setBad] = useState<string | null>(null);
  useEffect(() => { setT(JSON.stringify(value, null, 2)); }, [value]);
  return (<>
    {bad ? <div className="alert error">{bad}</div> : null}
    <textarea className="mono policy-json" spellCheck={false} value={t} onChange={(e) => {
      setT(e.target.value);
      try { onChange(JSON.parse(e.target.value)); setBad(null); } catch (x) { setBad(`not valid JSON yet: ${(x as Error).message}`); }
    }} />
  </>);
}

"use client";
// Policy Try page: step through the cases (labels/cases_v1.json) one by one, run the policy's labels on a case's
// text with the model service, and compare the flow (gate → level 1 → level 2 → decision) with what is expected.
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, useApi } from "@/lib/api";
import { href } from "@/lib/format";
import type { LabelCase, LabelCaseText, LabelCasesResp, LabelTryResp } from "@/lib/types";
import { CaseEditor, CaseInsertForm, TopicSelect, newCaseId, newText } from "./CaseEditor";
import { Crumbs, ErrorBox, Loading } from "./ui";
import { Flow } from "./LabelDocView";
import { readTryHandoff } from "./LabelPagePanel";
import { actionClass } from "./LabelRunView";

function docAction(r: LabelTryResp["rows"][number]): string {
  const ps = r.paragraphs || [];
  if (!ps.length) return r.action;  // untouched: no keyword (try "label without a keyword")
  const order = ["remove", "review", "keep", "pass"];
  return order.find((a) => ps.some((p) => p.action === a)) || r.action;
}

function matches(expected: string | null, got: string, acceptable?: string[]): boolean | null {
  if (!expected) return null;
  const ok = [...expected.split(" or ").map((x) => x.trim()), ...(acceptable || [])];
  // "pass" (the gate says not Russia-related) and "untouched" (no keyword at all) both leave the text as it is
  if (ok.includes("pass") || ok.includes("untouched")) ok.push("pass", "untouched");
  return ok.includes(got);
}

export function LabelTryView() {
  const sp = useSearchParams();
  const caseFiles = useApi("labelcasefiles", (s) => api.labelCaseFiles(s));
  const [caseFile, setCaseFile] = useState(sp.get("cases") || "");
  const cases = useApi(`labelcases:${caseFile}`, (s) => api.labelCases(caseFile || undefined, s));
  const policies = useApi("labelpolicies", (s) => api.labelPolicies(s));
  const topicList = useApi("labeltopics", (s) => api.labelTopics(s));
  const topics = topicList.data?.topics || [];
  const addTopic = async (t: string) => { await api.addTopic(t); topicList.reload(); };
  const [topicMode, setTopicMode] = useState("");  // "" = the policy's
  const [tryTopic, setTryTopic] = useState<string | undefined>(undefined);  // the topic sent with Try (from the case text)
  const [draft, setDraft] = useState<LabelCasesResp | null>(null);  // edited case set, not saved yet
  const [changes, setChanges] = useState(0);
  const [editing, setEditing] = useState(sp.get("edit") === "1");  // ?edit=1 opens the editor
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const data = draft ?? cases.data;
  const list = data?.cases || [];
  const [ci, setCi] = useState(0);
  const [ti, setTi] = useState(0);
  const [text, setText] = useState("");
  const [policy, setPolicy] = useState("");
  const [forceGate, setForceGate] = useState(false);
  const [useJudge, setUseJudge] = useState(true);
  const [res, setRes] = useState<LabelTryResp | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<Error | null>(null);
  const [sel, setSel] = useState(0);
  const [results, setResults] = useState<Record<string, boolean | null>>({});  // "case#text" -> matched expected
  // opened from a run's document page (?run=&file=&line=&para=): that paragraph, the run's policy
  const fromRun = sp.get("run"), fromFile = sp.get("file"), fromLine = Number(sp.get("line") || 0);
  const fromPara = Number(sp.get("para") || 0);
  const src = useApi(fromRun && fromFile && fromLine ? `trysrc:${fromRun}:${fromFile}:${fromLine}` : null,
    (s) => api.labelDoc(fromRun as string, { file: fromFile, line: fromLine }, s));
  const [extText, setExtText] = useState<string | null>(null);  // text from the run (until another case is picked)
  const [fromCorpus, setFromCorpus] = useState<{ ds: string; path: string; line: number } | null>(null);
  const pendingTi = useRef<number | null>(null);

  useEffect(() => {  // open ?case=<id>
    const want = sp.get("case");
    if (want && list.length) { const i = list.findIndex((c) => c.id === want); if (i >= 0) setCi(i); }
  }, [list.length, sp]);
  useEffect(() => {  // open ?run=…: the paragraph's text; its case (if the corpus is the case corpus); the run's policy
    const d = src.data;
    if (!d || !list.length) return;
    const ps = d.row.paragraphs || [];
    const p = ps[fromPara] || ps[0];
    setExtText(d.text ? (p ? d.text.slice(p.span[0], p.span[1]) : d.text) : "");
    const m = /^(.*)#(\d+)$/.exec(String(d.row.id || ""));
    const i = m ? list.findIndex((c) => c.id === m[1]) : -1;
    if (i >= 0) { pendingTi.current = Number(m![2]) - 1; setCi(i); setTi(Number(m![2]) - 1); }
    const base = d.policy_path ? `policy/${d.policy_path.split(/[\\/]/).pop()}` : "";
    if (base && (policies.data?.policies || []).includes(base)) setPolicy(base);
  }, [src.data, list.length, policies.data, fromPara]);
  useEffect(() => {  // opened from the corpus page's "flow →" (?from=corpus): that line's text and policy
    if (sp.get("from") !== "corpus" || !list.length) return;
    const h = readTryHandoff();
    if (!h) return;
    setExtText(h.text);
    setFromCorpus({ ds: h.ds, path: h.path, line: h.line });
    if (h.policy && (policies.data?.policies || []).includes(h.policy)) setPolicy(h.policy);
  }, [sp, list.length, policies.data]);
  const c: LabelCase | undefined = list[ci];
  const t = c?.texts[ti];
  useEffect(() => { setTryTopic(extText === null ? t?.topic : undefined); }, [t?.topic, extText, ci, ti]);
  const activePolicy = policy || cases.data?.policy || "";
  const polInfo = useApi(activePolicy ? `labelpolicy:${activePolicy}` : null, (s) => api.labelPolicy(activePolicy, s));
  useEffect(() => { setText(extText ?? t?.text ?? ""); setRes(null); setSel(0); setErr(null); }, [ci, ti, t?.text, extText]);
  useEffect(() => { setTi(pendingTi.current ?? 0); pendingTi.current = null; }, [ci]);
  const pick = (i: number) => { setExtText(null); setFromCorpus(null); setCi(i); };

  // ---- editing the case set (kept on the page until Save) ----
  useEffect(() => {
    if (!draft) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [draft]);
  const edit = (fn: (cs: LabelCase[]) => LabelCase[]) => {
    const base = draft ?? cases.data;
    if (!base) return;
    setDraft({ ...base, cases: fn(base.cases.map((x) => ({ ...x, texts: x.texts.map((y) => ({ ...y })) }))) });
    setChanges((n) => n + 1); setSaveMsg(null); setSaveErr(null);
  };
  const editCase = (patch: Partial<LabelCase>) => edit((cs) => cs.map((x, i) => (i === ci ? { ...x, ...patch } : x)));
  const editText = (patch: Partial<LabelCaseText>) =>
    edit((cs) => cs.map((x, i) => (i === ci ? { ...x, texts: x.texts.map((y, k) => (k === ti ? { ...y, ...patch } : y)) } : x)));
  const addText = () => {
    const n = list[ci]?.texts.length || 0;
    edit((cs) => cs.map((x, i) => (i === ci ? { ...x, texts: [...x.texts, newText(text || "New text.")] } : x)));
    setExtText(null); setTi(n);
  };
  const deleteText = () => {
    edit((cs) => cs.map((x, i) => (i === ci ? { ...x, texts: x.texts.filter((_, k) => k !== ti) } : x)));
    setTi(Math.max(0, ti - 1));
  };
  const addCase = (group: string) => {
    edit((cs) => {
      const nc: LabelCase = { id: newCaseId(cs, group), group, label: null, title: `${group.split(" (")[0]} (new)`,
        what: "", texts: [newText(text || "New text.")] };
      const at = group === cs[ci]?.group ? ci + 1 : cs.length;
      return [...cs.slice(0, at), nc, ...cs.slice(at)];
    });
    setExtText(null); setFromCorpus(null);
    setCi(group === list[ci]?.group ? ci + 1 : list.length);
  };
  const deleteCase = () => { edit((cs) => cs.filter((_, i) => i !== ci)); setCi(Math.max(0, ci - 1)); };
  const saveData = async (data: LabelCasesResp): Promise<boolean> => {
    if (!cases.data) return false;
    setSaving(true); setSaveErr(null);
    try {
      const r = await api.saveCases({ file: cases.data.file, data, base_sha: cases.data.sha });
      setSaveMsg(`Saved ${r.cases} cases (${r.texts} texts) to ${r.file}; the old file is in ${r.backup}` +
        (r.corpus ? `; ${r.corpus.path} rebuilt (${r.corpus.files} files)` : ""));
      setDraft(null); setChanges(0); cases.reload();
      setSaving(false);
      return true;
    } catch (e) { setSaveErr((e as Error).message); }
    setSaving(false);
    return false;
  };
  const saveDraft = async () => { if (draft) await saveData(draft); };
  // "+ insert here": a new case at position insertAt (before the case now at that index), saved at once
  const [insertAt, setInsertAt] = useState<number | null>(null);
  const insertCase = async (nc: LabelCase) => {
    const base = draft ?? cases.data;
    if (!base || insertAt === null) return;
    const at = insertAt;
    const ok = await saveData({ ...base, cases: [...base.cases.slice(0, at), nc, ...base.cases.slice(at)] });
    if (ok) { setInsertAt(null); setExtText(null); setFromCorpus(null); setCi(at); }
  };
  const discard = () => { if (window.confirm(`Discard ${changes} unsaved change${changes === 1 ? "" : "s"}?`)) { setDraft(null); setChanges(0); setSaveErr(null); } };

  const groups = useMemo(() => {
    const g: [string, { c: LabelCase; i: number }[]][] = [];
    list.forEach((x, i) => {
      const last = g[g.length - 1];
      if (last && last[0] === x.group) last[1].push({ c: x, i }); else g.push([x.group, [{ c: x, i }]]);
    });
    return g;
  }, [list]);

  const run = async () => {
    if (!text.trim()) return;
    setBusy(true); setErr(null); setRes(null);
    try {
      const r = await api.labelTry({ texts: [text], policy: policy || cases.data?.policy || undefined, all_labels: true,
        force_gate: forceGate, use_judge: useJudge, topics: [tryTopic || null],
        topic_mode: topicMode || undefined });
      setRes(r); setSel(0);
      if (c && t && text === t.text) {
        setResults((m) => ({ ...m, [`${c.id}#${ti}`]: matches(t.expected_action, docAction(r.rows[0]), t.acceptable) }));
      }
    } catch (e) { setErr(e as Error); }
    setBusy(false);
  };
  const go = (d: number) => { setExtText(null); setCi((i) => Math.max(0, Math.min(list.length - 1, i + d))); };

  if (cases.error) return <ErrorBox error={cases.error} onRetry={cases.reload} />;
  if (!cases.data) return <Loading what="Loading cases" />;
  const row = res?.rows[0];
  const paras = row?.paragraphs || [];
  const got = row ? docAction(row) : null;
  const ok = got && t ? matches(t.expected_action, got, t.acceptable) : null;
  const edited = t && text !== t.text;

  return (
    <>
      <div className="page-head">
        <div>
          <Crumbs items={[{ label: "Datasets", href: "/" }, { label: "labels", href: "/labels" }, { label: "try the policy" }]} />
          <h1>Try the policy, case by case</h1>
          <div className="sub">{list.length} cases from {cases.data.file}: every level-0 / 1 / 2 label as a “yes” and a “near miss” case, plus the edge cases.
            Run a text, then compare the flow with what is expected. Needs the model service with models: <code className="mono">python nli_playground.py</code>.</div>
          {(caseFiles.data?.files || []).length > 1 ? (
            <label className="faint" style={{ fontSize: 13 }}>cases&nbsp;
              <select value={caseFile || cases.data.file} data-testid="case-file" onChange={(e) => {
                if (draft && !window.confirm("Unsaved case changes will be lost. Switch anyway?")) return;
                setDraft(null); setChanges(0); setSaveMsg(null);
                setCaseFile(e.target.value); setCi(0); setTi(0); setResults({}); setPolicy(""); setExtText(null); }}>
                {(caseFiles.data?.files || []).map((f) => <option key={f} value={f}>{f}</option>)}
              </select></label>) : null}
          <div className="row" style={{ marginTop: 6 }}>
            <label className="faint" style={{ fontSize: 13 }}><input type="checkbox" checked={editing} onChange={(e) => setEditing(e.target.checked)} data-testid="edit-cases" /> Edit cases</label>
            {draft ? (<>
              <span className="badge warn">{changes} unsaved change{changes === 1 ? "" : "s"}</span>
              <button className="btn small primary" onClick={saveDraft} disabled={saving} data-testid="save-cases">{saving ? "Saving…" : `Save to ${cases.data.file}`}</button>
              <button className="btn small ghost" onClick={discard}>Discard</button>
            </>) : null}
            {saveMsg ? <span className="faint" style={{ fontSize: 12 }}>{saveMsg}</span> : null}
          </div>
          {saveErr ? <div className="alert warn" style={{ marginTop: 6 }}>{saveErr}</div> : null}
        </div>
      </div>
      <div className="try-grid">
        <div className="panel flush case-list" data-testid="case-list">
          {editing ? <button className={`case-insert${insertAt === 0 ? " on" : ""}`} onClick={() => setInsertAt(0)} data-testid="insert-0">+ insert here</button> : null}
          {groups.map(([g, items], gi) => (
            <div key={`${gi}:${g}`}>{/* a group name can come back later in the file: the position keeps keys unique */}
              <div className="case-group">{g}</div>
              {items.map(({ c: x, i }) => {
                const marks = x.texts.map((_, k) => results[`${x.id}#${k}`]);
                return (
                  <div key={x.id}>
                    <button className={`case-item${i === ci && insertAt === null ? " on" : ""}`} onClick={() => { setInsertAt(null); pick(i); }}>
                      <span>{x.title}</span>
                      <span>{marks.map((m, k) => <span key={k} className={`dot ${m === true ? "ok" : m === false ? "bad" : ""}`} />)}</span>
                    </button>
                    {editing ? <button className={`case-insert${insertAt === i + 1 ? " on" : ""}`} onClick={() => setInsertAt(i + 1)}
                      data-testid={`insert-${i + 1}`} title={`a new case after “${x.title}”`}>+ insert here</button> : null}
                  </div>);
              })}
            </div>))}
        </div>

        <div className="stack">
          {editing && insertAt !== null ? (
            <CaseInsertForm key={insertAt}
              where={insertAt === 0 ? "at the top of the list" : `after “${list[insertAt - 1]?.title}”${list[insertAt] ? `, before “${list[insertAt].title}”` : " (at the end)"}`}
              group={(list[insertAt - 1] || list[insertAt])?.group || "New group"}
              groups={Array.from(new Set(list.map((x) => x.group)))}
              labelKeys={Array.from(new Set([...Object.keys(res?.policy?.labels || {}), ...list.flatMap((x) => x.texts.flatMap((y) => y.labels_yes))])).sort()}
              existingIds={list.map((x) => x.id)} saving={saving}
              onCancel={() => setInsertAt(null)} onSave={insertCase} topics={topics} onAddTopic={addTopic} />
          ) : null}
          {c && insertAt === null ? (
            <div className="panel">
              <div className="row">
                <button className="btn small" onClick={() => go(-1)} disabled={ci === 0}>‹ prev case</button>
                <strong style={{ fontSize: 16 }}>{c.title}</strong>
                <span className="faint">{ci + 1} / {list.length}</span>
                <button className="btn small" onClick={() => go(1)} disabled={ci >= list.length - 1}>next case ›</button>
              </div>
              {extText !== null && fromCorpus ? (
                <div className="alert" style={{ marginTop: 8 }} data-testid="from-corpus">
                  Text from dataset <strong>{fromCorpus.ds}</strong>, {fromCorpus.path} line {fromCorpus.line}
                  {policy ? <> · policy <code className="mono">{policy}</code></> : null} · press <strong>Try</strong> for the flow
                  {" "}<a href={href("/corpus", { ds: fromCorpus.ds, file: fromCorpus.path, line: fromCorpus.line })}>back to the corpus</a>
                </div>) : null}
              {extText !== null && !fromCorpus ? (
                <div className="alert" style={{ marginTop: 8 }} data-testid="from-run">
                  Text from run <strong>{fromRun}</strong>, {fromFile} line {fromLine}, paragraph {fromPara + 1}
                  {policy ? <> · the run&apos;s policy <code className="mono">{policy}</code></> : null}
                  {t && extText === t.text ? " · it is this case's text: the expected result applies" : " · not a case text: no expected result"}
                  {" "}<a href={href("/labeldoc", { run: fromRun, file: fromFile, line: fromLine })}>back to the run</a>
                </div>) : null}
              <div style={{ marginTop: 6 }}>{c.what}</div>
              {c.hypothesis ? <div className="hyp" style={{ marginTop: 4 }}>Hypothesis: “{c.hypothesis}” <span className={`badge ${actionClass(c.decision || "")}`}>{c.decision}</span></div> : null}
              <div className="row" style={{ marginTop: 10 }}>
                {c.texts.length > 1 ? <span className="seg">{c.texts.map((_, k) => <button key={k} className={k === ti ? "on" : ""} onClick={() => { setExtText(null); setTi(k); }}>text {k + 1}</button>)}</span> : null}
                <span className="faint" style={{ fontSize: 12 }}>{t?.from}</span>
              </div>
              <textarea className="mono try-text" value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} data-testid="try-text" />
              <div className="row" style={{ fontSize: 13 }}>
                <span>Expected: <span className={`badge ${actionClass(t?.expected_action || "")}`}>{t?.expected_action || "?"}</span>
                  {t?.acceptable?.length ? <span className="faint"> (also fine: {t.acceptable.join(", ")})</span> : null}</span>
                {t?.your_decision && t.your_decision !== t.expected_action ? <span className="faint">your first decision: <span className={`badge ${actionClass(t.your_decision)}`}>{t.your_decision}</span></span> : null}
                <span className="faint">yes: {t?.labels_yes.length ? t.labels_yes.map((l) => <span key={l} className="chip">{l}</span>) : "none"}</span>
                {t?.topic ? <span className="faint" title="the corpus' topic field of this text">topic: <span className="chip">{t.topic}</span></span> : null}
                {t?.from.startsWith("seed") ? <span className="badge warn" title="Claude's draft labels: not checked yet">draft labels</span> : null}
                {edited ? <span className="badge neutral">edited: expected no longer applies</span> : null}
              </div>
              {t?.note ? <div className="faint" style={{ fontSize: 12, marginTop: 4 }}>{t.note}</div> : null}
              <div className="row" style={{ marginTop: 10 }}>
                <button className="btn primary" onClick={run} disabled={busy} data-testid="try-run">{busy ? "Scoring… (~1 s per label on a CPU)" : "Try"}</button>
                <label className="faint" style={{ fontSize: 13 }}><input type="checkbox" checked={forceGate} onChange={(e) => setForceGate(e.target.checked)} /> label without a keyword</label>
                <label className="faint" style={{ fontSize: 13 }}><input type="checkbox" checked={useJudge} onChange={(e) => setUseJudge(e.target.checked)} /> use the judge</label>
                <label className="faint" style={{ fontSize: 13 }} title="the corpus' topic field for this try (the case text's topic, or another one)">topic&nbsp;
                  <TopicSelect value={tryTopic} topics={topics} onChange={setTryTopic} onAdd={addTopic} /></label>
                <label className="faint" style={{ fontSize: 13 }} title="how the topic is used: hint, trust or off">mode&nbsp;
                  <select value={topicMode} onChange={(e) => setTopicMode(e.target.value)} data-testid="topic-mode">
                    <option value="">policy default ({polInfo.data?.topic.mode || "hint"})</option>
                    <option value="hint">hint</option>
                    <option value="trust">trust</option>
                    <option value="off">off</option>
                  </select></label>
                <label className="faint" style={{ fontSize: 13 }}>policy&nbsp;
                  <select value={policy} onChange={(e) => setPolicy(e.target.value)}>
                    <option value="">{cases.data?.policy ? `${cases.data.policy} (of the cases)` : "default"}</option>
                    {(policies.data?.policies || []).map((p) => <option key={p} value={p}>{p}</option>)}
                  </select></label>
                {edited ? <button className="btn small" onClick={() => setText(t?.text || "")}>reset text</button> : null}
              </div>
              <TopicHelp info={polInfo.data?.topic} topic={tryTopic} mode={topicMode || polInfo.data?.topic.mode || "hint"} />
              {editing ? (
                <CaseEditor c={c} t={t} ti={ti} boxText={text}
                  groups={Array.from(new Set(list.map((x) => x.group)))}
                  labelKeys={Array.from(new Set([...Object.keys(res?.policy?.labels || {}), ...list.flatMap((x) => x.texts.flatMap((y) => y.labels_yes))])).sort()}
                  onCase={editCase} onText={editText} onAddText={addText} onDeleteText={deleteText} onAddCase={addCase} onDeleteCase={deleteCase}
                  topics={topics} onAddTopic={addTopic} />
              ) : null}
              <ErrorBox error={err} />
            </div>
          ) : null}

          {row ? (
            <div className="panel">
              <div className="row">
                <h2 style={{ margin: 0 }}>Result</h2>
                <span className={`badge big ${actionClass(got || "")}`}>{got}</span>
                {ok === true ? <span className="badge keep">as expected</span> : ok === false ? <span className="badge filter">not as expected ({t?.expected_action})</span> : null}
                <span className="faint" style={{ fontSize: 12 }}>{res?.models.fast}{res?.models.judge ? ` + judge ${res.models.judge}` : ""} · {res?.pairs.fast} pairs{res?.pairs.judge ? ` (+${res.pairs.judge} judge)` : ""} · {res?.seconds}s</span>
              </div>
              {!paras.length ? (
                <div className="alert" style={{ marginTop: 8 }}>
                  {(row.hits || []).length ? `Keyword hit${(row.hits || []).length > 1 ? "s" : ""} ${(row.hits || []).map((h) => `“${h.kw}”${h.rule ? ` (rule: ${h.rule})` : ""}`).join(", ")}, all marked incidental by the cheap rules: no model runs.`
                    : "No keyword or marker term: the document is untouched (no model runs)."} Tick “label without a keyword” to see what the models would say.
                </div>) : null}
              {paras.length > 1 ? (
                <div className="row" style={{ marginTop: 8 }}><span className="seg">{paras.map((p, k) => (
                  <button key={k} className={k === sel ? "on" : ""} onClick={() => setSel(k)}>¶{k + 1} <span className={`badge ${actionClass(p.action)}`}>{p.action}</span></button>))}</span></div>) : null}
              {paras[sel] ? <div style={{ marginTop: 8 }}><Flow policy={res!.policy} p={paras[sel]} /></div> : null}
              {res?.clean[0] && res.clean[0] !== text ? (
                <div style={{ marginTop: 10 }}>
                  <strong>Cleaned text</strong> <span className="faint" style={{ fontSize: 12 }}>(removed paragraphs cut out, place names rewritten: {res.rewrites[0].map((r) => `${r.old} → ${r.new}`).join(", ") || "none"})</span>
                  <pre className="mono try-clean">{res.clean[0]}</pre>
                </div>) : null}
            </div>
          ) : busy ? <Loading what="Scoring the text with all labels" /> : null}
        </div>
      </div>
    </>
  );
}


/** What the topic does with this policy and mode: which subjects it decides, which it never touches. */
function TopicHelp({ info, topic, mode }: {
  info?: { field: string | null; mode: string; map: Record<string, string[]>; subjects: string[] }; topic?: string; mode: string;
}) {
  if (!info) return null;
  const entries = Object.entries(info.map || {});
  const mapped = Array.from(new Set(entries.flatMap(([, ks]) => ks)));
  const never = info.subjects.filter((k) => !mapped.includes(k));
  const target = topic ? (info.map[topic.toLowerCase()] || []) : [];
  let effect: string;
  if (!entries.length) effect = "This policy has no topic_map: a topic changes nothing, in any mode.";
  else if (!topic) effect = "No topic for this try: the models decide every subject (as without a topic field).";
  else if (!target.length) effect = `“${topic}” is not in this policy's topic_map: it changes nothing; the models decide every subject.`;
  else if (mode === "off") effect = `off: “${topic}” is recorded only; the models decide every subject.`;
  else if (mode === "trust") effect = `trust: ${target.join(", ")} = yes from the topic; ${mapped.filter((k) => !target.includes(k)).join(", ") || "no other mapped subject"} = no from the topic (no model); ${never.join(", ") || "no other subject"}: the model.`;
  else effect = `hint: ${target.join(", ")} = yes from the topic (no model); every other subject: the model.`;
  return (
    <details className="topic-help" data-testid="topic-help">
      <summary><span className="faint">topic → subject:</span> {effect}</summary>
      <div className="faint" style={{ fontSize: 12, marginTop: 6 }}>
        Subjects (level 1) of this policy: {info.subjects.map((k) => <span key={k} className="chip">{k}</span>)}.
        The topic only answers level-1 subjects listed in the policy&apos;s <code>topic_map</code>; the gate (level 0) and every
        level-2 label (opinions, hate, false claims, the guard) are always scored by the models.
      </div>
      {entries.length ? (
        <table className="flow-table" style={{ marginTop: 6 }}><tbody>
          {entries.map(([v, ks]) => (
            <tr key={v} className={topic && v === topic.toLowerCase() ? "yes" : ""}><td className="mono" style={{ fontSize: 12 }}>{v}</td><td>→ {ks.join(", ")}</td></tr>))}
          {never.length ? <tr><td className="faint" style={{ fontSize: 12 }}>(no topic)</td><td className="faint">{never.join(", ")}: never decided by a topic (the model, in every mode)</td></tr> : null}
        </tbody></table>) : null}
    </details>
  );
}

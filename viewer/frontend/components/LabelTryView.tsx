"use client";
// Policy Try page: step through the cases (labels/cases_v1.json) one by one, run the policy's labels on a case's
// text with the model service, and compare the flow (gate → level 1 → level 2 → decision) with what is expected.
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api, useApi } from "@/lib/api";
import type { LabelCase, LabelTryResp } from "@/lib/types";
import { Crumbs, ErrorBox, Loading } from "./ui";
import { Flow } from "./LabelDocView";
import { actionClass } from "./LabelRunView";

function docAction(r: LabelTryResp["rows"][number]): string {
  const ps = r.paragraphs || [];
  if (!ps.length) return r.action;  // untouched: no keyword (try "label without a keyword")
  const order = ["remove", "review", "keep", "pass"];
  return order.find((a) => ps.some((p) => p.action === a)) || r.action;
}

function matches(expected: string | null, got: string): boolean | null {
  if (!expected) return null;
  const ok = expected.split(" or ").map((x) => x.trim());
  // "pass" (the gate says not Russia-related) and "untouched" (no keyword at all) both leave the text as it is
  if (ok.includes("pass") || ok.includes("untouched")) ok.push("pass", "untouched");
  return ok.includes(got);
}

export function LabelTryView() {
  const sp = useSearchParams();
  const cases = useApi("labelcases", (s) => api.labelCases(s));
  const policies = useApi("labelpolicies", (s) => api.labelPolicies(s));
  const list = cases.data?.cases || [];
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

  useEffect(() => {  // open ?case=<id>
    const want = sp.get("case");
    if (want && list.length) { const i = list.findIndex((c) => c.id === want); if (i >= 0) setCi(i); }
  }, [list.length, sp]);
  const c: LabelCase | undefined = list[ci];
  const t = c?.texts[ti];
  useEffect(() => { setText(t?.text || ""); setRes(null); setSel(0); setErr(null); }, [ci, ti, t?.text]);
  useEffect(() => { setTi(0); }, [ci]);

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
      const r = await api.labelTry({ texts: [text], policy: policy || cases.data?.policy || undefined, all_labels: true, force_gate: forceGate, use_judge: useJudge });
      setRes(r); setSel(0);
      if (c && t && text === t.text) {
        setResults((m) => ({ ...m, [`${c.id}#${ti}`]: matches(t.expected_action, docAction(r.rows[0])) }));
      }
    } catch (e) { setErr(e as Error); }
    setBusy(false);
  };
  const go = (d: number) => setCi((i) => Math.max(0, Math.min(list.length - 1, i + d)));

  if (cases.error) return <ErrorBox error={cases.error} onRetry={cases.reload} />;
  if (!cases.data) return <Loading what="Loading cases" />;
  const row = res?.rows[0];
  const paras = row?.paragraphs || [];
  const got = row ? docAction(row) : null;
  const ok = got && t ? matches(t.expected_action, got) : null;
  const edited = t && text !== t.text;

  return (
    <>
      <div className="page-head">
        <div>
          <Crumbs items={[{ label: "Datasets", href: "/" }, { label: "labels", href: "/labels" }, { label: "try the policy" }]} />
          <h1>Try the policy, case by case</h1>
          <div className="sub">{list.length} cases from {cases.data.file}: every level-0 / 1 / 2 label as a “yes” and a “near miss” case, plus the edge cases.
            Run a text, then compare the flow with what is expected. Needs the model service with models: <code className="mono">python nli_playground.py</code>.</div>
        </div>
      </div>
      <div className="try-grid">
        <div className="panel flush case-list" data-testid="case-list">
          {groups.map(([g, items]) => (
            <div key={g}>
              <div className="case-group">{g}</div>
              {items.map(({ c: x, i }) => {
                const marks = x.texts.map((_, k) => results[`${x.id}#${k}`]);
                return (
                  <button key={x.id} className={`case-item${i === ci ? " on" : ""}`} onClick={() => setCi(i)}>
                    <span>{x.title}</span>
                    <span>{marks.map((m, k) => <span key={k} className={`dot ${m === true ? "ok" : m === false ? "bad" : ""}`} />)}</span>
                  </button>);
              })}
            </div>))}
        </div>

        <div className="stack">
          {c ? (
            <div className="panel">
              <div className="row">
                <button className="btn small" onClick={() => go(-1)} disabled={ci === 0}>‹ prev case</button>
                <strong style={{ fontSize: 16 }}>{c.title}</strong>
                <span className="faint">{ci + 1} / {list.length}</span>
                <button className="btn small" onClick={() => go(1)} disabled={ci >= list.length - 1}>next case ›</button>
              </div>
              <div style={{ marginTop: 6 }}>{c.what}</div>
              {c.hypothesis ? <div className="hyp" style={{ marginTop: 4 }}>Hypothesis: “{c.hypothesis}” <span className={`badge ${actionClass(c.decision || "")}`}>{c.decision}</span></div> : null}
              <div className="row" style={{ marginTop: 10 }}>
                {c.texts.length > 1 ? <span className="seg">{c.texts.map((_, k) => <button key={k} className={k === ti ? "on" : ""} onClick={() => setTi(k)}>text {k + 1}</button>)}</span> : null}
                <span className="faint" style={{ fontSize: 12 }}>{t?.from}</span>
              </div>
              <textarea className="mono try-text" value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} data-testid="try-text" />
              <div className="row" style={{ fontSize: 13 }}>
                <span>Expected: <span className={`badge ${actionClass(t?.expected_action || "")}`}>{t?.expected_action || "?"}</span></span>
                <span className="faint">yes: {t?.labels_yes.length ? t.labels_yes.map((l) => <span key={l} className="chip">{l}</span>) : "none"}</span>
                {t?.from.startsWith("seed") ? <span className="badge warn" title="Claude's draft labels: not checked yet">draft labels</span> : null}
                {edited ? <span className="badge neutral">edited: expected no longer applies</span> : null}
              </div>
              {t?.note ? <div className="faint" style={{ fontSize: 12, marginTop: 4 }}>{t.note}</div> : null}
              <div className="row" style={{ marginTop: 10 }}>
                <button className="btn primary" onClick={run} disabled={busy} data-testid="try-run">{busy ? "Scoring… (~1 s per label on a CPU)" : "Try"}</button>
                <label className="faint" style={{ fontSize: 13 }}><input type="checkbox" checked={forceGate} onChange={(e) => setForceGate(e.target.checked)} /> label without a keyword</label>
                <label className="faint" style={{ fontSize: 13 }}><input type="checkbox" checked={useJudge} onChange={(e) => setUseJudge(e.target.checked)} /> use the judge</label>
                <label className="faint" style={{ fontSize: 13 }}>policy&nbsp;
                  <select value={policy} onChange={(e) => setPolicy(e.target.value)}>
                    <option value="">{cases.data?.policy ? `${cases.data.policy} (of the cases)` : "default"}</option>
                    {(policies.data?.policies || []).map((p) => <option key={p} value={p}>{p}</option>)}
                  </select></label>
                {edited ? <button className="btn small" onClick={() => setText(t?.text || "")}>reset text</button> : null}
              </div>
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

"use client";
// One document of an nli_label.py run: the text with its labelled paragraphs, and for the chosen paragraph the flow
// gate → level 1 → level 2 → decision, with every score next to its threshold.
import { useSearchParams } from "next/navigation";
import { useEffect, useState, type ReactElement } from "react";
import { api, useApi } from "@/lib/api";
import { href, num } from "@/lib/format";
import type { FlowPolicyData, LabelDocResp, LabelParagraph, LabelPolicyLabel } from "@/lib/types";
import { Crumbs, ErrorBox, Loading, ScoreBar } from "./ui";
import { safeBack } from "@/lib/urlState";
import { TextTools } from "./TextTools";
import { actionClass } from "./LabelRunView";

const REASONS: Record<string, string> = {
  gate_negative: "Every gate label is below its threshold and there is no marker term: the keyword was incidental, the paragraph passes untouched.",
  narrative: "A level-2 narrative label is yes and nothing softens it: narratives win over 'keep' subjects.",
  conflict: "A 'remove' label and a 'keep' label are both yes: the policy's conflict rule decides.",
  remove_label: "A 'remove' subject label is yes and no 'keep' label is.",
  review_label: "A 'review' label is yes, or a narrative was softened by reports_or_debunks.",
  keep_label: "A 'keep' subject label is yes.",
  no_subject: "Russia-related (gate yes), but no level-1 / level-2 label is yes: the policy's \"no_subject\" setting decides (keep unless the policy says review or remove).",
  exception: "An exception of the policy matched: exceptions are checked first and their decision replaces the cascade's.",
  non_english_keyword: "A keyword written in a non-English script (the policy's non_english_file, keywords: remove): the paragraph is removed before the gate; exceptions cannot lower it.",
  non_english_marker: "A marker written in a non-English script (the policy's non_english_file, markers: remove): the paragraph is removed before the gate; exceptions cannot lower it.",
};

function Level({ title, keys, p, pol, note, used }: { title: string; keys: string[]; p: LabelParagraph; pol: Record<string, LabelPolicyLabel>; note?: string; used: boolean }) {
  const scored = keys.filter((k) => p.scores[k] !== undefined);
  return (
    <div className={`flow-step${used ? "" : " unused"}`}>
      <div className="row"><strong>{title}</strong>{note ? <span className="faint" style={{ fontSize: 12 }}>{note}</span> : null}
        {!used && scored.length ? <span className="badge neutral">does not run for this paragraph: scores shown for information only</span> : null}</div>
      {scored.length === 0 ? <div className="faint" style={{ fontSize: 13 }}>not run for this paragraph</div> : (
        <table className="flow-table"><tbody>{keys.map((k) => {
          const l = pol[k]; const s = p.scores[k];
          const yes = s !== undefined && s >= l.threshold;
          return (
            <tr key={k} className={yes ? "yes" : ""}>
              <td style={{ width: "40%" }}><span className="mono" style={{ fontSize: 12 }}>{k}</span><div className="hyp">{l.hypothesis}</div></td>
              <td><span className={`badge ${actionClass(l.decision)}`}>{l.decision}</span></td>
              <td><ScoreBar value={s} threshold={l.threshold} />{p.judged?.includes(k) ? <span className="chip">judge</span> : null}
                {p.from_field?.includes(k) ? <span className="chip" title="answered by the corpus' topic field, not by a model">topic field</span> : null}</td>
              <td>{s === undefined ? <span className="faint">not scored</span> : yes ? <strong>yes</strong> : <span className="faint">no</span>}</td>
            </tr>);
        })}</tbody></table>
      )}
    </div>
  );
}

export type FlowPolicy = FlowPolicyData;

function Exceptions({ policy, p }: { policy: FlowPolicy; p: LabelParagraph }) {
  const ex = policy.exceptions || [];
  if (!ex.length) return null;
  const hit = ex.find((e) => e.key === (p.exception || p.exception_blocked));
  return (
    <div className="flow-step" data-testid="flow-exceptions">
      <div className="row"><strong>Exceptions</strong><span className="faint" style={{ fontSize: 12 }}>checked first; the highest priority that matches decides</span></div>
      <table className="flow-table"><tbody>{ex.map((e) => {
        const s = p.exception_scores?.[`exception:${e.key}`];
        const on = e.key === p.exception || e.key === p.exception_blocked;
        return (
          <tr key={e.key} className={on ? "yes" : ""}>
            <td style={{ width: "40%" }}><span className="mono" style={{ fontSize: 12 }}>{e.key}</span>
              <div className="hyp">{e.hypothesis || `phrases: ${(e.phrases || []).slice(0, 6).join(", ")}${(e.phrases || []).length > 6 ? " …" : ""}${e.skip_quoted ? " (not inside quotes)" : ""}`}</div></td>
            <td><span className={`badge ${actionClass(e.decision)}`}>{e.decision}</span> <span className="faint" style={{ fontSize: 12 }}>priority {e.priority}</span></td>
            <td>{s !== undefined ? <ScoreBar value={s} threshold={e.threshold ?? 0.8} /> : on && p.exception_phrases ? <span>“{p.exception_phrases.join("”, “")}”</span> : null}</td>
            <td>{on ? <strong>matched</strong> : <span className="faint">no</span>}</td>
          </tr>);
      })}</tbody></table>
      {p.exception && hit ? <div style={{ marginTop: 6 }}>The cascade said <span className={`badge ${actionClass(p.action_before || "")}`}>{p.action_before}</span>; the exception decides <span className={`badge ${actionClass(p.action)}`}>{p.action}</span>.</div> : null}
      {p.exception_blocked ? <div style={{ marginTop: 6 }}>The exception matched, but a <strong>protected</strong> label (hate, violence) removes this paragraph: an exception never lowers that.</div> : null}
    </div>
  );
}

export function Flow({ policy, p }: { policy: FlowPolicy; p: LabelParagraph }) {
  const pol = policy.labels;
  const byLevel = (n: number) => Object.keys(pol).filter((k) => pol[k].level === n);
  const runIf = (n: number) => (policy.run_if[String(n)] || []).map((k) => (k === "@marker" ? "a marker term" : k === "@gate" ? "any gate" : k)).join(" or ");
  const gates = byLevel(0);
  const gateNote = p.marker ? "marker term in the paragraph: the gate is skipped"
    : p.opened_by?.length ? `${gates.length > 1 ? "every gate" : "the gate"} said no, but a narrative claim (${p.opened_by.join(", ")}) opened it`
    : gates.length > 1 ? (p.opened_by_gate ? `${gates.length} gates, OR: opened by ${p.opened_by_gate}` : p.reason === "gate_negative" ? `${gates.length} gates, OR: all below their thresholds` : `${gates.length} gates, OR`)
    : undefined;
  const used = (n: number) => (p.levels ? p.levels.includes(n) : true);
  return (
    <div className="flow">
      {p.non_english?.length ? (<>
        <div className="flow-step" data-testid="flow-non-english">
          <div className="row"><strong>Non-English hit</strong>
            {p.reason.startsWith("non_english") ? <span className="badge filter">remove</span> : <span className="badge neutral">check as usual</span>}</div>
          <div style={{ marginTop: 4 }}>{p.non_english.map((h) => <span key={h.kind + h.term} className="chip">{h.term} <span className="faint">{h.kind}, {h.script}</span></span>)}</div>
          {p.reason.startsWith("non_english") && !(p.levels || []).length ? <div className="faint" style={{ fontSize: 12, marginTop: 4 }}>not scored (score_when_removed is off)</div> : null}
        </div><div className="flow-arrow">↓</div></>) : null}
      <Level title={gates.length > 1 ? `Level 0 · gates (${gates.length}, OR)` : "Level 0 · gate"} keys={gates} p={p} pol={pol} used={used(0)} note={gateNote} />
      <div className="flow-arrow">↓</div>
      <Level title="Level 1 · subject" keys={byLevel(1)} p={p} pol={pol} used={used(1)} note={runIf(1) ? `runs when ${runIf(1)} is yes` : undefined} />
      <div className="flow-arrow">↓</div>
      <Level title="Level 2 · framing" keys={byLevel(2)} p={p} pol={pol} used={used(2)} note={runIf(2) ? `runs when ${runIf(2)} is yes` : undefined} />
      <div className="flow-arrow">↓</div>
      {policy.exceptions?.length ? <><Exceptions policy={policy} p={p} /><div className="flow-arrow">↓</div></> : null}
      <div className="flow-step">
        <div className="row"><strong>Decision</strong><span className={`badge big ${actionClass(p.action)}`}>{p.action}</span>
          <span className="mono faint" style={{ fontSize: 12 }}>{p.reason}</span></div>
        <div style={{ marginTop: 6 }}>{REASONS[p.reason] || p.reason}</div>
        {p.labels.length ? <div style={{ marginTop: 6 }}>yes: {p.labels.map((l) => <span key={l} className="chip">{l}</span>)}</div> : null}
        {p.flags?.length ? <div style={{ marginTop: 6 }}>flagged (not removed): {p.flags.map((l) => <span key={l} className="chip">⚑ {l}</span>)}</div> : null}
      </div>
    </div>
  );
}

export function DocText({ d, sel, onSel }: { d: LabelDocResp; sel: number; onSel: (i: number) => void }) {
  const text = d.text || "";
  const paras = d.row.paragraphs || [];
  const hits = (d.row.hits || []).filter((h) => !h.rule);
  const out: ReactElement[] = [];
  let pos = 0;
  const renderPlain = (a: number, b: number, key: string) => {
    const parts: ReactElement[] = [];
    let p0 = a;
    hits.filter((h) => h.span[0] >= a && h.span[1] <= b).forEach((h, i) => {
      if (h.span[0] > p0) parts.push(<span key={`${key}t${i}`}>{text.slice(p0, h.span[0])}</span>);
      parts.push(<span key={`${key}h${i}`} className="hit open">{text.slice(h.span[0], h.span[1])}</span>);
      p0 = h.span[1];
    });
    if (b > p0) parts.push(<span key={`${key}e`}>{text.slice(p0, b)}</span>);
    return parts;
  };
  paras.forEach((p, i) => {
    if (p.span[0] > pos) out.push(<span key={`g${i}`} className="faint">{renderPlain(pos, p.span[0], `g${i}`)}</span>);
    out.push(
      <span key={`p${i}`} className={`lpara ${p.action}${i === sel ? " sel" : ""}`} onClick={() => onSel(i)} title={`${p.action} (${p.reason}) — click for the flow`}>
        {renderPlain(p.span[0], p.span[1], `p${i}`)}
      </span>);
    pos = p.span[1];
  });
  if (pos < text.length) out.push(<span key="tail" className="faint">{renderPlain(pos, text.length, "tail")}</span>);
  return <div className="doc">{out}</div>;
}

function ExpectBox({ e, sel }: { e: NonNullable<LabelDocResp["expect"]>; sel?: [number, number] }) {
  const mark = (ok: boolean) => <span className={ok ? "badge keep" : "badge filter"}>{ok ? "✓ as expected" : "✗ not as expected"}</span>;
  const cur = sel ? e.paragraphs?.find((p) => p.span[0] === sel[0] && p.span[1] === sel[1]) : undefined;
  return (
    <div className="alert" style={{ marginBottom: 10 }} data-testid="expect-box">
      <div className="row">
        <strong>{e.kind === "document" ? "Document" : "Expected"}</strong>
        <span>expected <span className={`badge ${actionClass(e.expected)}`}>{e.expected}</span>
          {e.acceptable.length ? <span className="faint"> (also fine: {e.acceptable.join(", ")})</span> : null}</span>
        <span>got <span className={`badge ${actionClass(e.got)}`}>{e.got}</span></span>
        {mark(e.ok)}
      </div>
      {e.note ? <div className="faint" style={{ fontSize: 12, marginTop: 4 }}>{e.note}</div> : null}
      {e.paragraphs?.length ? (
        <div style={{ marginTop: 6, fontSize: 13 }}>
          {cur ? <div>this paragraph: expected <span className={`badge ${actionClass(cur.expected)}`}>{cur.expected}</span>
            {cur.acceptable.length ? <span className="faint"> (also {cur.acceptable.join(", ")})</span> : null} · got{" "}
            <span className={`badge ${actionClass(cur.got)}`}>{cur.got}</span> {mark(cur.ok)}
            {cur.note ? <span className="faint" style={{ fontSize: 12 }}> · {cur.note}</span> : null}</div> : null}
          <div className="faint" style={{ fontSize: 12, marginTop: 4 }}>all paragraphs: {e.paragraphs.map((p, i) => (
            <span key={i} className="chip" title={p.note}>¶{i + 1} {p.expected} → {p.got} {p.ok ? "✓" : "✗"}</span>))}</div>
        </div>) : null}
    </div>
  );
}

/** The original text with what the clean copy leaves out struck through (removed paragraphs; review paragraphs too
 * when the run used --review-as remove). */
function CutText({ d }: { d: LabelDocResp }) {
  const text = d.text || "";
  const reviewCut = d.clean?.review_as === "remove";
  const out: ReactElement[] = [];
  let pos = 0;
  (d.row.paragraphs || []).forEach((p, i) => {
    if (p.span[0] > pos) out.push(<span key={`g${i}`}>{text.slice(pos, p.span[0])}</span>);
    const cut = p.action === "remove" || (reviewCut && p.action === "review");
    out.push(cut
      ? <del key={`p${i}`} className="cut" title={`cut: ${p.action} (${p.labels.join(", ") || p.reason})`}>{text.slice(p.span[0], p.span[1])}</del>
      : <span key={`p${i}`} className={p.action === "review" ? "kept-review" : ""} title={p.action === "review" ? "review: kept in the clean copy (--review-as keep)" : p.action}>
          {text.slice(p.span[0], p.span[1])}</span>);
    pos = p.span[1];
  });
  if (pos < text.length) out.push(<span key="tail">{text.slice(pos)}</span>);
  return <div className="doc" data-testid="cut-text">{out}</div>;
}

/** The document as written to <file>.clean.jsonl[.zst], with the rewritten place names marked. */
function CleanText({ c }: { c: NonNullable<LabelDocResp["clean"]> }) {
  if (!c.available) return (
    <div className="empty" data-testid="clean-text">This run has no clean copy. Make one without the models:
      <pre className="json">python nli_label.py redecide &lt;this run&gt; --output-dir &lt;new folder&gt; --write-clean</pre>
      (or run with <code>--write-clean</code>).</div>);
  if (c.dropped) return <div className="empty" data-testid="clean-text">The whole document was <strong>dropped</strong>: less than <code>--min-doc-chars</code> (50) characters were left after cutting, so it is not in the clean copy.</div>;
  if (c.problem || c.text == null) return <div className="alert warn" data-testid="clean-text">{c.problem || "the clean copy has no text for this document"}</div>;
  const t = c.text;
  const out: ReactElement[] = [];
  let pos = 0;
  (c.rewrites || []).forEach((r, i) => {
    if (r.start > pos) out.push(<span key={`t${i}`}>{t.slice(pos, r.start)}</span>);
    out.push(<mark key={`r${i}`} className="rewritten" title={`${r.old} → ${r.new}`}>{t.slice(r.start, r.end)}</mark>);
    pos = r.end;
  });
  if (pos < t.length) out.push(<span key="tail">{t.slice(pos)}</span>);
  return <div className="doc" data-testid="clean-text">{out}</div>;
}

export function LabelDocView() {
  const sp = useSearchParams();
  const run = sp.get("run") || "", file = sp.get("file") || "", line = Number(sp.get("line") || 0);
  const res = useApi(run && file && line ? `labeldoc:${run}:${file}:${line}` : null, (s) => api.labelDoc(run, { file, line }, s));
  const [sel, setSel] = useState(Math.max(0, Number(sp.get("para")) || 0));  // ?para=N opens paragraph N (0-based)
  const [view, setView] = useState<"labels" | "cut" | "clean">("labels");
  const decidedBy = res.data?.row.decided_by;
  useEffect(() => {  // line unit: open the paragraph that decided the line (unless ?para= says otherwise)
    if (decidedBy !== undefined && decidedBy !== null && sp.get("para") === null) setSel(decidedBy);
  }, [decidedBy, sp]);
  if (!run || !file || !line) return <div className="alert error">Missing ?run=, ?file= or ?line=</div>;
  const d = res.data;
  const paras = d?.row.paragraphs || [];
  return (
    <>
      <div className="page-head">
        <div>
          <Crumbs items={[{ label: "Labelling", href: "/label" },
            { label: run, href: safeBack(sp.get("back")) || href("/label/run", { run, file, from_line: line }) }, { label: `line ${line}` }]} />
          <h1>{file} · line {line} {d ? <span className={`badge big ${actionClass(d.row.action)}`}>{d.row.action}</span> : null}</h1>
          {d ? <div className="sub">{num(d.row.tokens)} tokens (est.){d.row.tokens_removed ? `, ${num(d.row.tokens_removed)} removed` : ""}
            {d.row.rewrites ? `, ${d.row.rewrites} place name(s) rewritten` : ""}{d.row.id ? ` · id ${d.row.id}` : ""}</div> : null}
          {d?.row.decision ? (
            <div className="row" style={{ marginTop: 6 }} data-testid="line-decision">
              <span>Line decision <span className={`badge ${actionClass(d.row.decision)}`}>{d.row.decision}</span></span>
              <span className="faint" style={{ fontSize: 12 }}>decision unit: line · the strictest paragraph decides
                {d.row.decided_by !== undefined ? <> (¶{d.row.decided_by + 1}, {d.row.reason})</> : null}; the line is
                {d.row.action === "removed" ? " removed whole" : " kept whole"}</span></div>) : null}
        </div>
      </div>
      <ErrorBox error={res.error} onRetry={res.reload} />
      {res.loading && !d ? <Loading what="Loading document" /> : null}
      {d ? (
        <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1.1fr) minmax(0, 1fr)", alignItems: "start" }}>
          <div className="panel flush">
            <div className="panel-head"><h2>Text</h2>
              <span className="seg" data-testid="text-view">
                <button className={view === "labels" ? "on" : ""} onClick={() => setView("labels")}>Labels</button>
                <button className={view === "cut" ? "on" : ""} onClick={() => setView("cut")} title="the original, with what the clean copy leaves out struck through">What is cut</button>
                <button className={view === "clean" ? "on" : ""} onClick={() => setView("clean")} title="the text in the clean copy (<file>.clean.jsonl.zst)">Clean copy</button>
              </span>
              {view === "labels" ? (
                <span className="legend"><span><i className="swatch lpara remove" />remove</span><span><i className="swatch lpara review" />review</span>
                  <span><i className="swatch lpara keep" />keep</span><span><i className="swatch lpara pass" />pass</span></span>) : null}
              {view === "cut" && d.row.decision ? <span className="badge warn">line unit: nothing is cut; the whole line is {d.row.action === "removed" ? "dropped" : "kept"}</span> : null}
              {view === "cut" ? <span className="faint" style={{ fontSize: 12 }}>struck through = not in the clean copy{d.clean?.review_as === "remove" ? " (review paragraphs too: --review-as remove)" : "; review paragraphs stay (--review-as keep)"}</span> : null}
              <span className="spacer" />
              {d.text ? <TextTools text={view === "clean" && d.clean?.text ? d.clean.text : d.text} source={{ run, file, line, id: d.row.id ?? null }} row={d.row}
                paragraph={paras[sel] ? d.text.slice(paras[sel].span[0], paras[sel].span[1]) : undefined}
                paragraphs={paras.map((p) => ({ span: p.span, action: p.action }))} testid="doc-tools" /> : null}
              {view === "clean" && d.clean?.rewrites?.length ? <span className="faint" style={{ fontSize: 12 }}>marked = place name rewritten (hover: old → new)</span> : null}
            </div>
            {d.problem ? <div className="alert" style={{ margin: 12 }}>{d.problem}</div> : null}
            {view === "labels" && d.text !== null ? <DocText d={d} sel={sel} onSel={setSel} /> : null}
            {view === "cut" && d.text !== null ? <CutText d={d} /> : null}
            {view === "clean" && d.clean ? <CleanText c={d.clean} /> : null}
            {paras.length === 0 ? <div className="empty">No paragraph was labelled: {d.row.gate ? "" : "no keyword or marker hit (untouched)."}</div> : null}
          </div>
          <div className="panel">
            <div className="row" style={{ marginBottom: 8 }}><h2 style={{ margin: 0 }}>Flow</h2>
              {paras[sel] ? <a className="btn small" data-testid="try-this" href={href("/label/try", { run, file, line, para: sel })}
                title="Open the Try page with this paragraph and the run's policy">Try this paragraph →</a> : null}
              {d.text ? <a className="btn small" data-testid="lab-this" href={href("/label/lab", { run, file, line, para: paras[sel] ? sel : undefined })}
                title="Open the Experiment page with this paragraph: change any setting of the policy, compare with the run's policy; nothing is saved unless you confirm">Experiment →</a> : null}
              {paras.length > 1 ? <span className="seg">{paras.map((p, i) => (
                <button key={i} className={i === sel ? "on" : ""} onClick={() => setSel(i)} title={d.row.decided_by === i ? "this paragraph decided the line" : undefined}>
                  ¶{i + 1}{d.row.decided_by === i ? " ★" : ""} <span className={`badge ${actionClass(p.action)}`}>{p.action}</span></button>))}</span> : null}
            </div>
            {d.expect ? <ExpectBox e={d.expect} sel={paras[sel]?.span} /> : null}
            {paras[sel] ? <Flow policy={d.policy} p={paras[sel]} /> : <div className="faint">Nothing to show.</div>}
          </div>
        </div>
      ) : null}
    </>
  );
}

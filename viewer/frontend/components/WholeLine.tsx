"use client";
// "Whole line": how a line's result comes out of its paragraphs (nli_label.py, paragraph unit): only paragraphs with a
// keyword / marker are checked, the others stay untouched; each checked paragraph gets its own action; the document
// action: nothing cut -> review if any review, else pass if all pass, else kept; something cut -> the cut paragraphs
// go, "edited" (or "removed": too little left, or --max-removed-share / --drop-if-first-cut). The expected check uses
// the strictest paragraph action (remove > review > keep > pass). Line unit: the strictest paragraph decides the line.
import type { FlowPolicyData, LabelDocResp, LabelParagraph } from "@/lib/types";
import { actionClass } from "./LabelRunView";

const STRICT: Record<string, number> = { pass: 0, keep: 1, review: 2, remove: 3 };

type Row = LabelDocResp["row"] & { removed_by?: string; removed_share?: number };

/** The index of the paragraph that decides the line (the strictest; the first of equals). */
export function decidingParagraph(paras: LabelParagraph[]): number | null {
  if (!paras.length) return null;
  let best = 0;
  paras.forEach((p, i) => { if ((STRICT[p.action] ?? 0) > (STRICT[paras[best].action] ?? 0)) best = i; });
  return best;
}

export function WholeLine({ text, row, policy, unit, reviewAs, sel, onSel, expected, testid }: {
  text: string; row: Row; policy: FlowPolicyData | null; unit?: string; reviewAs?: string;
  sel?: number; onSel?: (i: number) => void;
  /** the line's expected action and whether the strictest action matches it (null = no expected result) */
  expected?: { action: string; ok: boolean | null } | null;
  testid?: string;
}) {
  const paras = (row.paragraphs || []).slice().sort((a, b) => a.span[0] - b.span[0]);
  const order = (row.paragraphs || []).map((p) => paras.indexOf(p));   // row order -> text order
  // the text in order: the checked paragraphs and the text between them (not checked)
  const all: ({ kind: "para"; p: LabelParagraph; i: number } | { kind: "gap"; text: string })[] = [];
  let pos = 0;
  paras.forEach((p) => {
    const gap = text.slice(pos, p.span[0]);
    for (const g of gap.split(/\n\s*\n/)) if (g.trim()) all.push({ kind: "gap", text: g.trim() });
    all.push({ kind: "para", p, i: (row.paragraphs || []).indexOf(p) });
    pos = p.span[1];
  });
  for (const g of text.slice(pos).split(/\n\s*\n/)) if (g.trim()) all.push({ kind: "gap", text: g.trim() });

  const labels = policy?.labels || {};
  const positive = (p: LabelParagraph) => Object.entries(p.scores || {})
    .filter(([k, s]) => labels[k] && labels[k].level > 0 && s !== null && s !== undefined && s >= (labels[k].threshold ?? 0.8))
    .sort((a, b) => b[1] - a[1]);
  const cut = (p: LabelParagraph) => p.action === "remove" || (p.action === "review" && reviewAs === "remove");
  const dIdx = decidingParagraph(row.paragraphs || []);
  const strictest = dIdx !== null ? (row.paragraphs || [])[dIdx].action : row.action;
  const num = (i: number) => `¶${order[i] + 1}`;
  const cutList = (row.paragraphs || []).map((p, i) => (cut(p) ? num(i) : null)).filter(Boolean) as string[];

  let rule: React.ReactNode;
  if (!row.gate) rule = <>No keyword or marker anywhere: the line is <strong>untouched</strong>.</>;
  else if (unit === "line") {
    rule = <>Decision unit <strong>line</strong>: the strictest paragraph ({dIdx !== null ? num(dIdx) : "–"}, {strictest}) decides the whole
      line, kept or dropped whole → <span className={`badge ${actionClass(row.action)}`}>{row.action}</span></>;
  } else if (!cutList.length) {
    rule = <>Nothing cut → {row.action === "review" ? "a paragraph is review" : row.action === "pass" ? "every checked paragraph passed" : "kept as it is"} → <span className={`badge ${actionClass(row.action)}`}>{row.action}</span></>;
  } else if (row.action === "removed") {
    const why = row.removed_by === "removed_share" ? <>{Math.round(100 * (row.removed_share ?? 0))} % of the tokens would be cut, above the limit (<code>--max-removed-share</code>)</>
      : row.removed_by === "first_cut" ? <>the first checked paragraph is cut (<code>--drop-if-first-cut</code>)</>
      : <>less than <code>--min-doc-chars</code> characters would be left</>;
    rule = <>{cutList.join(", ")} cut, and {why} → the whole document is <span className="badge remove">removed</span></>;
  } else {
    rule = <>{cutList.join(", ")} cut, the rest kept → <span className={`badge ${actionClass(row.action)}`}>{row.action}</span>
      {row.tokens_removed ? <span className="faint"> · {row.tokens_removed} of {row.tokens} tokens removed</span> : null}</>;
  }

  return (
    <div className="flow-step whole-line" data-testid={testid || "whole-line"}>
      <div className="row" style={{ flexWrap: "wrap" }}><strong>Whole line</strong>
        <span className="faint" style={{ fontSize: 12 }}>how the paragraphs give the line&apos;s result</span></div>
      <ol className="whole-paras">
        {all.map((it, k) => it.kind === "gap" ? (
          <li key={k} className="faint"><span className="mono">–</span> not checked (no keyword or marker): <em>{it.text.slice(0, 80)}{it.text.length > 80 ? "…" : ""}</em></li>
        ) : (
          <li key={k} className={sel === it.i ? "on" : ""}>
            <button className="linklike" onClick={() => onSel?.(it.i)} title="show this paragraph's flow">{num(it.i)}</button>{" "}
            <span className={`badge ${actionClass(it.p.action)}`}>{it.p.action}</span>
            <span className="mono faint" style={{ fontSize: 11.5 }}> {it.p.reason}</span>
            {positive(it.p).slice(0, 3).map(([k2, s]) => (
              <span key={k2} className="chip" title={`${labels[k2].decision}, threshold ${labels[k2].threshold ?? 0.8}`}>{k2} {s.toFixed(3)}</span>))}
            {cut(it.p) && unit !== "line" ? <span className="faint" style={{ fontSize: 11.5 }}> · cut</span> : null}
            {dIdx === it.i ? <span className="badge accent" style={{ marginLeft: 4 }} title="the strictest paragraph">decides</span> : null}
          </li>))}
      </ol>
      <div style={{ marginTop: 4 }}>Document: {rule}</div>
      <div style={{ marginTop: 4 }} data-testid="whole-line-result">Line result for the expected check: strictest{" "}
        <span className={`badge ${actionClass(strictest)}`}>{strictest}</span>
        {dIdx !== null ? <span className="faint"> (from {num(dIdx)})</span> : null}
        {expected ? <> · expected <span className={`badge ${actionClass(expected.action)}`}>{expected.action}</span>
          {expected.ok !== null ? <span className={`badge ${expected.ok ? "keep" : "filter"}`} style={{ marginLeft: 4 }}>{expected.ok ? "✓" : "✗"}</span> : null}</> : null}
        <span className="faint" style={{ fontSize: 11.5 }}> · remove &gt; review &gt; keep &gt; pass</span>
      </div>
    </div>);
}

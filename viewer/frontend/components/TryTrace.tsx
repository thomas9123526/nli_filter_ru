"use client";
// "Show the flow trace" on the Try page: the paragraph's real path through the policy, step by step, like
// cmds/labeling/russia_policy_flow.html filled with this text's values. The decision itself is the backend's
// (p.action / p.reason); this view only explains it, marking the rule that decided and why the others did not.
import type { LabelDocResp, LabelParagraph, LabelTryResp } from "@/lib/types";
import { ScoreBar } from "./ui";
import { actionClass } from "./LabelRunView";

type Pol = LabelTryResp["policy"] & { no_subject?: string; narrative_opens_gate?: boolean };
type Lab = { level: number; decision: string; threshold: number; hypothesis: string; softens?: string[]; protected?: boolean };

const glob = (pat: string, k: string) => new RegExp("^" + pat.split("*").map((s) => s.replace(/[.+?^${}()|[\]\\]/g, "\\$&")).join(".*") + "$").test(k);

function Step({ n, tag, title, state, side, children }: {
  n: number | string; tag: string; title: string; state?: "decided" | "skipped"; side?: React.ReactNode; children?: React.ReactNode;
}) {
  return (
    <>
      <div className="trace-stage">
        <div className={`trace-box${state ? ` ${state}` : ""}`}>
          <div className="trace-h"><span className="trace-tag">{n} · {tag}</span><strong>{title}</strong></div>
          {children}
        </div>
        <div className="trace-side">{side}</div>
      </div>
      <div className="trace-wire" />
    </>
  );
}

function Scores({ keys, p, labels }: { keys: string[]; p: LabelParagraph; labels: Record<string, Lab> }) {
  if (!keys.length) return <div className="faint" style={{ fontSize: 12 }}>no labels at this level</div>;
  return (
    <div className="trace-scores">
      {keys.map((k) => {
        const l = labels[k];
        const s = p.scores[k];
        const pos = s !== undefined && s !== null && s >= l.threshold;
        return (
          <div key={k} className="trace-sc">
            <span className="mono" style={{ fontSize: 12.5 }}>{k} <span className="faint" style={{ fontFamily: "var(--sans)" }}>
              {l.decision}{l.softens?.length ? " (softener)" : ""}{l.protected ? ", protected" : ""}{p.judged?.includes(k) ? " · judged" : ""}{p.from_field?.includes(k) ? " · topic field" : ""}</span></span>
            <ScoreBar value={s} threshold={l.threshold} />
            {s === undefined || s === null ? <span className="badge neutral">not scored</span>
              : <span className={`badge ${pos ? (l.decision === "gate" ? "accent" : actionClass(l.decision)) : "neutral"}`}>{pos ? "yes" : "no"}</span>}
          </div>);
      })}
    </div>
  );
}

export function TryTrace({ res, p, text, row, docAction, expected }: {
  res: LabelTryResp; p: LabelParagraph; text: string; row: LabelDocResp["row"]; docAction: string;
  expected?: string | null;
}) {
  const pol = res.policy as Pol;
  const labels = pol.labels as unknown as Record<string, Lab>;
  const keys = Object.keys(labels);
  const lv = (n: number) => keys.filter((k) => labels[k].level === n);
  const gateKeys = lv(0);
  const gateKey = p.opened_by_gate || gateKeys[0];
  const gateScore = gateKey ? p.scores[gateKey] : undefined;
  const many = gateKeys.length > 1;
  const isPos = (k: string) => p.scores[k] !== undefined && p.scores[k] !== null && p.scores[k] >= labels[k].threshold;
  const pos = keys.filter((k) => labels[k].level > 0 && isPos(k));
  const softeners = pos.filter((k) => labels[k].softens?.length);
  const softened = new Set(pos.filter((k) => softeners.some((s) => (labels[s].softens || []).some((pat) => glob(pat, k)))));
  const l2remove = pos.filter((k) => labels[k].level === 2 && labels[k].decision === "remove" && !softened.has(k));
  const counted = pos.filter((k) => !labels[k].softens?.length && labels[k].decision !== "flag");
  const dec = (k: string) => (labels[k].decision === "remove" && softened.has(k) ? "review" : labels[k].decision);
  // a positive, unsoftened level-2 remove already decided (rule 1); only level-1 removes reach rules 2 and 3
  const removeL = counted.filter((k) => dec(k) === "remove" && labels[k].level === 1);
  const reviewL = counted.filter((k) => dec(k) === "review");
  const keepL = counted.filter((k) => dec(k) === "keep");
  const gateOpen = p.reason !== "gate_negative";
  const neRemoved = p.reason?.startsWith("non_english");  // removed for a non-English hit, before the gate
  // the reason before an exception changed it is not stored; derive which rule gave action_before
  const cascadeReason = p.reason === "exception" || p.exception_blocked
    ? (!gateOpen ? "gate_negative" : l2remove.length ? "narrative" : removeL.length && keepL.length ? "conflict"
      : removeL.length ? "remove_label" : reviewL.length ? "review_label" : keepL.length ? "keep_label" : "no_subject")
    : p.reason;
  const cascadeAction = p.action_before || p.action;
  const list = (ks: string[]) => ks.map((k) => <code key={k} style={{ marginRight: 4 }}>{k}</code>);
  const rules: { key: string; text: React.ReactNode; why: React.ReactNode }[] = [
    { key: "narrative", text: <>A Level-2 <strong>remove</strong> label positive, not softened → remove</>,
      why: l2remove.length ? list(l2remove) : "none" },
    { key: "conflict", text: <>A Level-1 remove label and a keep label both positive → conflict ({pol.conflict || "review"})</>,
      why: removeL.length && keepL.length ? <>{list(removeL)} + {list(keepL)}</> : removeL.length ? "no keep label positive" : "no Level-1 remove label positive" },
    { key: "remove_label", text: <>A Level-1 <strong>remove</strong> label positive → remove (a remove beats any review)</>,
      why: removeL.length ? list(removeL) : "none" },
    { key: "review_label", text: <>A <strong>review</strong> label positive (or a softened remove) → review</>,
      why: reviewL.length ? list(reviewL) : "none" },
    { key: "keep_label", text: <>A <strong>keep</strong> label positive → keep</>, why: keepL.length ? list(keepL) : "none" },
    { key: "no_subject", text: <>Nothing positive → no_subject ({pol.no_subject || "keep"})</>, why: "" },
  ];
  const decidedAt = rules.findIndex((r) => r.key === cascadeReason);
  const near = keys.filter((k) => p.scores[k] !== undefined && p.scores[k] !== null && Math.abs(p.scores[k] - labels[k].threshold) < 0.1)
    .sort((a, b) => Math.abs(p.scores[a] - labels[a].threshold) - Math.abs(p.scores[b] - labels[b].threshold));
  const hits = row.hits || [];
  const ok = expected ? [...expected.split(" or ").map((x) => x.trim())] : null;

  return (
    <div className="trace" data-testid="try-trace">
      <div className="trace-verdicts">
        <span>This paragraph <span className={`badge ${actionClass(p.action)}`}>{p.action}</span></span>
        <span>Document <span className={`badge ${actionClass(docAction)}`}>{docAction}</span></span>
        {ok ? <span>Expected <span className={`badge ${actionClass(ok[0])}`}>{expected}</span></span> : null}
      </div>

      <Step n={1} tag="Document" title="Keyword scan" side={hits.length ? "→ checked" : "→ untouched"}>
        <div className="trace-p">{hits.length ? <>Hit{hits.length > 1 ? "s" : ""}: {hits.map((h, i) => <strong key={i}>“{h.kw}”{i < hits.length - 1 ? ", " : ""}</strong>)}</> : "No keyword."}
          {row.markers?.length ? <> · marker{row.markers.length > 1 ? "s" : ""}: <strong>{row.markers.join(", ")}</strong></> : " · no marker term"}</div>
      </Step>

      <Step n={2} tag="Document" title="Paragraph" side={`→ characters ${p.span[0]}–${p.span[1]}`}>
        <div className="trace-p">{(row.paragraphs || []).length} paragraph{(row.paragraphs || []).length === 1 ? "" : "s"} checked; this one: {p.span[1] - p.span[0]} characters.</div>
        <div className="trace-quote">{text.slice(p.span[0], p.span[1])}</div>
      </Step>

      {p.non_english?.length ? (
        <Step n="2b" tag="Non-English" title="Keyword / marker in a non-English script" state={neRemoved ? "decided" : undefined}
          side={neRemoved ? <span className="badge filter">remove</span> : "→ checked as usual"}>
          <div className="trace-p">{p.non_english.map((h) => <strong key={h.kind + h.term}>“{h.term}” <span className="faint">({h.kind}, {h.script}) </span></strong>)}
            {neRemoved ? <> The policy&apos;s non-English setting removes such a paragraph; exceptions cannot lower it.
              {(p.levels || []).length ? " It was still scored (score_when_removed), shown below for information." : " It was not scored."}</>
              : " The setting says check: the normal check below decides."}</div>
        </Step>) : null}

      {neRemoved && !(p.levels || []).length ? null : <>
      <Step n={3} tag="L0" title="Gate" state={gateOpen ? undefined : "decided"}
        side={gateOpen ? <span className="badge accent">open</span> : <span className="badge neutral">pass</span>}>
        {gateKeys.length ? <Scores keys={gateKeys} p={p} labels={labels} /> : null}
        <div className="trace-p" data-testid="trace-gates">
          {p.marker ? "A marker term is in the paragraph: the gate is open without the model."
            : p.opened_by?.length ? <>{many ? "Every gate label" : "The gate label"} said no, but {list(p.opened_by)} opened it (narrative_opens_gate).</>
            : gateOpen && many ? <>{gateKeys.length} gates, OR-combined: opened by <strong>{gateKey}</strong> ({gateScore?.toFixed(4)} ≥ {gateKey ? labels[gateKey].threshold : "?"}){gateKey !== gateKeys[0] ? "; the gates before it said no" : ""}.</>
            : gateOpen ? <>Gate label {gateScore?.toFixed(4)} ≥ {gateKey ? labels[gateKey].threshold : "?"}: open.</>
            : many ? <>All {gateKeys.length} gate labels below their thresholds (later gates are scored only where the earlier ones said no), no marker: the keyword was incidental → <strong>pass</strong>.</>
            : <>Gate label {gateScore?.toFixed(4)} below {gateKey ? labels[gateKey].threshold : "?"}, no marker: the keyword was incidental → <strong>pass</strong>.</>}
        </div>
      </Step>

      {gateOpen ? (<>
        <Step n={4} tag="L1 ∥ L2" title="Scores (bar = score, tick = threshold)"
          side={pos.length ? <>→ positive: {list(pos)}</> : "→ nothing positive"}>
          <div className="trace-lvl">Level 1 · subject</div>
          <Scores keys={lv(1)} p={p} labels={labels} />
          <div className="trace-lvl">Level 2 · framing</div>
          <Scores keys={lv(2).filter((k) => !labels[k].softens?.length)} p={p} labels={labels} />
        </Step>

        <Step n={5} tag="L2" title="Softener" state={softened.size ? undefined : "skipped"}
          side={softened.size ? <>→ softened: {list([...softened])}</> : "→ no effect"}>
          <Scores keys={lv(2).filter((k) => labels[k].softens?.length)} p={p} labels={labels} />
          <div className="trace-p">{softened.size ? <>{list(softeners)} is positive: {list([...softened])} count as review instead of remove.</>
            : softeners.length ? "Positive, but no positive label to soften." : "Not positive: nothing is softened."}</div>
        </Step>

        <Step n={6} tag="Rules" title="Decision rules, first match wins" state="decided"
          side={<><span className={`badge ${actionClass(cascadeAction)}`}>{cascadeAction}</span><span className="faint">reason {cascadeReason}</span></>}>
          <ol className="trace-rules">
            {rules.map((r, i) => (
              <li key={r.key} className={i === decidedAt ? "hit" : "miss"}>
                {r.text}{r.why ? <span className="faint"> · {r.why}</span> : null}
                {i === decidedAt ? <span className="trace-mark">← decided here</span> : i > decidedAt && decidedAt >= 0 ? <span className="faint"> (not reached)</span> : null}
              </li>))}
          </ol>
        </Step>
      </>) : null}

      <Step n={7} tag="Exception" title="Exceptions" state={p.exception || p.exception_blocked ? "decided" : "skipped"}
        side={p.exception ? <span className={`badge ${actionClass(p.action)}`}>{p.action}</span> : p.exception_blocked ? "→ blocked" : "→ unchanged"}>
        <div className="trace-p">
          {p.exception ? <>Exception <code>{p.exception}</code> matched{p.exception_phrases?.length ? <> (phrase{p.exception_phrases.length > 1 ? "s" : ""} {p.exception_phrases.map((x) => `“${x}”`).join(", ")})</> : null}: {p.action_before} → <strong>{p.action}</strong>.</>
            : p.exception_blocked ? <>Exception <code>{p.exception_blocked}</code> matched, but a <strong>protected</strong> label removed the paragraph: it stays remove.</>
            : (pol.exceptions || []).length ? <>No exception matched ({(pol.exceptions || []).map((e) => e.key).join(", ")}).</> : "The policy has no exceptions."}
        </div>
      </Step>
      </>}

      <div className="trace-stage">
        <div className="trace-box">
          <div className="trace-h"><span className="trace-tag">8 · Document</span><strong>Document action</strong></div>
          <div className="trace-p">
            {row.decision ? <>Decision unit line: the strictest paragraph decides the whole line
              {row.decided_by !== undefined ? <> (¶{row.decided_by + 1}, <code>{row.reason}</code>)</> : null}: line decision
              {" "}<strong>{row.decision}</strong>, the line is {row.action === "removed" ? "removed whole" : "kept whole"}.</>
              : row.action === "removed" ? "Cut paragraphs leave fewer than 50 characters: the document is removed."
              : row.action === "edited" ? "A paragraph is cut, the rest stays: the document is edited."
              : row.action === "review" ? "Nothing cut, a paragraph is review: the document goes to review."
              : row.action === "pass" ? "Every checked paragraph passed."
              : "Nothing cut, no review: the document is kept."}
            {" "}(stored action <code>{row.action}</code>)</div>
        </div>
        <div className="trace-side"><span className={`badge ${actionClass(row.action)}`}>{row.action}</span></div>
      </div>

      <div className="trace-near">
        <strong>Close to a threshold</strong> (within 0.1): {near.length ? near.map((k) => (
          <span key={k} className="chip">{k} {p.scores[k].toFixed(3)} / {labels[k].threshold}</span>)) : <span className="faint">none: the result comes from the policy settings, not an uncertain score.</span>}
      </div>
    </div>
  );
}

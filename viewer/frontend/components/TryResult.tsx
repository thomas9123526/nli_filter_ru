"use client";
// One line's result of "Try settings": verdict (and the saved run's, to compare), expandable highlighted text and
// the check-1 / check-2 tables, as on the record page.
import { useState } from "react";
import type { RecordResp, TryResult } from "@/lib/types";
import { HighlightedText, Legend, initialFocus, type Focus, type TextOptions } from "./HighlightedText";
import { Check1Table, Check2Table } from "./RecordView";
import { DecisionBadge, ReasonBadge } from "./ui";

export function TryLineResult({ r }: { r: TryResult }) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState<number[]>([]);
  const [opts, setOpts] = useState<TextOptions>({ check1: true, check2: true });
  const [focus, setFocus] = useState<Focus>(null);
  const ex = r.explanation;
  const rec = { explanation: ex, decision: r.decision } as unknown as RecordResp;
  const jump = (id: number | null) => { if (id !== null) { setFocus((f) => ({ id, n: (f?.n || 1) + 1 })); setActive([id]); } };
  const changed = r.previous && r.previous.decision !== r.decision.decision;
  return (
    <div className={`try-result${changed ? " changed" : ""}`} data-testid={`try-${r.line}`}>
      <div className="row">
        <span className="faint">try:</span>
        <DecisionBadge decision={r.decision.decision} />
        <ReasonBadge reason={r.decision.reason} />
        {ex.check1 ? <span className="muted mono" title="best check-1 score">c1 {ex.check1.score?.toFixed(3)}</span> : null}
        {r.previous ? (
          <span className={changed ? "badge warn" : "faint"} title="the decision of the saved filter run">
            was {r.previous.decision} ({r.previous.reason}){changed ? " → changed" : ""}
          </span>
        ) : null}
        <span className="spacer" />
        {ex.text_available ? <button className="btn small ghost" onClick={() => { setOpen((o) => !o); setFocus(() => { const id = initialFocus(ex.marks); return id === null ? null : { id, n: 1 }; }); }}>
          {open ? "Hide details" : "Details"}</button> : null}
      </div>
      <div className="faint" style={{ fontSize: 12 }}>{ex.verdict.summary}</div>
      {open ? (
        <div className="stack" style={{ marginTop: 8 }}>
          <div className="panel flush">
            <div className="panel-body" style={{ paddingBottom: 0 }}>
              <Legend options={opts} setOptions={setOpts} hasCheck1={!!ex.check1} hasCheck2={!!ex.check2} />
            </div>
            <HighlightedText segments={ex.segments} marks={ex.marks} active={active} options={opts} onHover={setActive} focus={focus} />
          </div>
          <Check1Table rec={rec} setActive={setActive} jump={jump} />
          <Check2Table rec={rec} setActive={setActive} jump={jump} />
        </div>
      ) : null}
    </div>
  );
}

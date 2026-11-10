"use client";
// The original text cut into segments by the backend, with keyword hits and NLI windows highlighted.
// `active` = mark ids to emphasise (hovering a score row highlights the window / hit it belongs to).
import { useEffect, useRef } from "react";
import type { Mark, Segment } from "@/lib/types";
import { HIT_STATE_LABEL, RULE_LABEL, score } from "@/lib/format";

export type TextOptions = { check1: boolean; check2: boolean };
/** Ask the text box to scroll to a mark; n changes on every request so the same mark can be asked again. */
export type Focus = { id: number; n: number } | null;

/** The mark worth showing first: the best check-1 window, else the first hit not resolved by a rule. */
export function initialFocus(marks: Mark[]): number | null {
  const best = marks.find((m) => m.kind === "check1_window" && m.best);
  const hit = marks.find((m) => m.kind === "hit" && m.state !== "rule") || marks.find((m) => m.kind === "hit");
  if (hit && best && hit.start >= best.start && hit.end <= best.end) return hit.id;
  return best ? best.id : hit ? hit.id : null;
}

function hitTitle(m: Mark): string {
  const parts = [`'${m.kw}' — ${HIT_STATE_LABEL[m.state || "open"]}`];
  if (m.rule) parts.push(`rule: ${RULE_LABEL[m.rule] || m.rule}`);
  if (m.check2) parts.push(`check 2 ${m.check2.hyp}: ${score(m.check2.score)}${m.check2.judge !== null ? " (judge)" : ""}`);
  parts.push(`characters ${m.start}–${m.end}`);
  return parts.join("\n");
}

export function HighlightedText({ segments, marks, active, options, onHover, focus }: {
  segments: Segment[];
  marks: Mark[];
  active: number[];
  options: TextOptions;
  onHover?: (ids: number[]) => void;
  focus?: Focus;
}) {
  const byId = new Map(marks.map((m) => [m.id, m]));
  const activeSet = new Set(active);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const c = box.current;
    if (!c || !focus) return;
    const el = c.querySelector<HTMLElement>(`[data-m~="${focus.id}"]`);
    if (!el) return;
    const frame = requestAnimationFrame(() => {
      const top = el.getBoundingClientRect().top - c.getBoundingClientRect().top + c.scrollTop;
      c.scrollTo({ top: Math.max(0, top - c.clientHeight / 3), behavior: focus.n > 1 ? "smooth" : "auto" });
    });
    return () => cancelAnimationFrame(frame);
  }, [focus]);
  return (
    <div className={`doc${segments.reduce((n, s) => n + (s.text?.length || 0), 0) > 2500 ? " long" : ""}`} data-testid="highlighted-text" ref={box}>
      {segments.map((seg, i) => {
        if (seg.gap !== undefined) {
          return <span key={i} className="gap" title={`characters ${seg.start}–${seg.end} not shown`}>… {seg.gap.toLocaleString("en-US")} characters …</span>;
        }
        const ms = (seg.marks || []).map((id) => byId.get(id)!).filter(Boolean);
        const hit = ms.find((m) => m.kind === "hit");
        const w1 = options.check1 ? ms.filter((m) => m.kind === "check1_window") : [];
        const w2 = options.check2 ? ms.filter((m) => m.kind === "check2_window") : [];
        const cls = ["seg"];
        if (w1.length) cls.push("w1");
        if (w1.some((m) => m.best)) cls.push("best");
        if (w2.length) cls.push("w2");
        if (hit) cls.push("hit", hit.state || "open");
        if (ms.some((m) => activeSet.has(m.id))) cls.push("active");
        const title = hit ? hitTitle(hit) : w1.length || w2.length
          ? [w1.length ? `check-1 window${w1.some((m) => m.best) ? " (best)" : ""}` : "", w2.length ? "check-2 window" : ""].filter(Boolean).join(", ")
          : undefined;
        const dataM = (seg.marks || []).join(" ") || undefined;
        if (cls.length === 1) return <span key={i} data-m={dataM}>{seg.text}</span>;
        return (
          <span key={i} className={cls.join(" ")} title={title} data-m={dataM}
            onMouseEnter={hit && onHover ? () => onHover([hit.id, ...marks.filter((m) => m.kind === "check2_window" && m.hit === hit.hit).map((m) => m.id)]) : undefined}
            onMouseLeave={hit && onHover ? () => onHover([]) : undefined}>
            {seg.text}
          </span>
        );
      })}
    </div>
  );
}

export function Legend({ options, setOptions, hasCheck1, hasCheck2 }: {
  options: TextOptions;
  setOptions: (o: TextOptions) => void;
  hasCheck1: boolean;
  hasCheck2: boolean;
}) {
  return (
    <div className="legend">
      <span><i className="swatch about" /> hit, not incidental</span>
      <span><i className="swatch open" /> hit, check 1 only</span>
      <span><i className="swatch incidental" /> hit, incidental (check 2)</span>
      <span><i className="swatch rule" /> hit, resolved by rule</span>
      {hasCheck1 ? (
        <label className="check"><input type="checkbox" checked={options.check1} onChange={(e) => setOptions({ ...options, check1: e.target.checked })} /><i className="swatch w1" /> check-1 window</label>
      ) : null}
      {hasCheck2 ? (
        <label className="check"><input type="checkbox" checked={options.check2} onChange={(e) => setOptions({ ...options, check2: e.target.checked })} /><i className="swatch w2" /> check-2 window</label>
      ) : null}
    </div>
  );
}

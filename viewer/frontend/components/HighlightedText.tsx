"use client";
// The original text cut into segments by the backend, with keyword hits and NLI windows highlighted.
// `active` = mark ids to emphasise (hovering a score row highlights the window / hit it belongs to).
import React, { useEffect, useRef } from "react";
import type { Mark, Segment } from "@/lib/types";
import { HIT_STATE_LABEL, RULE_LABEL, score } from "@/lib/format";

export type TextOptions = { check1: boolean; check2: boolean };
/** Ask the text box to scroll to a mark; n changes on every request so the same mark can be asked again. */
export type Focus = { id: number; n: number } | null;
/** Search matches as [start, end) code-point offsets (sorted), the current one, and a counter to re-scroll. */
export type Find = { ranges: [number, number][]; current: number; n: number } | null;

/** Characters of context shown around a search match that lies in a part a long text leaves out. */
const FIND_CONTEXT = 150;

/**
 * The whole text as code points (the backend's offsets are Python string indices = code points).
 * `full` is the record's text; it is used only if it agrees with every shown segment. Otherwise the text is
 * rebuilt from the shown segments (left-out parts become "\0", which no search can match): complete = false.
 */
export function documentText(segments: Segment[], full: string | null | undefined): { cps: string[]; complete: boolean } {
  if (full) {
    const cps = Array.from(full);
    if (segments.every((s) => s.gap !== undefined || cps.slice(s.start, s.end).join("") === (s.text || ""))) {
      return { cps, complete: true };
    }
  }
  const n = segments.length ? segments[segments.length - 1].end : 0;
  const cps: string[] = new Array(n).fill("\0");
  for (const s of segments) {
    if (s.gap === undefined) Array.from(s.text || "").forEach((c, i) => { cps[s.start + i] = c; });
  }
  return { cps, complete: false };
}

/** Case-insensitive matches of `query` in the text, as code-point ranges (at most `max`). */
export function findMatches(cps: string[], query: string, max = 2000): [number, number][] {
  if (!query) return [];
  const low = (c: string) => { const l = c.toLowerCase(); return l.length === c.length ? l : c; };
  const at: number[] = [];  // UTF-16 index -> code-point index
  let u = 0;
  const hay = cps.map((c, i) => { at[u] = i; const l = low(c); u += l.length; return l; }).join("");
  at[u] = cps.length;
  const q = Array.from(query).map(low).join("");
  const out: [number, number][] = [];
  for (let i = hay.indexOf(q); i >= 0 && out.length < max; i = hay.indexOf(q, i + q.length)) {
    if (at[i] !== undefined && at[i + q.length] !== undefined) out.push([at[i], at[i + q.length]]);
  }
  return out;
}

/** The text start..end (code-point offsets) with the search matches in it wrapped in <mark>. */
function withMatches(chars: string[], start: number, find: Find): React.ReactNode {
  const end = start + chars.length;
  const ranges = find?.ranges || [];
  let lo = 0, hi = ranges.length;  // first range ending after start
  while (lo < hi) { const mid = (lo + hi) >> 1; if (ranges[mid][1] <= start) lo = mid + 1; else hi = mid; }
  if (lo >= ranges.length || ranges[lo][0] >= end) return chars.join("");
  const parts: React.ReactNode[] = [];
  let pos = start;
  for (let k = lo; k < ranges.length && ranges[k][0] < end; k++) {
    const a = Math.max(start, ranges[k][0]), b = Math.min(end, ranges[k][1]);
    if (a > pos) parts.push(chars.slice(pos - start, a - start).join(""));
    parts.push(<mark key={k} className={`find${k === find!.current ? " current" : ""}`} data-f={k}>{chars.slice(a - start, b - start).join("")}</mark>);
    pos = b;
  }
  if (pos < end) parts.push(chars.slice(pos - start).join(""));
  return parts;
}

/** A left-out part of a long text, with the context around any search match inside it shown. */
function gapWithMatches(seg: Segment, cps: string[] | null, find: Find, key: number): React.ReactNode {
  const gap = (s: number, e: number, k: string) => (
    <span key={k} className="gap" title={`characters ${s}–${e} not shown`}>… {(e - s).toLocaleString("en-US")} characters …</span>
  );
  const inside = cps ? (find?.ranges || []).filter(([a, b]) => a < seg.end && b > seg.start) : [];
  if (!inside.length) return gap(seg.start, seg.end, String(key));
  const keep: [number, number][] = [];
  for (const [a, b] of inside) {
    const s = Math.max(seg.start, a - FIND_CONTEXT), e = Math.min(seg.end, b + FIND_CONTEXT);
    if (keep.length && s <= keep[keep.length - 1][1]) keep[keep.length - 1][1] = Math.max(keep[keep.length - 1][1], e);
    else keep.push([s, e]);
  }
  const out: React.ReactNode[] = [];
  let pos = seg.start;
  keep.forEach(([s, e], i) => {
    if (s > pos) out.push(gap(pos, s, `${key}g${i}`));
    out.push(<span key={`${key}c${i}`} className="found-ctx" title="shown because the search matches here">{withMatches(cps!.slice(s, e), s, find)}</span>);
    pos = e;
  });
  if (pos < seg.end) out.push(gap(pos, seg.end, `${key}g`));
  return out;
}

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

export function HighlightedText({ segments, marks, active, options, onHover, focus, find, text }: {
  segments: Segment[];
  marks: Mark[];
  active: number[];
  options: TextOptions;
  onHover?: (ids: number[]) => void;
  focus?: Focus;
  /** search matches to highlight (code-point offsets) */
  find?: Find;
  /** the whole text as code points, when known: matches in left-out parts of a long text are shown with context */
  text?: string[] | null;
}) {
  const byId = new Map(marks.map((m) => [m.id, m]));
  const activeSet = new Set(active);
  const box = useRef<HTMLDivElement>(null);
  const scrollTo = (el: HTMLElement | null, smooth: boolean) => {
    const c = box.current;
    if (!c || !el) return () => {};
    const frame = requestAnimationFrame(() => {
      const top = el.getBoundingClientRect().top - c.getBoundingClientRect().top + c.scrollTop;
      c.scrollTo({ top: Math.max(0, top - c.clientHeight / 3), behavior: smooth ? "smooth" : "auto" });
    });
    return () => cancelAnimationFrame(frame);
  };
  useEffect(() => {
    if (!focus) return;
    return scrollTo(box.current?.querySelector<HTMLElement>(`[data-m~="${focus.id}"]`) || null, focus.n > 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus]);
  useEffect(() => {
    if (!find || !find.ranges.length) return;
    return scrollTo(box.current?.querySelector<HTMLElement>(`[data-f="${find.current}"]`) || null, find.n > 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [find?.current, find?.n, find?.ranges]);
  return (
    <div className={`doc${segments.reduce((n, s) => n + (s.text?.length || 0), 0) > 2500 ? " long" : ""}`} data-testid="highlighted-text" ref={box}>
      {segments.map((seg, i) => {
        if (seg.gap !== undefined) return gapWithMatches(seg, text || null, find || null, i);
        const body = find?.ranges.length ? withMatches(Array.from(seg.text || ""), seg.start, find) : seg.text;
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
        if (cls.length === 1) return <span key={i} data-m={dataM}>{body}</span>;
        return (
          <span key={i} className={cls.join(" ")} title={title} data-m={dataM}
            onMouseEnter={hit && onHover ? () => onHover([hit.id, ...marks.filter((m) => m.kind === "check2_window" && m.hit === hit.hit).map((m) => m.id)]) : undefined}
            onMouseLeave={hit && onHover ? () => onHover([]) : undefined}>
            {body}
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

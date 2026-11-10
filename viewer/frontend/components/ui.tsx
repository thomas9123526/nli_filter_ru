"use client";
// Small reusable building blocks: badges, stats, score bars, states, copy button, theme toggle.
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { REASON_LABEL, RULE_LABEL, score } from "@/lib/format";
import type { ApiError } from "@/lib/api";

export function DecisionBadge({ decision, big }: { decision: string; big?: boolean }) {
  const cls = decision === "filter" ? "filter" : decision === "keep" ? "keep" : "neutral";
  return <span className={`badge ${cls}${big ? " big" : ""}`}>{decision === "filter" ? "Filtered" : decision === "keep" ? "Kept" : decision}</span>;
}

export function ReasonBadge({ reason }: { reason: string }) {
  return <span className="badge neutral" title={reason}>{REASON_LABEL[reason] || reason}</span>;
}

export function RuleChip({ rule }: { rule: string }) {
  return <span className="chip">{RULE_LABEL[rule] || rule}</span>;
}

export function ExpectBadge({ ok }: { ok: boolean | null | undefined }) {
  if (ok === null || ok === undefined) return <span className="faint">–</span>;
  return ok ? <span className="badge keep" title="decision matches the expected label">✓</span>
            : <span className="badge filter" title="decision differs from the expected label">✗ wrong</span>;
}

export function Stat({ label, value, note }: { label: string; value: ReactNode; note?: ReactNode }) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {note ? <div className="note">{note}</div> : null}
    </div>
  );
}

/** Score as a small bar with the threshold drawn as a tick. kind: pass colour when >= threshold. */
export function ScoreBar({ value, threshold, kind = "pass" }: { value: number | null | undefined; threshold?: number; kind?: "pass" | "inc" }) {
  if (value === null || value === undefined) return <span className="faint">–</span>;
  const pass = threshold !== undefined && value >= threshold;
  return (
    <span className="nowrap" title={threshold !== undefined ? `${score(value)} (threshold ${threshold})` : score(value)}>
      <span className="scorebar">
        <span className={`fill${pass ? ` ${kind}` : ""}`} style={{ width: `${Math.max(2, value * 100)}%` }} />
        {threshold !== undefined ? <span className="thr" style={{ left: `calc(${threshold * 100}% - 1px)` }} /> : null}
      </span>
      <span className="mono">{score(value)}</span>
    </span>
  );
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return <div className="loading"><span className="spinner" />{what}…</div>;
}

export function ErrorBox({ error, onRetry }: { error: ApiError | Error | null; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <div className="alert error row" role="alert">
      <span style={{ flex: 1 }}>{error.message}</span>
      {onRetry ? <button className="btn small" onClick={onRetry}>Retry</button> : null}
    </div>
  );
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      className="btn small ghost"
      title={text}
      onClick={() => {
        navigator.clipboard?.writeText(text).then(() => {
          setDone(true);
          setTimeout(() => setDone(false), 1200);
        });
      }}
    >
      {done ? "Copied" : label}
    </button>
  );
}

export function Crumbs({ items }: { items: { label: string; href?: string }[] }) {
  return (
    <nav className="crumbs" aria-label="Breadcrumb">
      {items.map((it, i) => (
        <span key={i} className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
          {i > 0 ? <span className="sep">/</span> : null}
          {it.href ? <Link href={it.href}>{it.label}</Link> : <span className="cur" title={it.label}>{it.label}</span>}
        </span>
      ))}
    </nav>
  );
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<string>("system");
  useEffect(() => {
    try {
      const t = localStorage.getItem("nli-viewer-theme") || "system";
      setTheme(t);
      apply(t);
    } catch {
      /* storage blocked */
    }
  }, []);
  function apply(t: string) {
    if (t === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", t);
  }
  function next() {
    const t = theme === "system" ? "dark" : theme === "dark" ? "light" : "system";
    setTheme(t);
    apply(t);
    try {
      localStorage.setItem("nli-viewer-theme", t);
    } catch {
      /* ignore */
    }
  }
  return (
    <button className="btn small ghost" onClick={next} title="Switch theme (system / dark / light)">
      {theme === "system" ? "◐ System" : theme === "dark" ? "● Dark" : "○ Light"}
    </button>
  );
}

/** Horizontal bars for a {label: count} map. */
export function Bars({ items, total, labels, colorOf }: {
  items: [string, number][];
  total: number;
  labels?: Record<string, string>;
  colorOf?: (key: string) => string;
}) {
  const max = Math.max(1, ...items.map(([, v]) => v));
  return (
    <div className="bars">
      {items.map(([k, v]) => (
        <div className="bar-row" key={k}>
          <span title={k}>{labels?.[k] || k}</span>
          <span className="bar-track"><span className={`bar-fill ${colorOf ? colorOf(k) : ""}`} style={{ width: `${(100 * v) / max}%`, display: "block" }} /></span>
          <span className="count">{v.toLocaleString("en-US")} · {total ? ((100 * v) / total).toFixed(1) : 0}%</span>
        </div>
      ))}
    </div>
  );
}

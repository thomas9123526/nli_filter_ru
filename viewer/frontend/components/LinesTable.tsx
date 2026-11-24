"use client";
// Decisions from any file of a dataset (Keywords and Review pages): open the text in place, go to the record,
// and label the line for the golden set (golden/<dataset>.jsonl: the corpus itself is never changed).
import Link from "next/link";
import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import { href, score } from "@/lib/format";
import type { LineRow, RecordResp } from "@/lib/types";
import { DecisionBadge, ReasonBadge } from "./ui";

export function LinesTable({ ds, rows, thresholds, onLabelled, testid }: {
  ds: string; rows: LineRow[]; thresholds?: { check1: number; check2: number };
  onLabelled?: () => void; testid?: string;
}) {
  const [open, setOpen] = useState<Record<string, RecordResp | "loading" | string>>({});
  const [labels, setLabels] = useState<Record<string, string | null>>({});
  const [err, setErr] = useState<string | null>(null);
  const keyOf = (r: LineRow) => `${r.file}#${r.row}`;

  async function toggle(r: LineRow) {
    const k = keyOf(r);
    if (open[k]) { const n = { ...open }; delete n[k]; setOpen(n); return; }
    setOpen((o) => ({ ...o, [k]: "loading" }));
    try {
      const rec = await api.record(ds, { file: r.file, row: r.row, max_chars: 4000 });
      setOpen((o) => ({ ...o, [k]: rec }));
    } catch (e) {
      setOpen((o) => ({ ...o, [k]: (e as Error).message }));
    }
  }
  async function label(r: LineRow, expect: string) {
    setErr(null);
    try {
      await api.setGolden(ds, { file: r.file, row: r.row, expect });
      setLabels((l) => ({ ...l, [`${r.file}#${r.line}`]: expect || null }));
      onLabelled?.();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : (e as Error).message);
    }
  }

  return (
    <div data-testid={testid}>
      {err ? <div className="alert warn">Label not saved: {err}</div> : null}
      <div className="table-wrap">
        <table className="lines-table">
          <thead>
            <tr>
              <th></th><th>file · line</th><th>id</th><th>decision</th><th>reason</th>
              <th className="num" title={thresholds ? `threshold ${thresholds.check1}` : undefined}>check 1</th>
              <th className="num" title={thresholds ? `threshold ${thresholds.check2}` : undefined}>check 2</th>
              <th>keywords</th><th>expect</th>
              <th title="golden set label (golden/<dataset>.jsonl; the corpus is not changed)">golden</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const k = keyOf(r), o = open[k];
              const g = `${r.file}#${r.line}` in labels ? labels[`${r.file}#${r.line}`] : r.golden;
              return [
                <tr key={k} className="hoverable">
                  <td><button className="btn small ghost" onClick={() => toggle(r)} title="show the text here">{o ? "▾" : "▸"}</button></td>
                  <td className="mono"><Link href={href("/filter/record", { ds, f: r.file, row: r.row })}>{r.file}</Link> · {r.line}</td>
                  <td className="mono">{r.id ?? "–"}</td>
                  <td><DecisionBadge decision={r.decision} />{r.audit ? <div className="faint" title="level-A audit: what the rules / models would decide">audit: {r.audit}</div> : null}</td>
                  <td><ReasonBadge reason={r.reason} /></td>
                  <td className="num mono">{score(r.c1)}</td>
                  <td className="num mono">{score(r.c2)}</td>
                  <td>{r.kws.map((w) => <span key={w} className="chip">{w}</span>)}</td>
                  <td>{r.expect ? <span className={r.ok === false ? "bad" : r.ok ? "ok" : ""}>{r.expect}{r.ok === false ? " ✗" : r.ok ? " ✓" : ""}</span> : <span className="faint">–</span>}</td>
                  <td className="golden-cell">
                    {(["filter", "keep"] as const).map((e) => (
                      <button key={e} className={`btn small${g === e ? (e === "filter" ? " lbl-filter" : " lbl-keep") : " ghost"}`}
                        onClick={() => label(r, g === e ? "" : e)} title={g === e ? "remove the label" : `label: ${e}`}
                        data-testid={`golden-${e}-${r.file}-${r.row}`}>{e}</button>
                    ))}
                  </td>
                </tr>,
                o ? (
                  <tr key={k + ":text"} className="line-preview">
                    <td></td>
                    <td colSpan={9}>
                      {o === "loading" ? <span className="faint">loading…</span>
                        : typeof o === "string" ? <span className="alert warn">{o}</span>
                          : <Preview rec={o} />}
                    </td>
                  </tr>
                ) : null,
              ];
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Preview({ rec }: { rec: RecordResp }) {
  const rcd = rec.original.record as Record<string, unknown> | undefined;
  const text = rcd ? rcd[rec.text_field] : null;
  return (
    <div className="preview">
      <div className="faint" style={{ fontSize: 12 }}>{rec.explanation.verdict.summary}</div>
      <ul className="faint" style={{ fontSize: 12, margin: "4px 0" }}>
        {rec.explanation.verdict.steps.map((s) => <li key={s}>{s}</li>)}
      </ul>
      {typeof text === "string"
        ? <div className="preview-text">{text.length > 3000 ? text.slice(0, 3000) + " …" : text}</div>
        : <span className="faint">{rec.original.error || "the text is not available"}</span>}
    </div>
  );
}

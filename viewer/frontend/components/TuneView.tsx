"use client";
// Threshold tuning: decisions recomputed from the stored scores with other thresholds (no model is run).
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api, useApi } from "@/lib/api";
import { href, num, score } from "@/lib/format";
import type { SimMetrics } from "@/lib/types";
import { Crumbs, DecisionBadge, ErrorBox, Loading, ReasonBadge, Stat } from "./ui";

function delta(a: number | null | undefined, b: number | null | undefined): string {
  if (a === null || a === undefined || b === null || b === undefined) return "";
  const d = b - a;
  if (Math.abs(d) < 0.0005) return "±0";
  return `${d > 0 ? "+" : ""}${d.toFixed(3)}`;
}

export function TuneView() {
  const sp = useSearchParams();
  const router = useRouter();
  const ds = sp.get("ds") || "";
  const t1 = sp.get("check1") || "";
  const t2 = sp.get("check2") || "";
  // first load without thresholds -> ask with the run's own (returned as "current")
  const base = useApi(ds && (!t1 || !t2) ? `simbase:${ds}` : null, (s) => api.simulate(ds, { check1: 0.8, check2: 0.8 }, s));
  useEffect(() => {
    if (base.data && (!t1 || !t2)) {
      router.replace(href("/filter/tune", { ds, check1: base.data.current.check1, check2: base.data.current.check2 }));
    }
  }, [base.data, t1, t2, ds, router]);
  const res = useApi(ds && t1 && t2 ? `sim:${ds}:${t1}:${t2}` : null, (s) => api.simulate(ds, { check1: t1, check2: t2, sweep: true }, s));
  const [d1, setD1] = useState(t1);
  const [d2, setD2] = useState(t2);
  useEffect(() => { setD1(t1); setD2(t2); }, [t1, t2]);
  useEffect(() => {  // apply slider changes after a short pause
    if (d1 === t1 && d2 === t2) return;
    const h = setTimeout(() => router.replace(href("/filter/tune", { ds, check1: d1, check2: d2 }), { scroll: false }), 250);
    return () => clearTimeout(h);
  }, [d1, d2, t1, t2, ds, router]);

  const r = res.data;
  if (!ds) return <div className="alert error">No dataset given (?ds=…)</div>;
  return (
    <>
      <div className="page-head">
        <div>
          <Crumbs items={[{ label: "Filter", href: "/filter" }, { label: ds, href: href("/filter/dataset", { ds }) }, { label: "Tune thresholds" }]} />
          <h1>Tune thresholds</h1>
          <div className="sub">Decisions recomputed from the scores stored in the decisions files. No model is run, so this is instant.</div>
        </div>
      </div>
      <ErrorBox error={res.error || base.error} onRetry={res.reload} />
      <div className="panel" style={{ marginBottom: 16 }}>
        <div className="grid cols-2">
          <Slider label="Check 1 threshold (about the country)" value={d1} onChange={setD1} current={r?.current.check1} />
          <Slider label="Check 2 threshold (only incidental)" value={d2} onChange={setD2} current={r?.current.check2} />
        </div>
        <p className="faint" style={{ marginBottom: 0 }}>
          Lines that were check-1 negative never went to check 2. If a lower check-1 threshold makes them positive, they
          count as filtered and are marked <span className="badge warn">estimated</span>: a real rerun could still rescue some
          with check 2. The judge only re-scored pairs in the run's uncertain band{r?.band ? ` (${r.band[0]}–${r.band[1]})` : ""},
          so thresholds far outside it are approximate too.
        </p>
      </div>
      {(res.loading || base.loading) && !r ? <Loading what="Reading the scores of every file" /> : null}
      {r ? (
        <>
          <div className="stats">
            <Stat label="Filtered" value={num(r.simulated.counts.filter)} note={`now ${num(r.current.counts.filter)} · ${delta(r.current.counts.filter, r.simulated.counts.filter).replace(".000", "")}`} />
            <Stat label="Kept → filtered" value={num(r.simulated.counts.to_filter)} note={`${num(r.simulated.counts.estimated)} estimated`} />
            <Stat label="Filtered → kept" value={num(r.simulated.counts.to_keep)} />
            {r.simulated.metrics ? <Stat label="Precision" value={score(r.simulated.metrics.precision)} note={`now ${score(r.current.metrics?.precision)} (${delta(r.current.metrics?.precision, r.simulated.metrics.precision)})`} /> : null}
            {r.simulated.metrics ? <Stat label="Recall" value={score(r.simulated.metrics.recall)} note={`now ${score(r.current.metrics?.recall)} (${delta(r.current.metrics?.recall, r.simulated.metrics.recall)})`} /> : null}
            {r.simulated.metrics ? <Stat label="F1" value={score(r.simulated.metrics.f1)} note={`now ${score(r.current.metrics?.f1)} (${delta(r.current.metrics?.f1, r.simulated.metrics.f1)})`} /> : null}
          </div>
          <div className="grid cols-2" style={{ marginBottom: 16 }}>
            <div className="panel flush">
              <div className="panel-head"><h2>Check-1 sweep</h2><span className="muted">check 2 fixed at {t2} · click a row to use it</span></div>
              <div className="table-wrap">
                <table>
                  <thead><tr><th className="num">Check 1</th><th className="num">Filtered</th><th className="num">Estimated</th>
                    {r.sweep[0]?.metrics ? <><th className="num">Precision</th><th className="num">Recall</th><th className="num">F1</th></> : null}</tr></thead>
                  <tbody>
                    {r.sweep.map((s) => (
                      <tr key={s.check1} className={`clickable${Math.abs(s.check1 - Number(t1)) < 1e-9 ? " active" : ""}`} onClick={() => setD1(String(s.check1))}>
                        <td className="num mono">{s.check1.toFixed(2)}</td>
                        <td className="num">{num(s.filter)}</td>
                        <td className="num">{s.estimated ? num(s.estimated) : <span className="faint">–</span>}</td>
                        {s.metrics ? <MetricCells m={s.metrics} /> : null}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="panel">
              <h2>Confusion (lines with an expected label)</h2>
              {r.simulated.metrics ? (
                <table>
                  <thead><tr><th></th><th className="num">Now</th><th className="num">Simulated</th></tr></thead>
                  <tbody>
                    {(["tp", "fp", "tn", "fn"] as const).map((k) => (
                      <tr key={k}><td>{{ tp: "Filtered, should be filtered (TP)", fp: "Filtered, should be kept (FP)", tn: "Kept, should be kept (TN)", fn: "Kept, should be filtered (FN)" }[k]}</td>
                        <td className="num">{r.current.metrics?.[k]}</td><td className="num">{r.simulated.metrics?.[k]}</td></tr>
                    ))}
                    <tr><td>Accuracy</td><td className="num">{score(r.current.metrics?.accuracy)}</td><td className="num">{score(r.simulated.metrics.accuracy)}</td></tr>
                  </tbody>
                </table>
              ) : <span className="muted">The lines have no expected label (“expect” field), so only the counts change.</span>}
            </div>
          </div>
          <div className="panel flush">
            <div className="panel-head"><h2>Lines that change</h2><span className="muted">{num(r.simulated.counts.to_filter + r.simulated.counts.to_keep)}{r.flips_truncated ? `, first ${r.flips.length} shown` : ""}</span></div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>File</th><th className="num">Line</th><th>Id</th><th>Now</th><th>Would be</th><th className="num">Check 1</th><th className="num">Check 2 (min)</th><th>Expected</th></tr></thead>
                <tbody>
                  {r.flips.map((f) => {
                    const link = href("/filter/record", { ds, f: f.file, row: f.row });
                    const right = f.expect ? f.expect.toLowerCase() === f.to : null;
                    return (
                      <tr key={`${f.file}:${f.row}`} className="clickable" onClick={() => router.push(link)}>
                        <td className="mono"><Link href={link} onClick={(e) => e.stopPropagation()}>{f.file}</Link></td>
                        <td className="num">{f.line}</td>
                        <td className="mono">{f.id ?? "–"}</td>
                        <td><DecisionBadge decision={f.from} /> <ReasonBadge reason={f.reason} /></td>
                        <td><DecisionBadge decision={f.to} />{f.estimated ? <span className="badge warn" style={{ marginLeft: 4 }}>estimated</span> : null}</td>
                        <td className="num mono">{score(f.c1)}</td>
                        <td className="num mono">{score(f.c2)}</td>
                        <td>{right === null ? <span className="faint">–</span> : right ? <span className="badge keep">better</span> : <span className="badge filter">worse</span>}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {r.flips.length === 0 ? <div className="empty">No decision changes with these thresholds.</div> : null}
            </div>
          </div>
        </>
      ) : null}
    </>
  );
}

function MetricCells({ m }: { m: SimMetrics }) {
  return <><td className="num mono">{score(m?.precision)}</td><td className="num mono">{score(m?.recall)}</td><td className="num mono">{score(m?.f1)}</td></>;
}

function Slider({ label, value, onChange, current }: { label: string; value: string; onChange: (v: string) => void; current?: number }) {
  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>{label}</strong>
        <span className="muted">run used {current ?? "–"}</span>
      </div>
      <div className="row">
        <input type="range" min="0.3" max="0.99" step="0.01" value={value || "0.8"} onChange={(e) => onChange(e.target.value)} style={{ flex: 1 }} aria-label={label} />
        <input type="number" min="0" max="1" step="0.01" value={value} onChange={(e) => onChange(e.target.value)} aria-label={`${label} value`} />
        {current !== undefined && Number(value) !== current ? <button className="btn small" onClick={() => onChange(String(current))}>Reset</button> : null}
      </div>
    </div>
  );
}

"use client";
// /label/kwstats/: keyword and marker statistics over a corpus (nli_label.py kwstats, no models). Without ?run: the
// scans and a start form; with ?run=<folder>: the rank-frequency chart, the term table, the heatmap of terms x units,
// the never-hit terms, the histograms, the co-occurring pairs and the written report. Charts are plain SVG; each one
// downloads as SVG or PNG. Guide: cmds/labeling/keyword_stats.md.
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, useApi } from "@/lib/api";
import { href, num } from "@/lib/format";
import { kw, type KwHeatmap, type KwOverview, type KwRankFreq } from "@/lib/kwstats";
import type { RunJob } from "@/lib/types";
import { CopyButton, Crumbs, ErrorBox, Loading, SortTh, Stat } from "./ui";

const DEFAULT_POLICY = "policy/russia_llm_policy_v2.json";
const KIND_COLOR: Record<string, string> = { keyword: "var(--accent)", marker: "var(--filter)", narrative: "var(--warn)" };
const kindColor = (k: string) => KIND_COLOR[k] || "var(--muted)";
const pctS = (x: number, d = 1) => `${(100 * x).toFixed(d)} %`;
const hoursS = (h: number) => (h * 3600 < 1 ? "< 1 s" : h * 3600 < 60 ? `${(h * 3600).toFixed(0)} s` : h < 1 ? `${(h * 60).toFixed(0)} min` : `${h.toFixed(1)} h`);

// ---- downloading a chart ------------------------------------------------------------------------------

/** A copy of the SVG with the computed colours / fonts written inline (CSS variables do not survive a download). */
function standalone(svg: SVGSVGElement): string {
  const clone = svg.cloneNode(true) as SVGSVGElement;
  const src = [svg, ...Array.from(svg.querySelectorAll("*"))] as Element[];
  const dst = [clone, ...Array.from(clone.querySelectorAll("*"))] as Element[];
  src.forEach((el, i) => {
    const cs = getComputedStyle(el);
    const d = dst[i] as SVGElement;
    for (const p of ["fill", "stroke", "stroke-width", "opacity", "fill-opacity", "font-size", "font-family", "font-weight", "text-anchor", "dominant-baseline"]) {
      const v = cs.getPropertyValue(p);
      if (v) d.style.setProperty(p, v);
    }
  });
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  const bg = getComputedStyle(document.body).getPropertyValue("--panel") || "#fff";
  const vb = svg.viewBox.baseVal;
  const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  rect.setAttribute("x", String(vb?.x || 0)); rect.setAttribute("y", String(vb?.y || 0));
  rect.setAttribute("width", String(vb?.width || svg.clientWidth)); rect.setAttribute("height", String(vb?.height || svg.clientHeight));
  rect.setAttribute("fill", bg.trim() || "#fff");
  clone.insertBefore(rect, clone.firstChild);
  return new XMLSerializer().serializeToString(clone);
}

function save(blob: Blob, name: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
}

function downloadSvg(svg: SVGSVGElement | null, name: string) {
  if (svg) save(new Blob([standalone(svg)], { type: "image/svg+xml" }), `${name}.svg`);
}

function downloadPng(svg: SVGSVGElement | null, name: string) {
  if (!svg) return;
  const vb = svg.viewBox.baseVal;
  const w = vb?.width || svg.clientWidth, h = vb?.height || svg.clientHeight;
  const img = new Image();
  img.onload = () => {
    const c = document.createElement("canvas");
    c.width = w * 2; c.height = h * 2;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    ctx.scale(2, 2);
    ctx.drawImage(img, 0, 0, w, h);
    c.toBlob((b) => { if (b) save(b, `${name}.png`); }, "image/png");
  };
  img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(standalone(svg));
}

function ChartPanel({ title, file, note, controls, children, testid }: {
  title: string; file: string; note?: ReactNode; controls?: ReactNode; children: (ref: React.RefObject<SVGSVGElement | null>) => ReactNode; testid?: string }) {
  const ref = useRef<SVGSVGElement | null>(null);
  return (
    <div className="panel" style={{ marginBottom: 16 }} data-testid={testid}>
      <div className="row" style={{ flexWrap: "wrap", marginBottom: 6 }}>
        <h2 style={{ margin: 0 }}>{title}</h2>
        {controls}
        <span className="spacer" />
        <button className="btn small ghost" onClick={() => downloadSvg(ref.current, file)} title="download the chart as SVG">SVG ↓</button>
        <button className="btn small ghost" onClick={() => downloadPng(ref.current, file)} title="download the chart as PNG">PNG ↓</button>
      </div>
      {note ? <div className="faint" style={{ fontSize: 12, marginBottom: 6 }}>{note}</div> : null}
      <div style={{ overflowX: "auto" }}>{children(ref)}</div>
    </div>
  );
}

function Legend({ kinds }: { kinds: string[] }) {
  return (
    <span className="row" style={{ gap: 10, fontSize: 12 }}>
      {kinds.map((k) => (
        <span key={k} className="row" style={{ gap: 4 }}>
          <svg width="10" height="10" aria-hidden><rect width="10" height="10" rx="2" style={{ fill: kindColor(k) }} /></svg>{k}
        </span>))}
    </span>
  );
}

// ---- rank-frequency -------------------------------------------------------------------------------

const logTicks = (max: number) => { const t = [1]; while (t[t.length - 1] * 10 <= max) t.push(t[t.length - 1] * 10); return t; };

function RankFreq({ d, svgRef, onPick }: { d: KwRankFreq; svgRef: React.RefObject<SVGSVGElement | null>; onPick: (id: number) => void }) {
  const [hover, setHover] = useState<number | null>(null);
  const n = d.hits.length;
  const W = 960, H = 300, L = 56, R = 16, T = 14, Bm = 40;
  const max = Math.max(1, ...d.hits);
  const lmax = Math.log10(max) || 1;
  const x = (i: number) => L + (n <= 1 ? 0 : (i / (n - 1)) * (W - L - R));
  const y = (v: number) => (v <= 0 ? H - Bm : H - Bm - 8 - (Math.log10(v) / lmax) * (H - Bm - T - 8));
  const firstZero = d.hits.findIndex((v) => v === 0);
  const path = useMemo(() => {
    const pts: string[] = [];
    const step = Math.max(1, Math.floor(n / 2000));
    for (let i = 0; i < n; i += step) pts.push(`${x(i).toFixed(1)},${y(d.hits[i]).toFixed(1)}`);
    if (n) pts.push(`${x(n - 1).toFixed(1)},${y(d.hits[n - 1]).toFixed(1)}`);
    return "M" + pts.join("L");
  }, [d]); // eslint-disable-line react-hooks/exhaustive-deps
  const move = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    const i = Math.round(((px - L) / (W - L - R)) * (n - 1));
    setHover(i >= 0 && i < n ? i : null);
  };
  const xt = [0, Math.floor((n - 1) / 4), Math.floor((n - 1) / 2), Math.floor((3 * (n - 1)) / 4), n - 1].filter((v, i, a) => v >= 0 && a.indexOf(v) === i);
  return (
    <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxWidth: W, minWidth: 560, display: "block" }} onMouseMove={move}
      onMouseLeave={() => setHover(null)} onClick={() => hover !== null && onPick(d.ids[hover])} role="img" aria-label="rank-frequency chart of every term">
      {logTicks(max).map((t) => (
        <g key={t}><line x1={L} x2={W - R} y1={y(t)} y2={y(t)} style={{ stroke: "var(--border)" }} strokeWidth={1} />
          <text x={L - 6} y={y(t)} textAnchor="end" dominantBaseline="middle" style={{ fill: "var(--muted)", fontSize: 11 }}>{num(t)}</text></g>))}
      <text x={L - 6} y={H - Bm} textAnchor="end" dominantBaseline="middle" style={{ fill: "var(--muted)", fontSize: 11 }}>0</text>
      {firstZero >= 0 ? <rect x={x(firstZero) - 1} y={T} width={Math.max(2, x(n - 1) - x(firstZero) + 2)} height={H - Bm - T} style={{ fill: "var(--filter-soft)" }} opacity={0.6} /> : null}
      {firstZero >= 0 ? <text x={x(firstZero) + 4} y={T + 10} style={{ fill: "var(--filter)", fontSize: 11 }}>never hit ({num(n - firstZero)})</text> : null}
      <path d={path} fill="none" style={{ stroke: "var(--accent)" }} strokeWidth={2} />
      {n <= 400 ? d.hits.map((v, i) => <circle key={i} cx={x(i)} cy={y(v)} r={2.5} style={{ fill: kindColor(d.kind[i]) }} />) : null}
      <line x1={L} x2={W - R} y1={H - Bm} y2={H - Bm} style={{ stroke: "var(--muted)" }} strokeWidth={1} />
      {xt.map((i) => <text key={i} x={x(i)} y={H - Bm + 16} textAnchor="middle" style={{ fill: "var(--muted)", fontSize: 11 }}>{num(i + 1)}</text>)}
      <text x={(L + W - R) / 2} y={H - 6} textAnchor="middle" style={{ fill: "var(--muted)", fontSize: 11 }}>rank (1 = most hits)</text>
      <text x={14} y={(T + H - Bm) / 2} textAnchor="middle" transform={`rotate(-90 14 ${(T + H - Bm) / 2})`} style={{ fill: "var(--muted)", fontSize: 11 }}>hits (log scale)</text>
      {hover !== null ? (<g pointerEvents="none">
        <line x1={x(hover)} x2={x(hover)} y1={T} y2={H - Bm} style={{ stroke: "var(--muted)" }} strokeDasharray="3 3" />
        <circle cx={x(hover)} cy={y(d.hits[hover])} r={5} style={{ fill: kindColor(d.kind[hover]), stroke: "var(--panel)" }} strokeWidth={2} />
        {(() => {
          const label = `#${hover + 1} ${d.terms[hover]} · ${num(d.hits[hover])} hits · ${d.kind[hover]} · ${d.lists[d.list[hover]]}`;
          const w = Math.min(420, 12 + label.length * 6.6);
          const lx = Math.min(W - R - w, Math.max(L, x(hover) + 8));
          return (<g><rect x={lx} y={T} width={w} height={22} rx={4} style={{ fill: "var(--panel)", stroke: "var(--border)" }} />
            <text x={lx + 6} y={T + 15} style={{ fill: "var(--text)", fontSize: 12 }}>{label}</text></g>);
        })()}
      </g>) : null}
    </svg>
  );
}

function TopBottomBars({ d, svgRef, onPick }: { d: KwRankFreq; svgRef: React.RefObject<SVGSVGElement | null>; onPick: (id: number) => void }) {
  const n = d.hits.length;
  const top = Array.from({ length: Math.min(50, n) }, (_, i) => i);
  const bottom = n > 50 ? Array.from({ length: Math.min(50, n - 50) }, (_, i) => n - Math.min(50, n - 50) + i) : [];
  const idx = [...top, ...(bottom.length ? [-1] : []), ...bottom];
  const W = Math.max(560, 60 + idx.length * 14), H = 300, L = 50, T = 12, Bm = 120;
  const max = Math.max(1, ...d.hits);
  const lmax = Math.log10(max + 1);
  const bw = (W - L - 10) / idx.length;
  const yh = (v: number) => (Math.log10(v + 1) / lmax) * (H - Bm - T);
  return (
    <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} width={W} height={H} style={{ display: "block" }} role="img" aria-label="hits of the top 50 and bottom 50 terms">
      {logTicks(max).map((t) => (
        <g key={t}><line x1={L} x2={W - 10} y1={H - Bm - yh(t)} y2={H - Bm - yh(t)} style={{ stroke: "var(--border)" }} />
          <text x={L - 6} y={H - Bm - yh(t)} textAnchor="end" dominantBaseline="middle" style={{ fill: "var(--muted)", fontSize: 10 }}>{num(t)}</text></g>))}
      {idx.map((i, k) => {
        const cx = L + k * bw;
        if (i < 0) return <text key="gap" x={cx + bw / 2} y={H - Bm - 4} textAnchor="middle" style={{ fill: "var(--muted)", fontSize: 11 }}>…</text>;
        const h = yh(d.hits[i]);
        return (
          <g key={i} style={{ cursor: "pointer" }} onClick={() => onPick(d.ids[i])}>
            <title>{`#${i + 1} ${d.terms[i]}: ${num(d.hits[i])} hits (${d.kind[i]}, ${d.lists[d.list[i]]})`}</title>
            <rect x={cx + 1} y={H - Bm - h} width={Math.max(1, bw - 2)} height={Math.max(h, 0)} rx={2} style={{ fill: kindColor(d.kind[i]) }} />
            {d.hits[i] === 0 ? <text x={cx + bw / 2} y={H - Bm - 3} textAnchor="middle" style={{ fill: "var(--filter)", fontSize: 9 }}>0</text> : null}
            <rect x={cx} y={T} width={bw} height={H - T} fill="transparent" />
            <text x={cx + bw / 2} y={H - Bm + 6} transform={`rotate(60 ${cx + bw / 2} ${H - Bm + 6})`} style={{ fill: "var(--text)", fontSize: 10 }}>
              {d.terms[i].length > 18 ? d.terms[i].slice(0, 17) + "…" : d.terms[i]}</text>
          </g>);
      })}
      <line x1={L} x2={W - 10} y1={H - Bm} y2={H - Bm} style={{ stroke: "var(--muted)" }} />
    </svg>
  );
}

// ---- histograms -------------------------------------------------------------------------------------

const BUCKETS: [string, (n: number) => boolean][] = [
  ["0", (n) => n === 0], ["1", (n) => n === 1], ["2", (n) => n === 2], ["3", (n) => n === 3], ["4", (n) => n === 4],
  ["5–9", (n) => n >= 5 && n <= 9], ["10–19", (n) => n >= 10 && n <= 19], ["20–49", (n) => n >= 20 && n <= 49],
  ["50–99", (n) => n >= 50 && n <= 99], ["100+", (n) => n >= 100]];

function bucketize(h: Record<string, number>): [string, number][] {
  const out = BUCKETS.map(([k]) => [k, 0] as [string, number]);
  for (const [k, v] of Object.entries(h || {})) {
    const n = k.endsWith("+") ? 100 : Number(k);
    const i = BUCKETS.findIndex(([, f]) => f(n));
    if (i >= 0) out[i][1] += v;
  }
  return out;
}

function Histogram({ data, svgRef, xLabel, skipZero }: { data: [string, number][]; svgRef: React.RefObject<SVGSVGElement | null>; xLabel: string; skipZero: boolean }) {
  const items = skipZero ? data.slice(1) : data;
  const W = 460, H = 220, L = 50, R = 10, T = 18, Bm = 40;
  const max = Math.max(1, ...items.map(([, v]) => v));
  const bw = (W - L - R) / items.length;
  const total = data.reduce((a, [, v]) => a + v, 0);
  return (
    <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxWidth: W, display: "block" }} role="img" aria-label={xLabel}>
      {[0, 0.5, 1].map((f) => (
        <g key={f}><line x1={L} x2={W - R} y1={H - Bm - f * (H - Bm - T)} y2={H - Bm - f * (H - Bm - T)} style={{ stroke: "var(--border)" }} />
          <text x={L - 6} y={H - Bm - f * (H - Bm - T)} textAnchor="end" dominantBaseline="middle" style={{ fill: "var(--muted)", fontSize: 10 }}>{num(Math.round(f * max))}</text></g>))}
      {items.map(([k, v], i) => {
        const h = (v / max) * (H - Bm - T);
        return (<g key={k}>
          <title>{`${k}: ${num(v)} lines (${total ? ((100 * v) / total).toFixed(1) : 0} %)`}</title>
          <rect x={L + i * bw + 2} y={H - Bm - h} width={bw - 4} height={h} rx={2} style={{ fill: "var(--accent)" }} />
          {v ? <text x={L + i * bw + bw / 2} y={H - Bm - h - 4} textAnchor="middle" style={{ fill: "var(--text)", fontSize: 10 }}>{num(v)}</text> : null}
          <text x={L + i * bw + bw / 2} y={H - Bm + 14} textAnchor="middle" style={{ fill: "var(--muted)", fontSize: 10.5 }}>{k}</text>
        </g>);
      })}
      <line x1={L} x2={W - R} y1={H - Bm} y2={H - Bm} style={{ stroke: "var(--muted)" }} />
      <text x={(L + W - R) / 2} y={H - 6} textAnchor="middle" style={{ fill: "var(--muted)", fontSize: 11 }}>{xLabel}</text>
    </svg>
  );
}

// ---- heatmap ----------------------------------------------------------------------------------------

function Heatmap({ d, svgRef, onPick }: { d: KwHeatmap; svgRef: React.RefObject<SVGSVGElement | null>; onPick: (id: number) => void }) {
  const cw = Math.max(34, Math.min(70, Math.floor(760 / Math.max(1, d.units.length)))), ch = 20, L = 170, T = 110;
  const W = L + d.units.length * cw + 10, H = T + d.terms.length * ch + 10;
  const max = Math.max(1e-9, ...d.terms.flatMap((t) => t.cells));
  const fmt = (v: number) => (d.norm === "per1k" ? v.toFixed(v < 10 ? 1 : 0) : num(v));
  return (
    <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} width={W} height={H} style={{ display: "block" }} role="img" aria-label="heatmap of terms by unit">
      <defs><pattern id="kw-zero" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <line x1="0" y1="0" x2="0" y2="6" style={{ stroke: "var(--border)" }} strokeWidth={2} /></pattern></defs>
      {d.units.map((u, j) => (
        <text key={u} x={L + j * cw + cw / 2} y={T - 6} transform={`rotate(-50 ${L + j * cw + cw / 2} ${T - 6})`} style={{ fill: "var(--text)", fontSize: 11 }}>
          <title>{`${u}: ${num(d.unit_lines[j])} lines, ${num(d.unit_gated[j])} gated`}</title>{u.length > 22 ? u.slice(0, 21) + "…" : u}</text>))}
      {d.terms.map((t, i) => (
        <g key={t.id}>
          <text x={L - 8} y={T + i * ch + ch / 2} textAnchor="end" dominantBaseline="middle" style={{ fill: kindColor(t.kind), fontSize: 11, cursor: "pointer" }} onClick={() => onPick(t.id)}>
            <title>{`${t.term}: ${num(t.hits)} hits (${t.kind}, ${t.list})`}</title>{t.term.length > 24 ? t.term.slice(0, 23) + "…" : t.term}</text>
          {t.cells.map((v, j) => (
            <g key={j}>
              <title>{`${t.term} × ${d.units[j]}: ${fmt(v)}${d.norm === "per1k" ? " hits per 1,000 lines" : " hits"}`}</title>
              {v === 0
                ? <rect x={L + j * cw + 1} y={T + i * ch + 1} width={cw - 2} height={ch - 2} fill="url(#kw-zero)" style={{ stroke: "var(--border)" }} strokeWidth={0.5} />
                : <rect x={L + j * cw + 1} y={T + i * ch + 1} width={cw - 2} height={ch - 2} rx={2} style={{ fill: "var(--accent)" }} fillOpacity={0.12 + 0.88 * Math.sqrt(v / max)} />}
              <text x={L + j * cw + cw / 2} y={T + i * ch + ch / 2} textAnchor="middle" dominantBaseline="middle"
                style={{ fill: v === 0 ? "var(--faint)" : Math.sqrt(v / max) > 0.55 ? "var(--panel)" : "var(--text)", fontSize: 10 }}>{v === 0 ? "0" : fmt(v)}</text>
            </g>))}
        </g>))}
    </svg>
  );
}

// ---- start form ---------------------------------------------------------------------------------------

export function KwstatsStartForm({ onDone }: { onDone?: () => void }) {
  const form = useApi("kwform", (s) => kw.form(s));
  const [corpus, setCorpus] = useState("dataset/corpus_benchmark");
  const [policy, setPolicy] = useState(DEFAULT_POLICY);
  const [out, setOut] = useState("");
  const [topic, setTopic] = useState("");
  const [groupBy, setGroupBy] = useState("folder");
  const [limit, setLimit] = useState("");
  const [job, setJob] = useState<RunJob | null>(null);
  const [run, setRun] = useState<string | null>(null);
  const [err, setErr] = useState<Error | null>(null);
  const base = corpus.replace(/[\\/]+$/, "").split(/[\\/]/).pop()?.split(".")[0] || "corpus";
  const outName = out.trim() || `kwstats_${base}`;
  const cmd = `python nli_label.py kwstats ${corpus} --policy ${policy} --output-dir dataset/${outName} --group-by ${groupBy}`
    + (topic.trim() ? ` --topic-field ${topic.trim()}` : "") + (Number(limit) > 0 ? ` --limit ${Math.floor(Number(limit))}` : "");
  useEffect(() => {
    if (!job || job.state !== "running") return;
    const t = setInterval(() => { api.run(job.id).then((j) => { setJob(j); if (j.state !== "running") onDone?.(); }).catch(() => undefined); }, 2000);
    return () => clearInterval(t);
  }, [job, onDone]);
  const start = async () => {
    setErr(null);
    try {
      const r = await kw.start({ corpus, policy, output_dir: outName, topic_field: topic.trim() || undefined, group_by: groupBy,
        limit: Number(limit) > 0 ? Math.floor(Number(limit)) : null });
      setJob(r.job); setRun(r.run);
    } catch (e) { setErr(e as Error); }
  };
  const corpora = form.data?.corpora || [];
  return (
    <div className="panel" data-testid="kwstats-start">
      <div className="row" style={{ flexWrap: "wrap" }}><strong>Keyword statistics of a corpus</strong>
        <span className="faint" style={{ fontSize: 12 }}>no models, CPU only: which terms hit, how often, where, and a GPU-time forecast.
          Runs through the model service (<code className="mono">python nli_playground.py --no-models</code> is enough).</span></div>
      <div className="start-grid">
        <label className="pfield"><span className="pfield-label">corpus</span>
          <select value={corpus} onChange={(e) => setCorpus(e.target.value)} data-testid="kwstats-corpus">
            {corpora.map((c) => <option key={c.path} value={c.path}>{c.path} ({c.files} file{c.files === 1 ? "" : "s"})</option>)}
            {!corpora.some((c) => c.path === corpus) ? <option value={corpus}>{corpus}</option> : null}
          </select></label>
        <label className="pfield"><span className="pfield-label">policy</span>
          <select value={policy} onChange={(e) => setPolicy(e.target.value)}>
            {[...new Set([DEFAULT_POLICY, ...(form.data?.policies || [])])].map((p) => <option key={p} value={p}>{p}</option>)}</select></label>
        <label className="pfield"><span className="pfield-label">output folder (in dataset/)</span>
          <input type="text" className="mono" placeholder={outName} value={out} onChange={(e) => setOut(e.target.value)} /></label>
        <label className="pfield"><span className="pfield-label">topic field</span>
          <input type="text" placeholder="(none) e.g. case" value={topic} onChange={(e) => setTopic(e.target.value)} />
          <span className="pfield-help">a field per line used as the topic unit</span></label>
        <label className="pfield"><span className="pfield-label">units</span>
          <select value={groupBy} onChange={(e) => setGroupBy(e.target.value)}><option value="folder">by folder</option><option value="file">by file</option></select></label>
        <label className="pfield"><span className="pfield-label">--limit</span>
          <input type="number" min={0} placeholder="all lines" value={limit} onChange={(e) => setLimit(e.target.value)} />
          <span className="pfield-help">lines per file</span></label>
      </div>
      <div className="row" style={{ marginTop: 8, flexWrap: "wrap" }}>
        <code className="mono" style={{ fontSize: 12, flex: "1 1 500px" }} data-testid="kwstats-command">{cmd}</code>
        <CopyButton text={cmd} />
        <button className="btn primary small" onClick={start} disabled={job?.state === "running"} data-testid="kwstats-start-button">Start scan</button>
      </div>
      <ErrorBox error={err} />
      {job ? (
        <div style={{ marginTop: 8 }}>
          <div className="row">
            <span className={`badge ${job.state === "done" ? "keep" : job.state === "running" ? "accent" : "filter"}`}>{job.state} · {job.seconds}s</span>
            {job.state === "done" && run ? <Link className="btn small primary" href={href("/label/kwstats", { run })}>open {run} →</Link> : null}
          </div>
          <pre className="mono" style={{ maxHeight: 200, overflow: "auto", fontSize: 12, marginTop: 6 }}>{job.output.slice(-30).join("\n") || "(no output yet)"}</pre>
        </div>) : null}
    </div>
  );
}

// ---- the list of scans ----------------------------------------------------------------------------------

function KwstatsList() {
  const [tick, setTick] = useState(0);
  const runs = useApi(`kwruns:${tick}`, (s) => kw.runs(s));
  return (<>
    <div className="page-head"><div>
      <Crumbs items={[{ label: "Labelling", href: "/label" }, { label: "Keyword statistics" }]} />
      <h1>Keyword statistics</h1>
      <div className="sub">Scans made with <code className="mono">nli_label.py kwstats</code>: every keyword and marker of a policy counted over a corpus,
        with the same matcher and cheap rules as a run. Guide: cmds\labeling\keyword_stats.md.</div>
    </div></div>
    <KwstatsStartForm onDone={() => setTick((t) => t + 1)} />
    <ErrorBox error={runs.error} onRetry={runs.reload} />
    {runs.loading && !runs.data ? <Loading what="Finding scans" /> : null}
    {runs.data ? (
      <div className="panel flush" style={{ marginTop: 16 }}>
        <div className="table-wrap"><table data-testid="kwstats-runs">
          <thead><tr><th>Scan</th><th>Corpus</th><th className="right">Lines</th><th className="right">Gated</th><th className="right">Terms hit</th><th>Made</th></tr></thead>
          <tbody>{runs.data.runs.map((r) => (
            <tr key={r.name}>
              <td>{r.complete ? <Link href={href("/label/kwstats", { run: r.name })}><strong>{r.name}</strong></Link> : <strong>{r.name}</strong>}
                {!r.complete ? <span className="badge warn" style={{ marginLeft: 6 }}>{r.parts} shard part(s), not merged</span> : null}
                <div className="faint mono" style={{ fontSize: 11 }}>{r.policy || ""}</div></td>
              <td className="mono" style={{ fontSize: 12 }}>{(r.inputs || []).join(" ")}</td>
              <td className="right">{num(r.lines)}</td>
              <td className="right">{r.lines ? `${num(r.lines_gated)} (${pctS((r.lines_gated || 0) / r.lines)})` : "–"}</td>
              <td className="right">{r.terms ? `${num(r.terms_hit)} / ${num(r.terms)}` : "–"}</td>
              <td className="faint">{r.created || r.error || ""}</td>
            </tr>))}</tbody>
        </table></div>
        {runs.data.runs.length === 0 ? <div className="empty">No keyword statistics yet: start a scan above.</div> : null}
      </div>) : null}
  </>);
}

// ---- one scan ---------------------------------------------------------------------------------------------

const PAGE = 50;

function TermDetail({ run, id, dims, onPick, onClose }: { run: string; id: number; dims: string[]; onPick: (id: number) => void; onClose: () => void }) {
  const [dim, setDim] = useState(dims[0] || "");
  const t = useApi(`kwterm:${run}:${id}:${dim}`, (s) => kw.term(run, id, { dim }, s));
  const d = t.data;
  const units = d ? Object.entries(d.units).sort((a, b) => b[1][0] - a[1][0]) : [];
  return (
    <div className="panel" style={{ marginBottom: 16 }} data-testid="kwstats-term">
      <div className="row" style={{ flexWrap: "wrap" }}>
        <h2 style={{ margin: 0 }}>{d ? d.term : "…"}</h2>
        {d ? <span className="badge neutral">{d.kind} · {d.list}</span> : null}
        {dims.length > 1 ? <span className="seg">{dims.map((x) => <button key={x} className={dim === x ? "on" : ""} onClick={() => setDim(x)}>{x}</button>)}</span> : null}
        <span className="spacer" /><button className="btn small ghost" onClick={onClose}>close ✕</button>
      </div>
      <ErrorBox error={t.error} />
      {d ? (<div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", marginTop: 8 }}>
        <div>
          <div className="faint" style={{ fontSize: 12 }}>rank {d.rank} · {num(d.hits)} hits ({num(d.incidental)} incidental) · {num(d.lines)} lines ({pctS(d.line_share, 2)}) ·
            {" "}{num(d.gate_lines)} gated lines · {num(d.paragraphs)} paragraphs · {num(d.sentences)} sentences · {num(d.files)} files</div>
          <table style={{ marginTop: 6 }}><thead><tr><th>{d.dim}</th><th className="right">Hits</th><th className="right">Lines</th></tr></thead>
            <tbody>{units.map(([u, [h, l]]) => <tr key={u}><td>{u}</td><td className="right">{num(h)}</td><td className="right">{num(l)}</td></tr>)}</tbody></table>
          {!units.length ? <div className="faint">No hits.</div> : null}
        </div>
        <div><strong style={{ fontSize: 13 }}>Co-occurring terms</strong> <span className="faint" style={{ fontSize: 12 }}>(same paragraph)</span>
          <div style={{ marginTop: 4 }}>{d.pairs.length ? d.pairs.map((p) => (
            <button key={p.id} className="chip linklike" onClick={() => onPick(p.id)}>{p.term} ×{p.n}</button>)) : <span className="faint">none</span>}</div></div>
      </div>) : <Loading />}
    </div>
  );
}

function ScanView({ run }: { run: string }) {
  const [depth, setDepth] = useState(0);
  const ov = useApi(`kwov:${run}:${depth}`, (s) => kw.overview(run, { depth }, s));
  const rf = useApi(`kwrf:${run}`, (s) => kw.rankfreq(run, s));
  const o = ov.data;
  const [pick, setPick] = useState<number | null>(null);
  const pickTerm = (id: number) => { setPick(id); setTimeout(() => document.getElementById("kw-term-anchor")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50); };
  if (ov.error) return <ErrorBox error={ov.error} onRetry={ov.reload} />;
  if (!o) return <Loading what="Loading the statistics" />;
  const tot = o.totals;
  const f = o.forecast;
  return (<>
    <div className="page-head"><div>
      <Crumbs items={[{ label: "Labelling", href: "/label" }, { label: "Keyword statistics", href: "/label/kwstats" }, { label: run }]} />
      <h1>{run}</h1>
      <div className="sub mono" style={{ fontSize: 12 }}>{String(o.settings.command || "")}</div>
      <div className="faint" style={{ fontSize: 12 }}>policy {o.policy} · made {o.created} · {num(o.files)} files{o.settings.limit ? ` · first ${o.settings.limit} lines per file` : ""}
        {" "}· <a href={kw.url(run, "/report.md")} download={`${run}_report.md`}>report.md ↓</a></div>
    </div></div>

    <div className="stats">
      <Stat label="Lines" value={num(tot.lines_text)} note={`${num(tot.paragraphs)} paragraphs · ${num(tot.sentences)} sentences`} />
      <Stat label="Lines gated" value={num(tot.lines_gated)} note={`${pctS((tot.lines_gated || 0) / Math.max(1, tot.lines_text))} · any hit ${num(tot.lines_with_hit)}`} />
      <Stat label="Terms hit" value={`${num(o.concentration.terms_hit)} / ${num(o.n_terms)}`} note={`${num(o.never_hit)} never hit`} />
      <Stat label="Top 10 terms" value={pctS(o.concentration.top10)} note={`of ${num((tot.keyword_hits || 0) + (tot.marker_hits || 0) + (tot.narrative_hits || 0))} hits`} />
      <Stat label="Paragraphs to label" value={num(tot.paragraphs_candidate)} note={`${num(f.pairs_low)}–${num(f.pairs_high)} model pairs`} />
      <Stat label="GPU time" value={`${hoursS(f.hours_high[0])} – ${hoursS(f.hours_high[1])}`} note={`${f.gpus} GPUs, ${num(f.pairs_per_second[0])}–${num(f.pairs_per_second[1])} pairs/s each`} />
    </div>

    <div className="panel" style={{ marginBottom: 16 }} data-testid="kwstats-report">
      <div className="row"><h2 style={{ margin: 0 }}>Report</h2><span className="faint" style={{ fontSize: 12 }}>generated from the numbers; the same as report.md</span>
        <span className="spacer" /><CopyButton text={o.report_md} label="Copy as Markdown" /></div>
      {o.report.map((it) => (
        <div key={it.key} style={{ marginTop: 10 }}>
          <strong>{it.title}</strong>
          <ul style={{ margin: "4px 0 0 18px", padding: 0 }}>{it.lines.map((l, i) => <li key={i} style={{ fontSize: 13, marginBottom: 2 }}>{l}</li>)}</ul>
        </div>))}
    </div>

    <ChartPanel title="Rank-frequency" file={`${run}_rank_frequency`} testid="kwstats-rankfreq"
      note={<>every term by rank, hits on a log scale; hover shows the term, a click opens it. <Legend kinds={o.kinds} /></>}>
      {(ref) => rf.data ? <RankFreq d={rf.data} svgRef={ref} onPick={pickTerm} /> : <Loading />}
    </ChartPanel>
    <ChartPanel title="Top 50 and bottom 50 terms" file={`${run}_top_bottom`} note={<>hits per term (log scale). <Legend kinds={o.kinds} /></>}>
      {(ref) => rf.data ? <TopBottomBars d={rf.data} svgRef={ref} onPick={pickTerm} /> : <Loading />}
    </ChartPanel>

    <div id="kw-term-anchor" />
    {pick !== null ? <TermDetail run={run} id={pick} dims={o.dims} onPick={pickTerm} onClose={() => setPick(null)} /> : null}

    <TermTable run={run} o={o} onPick={pickTerm} />
    <HeatmapPanel run={run} o={o} onPick={pickTerm} depth={depth} setDepth={setDepth} />
    <NeverPanel run={run} o={o} depth={depth} />
    <HistPanel run={run} o={o} />
    <PairsPanel run={run} o={o} onPick={pickTerm} />
  </>);
}

function TermTable({ run, o, onPick }: { run: string; o: KwOverview; onPick: (id: number) => void }) {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [list, setList] = useState("");
  const [hit, setHit] = useState("");
  const [sort, setSort] = useState("rank");
  const [desc, setDesc] = useState(false);
  const [offset, setOffset] = useState(0);
  const p = { q, kind, list, hit, sort, desc, offset, limit: PAGE };
  const res = useApi(`kwterms:${run}:${JSON.stringify(p)}`, (s) => kw.terms(run, p, s));
  const r = res.data;
  const onSort = (c: string) => { if (c === sort) setDesc(!desc); else { setSort(c); setDesc(!["rank", "term", "kind", "list"].includes(c)); } setOffset(0); };
  const th = (c: string, label: string, n = true) => <SortTh col={c} label={label} sort={sort} desc={desc} onSort={onSort} num={n} />;
  return (
    <div className="panel flush" style={{ marginBottom: 16 }} data-testid="kwstats-terms">
      <div className="panel-head" style={{ flexWrap: "wrap" }}>
        <h2>Terms</h2>
        <input type="search" placeholder="search terms" value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} data-testid="kwstats-search" />
        <select value={kind} onChange={(e) => { setKind(e.target.value); setOffset(0); }}><option value="">every kind</option>{o.kinds.map((k) => <option key={k}>{k}</option>)}</select>
        <select value={list} onChange={(e) => { setList(e.target.value); setOffset(0); }}><option value="">every list</option>{o.lists.map((k) => <option key={k}>{k}</option>)}</select>
        <select value={hit} onChange={(e) => { setHit(e.target.value); setOffset(0); }}><option value="">hit or not</option><option value="hit">hit</option><option value="never">never hit</option></select>
        <span className="faint" style={{ fontSize: 12 }}>{r ? `${num(r.total)} terms` : ""}</span>
        <span className="spacer" />
        <a className="btn small" href={kw.url(run, "/terms", { q, kind, list, hit, sort, desc, format: "csv" })} download>CSV ↓</a>
      </div>
      <ErrorBox error={res.error} onRetry={res.reload} />
      {r ? (<div className="table-wrap"><table>
        <thead><tr>{th("rank", "#")}{th("term", "Term", false)}{th("kind", "Kind", false)}{th("list", "List", false)}{th("hits", "Hits")}{th("incidental", "Incid.")}
          {th("lines", "Lines")}{th("line_share", "Share")}{th("gate_lines", "Gated")}{th("paragraphs", "Paras")}{th("sentences", "Sents")}{th("files", "Files")}{th("units_hit", "Units")}<th>Co-occurring</th></tr></thead>
        <tbody>{r.rows.map((t) => (
          <tr key={t.id}>
            <td className="right faint">{t.rank}</td>
            <td><button className="linklike" onClick={() => onPick(t.id)}>{t.term}</button></td>
            <td><span className="row" style={{ gap: 4 }}><svg width="8" height="8" aria-hidden><rect width="8" height="8" rx="2" style={{ fill: kindColor(t.kind) }} /></svg>{t.kind}</span></td>
            <td className="faint">{t.list}</td>
            <td className="right">{t.hits ? num(t.hits) : <span className="badge filter">0</span>}</td>
            <td className="right">{t.incidental ? `${num(t.incidental)} (${pctS(t.incidental_share, 0)})` : "–"}</td>
            <td className="right">{num(t.lines)}</td>
            <td className="right">{t.lines ? pctS(t.line_share, 2) : "–"}</td>
            <td className="right">{num(t.gate_lines)}</td>
            <td className="right">{num(t.paragraphs)}</td>
            <td className="right">{num(t.sentences)}</td>
            <td className="right">{num(t.files)}</td>
            <td className="right">{num(t.units_hit)}</td>
            <td>{t.co.map((c) => <button key={c.id} className="chip linklike" onClick={() => onPick(c.id)}>{c.term} ×{c.n}</button>)}</td>
          </tr>))}</tbody>
      </table></div>) : <Loading />}
      {r && r.total > PAGE ? (
        <div className="pager">
          <button className="btn small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>← previous</button>
          <span>{offset + 1}–{Math.min(offset + PAGE, r.total)} of {num(r.total)}</span>
          <button className="btn small" disabled={offset + PAGE >= r.total} onClick={() => setOffset(offset + PAGE)}>next →</button>
        </div>) : null}
    </div>
  );
}

function DimControls({ o, dim, setDim, depth, setDepth }: { o: KwOverview; dim: string; setDim: (d: string) => void; depth: number; setDepth: (n: number) => void }) {
  const folderDepth = Math.max(1, ...Object.keys(o.units.folder || {}).map((u) => u.split("/").length));
  return (<>
    {o.dims.length > 1 ? <span className="seg">{o.dims.map((x) => <button key={x} className={dim === x ? "on" : ""} onClick={() => setDim(x)}>{x}</button>)}</span> : null}
    {dim === "folder" && folderDepth > 1 ? (
      <span className="seg" title="folder level: 1 = the top folder (e.g. the side), all = the whole sub-folder">
        {Array.from({ length: folderDepth }, (_, i) => i + 1).map((n) => <button key={n} className={depth === n ? "on" : ""} onClick={() => setDepth(n)}>level {n}</button>)}
        <button className={depth === 0 ? "on" : ""} onClick={() => setDepth(0)}>all</button></span>) : null}
  </>);
}

function HeatmapPanel({ run, o, onPick, depth, setDepth }: { run: string; o: KwOverview; onPick: (id: number) => void; depth: number; setDepth: (n: number) => void }) {
  const [dim, setDim] = useState(String(o.settings.group_by || o.dims[0] || "folder"));
  const [top, setTop] = useState(30);
  const [q, setQ] = useState("");
  const [norm, setNorm] = useState("hits");
  const p = { dim, depth, top, q, norm };
  const h = useApi(o.dims.length ? `kwheat:${run}:${JSON.stringify(p)}` : null, (s) => kw.heatmap(run, p, s));
  return (
    <ChartPanel title="Heatmap: terms × units" file={`${run}_heatmap_${dim}`} testid="kwstats-heatmap"
      controls={<>
        <DimControls o={o} dim={dim} setDim={setDim} depth={depth} setDepth={setDepth} />
        <select value={top} onChange={(e) => setTop(Number(e.target.value))}>{[20, 30, 50, 100, 200].map((n) => <option key={n} value={n}>top {n}</option>)}</select>
        <input type="search" placeholder="filter terms" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 130 }} />
        <span className="seg"><button className={norm === "hits" ? "on" : ""} onClick={() => setNorm("hits")}>hits</button>
          <button className={norm === "per1k" ? "on" : ""} onClick={() => setNorm("per1k")}>per 1,000 lines</button></span></>}
      note="the most frequent terms (or the filtered ones) by unit; hatched cells with 0 = no hit in that unit; a click on a term opens it">
      {(ref) => h.error ? <ErrorBox error={h.error} /> : h.data ? (h.data.terms.length ? <Heatmap d={h.data} svgRef={ref} onPick={onPick} /> : <div className="empty">No term with hits matches.</div>) : <Loading />}
    </ChartPanel>
  );
}

function NeverPanel({ run, o, depth }: { run: string; o: KwOverview; depth: number }) {
  const [dim, setDim] = useState(String(o.settings.group_by || o.dims[0] || "folder"));
  const [unit, setUnit] = useState("");
  const [q, setQ] = useState("");
  const p = { dim, unit, depth, q };
  const n = useApi(`kwnever:${run}:${JSON.stringify(p)}`, (s) => kw.never(run, p, s));
  const units = Object.keys(o.units[dim] || {}).sort();
  useEffect(() => { setUnit(""); }, [dim, depth]);
  return (
    <div className="panel" style={{ marginBottom: 16 }} data-testid="kwstats-never">
      <div className="row" style={{ flexWrap: "wrap" }}>
        <h2 style={{ margin: 0 }}>Never-hit terms</h2>
        {o.dims.length > 1 ? <span className="seg">{o.dims.map((x) => <button key={x} className={dim === x ? "on" : ""} onClick={() => setDim(x)}>{x}</button>)}</span> : null}
        <select value={unit} onChange={(e) => setUnit(e.target.value)} data-testid="kwstats-never-unit">
          <option value="">overall ({num(o.never_hit)})</option>
          {units.map((u) => <option key={u} value={u}>in {u}{n.data?.per_unit[u] !== undefined ? ` (${num(n.data.per_unit[u])})` : ""}</option>)}
        </select>
        <input type="search" placeholder="filter" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 130 }} />
        <span className="faint" style={{ fontSize: 12 }}>{n.data ? `${num(n.data.total)} terms` : ""}</span>
        <span className="spacer" />
        <a className="btn small" href={kw.url(run, "/never", { ...p, format: "csv" })} download>CSV ↓</a>
      </div>
      <ErrorBox error={n.error} />
      {n.data ? (<div style={{ marginTop: 8, maxHeight: 260, overflow: "auto" }}>
        {n.data.rows.map((t) => <span key={t.id} className="chip" title={`${t.kind}, ${t.list}${unit ? `; ${t.hits} hits overall` : ""}`}>{t.term}{unit && t.hits ? <span className="faint"> ({num(t.hits)})</span> : null}</span>)}
        {n.data.total > n.data.rows.length ? <div className="faint">… {num(n.data.total - n.data.rows.length)} more in the CSV</div> : null}
        {!n.data.total ? <span className="faint">none</span> : null}
      </div>) : <Loading />}
    </div>
  );
}

function HistPanel({ run, o }: { run: string; o: KwOverview }) {
  const [skip, setSkip] = useState(true);
  const a = bucketize(o.hist.hits_per_line), b = bucketize(o.hist.terms_per_line);
  const toggle = <label className="faint" style={{ fontSize: 12 }}><input type="checkbox" checked={skip} onChange={(e) => setSkip(e.target.checked)} /> hide lines without a hit ({num(a[0][1])})</label>;
  return (
    <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(420px, 1fr))" }} data-testid="kwstats-hist">
      <ChartPanel title="Hits per line" file={`${run}_hits_per_line`} controls={toggle}>
        {(ref) => <Histogram data={a} svgRef={ref} xLabel="hits in the line (keywords, markers, narrative words)" skipZero={skip} />}
      </ChartPanel>
      <ChartPanel title="Distinct terms per line" file={`${run}_terms_per_line`}>
        {(ref) => <Histogram data={b} svgRef={ref} xLabel="different terms in the line" skipZero={skip} />}
      </ChartPanel>
    </div>
  );
}

function PairsPanel({ run, o, onPick }: { run: string; o: KwOverview; onPick: (id: number) => void }) {
  const [q, setQ] = useState("");
  const res = useApi(`kwpairs:${run}:${q}`, (s) => kw.pairs(run, { q, limit: 100 }, s));
  const rows = res.data?.rows || [];
  const max = Math.max(1, ...rows.map((r) => r.n));
  return (
    <div className="panel" style={{ marginBottom: 16 }} data-testid="kwstats-pairs">
      <div className="row" style={{ flexWrap: "wrap" }}>
        <h2 style={{ margin: 0 }}>Co-occurring pairs</h2>
        <span className="faint" style={{ fontSize: 12 }}>two terms in the same paragraph; {num(o.pairs_total)} different pairs, the top {num(res.data?.stored || 0)} kept</span>
        <input type="search" placeholder="pairs with this term" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 170 }} />
      </div>
      <ErrorBox error={res.error} />
      <div className="bars" style={{ marginTop: 8 }}>
        {rows.map((r) => (
          <div className="bar-row" key={`${r.a_id}-${r.b_id}`}>
            <span><button className="linklike" onClick={() => onPick(r.a_id)}>{r.a}</button> + <button className="linklike" onClick={() => onPick(r.b_id)}>{r.b}</button></span>
            <span className="bar-track"><span className="bar-fill" style={{ width: `${(100 * r.n) / max}%`, display: "block" }} /></span>
            <span className="count">{num(r.n)} paragraphs</span>
          </div>))}
        {!rows.length && res.data ? <span className="faint">No pairs.</span> : null}
      </div>
      {o.duplicates.length || o.overlaps.length ? (
        <div style={{ marginTop: 12, fontSize: 13 }}>
          {o.duplicates.length ? <div><strong>Listed twice:</strong> {o.duplicates.map((d) => <span key={d.term} className="chip" title={d.places.join(", ")}>{d.term}</span>)}</div> : null}
          {o.overlaps.length ? <div style={{ marginTop: 4 }}><strong>Overlaps</strong> <span className="faint">(inner term in a longer one; {num(o.n_overlaps)})</span>: {o.overlaps.slice(0, 60).map((x) => <span key={`${x.inner_id}-${x.outer_id}`} className="chip">{x.inner} ⊂ {x.outer}</span>)}</div> : null}
        </div>) : null}
    </div>
  );
}

export function KwstatsView() {
  const sp = useSearchParams();
  const run = sp.get("run");
  return run ? <ScanView key={run} run={run} /> : <KwstatsList />;
}

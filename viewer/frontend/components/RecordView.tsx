"use client";
// One decision next to its original line: verdict, highlighted text, check-1 / check-2 scores, models, raw JSON.
// Keyboard: j / → next match, k / ← previous match, Esc back to the list.
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api, useApi } from "@/lib/api";
import { RULE_LABEL, href, pickFilters, score } from "@/lib/format";
import type { RecordResp } from "@/lib/types";
import { HighlightedText, Legend, initialFocus, type Focus, type TextOptions } from "./HighlightedText";
import { CopyButton, Crumbs, DecisionBadge, ErrorBox, Loading, ReasonBadge, ScoreBar } from "./ui";

export function RecordView() {
  const sp = useSearchParams();
  const router = useRouter();
  const ds = sp.get("ds") || "";
  const f = sp.get("f") || "";
  const row = sp.get("row") || "";
  const line = sp.get("line") || "";
  const filters = pickFilters(sp);
  const params = { file: f, row, line, ...filters };
  const key = ds && f && (row || line) ? `rec:${ds}:${JSON.stringify(params)}` : null;
  const res = useApi(key, (s) => api.record(ds, params, s));
  const rec = res.data;
  const [active, setActive] = useState<number[]>([]);
  const [opts, setOpts] = useState<TextOptions>({ check1: true, check2: true });
  const [focus, setFocus] = useState<Focus>(null);
  const jump = (id: number | null) => {
    if (id === null) return;
    setFocus((f) => ({ id, n: (f?.n || 1) + 1 }));
    setActive([id]);
  };
  useEffect(() => {
    if (!rec) return;
    const id = initialFocus(rec.explanation.marks);
    setFocus(id === null ? null : { id, n: 1 });
  }, [rec]);
  const listLink = href("/file", { ds, f, ...filters });
  const go = (r: number | null) => (r ? href("/record", { ds, f, row: r, ...filters }) : null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!rec || (e.target as HTMLElement)?.closest("input, textarea, select")) return;
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      const next = go(rec.nav.next_match);
      const prev = go(rec.nav.prev_match);
      if ((e.key === "j" || e.key === "ArrowRight") && next) router.push(next);
      else if ((e.key === "k" || e.key === "ArrowLeft") && prev) router.push(prev);
      else if (e.key === "Escape") router.push(listLink);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rec, listLink]);

  if (!ds || !f) return <div className="alert error">Missing ?ds= or ?f=</div>;
  const anyFilter = Object.values(filters).some(Boolean);
  return (
    <>
      <div className="page-head">
        <div style={{ minWidth: 0 }}>
          <Crumbs items={[{ label: "Datasets", href: "/" }, { label: ds, href: href("/dataset", { ds }) }, { label: f, href: listLink },
            { label: rec ? `line ${rec.line}` : "…" }]} />
          <h1 className="row" style={{ gap: 10 }}>
            {rec ? <DecisionBadge decision={rec.decision.decision} big /> : null}
            <span className="mono" style={{ fontSize: 18 }}>{f} · line {rec?.line ?? line ?? "…"}</span>
          </h1>
        </div>
      </div>
      {rec ? (
        <div className="navbar">
          <Link className="btn" href={listLink}>← List</Link>
          <NavBtn to={go(rec.nav.prev_match)} label={anyFilter ? "‹ Previous match" : "‹ Previous"} hint="k" />
          <NavBtn to={go(rec.nav.next_match)} label={anyFilter ? "Next match ›" : "Next ›"} hint="j" />
          <span className="muted">{rec.nav.position ?? "–"} of {rec.nav.matches ?? "–"}{anyFilter ? " matching" : ""}</span>
          {anyFilter ? (
            <span className="muted">· all lines: <NavLink to={go(rec.nav.prev)} label="‹ prev" /> <NavLink to={go(rec.nav.next)} label="next ›" /></span>
          ) : null}
          <span className="spacer" />
          <span className="faint"><span className="kbd">j</span> <span className="kbd">k</span> next / previous · <span className="kbd">Esc</span> list</span>
        </div>
      ) : null}
      <ErrorBox error={res.error} onRetry={res.reload} />
      {res.loading && !rec ? <Loading what="Loading the decision and the original line" /> : null}
      {rec ? (
        <div className="grid side" style={{ opacity: res.loading ? 0.6 : 1 }}>
          <div className="stack">
            <Verdict rec={rec} />
            <div className="panel flush">
              <div className="panel-head">
                <h2>Original text</h2>
                <span className="muted">field “{rec.text_field}”{rec.explanation.text_length !== null ? ` · ${rec.explanation.text_length.toLocaleString("en-US")} characters` : ""}</span>
                <span className="spacer" />
                {rec.explanation.excerpted ? <span className="badge warn">long text: only the parts around the marks are shown</span> : null}
              </div>
              <div className="panel-body" style={{ paddingBottom: 0 }}>
                <Legend options={opts} setOptions={setOpts} hasCheck1={!!rec.explanation.check1} hasCheck2={!!rec.explanation.check2} />
              </div>
              {rec.explanation.text_available ? (
                <HighlightedText segments={rec.explanation.segments} marks={rec.explanation.marks} active={active} options={opts} onHover={setActive} focus={focus} />
              ) : (
                <div className="panel-body"><div className="alert warn">Original text not available: {rec.original.error || `no “${rec.text_field}” field`}</div></div>
              )}
            </div>
            <Check1Table rec={rec} setActive={setActive} jump={jump} />
            <Check2Table rec={rec} setActive={setActive} jump={jump} />
          </div>
          <div className="stack">
            <Hits rec={rec} setActive={setActive} jump={jump} />
            <Models rec={rec} />
            <Sources rec={rec} />
            <Raw rec={rec} />
          </div>
        </div>
      ) : null}
    </>
  );
}

function NavBtn({ to, label, hint }: { to: string | null; label: string; hint: string }) {
  return to ? <Link className="btn" href={to} title={`keyboard: ${hint}`}>{label}</Link> : <button className="btn" disabled>{label}</button>;
}
function NavLink({ to, label }: { to: string | null; label: string }) {
  return to ? <Link href={to}>{label}</Link> : <span className="faint">{label}</span>;
}

function Verdict({ rec }: { rec: RecordResp }) {
  const v = rec.explanation.verdict;
  const ex = rec.explanation.expect;
  return (
    <div className="panel verdict" data-testid="verdict">
      <div className="row">
        <DecisionBadge decision={v.decision} />
        <ReasonBadge reason={v.reason} />
        {ex ? (ex.correct ? <span className="badge keep">matches expected “{ex.value}”</span> : <span className="badge filter">expected “{ex.value}”: WRONG</span>) : null}
        {rec.decision.id !== undefined ? <span className="muted mono">id {String(rec.decision.id)}</span> : null}
      </div>
      <div className="summary">{v.summary}</div>
      {v.steps.length ? <ul>{v.steps.map((s, i) => <li key={i}>{s}</li>)}</ul> : null}
      {!rec.id_check.match ? (
        <div className="alert warn">The id in the decisions file ({String(rec.id_check.decision_id)}) differs from the id of the corpus line ({String(rec.id_check.original_id)}): the corpus file may have changed since the run.</div>
      ) : null}
    </div>
  );
}

type Jump = (id: number | null) => void;

function Check1Table({ rec, setActive, jump }: { rec: RecordResp; setActive: (ids: number[]) => void; jump: Jump }) {
  const c1 = rec.explanation.check1;
  if (!c1) return null;
  return (
    <div className="panel flush">
      <div className="panel-head">
        <h2>Check 1 · is the text about the country?</h2>
        <span className="muted">threshold {c1.threshold} · best {score(c1.score)} → {c1.positive ? "positive" : "negative"}</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Hypothesis</th><th>Window</th><th className="num">Fast</th><th className="num">Judge</th><th>Final</th></tr></thead>
          <tbody>
            {c1.rows.map((r, i) => (
              <tr key={i} className="hoverable jump" title="Click to show this window in the text" onClick={() => jump(r.window_mark)}
                onMouseEnter={() => setActive(r.window_mark !== null ? [r.window_mark] : [])} onMouseLeave={() => setActive([])}>
                <td><div className="hyp-key">{r.hyp}</div><div className="hyp">{r.hypothesis || <span className="faint">(text not in run summary)</span>}</div></td>
                <td className="mono nowrap" title={r.window_text || ""}>{r.window[0]}–{r.window[1]}</td>
                <td className="num mono">{score(r.fast)}</td>
                <td className="num mono">{r.judged ? score(r.judge) : <span className="faint">–</span>}</td>
                <td className="nowrap"><ScoreBar value={r.score} threshold={c1.threshold} /> {r.passed ? <span className="badge filter">pass</span> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Check2Table({ rec, setActive, jump }: { rec: RecordResp; setActive: (ids: number[]) => void; jump: Jump }) {
  const c2 = rec.explanation.check2;
  if (!c2) return null;
  const winOf = (hit: number) => rec.explanation.marks.filter((m) => m.kind === "check2_window" && m.hit === hit).map((m) => m.id);
  return (
    <div className="panel flush">
      <div className="panel-head">
        <h2>Check 2 · is a hit only incidental?</h2>
        <span className="muted">threshold {c2.threshold} · best hypothesis per hit · {c2.all_incidental ? "all hits incidental → kept" : "not all incidental"}</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Hit</th><th>Best hypothesis</th><th className="num">Fast</th><th className="num">Judge</th><th>Final</th></tr></thead>
          <tbody>
            {c2.rows.map((r) => (
              <tr key={r.hit} className="hoverable jump" title="Click to show this hit in the text" onClick={() => jump(r.hit_mark)}
                onMouseEnter={() => setActive([r.hit_mark, ...winOf(r.hit)])} onMouseLeave={() => setActive([])}>
                <td className="nowrap"><strong>{r.kw}</strong> <span className="faint mono">{r.span[0]}–{r.span[1]}</span></td>
                <td><div className="hyp-key">{r.hyp}</div><div className="hyp">{r.hypothesis || <span className="faint">(text not in run summary)</span>}</div>
                  {r.window_text ? <div className="faint" style={{ fontSize: 12, marginTop: 4 }}>window: “{r.window_text}”</div> : null}</td>
                <td className="num mono">{score(r.fast)}</td>
                <td className="num mono">{r.judged ? score(r.judge) : <span className="faint">–</span>}</td>
                <td className="nowrap"><ScoreBar value={r.score} threshold={c2.threshold} kind="inc" /> {r.incidental ? <span className="badge keep">incidental</span> : <span className="badge filter">not incidental</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Hits({ rec, setActive, jump }: { rec: RecordResp; setActive: (ids: number[]) => void; jump: Jump }) {
  const hits = rec.explanation.marks.filter((m) => m.kind === "hit");
  return (
    <div className="panel">
      <h2>Keyword hits ({hits.length}) <span className="faint" style={{ fontWeight: 400, fontSize: 12 }}>click to jump</span></h2>
      {hits.length === 0 ? <span className="muted">none</span> : null}
      <table>
        <tbody>
          {hits.map((m) => (
            <tr key={m.id} className="hoverable jump" title="Click to show this hit in the text" onClick={() => jump(m.id)}
              onMouseEnter={() => setActive([m.id])} onMouseLeave={() => setActive([])}>
              <td><span className={`swatch ${m.state}`} /> <strong>{m.kw}</strong></td>
              <td className="mono faint">{m.start}–{m.end}</td>
              <td>{m.rule ? RULE_LABEL[m.rule] || m.rule : m.state === "incidental" ? "incidental" : m.state === "about" ? "not incidental" : "check 1 only"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Models({ rec }: { rec: RecordResp }) {
  const m = rec.explanation.models;
  return (
    <div className="panel">
      <h2>Models and settings</h2>
      <dl className="kv">
        <dt>Fast model</dt><dd>{m.fast || "–"} {m.fast_info?.dtype ? <span className="faint">{m.fast_info.dtype} · {m.fast_info.devices?.join(",")}</span> : null}</dd>
        <dt>Judge</dt><dd>{m.judge || "none"}</dd>
        <dt>Uncertain band</dt><dd>{m.band ? `${m.band[0]} – ${m.band[1]} (fast scores here go to the judge)` : "–"}</dd>
        <dt>Thresholds</dt><dd>check 1 ≥ {m.check1_threshold}, check 2 ≥ {m.check2_threshold}</dd>
      </dl>
    </div>
  );
}

function Sources({ rec }: { rec: RecordResp }) {
  return (
    <div className="panel">
      <h2>Where it comes from</h2>
      <dl className="kv">
        <dt>Corpus file</dt><dd className="mono">{rec.files.corpus || "not found"}{rec.original.member ? `!${rec.original.member}` : ""} <span className="faint">line {rec.line}</span> {rec.files.corpus ? <CopyButton text={`${rec.files.corpus}:${rec.line}`} /> : null}</dd>
        <dt>Decisions file</dt><dd className="mono">{rec.files.decisions} <span className="faint">row {rec.row}</span></dd>
        <dt>File summary</dt><dd className="mono">{rec.files.summary}</dd>
        {rec.original.fields ? <><dt>Fields</dt><dd>{rec.original.fields.map((k) => <span className="chip" key={k}>{k}</span>)}</dd></> : null}
      </dl>
    </div>
  );
}

function Raw({ rec }: { rec: RecordResp }) {
  return (
    <div className="panel flush">
      <details>
        <summary>Original line (raw JSON)</summary>
        <pre className="json">{rec.original.raw ? pretty(rec.original.raw) : rec.original.error}</pre>
        {rec.original.raw ? <div className="panel-body"><CopyButton text={rec.original.raw} label="Copy line" /></div> : null}
      </details>
      <details>
        <summary>Decision record</summary>
        <pre className="json">{JSON.stringify(rec.decision, null, 2)}</pre>
      </details>
    </div>
  );
}

function pretty(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}

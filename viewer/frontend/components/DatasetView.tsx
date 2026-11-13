"use client";
// One dataset: totals, reasons, evaluation, run settings and the list of result files.
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { api, useApi } from "@/lib/api";
import { REASON_LABEL, REASON_ORDER, RULE_LABEL, href, num, pct, score, seconds } from "@/lib/format";
import type { Overview } from "@/lib/types";
import { Bars, Crumbs, DecisionBadge, ErrorBox, Loading, ReasonBadge, Stat } from "./ui";

export function DatasetView() {
  const sp = useSearchParams();
  const ds = sp.get("ds") || "";
  const ov = useApi(ds ? `ov:${ds}` : null, (s) => api.overview(ds, s));
  if (!ds) return <div className="alert error">No dataset given (?ds=…)</div>;
  return (
    <>
      <div className="page-head">
        <div style={{ minWidth: 0 }}>
          <Crumbs items={[{ label: "Datasets", href: "/" }, { label: ov.data?.title || ds }]} />
          <h1>{ov.data?.title || ds}</h1>
          {ov.data?.description ? <div className="sub">{ov.data.description}</div> : null}
        </div>
        <span className="spacer" />
        <Link className="btn" href={href("/tune", { ds })}>Tune thresholds</Link>
        <Link className="btn" href={href("/corpus", { ds })}>Browse corpus</Link>
        <FindById ds={ds} />
      </div>
      <ErrorBox error={ov.error} onRetry={ov.reload} />
      {ov.loading && !ov.data ? <Loading what="Reading summaries" /> : null}
      {ov.data ? <OverviewPanels ds={ds} ov={ov.data} /> : null}
      {ov.data ? <FilesTable ds={ds} /> : null}
    </>
  );
}

function OverviewPanels({ ds, ov }: { ds: string; ov: Overview }) {
  const t = ov.totals;
  const filtered = t.decisions.filter || 0;
  const ev = ov.evaluation;
  const run = ov.run;
  const reasons = REASON_ORDER.filter((r) => t.reasons[r]).map((r) => [r, t.reasons[r]] as [string, number]);
  return (
    <>
      <div className="stats">
        <Stat label="Lines" value={num(t.lines)} note={`${ov.files} files${ov.files_complete < ov.files ? `, ${ov.files - ov.files_complete} partial` : ""}`} />
        <Stat label="Filtered" value={num(filtered)} note={pct(filtered, t.lines)} />
        <Stat label="Kept" value={num(t.decisions.keep || 0)} note={pct(t.decisions.keep || 0, t.lines)} />
        <Stat label="Keyword hits" value={num(t.hits)} note={`${num(t.check1_windows)} check-1 windows`} />
        {ev ? <Stat label="Accuracy" value={score(ev.accuracy)} note={`${ev.fp + ev.fn} mistakes of ${num(ev.n)} labelled`} /> : null}
        {ev ? <Stat label="Precision / recall" value={`${score(ev.precision, 2)} / ${score(ev.recall, 2)}`} note={`F1 ${score(ev.f1)}`} /> : null}
      </div>
      {ov.files_without_corpus.length ? (
        <div className="alert warn" style={{ marginBottom: 16 }}>
          {ov.files_without_corpus.length} result file(s) have no matching corpus file: {ov.files_without_corpus.slice(0, 5).join(", ")}
          {ov.files_without_corpus.length > 5 ? " …" : ""}
        </div>
      ) : null}
      <div className="grid cols-2" style={{ marginBottom: 16 }}>
        <div className="panel">
          <h2>Why lines were kept or filtered</h2>
          <Bars items={reasons} total={t.lines} labels={REASON_LABEL} colorOf={(k) => (k === "about_country" ? "filter" : "keep")} />
          {Object.keys(t.rules).length ? (
            <p className="muted" style={{ marginBottom: 0 }}>
              Rule hits: {Object.entries(t.rules).map(([k, v]) => `${RULE_LABEL[k] || k} ${v}`).join(" · ")}
            </p>
          ) : null}
        </div>
        <div className="panel">
          <h2>Run</h2>
          {run ? (
            <dl className="kv">
              <dt>Country</dt><dd>{run.country?.name} ({run.country?.adj})</dd>
              <dt>Fast model</dt><dd>{run.models?.fast?.model} <span className="faint">{run.models?.fast?.mode} · {run.models?.fast?.devices?.join(",")} · {run.models?.fast?.dtype}</span></dd>
              <dt>Judge</dt><dd>{run.models?.judge ? <>{run.models.judge.model} <span className="faint">band {JSON.stringify(run.settings?.uncertain_band)}</span></> : "none"}</dd>
              <dt>Thresholds</dt><dd>check 1 ≥ {String(run.settings?.check1_threshold)} · check 2 ≥ {String(run.settings?.check2_threshold)}</dd>
              <dt>Keywords</dt><dd>{run.country?.keywords?.map((k) => <span className="chip" key={k}>{k}</span>)}</dd>
              <dt>Speed</dt><dd>{run.timing ? `${score(run.timing.lines_per_second, 1)} lines/s · ${num(run.timing.fast_pairs)} fast + ${num(run.timing.judge_pairs)} judge pairs · ${seconds(run.timing.run_seconds)}` : "–"}</dd>
              <dt>Finished</dt><dd>{run.finished || "–"}{ov.runs.length > 1 ? <span className="faint"> · {ov.runs.length} run summaries</span> : null}</dd>
            </dl>
          ) : <span className="muted">No run summary (summary.json) in the output folder.</span>}
        </div>
      </div>
      {run?.hypotheses ? (
        <div className="panel" style={{ marginBottom: 16 }}>
          <h2>Hypotheses</h2>
          <div className="grid cols-2">
            <div>
              <h3>Check 1 · is the text about the country?</h3>
              {Object.entries(run.hypotheses.check1).map(([k, v]) => (
                <p key={k} style={{ margin: "4px 0" }}><span className="hyp-key">{k}</span> <span className="hyp">{v}</span></p>
              ))}
            </div>
            <div>
              <h3>Check 2 · is a hit only incidental?</h3>
              {Object.keys(run.hypotheses.check2).length ? Object.entries(run.hypotheses.check2).map(([k, v]) => (
                <p key={k} style={{ margin: "4px 0" }}><span className="hyp-key">{k}</span> <span className="hyp">{v}</span></p>
              )) : <span className="muted">check 2 off</span>}
            </div>
          </div>
        </div>
      ) : null}
      {ev && Object.keys(ev.by_group).length ? (
        <div className="panel flush" style={{ marginBottom: 16 }}>
          <div className="panel-head"><h2>Evaluation by group</h2><span className="muted">lines with an expected label, positive class = filter</span></div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Group</th><th className="num">Lines</th><th className="num">Correct</th><th className="num">TP</th><th className="num">FP</th><th className="num">TN</th><th className="num">FN</th></tr></thead>
              <tbody>
                {Object.entries(ev.by_group).map(([g, c]) => {
                  const n = c.tp + c.fp + c.tn + c.fn;
                  return (
                    <tr key={g} className={c.fp + c.fn ? "wrong" : ""}>
                      <td>{g}</td><td className="num">{n}</td><td className="num">{pct(c.tp + c.tn, n)}</td>
                      <td className="num">{c.tp}</td><td className="num">{c.fp}</td><td className="num">{c.tn}</td><td className="num">{c.fn}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </>
  );
}

function FilesTable({ ds }: { ds: string }) {
  const [q, setQ] = useState("");
  const [only, setOnly] = useState("");
  const files = useApi(`files:${ds}:${only}`, (s) => api.files(ds, { only }, s));
  const router = useRouter();
  const rows = useMemo(() => (files.data?.files || []).filter((f) => !q || f.key.toLowerCase().includes(q.toLowerCase())), [files.data, q]);
  return (
    <div className="panel flush">
      <div className="panel-head"><h2>Files</h2><span className="muted">{rows.length} shown</span></div>
      <div className="toolbar">
        <input type="search" placeholder="Filter by path…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter files by path" />
        <select value={only} onChange={(e) => setOnly(e.target.value)} aria-label="Show only">
          <option value="">All files</option>
          <option value="mistakes">With mistakes</option>
          <option value="partial">Partial (--limit)</option>
          <option value="no_corpus">Corpus file missing</option>
        </select>
      </div>
      <ErrorBox error={files.error} onRetry={files.reload} />
      {files.loading && !files.data ? <Loading what="Listing files" /> : null}
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>File</th><th className="num">Lines</th><th className="num">Filtered</th><th>Reasons</th><th className="num">Accuracy</th><th className="num">Mistakes</th><th>Corpus file</th></tr>
          </thead>
          <tbody>
            {rows.map((f) => {
              const link = href("/file", { ds, f: f.key });
              return (
                <tr key={f.key} className={`clickable${f.mistakes ? " wrong" : ""}`} onClick={() => router.push(link)}>
                  <td><Link href={link} onClick={(e) => e.stopPropagation()} className="mono">{f.key}</Link>{f.complete ? null : <span className="badge warn" style={{ marginLeft: 6 }}>partial</span>}</td>
                  <td className="num">{num(f.lines)}</td>
                  <td className="num">{num(f.filtered)} <span className="faint">{pct(f.filtered, f.lines, 0)}</span></td>
                  <td>{REASON_ORDER.filter((r) => f.reasons[r]).map((r) => <span key={r} className="chip" title={REASON_LABEL[r]}>{shortReason(r)} {f.reasons[r]}</span>)}</td>
                  <td className="num">{score(f.accuracy)}</td>
                  <td className="num">{f.mistakes ?? "–"}</td>
                  <td className="mono muted">{f.corpus_path || <span className="badge filter">not found</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {files.data && rows.length === 0 ? <div className="empty">No files match.</div> : null}
      </div>
    </div>
  );
}

function shortReason(r: string): string {
  return ({ no_keyword: "no kw", rules_incidental: "rules", check1_negative: "c1 neg", check2_incidental: "c2 inc", about_country: "about", no_text: "no text", blank: "blank", bad_json: "bad" } as Record<string, string>)[r] || r;
}

function FindById({ ds }: { ds: string }) {
  const [id, setId] = useState("");
  const [submitted, setSubmitted] = useState("");
  const res = useApi(submitted ? `find:${ds}:${submitted}` : null, (s) => api.find(ds, submitted, s));
  return (
    <div style={{ position: "relative" }}>
      <form className="row" onSubmit={(e) => { e.preventDefault(); setSubmitted(id.trim()); }}>
        <input type="search" placeholder="Find a line by id…" value={id} onChange={(e) => setId(e.target.value)} aria-label="Find by id" style={{ width: 230 }} />
        <button className="btn" type="submit" disabled={!id.trim()}>Find</button>
      </form>
      {submitted ? (
        <div className="panel" style={{ position: "absolute", right: 0, top: 40, width: 420, zIndex: 5, padding: 10 }}>
          <div className="row" style={{ marginBottom: 6 }}>
            <strong>id “{submitted}”</strong><span className="spacer" />
            <button className="btn small ghost" onClick={() => setSubmitted("")}>Close</button>
          </div>
          {res.loading ? <Loading what="Searching (indexes every file on first use)" /> : null}
          <ErrorBox error={res.error} />
          {res.data && res.data.matches.length === 0 ? <div className="muted">No line with this id.</div> : null}
          {res.data?.matches.map((m) => (
            <div key={`${m.file}:${m.row}`} className="row" style={{ padding: "4px 0" }}>
              <Link className="mono" href={href("/record", { ds, f: m.file, row: m.row })}>{m.file} · line {m.line}</Link>
              <DecisionBadge decision={m.decision} /><ReasonBadge reason={m.reason} />
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

"use client";
// Decisions of one file: facets, filters, sortable table. Filters live in the URL (shareable, back button works).
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api, useApi } from "@/lib/api";
import { FILTER_KEYS, REASON_LABEL, REASON_ORDER, href, num, pickFilters, score } from "@/lib/format";
import type { DecisionRow } from "@/lib/types";
import { Crumbs, DecisionBadge, ErrorBox, ExpectBadge, Loading, ReasonBadge, RuleChip, ScoreBar, SortTh } from "./ui";

const PAGE = 50;

export function FileView() {
  const sp = useSearchParams();
  const router = useRouter();
  const ds = sp.get("ds") || "";
  const f = sp.get("f") || "";
  const filters = pickFilters(sp);
  const sort = sp.get("sort") || "row";
  const desc = sp.get("desc") === "1";
  const offset = Number(sp.get("offset") || 0);
  const params = { file: f, ...filters, sort, desc, offset, limit: PAGE };
  const key = ds && f ? `dec:${ds}:${JSON.stringify(params)}` : null;
  const res = useApi(key, (s) => api.decisions(ds, params, s));
  const [q, setQ] = useState(filters.q);
  useEffect(() => setQ(filters.q), [filters.q]);

  function update(change: Record<string, string | number | boolean | null>, keepOffset = false) {
    const next: Record<string, string | number | boolean | null> = { ds, f, ...filters, sort, desc: desc ? "1" : "", offset: keepOffset ? offset : 0, ...change };
    router.replace(href("/file", next), { scroll: false });
  }
  function toggleSort(col: string) {
    if (sort === col) update({ desc: desc ? "" : "1" });
    else update({ sort: col, desc: col === "row" ? "" : "1" });
  }
  const recordLink = (r: DecisionRow) => href("/record", { ds, f, row: r.row, ...filters });
  const data = res.data;
  const facets = data?.facets;
  const t1 = data?.thresholds?.check1 ?? 0.8;
  const t2 = data?.thresholds?.check2 ?? 0.8;
  const anyFilter = FILTER_KEYS.some((k) => filters[k]);

  if (!ds || !f) return <div className="alert error">Missing ?ds= or ?f=</div>;
  return (
    <>
      <div className="page-head">
        <div style={{ minWidth: 0 }}>
          <Crumbs items={[{ label: "Datasets", href: "/" }, { label: ds, href: href("/dataset", { ds }) }, { label: f }]} />
          <h1 className="mono" style={{ fontSize: 18 }}>{f}</h1>
          {data ? (
            <div className="sub">
              {num(data.file.lines)} lines · {num(data.file.filtered)} filtered · corpus <span className="mono">{data.file.corpus_path || "not found"}</span>
            </div>
          ) : null}
        </div>
      </div>
      <ErrorBox error={res.error} onRetry={res.reload} />
      <div className="panel flush">
        {facets ? (
          <div className="facets" aria-label="Quick filters">
            <button className={`facet${!anyFilter ? " on" : ""}`} onClick={() => update(Object.fromEntries(FILTER_KEYS.map((k) => [k, ""])))}>
              All <span className="n">{num(facets.total)}</span>
            </button>
            {(["filter", "keep"] as const).map((d) => (
              <button key={d} className={`facet${filters.decision === d ? " on" : ""}`} onClick={() => update({ decision: filters.decision === d ? "" : d })}>
                {d === "filter" ? "Filtered" : "Kept"} <span className="n">{num(facets.decisions[d] || 0)}</span>
              </button>
            ))}
            {REASON_ORDER.filter((r) => facets.reasons[r]).map((r) => (
              <button key={r} className={`facet${filters.reason === r ? " on" : ""}`} onClick={() => update({ reason: filters.reason === r ? "" : r })}>
                {REASON_LABEL[r]} <span className="n">{num(facets.reasons[r])}</span>
              </button>
            ))}
            {facets.labelled ? (
              <button className={`facet${filters.mismatch ? " on" : ""}`} onClick={() => update({ mismatch: filters.mismatch ? "" : "1" })}>
                Wrong vs expected <span className="n">{num(facets.mismatches)}</span>
              </button>
            ) : null}
            {facets.judged ? (
              <button className={`facet${filters.judged === "true" ? " on" : ""}`} onClick={() => update({ judged: filters.judged === "true" ? "" : "true" })}>
                Decided by judge <span className="n">{num(facets.judged)}</span>
              </button>
            ) : null}
          </div>
        ) : null}
        <form className="toolbar" onSubmit={(e) => { e.preventDefault(); update({ q }); }}>
          <input type="search" placeholder="id, keyword or line number…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search" style={{ width: 240 }} />
          <select value={filters.kw} onChange={(e) => update({ kw: e.target.value })} aria-label="Keyword">
            <option value="">Any keyword</option>
            {facets ? Object.entries(facets.keywords).map(([k, n]) => <option key={k} value={k}>{k} ({n})</option>) : null}
          </select>
          <label className="check">check 1 ≥ <input type="number" step="0.05" min="0" max="1" value={filters.min_score} onChange={(e) => update({ min_score: e.target.value })} aria-label="Minimum check-1 score" /></label>
          <label className="check">≤ <input type="number" step="0.05" min="0" max="1" value={filters.max_score} onChange={(e) => update({ max_score: e.target.value })} aria-label="Maximum check-1 score" /></label>
          <button className="btn" type="submit">Search</button>
          {anyFilter ? <button className="btn ghost" type="button" onClick={() => update(Object.fromEntries(FILTER_KEYS.map((k) => [k, ""])))}>Clear filters</button> : null}
          <span className="spacer" />
          {data ? <span className="muted">{num(data.total)} match{data.total === 1 ? "" : "es"}</span> : null}
        </form>
        {res.loading && !data ? <Loading what="Indexing decisions (first time only)" /> : null}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <SortTh col="line" label="Line" sort={sort} desc={desc} onSort={toggleSort} num />
                <SortTh col="id" label="Id" sort={sort} desc={desc} onSort={toggleSort} />
                <th>Decision</th>
                <th>Reason</th>
                <SortTh col="score" label="Check 1" sort={sort} desc={desc} onSort={toggleSort} />
                <SortTh col="check2" label="Check 2 (min)" sort={sort} desc={desc} onSort={toggleSort} />
                <SortTh col="hits" label="Keyword hits" sort={sort} desc={desc} onSort={toggleSort} />
                {facets?.labelled ? <th>Expected</th> : null}
              </tr>
            </thead>
            <tbody>
              {data?.rows.map((r) => (
                <tr key={r.row} className={`clickable${r.ok === false ? " wrong" : ""}`} onClick={() => router.push(recordLink(r))}>
                  <td className="num"><Link href={recordLink(r)} onClick={(e) => e.stopPropagation()}>{r.line}</Link>{r.source ? <div className="faint mono">{r.source}</div> : null}</td>
                  <td className="mono">{r.id ?? <span className="faint">–</span>}</td>
                  <td><DecisionBadge decision={r.decision} /></td>
                  <td><ReasonBadge reason={r.reason} /></td>
                  <td>{r.c1 !== null ? <><ScoreBar value={r.c1} threshold={t1} />{r.judged ? <span className="badge accent" title="the judge model decided this score">judge</span> : null}</> : <span className="faint">–</span>}</td>
                  <td><ScoreBar value={r.c2} threshold={t2} kind="inc" /></td>
                  <td>{r.kws.map((k) => <span className="chip" key={k}>{k}</span>)}{r.rules.map((x) => <RuleChip key={x} rule={x} />)}</td>
                  {facets?.labelled ? <td><ExpectBadge ok={r.ok} /></td> : null}
                </tr>
              ))}
            </tbody>
          </table>
          {data && data.rows.length === 0 ? <div className="empty">No decisions match these filters.</div> : null}
        </div>
        {data && data.total > PAGE ? (
          <div className="pager">
            <span>{num(offset + 1)}–{num(Math.min(offset + PAGE, data.total))} of {num(data.total)}</span>
            <button className="btn small" disabled={offset === 0} onClick={() => update({ offset: Math.max(0, offset - PAGE) }, true)}>‹ Previous</button>
            <button className="btn small" disabled={offset + PAGE >= data.total} onClick={() => update({ offset: offset + PAGE }, true)}>Next ›</button>
          </div>
        ) : null}
      </div>
    </>
  );
}


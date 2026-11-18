"use client";
// Per keyword over the whole dataset: how many lines it brings in, how they were decided, mistakes, the
// level-A audit, and flags for keywords worth a look. A row opens the keyword's lines.
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api, useApi } from "@/lib/api";
import { REASON_LABEL, href, num, pct } from "@/lib/format";
import type { KeywordStat, LinesResp } from "@/lib/types";
import { LinesTable } from "./LinesTable";
import { CopyButton, Crumbs, ErrorBox, Loading, SortTh } from "./ui";

const FLAG_LABEL: Record<string, string> = {
  noisy: "mostly kept", rules: "mostly rules", wrong: "mistakes", broad: "A too broad?", no_audit: "A not audited",
  unused: "no hits",
};

type SortCol = "keyword" | "level" | "type" | "hits" | "lines" | "filter" | "keep" | "rules" | "only" | "wrong" | "audit";

export function KeywordsView() {
  const sp = useSearchParams();
  const ds = sp.get("ds") || "";
  const st = useApi(ds ? `kwstats:${ds}` : null, (s) => api.keywordStats(ds, s));
  // indexes still being built: ask again until they are ready
  useEffect(() => {
    if (!st.data?.pending) return;
    const t = setTimeout(st.reload, 1500);
    return () => clearTimeout(t);
  }, [st.data, st.reload]);
  const [q, setQ] = useState("");
  const [level, setLevel] = useState<"" | "A" | "B">("");
  const [flag, setFlag] = useState("");
  const [showUnused, setShowUnused] = useState(false);
  const [sort, setSort] = useState<SortCol>("lines");
  const [desc, setDesc] = useState(true);
  const [openKw, setOpenKw] = useState<string | null>(null);

  const all = st.data?.keywords || [];
  const flagCounts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const k of all) for (const f of k.flags) c[f.kind] = (c[f.kind] || 0) + 1;
    return c;
  }, [all]);
  const val = (k: KeywordStat): number | string => ({
    keyword: k.keyword.toLowerCase(), level: k.level, type: k.type || "", hits: k.hits, lines: k.lines,
    filter: k.lines ? k.filter / k.lines : -1, keep: k.lines ? k.keep / k.lines : -1,
    rules: k.hits ? k.rule_hits / k.hits : -1, only: k.only_lines, wrong: k.wrong,
    audit: k.level === "A" && k.audited ? k.audit_keep / k.audited : -1,
  } as Record<SortCol, number | string>)[sort];
  const rows = useMemo(() => {
    const ql = q.trim().toLowerCase();
    const r = all.filter((k) => (showUnused || k.hits > 0 || flag === "unused")
      && (!level || k.level === level) && (!flag || (flag === "any" ? k.flags.some((f) => f.kind !== "unused") : k.flags.some((f) => f.kind === flag)))
      && (!ql || k.keyword.toLowerCase().includes(ql) || (k.type || "").includes(ql) || (k.gloss || "").toLowerCase().includes(ql)));
    return [...r].sort((a, b) => {
      const x = val(a), y = val(b);
      const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
      return desc ? -c : c;
    });
  }, [all, q, level, flag, showUnused, sort, desc]);  // eslint-disable-line react-hooks/exhaustive-deps
  const onSort = (c: string) => { if (c === sort) setDesc((d) => !d); else { setSort(c as SortCol); setDesc(c !== "keyword" && c !== "type" && c !== "level"); } };
  const th = { sort, desc, onSort };
  const tsv = ["keyword\tlevel\ttype\thits\tlines\tfiltered\tkept\trule_hits\tonly_this_keyword\tlabelled\twrong\taudited\taudit_keep\tflags",
    ...rows.map((k) => [k.keyword, k.level, k.type || "", k.hits, k.lines, k.filter, k.keep, k.rule_hits, k.only_lines, k.labelled,
      k.wrong, k.audited, k.audit_keep, k.flags.map((f) => f.kind).join(",")].join("\t"))].join("\n") + "\n";

  if (!ds) return <div className="alert error">Missing ?ds=</div>;
  const withHits = all.filter((k) => k.hits > 0).length;
  return (
    <>
      <div className="page-head">
        <div>
          <Crumbs items={[{ label: "Datasets", href: "/" }, { label: ds, href: href("/dataset", { ds }) }, { label: "keywords" }]} />
          <h1>Keywords of {ds}</h1>
          <div className="sub">Which keywords bring which lines in, and how those lines were decided. Click a keyword to see its lines.</div>
        </div>
      </div>
      <ErrorBox error={st.error} onRetry={st.reload} />
      {st.loading && !st.data ? <Loading what="Counting keyword hits" /> : null}
      {st.data?.pending ? <div className="alert">Indexing {st.data.pending} of {st.data.files} result files (first look at a big dataset)… the numbers grow until it is done.</div> : null}
      {st.data ? (
        <div className="stack">
          <div className="row kw-summary">
            <span className="badge neutral">{num(all.length)} keywords</span>
            <span className="badge neutral">{num(withHits)} with hits</span>
            <span className="badge neutral">{num(all.filter((k) => k.level === "A").length)} level A</span>
            {Object.entries(flagCounts).map(([f, n]) => (
              <button key={f} className={`btn small${flag === f ? " primary" : ""}`} onClick={() => setFlag(flag === f ? "" : f)}
                title={all.find((k) => k.flags.some((x) => x.kind === f))?.flags.find((x) => x.kind === f)?.text}>
                {FLAG_LABEL[f] || f} <span className="badge warn">{n}</span></button>
            ))}
          </div>
          <div className="row">
            <input type="search" placeholder="search keyword, type, gloss…" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 220 }} data-testid="kwstats-search" />
            <span className="seg">
              {(["", "A", "B"] as const).map((l) => <button key={l || "all"} className={level === l ? `on${l ? " lvl-" + l : ""}` : ""} onClick={() => setLevel(l)}>{l || "all"}</button>)}
            </span>
            <select value={flag} onChange={(e) => setFlag(e.target.value)}>
              <option value="">every keyword</option>
              <option value="any">with a flag</option>
              {Object.keys(FLAG_LABEL).map((f) => <option key={f} value={f}>{FLAG_LABEL[f]} ({flagCounts[f] || 0})</option>)}
            </select>
            <label><input type="checkbox" checked={showUnused} onChange={(e) => setShowUnused(e.target.checked)} /> show keywords without hits</label>
            <span className="spacer" />
            <span className="faint">{rows.length} shown</span>
            <CopyButton text={tsv} label="Copy table" title="copy the shown rows as tab-separated text" />
          </div>
          <div className="panel flush">
            <div className="table-wrap">
              <table className="kw-stats" data-testid="kw-stats">
                <thead>
                  <tr>
                    <SortTh col="keyword" label="keyword" {...th} />
                    <SortTh col="level" label="level" {...th} />
                    <SortTh col="type" label="type" {...th} />
                    <SortTh col="hits" label="hits" num {...th} />
                    <SortTh col="lines" label="lines" num {...th} />
                    <SortTh col="filter" label="filtered" num {...th} />
                    <SortTh col="keep" label="kept" num {...th} />
                    <SortTh col="rules" label="by rules" num {...th} />
                    <SortTh col="only" label="only this kw" num {...th} />
                    <SortTh col="wrong" label="mistakes" num {...th} />
                    <SortTh col="audit" label="A audit: keep" num {...th} />
                    <th>flags</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((k) => [
                    <tr key={k.keyword} className={`hoverable${openKw === k.keyword ? " selected" : ""}`} style={{ cursor: "pointer" }}
                      onClick={() => setOpenKw(openKw === k.keyword ? null : k.keyword)} data-testid={`kwstat-${k.keyword}`}>
                      <td><strong>{k.keyword}</strong>{k.gloss ? <div className="faint" style={{ fontSize: 12 }}>{k.gloss}</div> : null}{!k.in_list && st.data!.keywords.some((x) => x.in_list) ? <div className="faint" style={{ fontSize: 11 }}>not in the run's list</div> : null}</td>
                      <td><span className={`badge ${k.level === "A" ? "filter" : "neutral"}`}>{k.level}</span></td>
                      <td>{k.type || <span className="faint">–</span>}</td>
                      <td className="num">{num(k.hits)}</td>
                      <td className="num">{num(k.lines)}</td>
                      <td className="num" title={`${k.filter} lines`}>{pct(k.filter, k.lines, 0)}</td>
                      <td className="num" title={`${k.keep} lines`}>{pct(k.keep, k.lines, 0)}</td>
                      <td className="num" title={`${k.rule_hits} of ${k.hits} hits resolved by rules`}>{pct(k.rule_hits, k.hits, 0)}</td>
                      <td className="num" title={`${k.only_lines} lines have no other keyword (${k.only_filter} of them filtered): removing it would keep them all`}>{num(k.only_lines)}</td>
                      <td className="num" title={`${k.labelled} labelled lines`}>{k.labelled ? <span className={k.wrong ? "bad" : ""}>{k.wrong} / {k.labelled}</span> : <span className="faint">–</span>}</td>
                      <td className="num" title={k.level !== "A" ? "level B: decided by the models anyway" : k.audited ? `${k.audit_keep} of ${k.audited} audited lines would be kept by the rules / models` : "not audited (run with --audit-strict)"}>{k.level === "A" && k.audited ? pct(k.audit_keep, k.audited, 0) : <span className="faint">–</span>}</td>
                      <td>{k.flags.map((f) => <span key={f.kind} className={`badge ${f.kind === "wrong" || f.kind === "broad" ? "filter" : "warn"}`} title={f.text} style={{ marginRight: 4 }}>{FLAG_LABEL[f.kind] || f.kind}</span>)}</td>
                    </tr>,
                    openKw === k.keyword ? (
                      <tr key={k.keyword + ":lines"}><td colSpan={12} className="kw-lines-cell"><KeywordLines ds={ds} k={k} /></td></tr>
                    ) : null,
                  ])}
                  {!rows.length ? <tr><td colSpan={12} className="faint">no keyword matches</td></tr> : null}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

const STATES = [
  ["", "every hit"], ["about", "not incidental"], ["incidental", "incidental (check 2)"], ["rule", "by a rule"],
  ["strict", "level A"], ["open", "check 1 only"],
] as const;

function KeywordLines({ ds, k }: { ds: string; k: KeywordStat }) {
  const [state, setState] = useState("");
  const [decision, setDecision] = useState("");
  const [mismatch, setMismatch] = useState(false);
  const [offset, setOffset] = useState(0);
  const params = { kw: k.keyword, kw_state: state, decision, mismatch, offset, limit: 25 };
  const res = useApi(`kwlines:${ds}:${JSON.stringify(params)}`, (s) => api.lines(ds, params, s));
  const d: LinesResp | null = res.data;
  return (
    <div className="stack" style={{ padding: "6px 0" }}>
      <div className="row">
        <strong>Lines with “{k.keyword}”</strong>
        <span className="seg">{STATES.map(([v, l]) => <button key={v || "all"} className={state === v ? "on" : ""} onClick={() => { setState(v); setOffset(0); }}>{l}</button>)}</span>
        <select value={decision} onChange={(e) => { setDecision(e.target.value); setOffset(0); }}>
          <option value="">filter + keep</option><option value="filter">filtered</option><option value="keep">kept</option>
        </select>
        <label><input type="checkbox" checked={mismatch} onChange={(e) => { setMismatch(e.target.checked); setOffset(0); }} /> mistakes only</label>
        {k.reasons ? <span className="faint" style={{ fontSize: 12 }}>{Object.entries(k.reasons).map(([r, n]) => `${REASON_LABEL[r] || r} ${n}`).join(" · ")}</span> : null}
      </div>
      <ErrorBox error={res.error} onRetry={res.reload} />
      {d ? <>
        <LinesTable ds={ds} rows={d.rows} thresholds={d.thresholds} />
        <div className="row">
          <span className="faint">{d.total ? `${offset + 1}–${offset + d.rows.length} of ${num(d.total)}` : "no lines"}</span>
          <button className="btn small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>‹ prev</button>
          <button className="btn small" disabled={offset + 25 >= d.total} onClick={() => setOffset(offset + 25)}>next ›</button>
        </div>
      </> : <Loading what="Loading lines" />}
    </div>
  );
}

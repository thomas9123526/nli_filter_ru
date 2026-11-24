"use client";
// The dataset cards of one area: "label" = outputs that are nli_label.py runs (open on /label/run),
// "filter" = nli_filter.py outputs (open on /filter/dataset). Sortable and searchable.
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, useApi } from "@/lib/api";
import { href } from "@/lib/format";
import { ErrorBox, Loading } from "./ui";
import type { DatasetInfo as Dataset } from "@/lib/types";

type SortKey = "config" | "modified" | "name" | "title" | "kind";
const SORT_KEY = "nli-viewer-datasets-sort";  // one remembered sort for both areas
const SORTS: { key: SortKey; label: string; title: string }[] = [
  { key: "config", label: "Config", title: "the order in viewer_config.json, then the auto datasets" },
  { key: "modified", label: "Modified", title: "when the output folder last changed (remote outputs last)" },
  { key: "name", label: "Name", title: "the dataset name (ds=…)" },
  { key: "title", label: "Title", title: "the title shown on the card" },
  { key: "kind", label: "Kind", title: "nli_filter outputs, then nli_label runs" },
];

function fmtTime(t?: number | null): string {
  if (!t) return "";
  const d = new Date(t * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function sortRows(rows: Dataset[], key: SortKey, desc: boolean): Dataset[] {
  const cmpText = (a: string, b: string) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
  const indexed = rows.map((d, i) => ({ d, i }));
  indexed.sort((x, y) => {
    const a = x.d, b = y.d;
    let c = 0;
    if (key === "modified") {
      // no time (remote / missing) always goes last, whatever the direction
      const ta = a.modified ?? null, tb = b.modified ?? null;
      if (ta === null || tb === null) return ta === tb ? x.i - y.i : ta === null ? 1 : -1;
      c = ta - tb;
    } else if (key === "name") c = cmpText(a.name, b.name);
    else if (key === "title") c = cmpText(a.title || a.name, b.title || b.name);
    else if (key === "kind") c = Number(!!a.label_run) - Number(!!b.label_run) || cmpText(a.name, b.name);
    else c = x.i - y.i;
    if (c === 0) c = x.i - y.i;
    return desc ? -c : c;
  });
  return indexed.map((v) => v.d);
}

export function DatasetList({ kind }: { kind: "label" | "filter" }) {
  const { data, error, loading, reload } = useApi("datasets", (s) => api.datasets(s));
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "config", desc: false });
  const [q, setQ] = useState("");
  useEffect(() => {
    try {
      const v = JSON.parse(localStorage.getItem(SORT_KEY) || "null");
      if (v && SORTS.some((s) => s.key === v.key)) setSort({ key: v.key, desc: !!v.desc });
    } catch { /* private window / bad value */ }
  }, []);
  const choose = (key: SortKey) => {
    // the same button again flips the direction; a new key starts newest-first for Modified, A→Z otherwise
    const next = sort.key === key ? { key, desc: !sort.desc } : { key, desc: key === "modified" };
    setSort(next);
    try { localStorage.setItem(SORT_KEY, JSON.stringify(next)); } catch { /* private window */ }
  };
  const rows = useMemo(() => {
    const all = (data?.datasets || []).filter((d) => (kind === "label") === !!d.label_run);
    const t = q.trim().toLowerCase();
    const hit = t ? all.filter((d) => [d.name, d.title, d.description, d.corpus, d.output].some((s) => (s || "").toLowerCase().includes(t))) : all;
    return sortRows(hit, sort.key, sort.desc);
  }, [data, sort, q]);

  return (
    <>
      <div className="row" style={{ marginBottom: 12, gap: 8, flexWrap: "wrap" }}>
        <span className="faint" style={{ fontSize: 12 }}>Sort</span>
        <span className="seg" data-testid="datasets-sort">
          {SORTS.map((s) => (
            <button key={s.key} className={sort.key === s.key ? "on" : ""} title={s.title} onClick={() => choose(s.key)}>
              {s.label}{sort.key === s.key && s.key !== "config" ? (sort.desc ? " ↓" : " ↑") : ""}
            </button>
          ))}
        </span>
        <input type="search" style={{ maxWidth: 260 }} placeholder="Filter by name, title, path…" value={q}
          onChange={(e) => setQ(e.target.value)} data-testid="datasets-filter" />
        {data ? <span className="faint" style={{ fontSize: 12 }}>{rows.length} shown</span> : null}
      </div>
      <ErrorBox error={error} onRetry={reload} />
      {loading && !data ? <Loading what="Loading datasets" /> : null}
      <div className="cards">
        {rows.map((d) =>
          d.error ? (
            <div className="card" key={d.name}>
              <div className="row"><strong>{d.title}</strong><span className="badge filter">unavailable</span></div>
              <p className="muted" style={{ margin: "6px 0" }}>{d.error}</p>
              <div className="uri">corpus {d.corpus}</div>
              <div className="uri">output {d.output}</div>
            </div>
          ) : (
            <Link className="card" key={d.name} href={d.label_run ? href("/label/run", { run: d.label_run }) : href("/filter/dataset", { ds: d.name })}>
              <div className="row"><strong>{d.title}</strong><span className="badge neutral">{d.name}</span>
                {d.label_run ? <span className="badge review" title="the output is an nli_label.py run: opens its labelling pages">labels</span> : null}
                {d.auto ? <span className="badge neutral" title="found automatically in auto_datasets: the most recent run for this corpus">auto</span> : null}</div>
              {d.description ? <p className="muted" style={{ margin: "6px 0" }}>{d.description}</p> : null}
              <div className="uri">corpus {d.corpus}</div>
              <div className="uri">output {d.output}</div>
              {d.modified ? <div className="faint" style={{ fontSize: 12, marginTop: 4 }} data-testid="dataset-modified">modified {fmtTime(d.modified)}</div> : null}
            </Link>
          ),
        )}
      </div>
      {data && rows.length === 0 ? <div className="empty">{q ? <>No dataset matches &quot;{q}&quot;.</> : kind === "label"
        ? "No labelling runs yet: run nli_label.py into dataset/ (or add a dataset whose output is a label run to viewer_config.json)."
        : "No nli_filter.py datasets configured. Add one to viewer_config.json."}</div> : null}
    </>
  );
}

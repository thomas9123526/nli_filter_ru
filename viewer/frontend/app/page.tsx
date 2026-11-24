"use client";
// Home: the two areas of the viewer. Labelling (nli_label.py, the Russia-side LLM policy) first, then Filter (nli_filter.py).
import Link from "next/link";
import { DatasetList } from "@/components/DatasetList";

export default function Home() {
  return (
    <>
      <div className="page-head">
        <div>
          <h1>NLI Result Viewer</h1>
          <div className="sub">Two areas, each with its own pages: every link inside an area stays in it.</div>
        </div>
      </div>
      <div className="area-cards">
        <Link className="card area-card" href="/label" data-testid="area-label">
          <div className="row"><strong>Labelling</strong><span className="badge review">nli_label.py</span></div>
          <p className="muted" style={{ margin: "6px 0" }}>The Russia-side LLM policy: labelling runs, each paragraph&apos;s flow, Try the policy case by case,
            expected vs result.</p>
          <div className="uri">/label/…</div>
        </Link>
        <Link className="card area-card" href="/filter" data-testid="area-filter">
          <div className="row"><strong>Filter</strong><span className="badge neutral">nli_filter.py</span></div>
          <p className="muted" style={{ margin: "6px 0" }}>Keyword + NLI filter outputs: decisions per line, review, tune thresholds, run the filter.</p>
          <div className="uri">/filter/…</div>
        </Link>
      </div>
      <h2 className="area-title">Labelling runs <Link className="btn small ghost" href="/label">all runs, start a run, Try →</Link></h2>
      <DatasetList kind="label" />
      <h2 className="area-title">Filter datasets <Link className="btn small ghost" href="/filter">open the Filter area →</Link></h2>
      <DatasetList kind="filter" />
    </>
  );
}

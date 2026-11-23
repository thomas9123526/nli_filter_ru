"use client";
// Datasets: every (corpus, output) pair configured in viewer_config.json.
import Link from "next/link";
import { api, useApi } from "@/lib/api";
import { href } from "@/lib/format";
import { ErrorBox, Loading } from "@/components/ui";

export default function Home() {
  const { data, error, loading, reload } = useApi("datasets", (s) => api.datasets(s));
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Datasets</h1>
          <div className="sub">An nli_filter.py output folder and the corpus it was made from. Pick one to browse its decisions.</div>
        </div>
      </div>
      <div className="row" style={{ marginBottom: 12 }}>
        <Link className="btn small" href="/labels" data-testid="labels-link">Labelling runs (nli_label.py) →</Link>
        <span className="faint" style={{ fontSize: 12 }}>policy labels per paragraph: see and start runs, follow each paragraph&apos;s flow</span>
      </div>
      <ErrorBox error={error} onRetry={reload} />
      {loading && !data ? <Loading what="Loading datasets" /> : null}
      <div className="cards">
        {data?.datasets.map((d) =>
          d.error ? (
            <div className="card" key={d.name}>
              <div className="row"><strong>{d.title}</strong><span className="badge filter">unavailable</span></div>
              <p className="muted" style={{ margin: "6px 0" }}>{d.error}</p>
              <div className="uri">corpus {d.corpus}</div>
              <div className="uri">output {d.output}</div>
            </div>
          ) : (
            <Link className="card" key={d.name} href={d.label_run ? href("/labelrun", { run: d.label_run }) : href("/dataset", { ds: d.name })}>
              <div className="row"><strong>{d.title}</strong><span className="badge neutral">{d.name}</span>
                {d.label_run ? <span className="badge review" title="the output is an nli_label.py run: opens its labelling pages">labels</span> : null}</div>
              {d.description ? <p className="muted" style={{ margin: "6px 0" }}>{d.description}</p> : null}
              <div className="uri">corpus {d.corpus}</div>
              <div className="uri">output {d.output}</div>
            </Link>
          ),
        )}
      </div>
      {data && data.datasets.length === 0 ? <div className="empty">No datasets configured. Add one to viewer_config.json.</div> : null}
    </>
  );
}

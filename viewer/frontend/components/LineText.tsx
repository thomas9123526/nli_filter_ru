"use client";
// Run page: a line's full text under its row (▸), loaded only when opened. Paragraphs coloured by their action,
// keyword hits marked, as on the document page; clicking a paragraph opens it on the document page.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, useApi } from "@/lib/api";
import { href } from "@/lib/format";
import { DocText } from "./LabelDocView";
import { ErrorBox, Loading } from "./ui";
import { backHere } from "@/lib/urlState";
import { TextTools } from "./TextTools";

export function LineText({ run, file, line }: { run: string; file: string; line: number }) {
  const router = useRouter();
  const res = useApi(`linetext:${run}:${file}:${line}`, (s) => api.labelDoc(run, { file, line }, s));
  const d = res.data;
  return (
    <div className="line-text" data-testid={`line-text-${line}`}>
      <ErrorBox error={res.error} onRetry={res.reload} />
      {!d && res.loading ? <Loading what="Loading the text" /> : null}
      {d ? (
        <>
          <div className="row" style={{ marginBottom: 4 }}>
            <span className="legend"><span><i className="swatch lpara remove" />remove</span><span><i className="swatch lpara review" />review</span>
              <span><i className="swatch lpara keep" />keep</span><span><i className="swatch lpara pass" />pass</span>
              <span className="faint">plain = not checked (no keyword)</span></span>
            <span className="spacer" />
            {d.text ? <TextTools text={d.text} source={{ file, line, id: d.row.id ?? null, run }} row={d.row} /> : null}
            <Link className="btn small ghost" href={href("/label/doc", { run, file, line })}
              onClick={(e) => { e.preventDefault(); router.push(href("/label/doc", { run, file, line, back: backHere(line) })); }}>open the document page →</Link>
          </div>
          {d.problem ? <div className="alert warn">{d.problem}</div> : null}
          {d.text !== null ? <div className="line-text-body"><DocText d={d} sel={-1}
            onSel={(i) => router.push(href("/label/doc", { run, file, line, para: i, back: backHere(line) }))} /></div>
            : <div className="faint">the source text is not available</div>}
        </>) : null}
    </div>
  );
}

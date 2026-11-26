"use client";
// "Expected vs result" of a run (detail or simple mode): n / ok under a profile of labels/expected_rules.json (strict,
// quick ...), and the lines that do not match. The profile switch changes the counts at once.
import Link from "next/link";
import { api, useApi } from "@/lib/api";
import { href } from "@/lib/format";
import { ErrorBox } from "./ui";
import { actionClass } from "./LabelRunView";

export function ExpectedPanel({ run, profile, setProfile, onFile, onOpen }: {
  run: string; profile: string; setProfile: (p: string) => void;
  onFile: (file: string) => void;
  /** simple runs: open the line on this page; detail runs: undefined = link to the document page */
  onOpen?: (file: string, line: number) => void;
}) {
  const exp = useApi(`labelexp:${run}:${profile}`, (s) => api.labelExpected(run, s, profile || undefined));
  const ex = exp.data?.expected;
  if (exp.error) return <ErrorBox error={exp.error} onRetry={exp.reload} />;
  if (!ex) return null;
  const prof = ex.profile || profile;
  return (
    <div className="panel flush" style={{ marginBottom: 16 }} data-testid="expected-panel">
      <div className="panel-head" style={{ flexWrap: "wrap" }}><h2>Expected vs result</h2>
        <span className={`badge ${ex.ok === ex.n ? "keep" : "warn"}`} data-testid="expected-count">{ex.ok} / {ex.n} as expected ({ex.n ? Math.round(100 * ex.ok / ex.n) : 0} %)</span>
        {ex.profiles && ex.profiles.length ? (
          <span className="seg" data-testid="expected-profile" title="labels/expected_rules.json: which actions count as the same">
            {ex.profiles.map((p) => (
              <button key={p} className={p === prof ? "on" : ""} title={ex.notes?.[p] || ""}
                onClick={() => setProfile(p === ex.default ? "" : p)}>{p}</button>))}
          </span>) : null}
        <span className="faint" style={{ fontSize: 12 }}>
          {ex.notes?.[prof || ""] || "from the expected actions in the corpus"}{ex.simple ? ` · simple run, line level (${ex.unit} unit)` : ""}{" · "}
          <Link href={href("/label/expected-rules", { run })}>rules →</Link></span>
      </div>
      {ex.rules_problem ? <div className="alert">{ex.rules_problem}</div> : null}
      {ex.problem ? <div className="alert">{ex.problem}</div> : null}
      {ex.note ? <div className="panel-body faint" style={{ fontSize: 12 }}>{ex.note}</div> : null}
      {ex.wrong.length ? (
        <div className="table-wrap" style={{ maxHeight: 420, overflow: "auto" }}><table data-testid="expected-wrong">
          <thead><tr><th>File</th><th>Line</th><th>Expected</th><th>Got</th><th>Note</th><th></th></tr></thead>
          <tbody>{ex.wrong.map((w) => (
            <tr key={`${w.file}:${w.line}`}>
              <td><button className="linklike" onClick={() => onFile(w.file)}>{w.file}</button></td>
              <td>{onOpen ? <button className="linklike" data-testid="expected-open" onClick={() => onOpen(w.file, w.line)}>{w.line}</button>
                : <Link href={href("/label/doc", { run, file: w.file, line: w.line })}>{w.line}</Link>}</td>
              <td><span className={`badge ${actionClass(w.expected)}`}>{w.expected}</span>{w.acceptable.length ? <span className="faint"> (also {w.acceptable.join(", ")})</span> : null}</td>
              <td><span className={`badge ${actionClass(w.got)}`}>{w.got}</span>{w.no_row ? <span className="faint"> (no row)</span> : null}
                {w.paragraphs_wrong ? <span className="faint"> · {w.paragraphs_wrong} paragraph{w.paragraphs_wrong > 1 ? "s" : ""} not as expected</span> : null}</td>
              <td className="faint" style={{ fontSize: 12 }}>{w.note}</td>
              <td><Link className="btn small" href={href("/label/try", { run, file: w.file, line: w.line, para: 0 })}>Try</Link></td>
            </tr>))}</tbody>
        </table></div>) : ex.n ? <div className="panel-body faint">Every line matches its expected result.</div> : null}
    </div>);
}

/** ✓ / ✗ expected got, with the rule that made it a match ("keep ≈ pass (quick)"). */
export function ExpectBadge({ v }: { v: { ok: boolean; expected: string; got: string; kind?: string; note?: string; rule?: string } }) {
  return (<>
    <span className={v.ok ? "badge keep" : "badge filter"} title={v.note || ""}>{v.ok ? "✓" : "✗"}</span>{" "}
    <span className={`badge ${actionClass(v.expected)}`}>{v.expected}</span>
    {v.kind !== "document" ? <span className="faint"> got {v.got}</span> : null}
    {v.rule ? <span className="faint" style={{ fontSize: 11 }}> · {v.rule}</span> : null}
  </>);
}

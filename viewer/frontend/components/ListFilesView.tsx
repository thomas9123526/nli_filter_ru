"use client";
// Keyword lists and place-name tables (/label/files/?file=…&policy=…): the files a labelling policy names in
// keywords_file / place_names_file / place_name_exceptions_file. Table view (rows on/off, add, delete; comments kept)
// or plain text; checked with nli_label.py's own parsers while typing; place names: a live preview on a sample text;
// saved with a backup (<folder>/.backup/), refused when the file changed since it was loaded.
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { getJSON, postJSON, useApi } from "@/lib/api";
import { href } from "@/lib/format";
import { Crumbs, ErrorBox, Loading } from "./ui";

type FileRow = { path: string; kind: "keywords" | "place_names" | "exceptions"; used_by_policy: string | null };
type FilesResp = { files: FileRow[]; kinds: Record<string, string>; policy: string | null };
type Check = { ok: boolean; errors: string[]; warnings?: string[]; entries?: number;
  preview?: { text: string; changes: { start: number; old: string; new: string }[] } };
type RawResp = { path: string; kind: FileRow["kind"]; text: string; crlf: boolean; sha: string; check: Check };

const COLS: Record<FileRow["kind"], string[]> = {
  keywords: ["keyword", "level", "type", "gloss", "other meanings", "exclude"],
  place_names: ["from_form", "to_form", "variants", "notes"],
  exceptions: ["pattern"],
};
const DEFAULT_POLICY = "policy/russia_llm_policy_v2.json";

// ---- lines <-> rows: comments and blank lines are kept as they are; a "#" line shaped like a row is a row switched off
// raw = the line as read: an untouched row is written back exactly as it was (only edited rows are re-formatted)
type Row = { kind: "row"; on: boolean; cells: string[]; caseSens?: boolean; raw?: string; edited?: boolean } | { kind: "text"; line: string };

function csvSplit(line: string): string[] {
  const out: string[] = []; let cur = ""; let q = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (q) { if (ch === '"' && line[i + 1] === '"') { cur += '"'; i++; } else if (ch === '"') q = false; else cur += ch; }
    else if (ch === '"' && cur === "") q = true;  // like Python's csv: a quote only opens at the start of a field
    else if (ch === ",") { out.push(cur); cur = ""; } else cur += ch;
  }
  out.push(cur);
  return out;
}
const csvJoin = (cells: string[]) => cells.map((c) => (/[",]/.test(c) ? `"${c.replace(/"/g, '""')}"` : c)).join(",");

export function parse(kind: FileRow["kind"], text: string): Row[] {
  const lines = text.replace(/\n$/, "").split("\n");
  return lines.map((line, i) => {
    const t = line.trim();
    const off = t.startsWith("#");
    const body = off ? t.replace(/^#\s?/, "") : line;
    if (!t) return { kind: "text", line };
    if (kind === "place_names") {
      if (i === 0 && /^from_form,/.test(t)) return { kind: "text", line };  // the header
      if (off && !body.includes(",")) return { kind: "text", line };
      const c = csvSplit(body);
      return { kind: "row", on: !off, cells: [0, 1, 2, 3].map((k) => c[k] ?? ""), raw: line };
    }
    if (kind === "keywords") {
      if (off && !body.includes("\t")) return { kind: "text", line };
      const c = body.split("\t");
      return { kind: "row", on: !off, cells: [0, 1, 2, 3, 4, 5].map((k) => c[k] ?? ""), raw: line };
    }
    if (off) return { kind: "text", line };  // exceptions: every # line is a comment
    const cs = /^case:/i.test(t);
    return { kind: "row", on: true, cells: [cs ? t.slice(5).trim() : t], caseSens: cs, raw: line };
  });
}

export function unparse(kind: FileRow["kind"], rows: Row[]): string {
  return rows.map((r) => {
    if (r.kind === "text") return r.line;
    if (!r.edited && r.raw !== undefined) return r.raw;
    let s: string;
    if (kind === "place_names") s = csvJoin(r.cells);
    else if (kind === "keywords") { const c = [...r.cells]; while (c.length > 1 && !c[c.length - 1]) c.pop(); s = c.join("\t"); }
    else s = (r.caseSens ? "case: " : "") + r.cells[0];
    return r.on ? s : `# ${s}`;
  }).join("\n") + "\n";
}

export function ListFilesView() {
  const sp = useSearchParams();
  const router = useRouter();
  const policy = sp.get("policy") || DEFAULT_POLICY;
  const list = useApi(`listfiles:${policy}`, (s) => getJSON<FilesResp>("/api/labels/files", { policy }, s));
  const files = list.data?.files || [];
  const file = sp.get("file") || files.find((f) => f.used_by_policy)?.path || files[0]?.path || "";
  const [tick, setTick] = useState(0);
  const raw = useApi(file ? `listraw:${file}:${tick}` : null, (s) => getJSON<RawResp>("/api/labels/files/raw", { path: file }, s));
  const [text, setText] = useState<string | null>(null);   // edited text (null = as loaded)
  const [view, setView] = useState<"table" | "text">("table");
  const [check, setCheck] = useState<Check | null>(null);
  const [sample, setSample] = useState("Flights from Kyiv to Kharkiv and Odesa; the Kyiv Independent reported from Lviv.");
  const [filter, setFilter] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const kind = raw.data?.kind;
  const cur = text ?? raw.data?.text ?? "";
  const dirty = text !== null && text !== raw.data?.text;
  const rows = useMemo(() => (kind ? parse(kind, cur) : []), [kind, cur]);

  useEffect(() => { setText(null); setMsg(null); setErr(null); }, [file]);
  useEffect(() => {  // check while typing (and the place-name preview)
    if (!kind) return;
    const ctl = new AbortController();
    const t = setTimeout(() => {
      postJSON<Check>("/api/labels/files/check", { path: file, text: cur, sample: kind === "keywords" ? null : sample, policy })
        .then(setCheck).catch(() => undefined);
    }, 300);
    return () => { clearTimeout(t); ctl.abort(); };
  }, [cur, kind, file, sample, policy]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const setRows = (fn: (r: Row[]) => Row[]) => { if (kind) { setText(unparse(kind, fn(rows.map((r) => ({ ...r }) as Row)))); setMsg(null); } };
  const save = async () => {
    setSaving(true); setErr(null); setMsg(null);
    try {
      const r = await postJSON<{ path: string; backup: string; check: Check }>("/api/labels/files/save", { path: file, text: cur, base_sha: raw.data?.sha });
      setMsg(`Saved ${r.path} (old version: ${r.backup}). Runs and Try use it from the next start.`);
      setText(null); setTick((t) => t + 1);
    } catch (e) { setErr((e as Error).message); }
    setSaving(false);
  };
  const cols = kind ? COLS[kind] : [];
  const q = filter.trim().toLowerCase();

  return (
    <>
      <div className="page-head">
        <div>
          <Crumbs items={[{ label: "Labelling", href: "/label" }, { label: "keywords and place names" }]} />
          <h1>Keyword lists and place names</h1>
          <div className="sub">The files the policy names: <code className="mono">keywords_file</code> (what makes a paragraph checked),
            <code className="mono"> place_names_file</code> and <code className="mono">place_name_exceptions_file</code> (the clean copy&apos;s renaming).
            {" "}<Link href={href("/label/policy", { file: policy })}>edit the policy →</Link></div>
          <div className="row" style={{ marginTop: 8, flexWrap: "wrap" }}>
            <label className="faint" style={{ fontSize: 13 }}>file&nbsp;
              <select value={file} data-testid="list-file" onChange={(e) => {
                if (dirty && !window.confirm("Unsaved changes will be lost. Switch anyway?")) return;
                router.replace(href("/label/files", { file: e.target.value, policy }));
              }}>
                {files.map((f) => <option key={f.path} value={f.path}>{f.path}{f.used_by_policy ? `  (${f.used_by_policy})` : ""}</option>)}
              </select></label>
            <span className="faint" style={{ fontSize: 12 }}>marked = used by {policy}</span>
            <span className="seg"><button className={view === "table" ? "on" : ""} onClick={() => setView("table")}>Table</button>
              <button className={view === "text" ? "on" : ""} onClick={() => setView("text")}>Text</button></span>
          </div>
        </div>
      </div>

      <div className="panel policy-bar" data-testid="list-bar">
        <div className="row" style={{ flexWrap: "wrap" }}>
          {dirty ? <span className="badge warn">unsaved changes</span> : <span className="faint" style={{ fontSize: 12 }}>no changes</span>}
          {check ? (check.ok ? <span className="badge keep" data-testid="list-ok">valid · {check.entries ?? 0} entries</span>
            : <span className="badge remove">{check.errors.length} problem{check.errors.length === 1 ? "" : "s"}</span>) : null}
          <button className="btn small primary" disabled={!dirty || saving || !check?.ok} onClick={save} data-testid="list-save">{saving ? "Saving…" : `Save ${file}`}</button>
          <button className="btn small" disabled={!dirty} onClick={() => setText(null)}>Discard</button>
          {kind ? <span className="faint" style={{ fontSize: 12 }}>{list.data?.kinds[kind]}</span> : null}
        </div>
        {check?.errors.length ? <ul className="policy-errors">{check.errors.map((e, i) => <li key={i}>{e}</li>)}</ul> : null}
        {check?.warnings?.length ? <ul className="policy-warnings">{check.warnings.map((e, i) => <li key={i}>{e}</li>)}</ul> : null}
        {msg ? <div className="faint" style={{ fontSize: 12, marginTop: 6 }} data-testid="list-saved">{msg}</div> : null}
        {err ? <div className="alert error" style={{ marginTop: 6 }}>{err}</div> : null}
      </div>

      {kind && kind !== "keywords" ? (
        <div className="panel" style={{ marginBottom: 12 }} data-testid="list-preview">
          <strong>Preview</strong> <span className="faint" style={{ fontSize: 12 }}>this text through the place names as edited (with the policy&apos;s other place-name file)</span>
          <textarea rows={2} value={sample} onChange={(e) => setSample(e.target.value)} style={{ width: "100%", marginTop: 6 }} />
          <div className="mono" style={{ fontSize: 13, marginTop: 4 }}>→ {check?.preview?.text ?? "…"}</div>
          {check?.preview?.changes.length ? <div className="faint" style={{ fontSize: 12 }}>{check.preview.changes.map((c) => `${c.old} → ${c.new}`).join(", ")}</div> : null}
        </div>) : null}

      <ErrorBox error={list.error || raw.error} onRetry={raw.reload} />
      {!raw.data && raw.loading ? <Loading what="Loading the file" /> : null}
      {raw.data && view === "text" ? (
        <textarea className="mono policy-json" spellCheck={false} value={cur} onChange={(e) => { setText(e.target.value); setMsg(null); }} data-testid="list-text" />
      ) : null}
      {raw.data && view === "table" && kind ? (
        <div className="panel flush">
          <div className="row" style={{ padding: "8px 12px" }}>
            <input type="search" placeholder="filter rows…" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ maxWidth: 260 }} />
            <span className="faint" style={{ fontSize: 12 }}>{rows.filter((r) => r.kind === "row").length} rows · comments are kept (edit them on the Text tab)</span>
            <span className="spacer" />
            <button className="btn small" onClick={() => setRows((rs) => [...rs, { kind: "row", on: true, cells: cols.map(() => ""), edited: true }])} data-testid="list-add">+ add a row</button>
          </div>
          <div className="table-wrap">
            <table className="ptable" data-testid="list-table">
              <thead><tr><th>on</th>{cols.map((c) => <th key={c}>{c}</th>)}{kind === "exceptions" ? <th>case-sensitive</th> : null}<th /></tr></thead>
              <tbody>
                {rows.map((r, i) => {
                  if (r.kind === "text") return q ? null : (r.line.trim() ? <tr key={i}><td /><td colSpan={cols.length + 2} className="faint mono" style={{ fontSize: 11.5 }}>{r.line}</td></tr> : null);
                  if (q && !r.cells.some((c) => c.toLowerCase().includes(q))) return null;
                  const set = (fn: (x: Extract<Row, { kind: "row" }>) => void) => setRows((rs) => rs.map((y, k) => {
                    if (k !== i || y.kind !== "row") return y;
                    const z = { ...y, cells: [...y.cells], edited: true }; fn(z); return z;
                  }));
                  return (
                    <tr key={i} className={r.on ? "" : "row-off"}>
                      <td><input type="checkbox" checked={r.on} onChange={(e) => set((x) => { x.on = e.target.checked; })} title="unticked = switched off (# in the file)" /></td>
                      {cols.map((c, k) => (
                        <td key={c}><input type="text" className={k === 0 ? "mono" : ""} value={r.cells[k] ?? ""} onChange={(e) => set((x) => { x.cells[k] = e.target.value; })}
                          style={{ width: k === 0 ? 180 : kind === "keywords" && (k === 1) ? 40 : 150 }} /></td>))}
                      {kind === "exceptions" ? <td style={{ textAlign: "center" }}><input type="checkbox" checked={!!r.caseSens} onChange={(e) => set((x) => { x.caseSens = e.target.checked; })} /></td> : null}
                      <td><button className="btn small ghost" title="delete this row" onClick={() => setRows((rs) => rs.filter((_, k) => k !== i))}>✕</button></td>
                    </tr>);
                })}
              </tbody>
            </table>
          </div>
        </div>) : null}
    </>
  );
}

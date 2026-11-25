"use client";
// Clean up run folders (/label/folders): the out* run folders of the dataset folder with their status (in use,
// older run, corpus missing, no summary, …). Tick folders, confirm on the page, delete. Running folders and corpus
// folders are never deleted; folders in use only when "also folders in use" is ticked.
import Link from "next/link";
import { useMemo, useState } from "react";
import { getJSON, postJSON, useApi } from "@/lib/api";
import { href } from "@/lib/format";
import { Crumbs, ErrorBox, Loading } from "./ui";

type Folder = { folder: string; kind: string; finished: string; input: string; corpus: string | null; status: string; reason: string; newer: string | null };
type FoldersResp = { folder: string | null; runs: Folder[] };

const UNUSED = ["older run", "single-file input", "server input"];
const INVALID = ["corpus missing", "no summary", "input unknown"];
const statusClass = (s: string) => (s === "in use" ? "keep" : s === "running" ? "accent" : INVALID.includes(s) ? "filter" : "warn");

export function RunFoldersView() {
  const [tick, setTick] = useState(0);
  const res = useApi(`runfolders:${tick}`, (s) => getJSON<FoldersResp>("/api/run-folders", undefined, s));
  const [kind, setKind] = useState("label");
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [allowInUse, setAllowInUse] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ deleted: string[]; failed: { folder: string; error: string }[] } | null>(null);
  const [err, setErr] = useState<Error | null>(null);
  const name = (f: Folder) => f.folder.replace(/\\/g, "/").split("/").pop() || f.folder;
  const rows = useMemo(() => (res.data?.runs || []).filter((r) => kind === "all" || r.kind === kind), [res.data, kind]);
  const can = (r: Folder) => r.status !== "running" && (r.status !== "in use" || allowInUse);
  const toggle = (n: string) => setSel((s) => { const x = new Set(s); if (x.has(n)) x.delete(n); else x.add(n); return x; });
  const pick = (statuses: string[]) => setSel(new Set(rows.filter((r) => statuses.includes(r.status)).map(name)));
  const chosen = rows.filter((r) => sel.has(name(r)) && can(r));

  const del = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await postJSON<{ deleted: string[]; failed: { folder: string; error: string }[] }>("/api/run-folders/delete",
        { folders: chosen.map(name), allow_in_use: allowInUse });
      setResult(r); setSel(new Set()); setConfirming(false); setTick((t) => t + 1);
    } catch (e) { setErr(e as Error); }
    setBusy(false);
  };

  return (
    <>
      <div className="page-head">
        <div>
          <Crumbs items={[{ label: "Labelling", href: "/label" }, { label: "clean up run folders" }]} />
          <h1>Clean up run folders</h1>
          <div className="sub">The run folders (<code className="mono">out*</code>) in {res.data?.folder || "the dataset folder"}. “In use” = the newest run
            for its corpus (what the viewer shows) or a dataset&apos;s output in viewer_config.json. Deleting cannot be undone.</div>
        </div>
      </div>
      <ErrorBox error={res.error || err} onRetry={res.reload} />
      {res.loading && !res.data ? <Loading what="Scanning run folders" /> : null}
      {result ? (
        <div className={`alert${result.failed.length ? " warn" : ""}`} style={{ marginBottom: 12 }} data-testid="folders-result">
          Deleted {result.deleted.length}: {result.deleted.join(", ") || "none"}.
          {result.failed.length ? <> Not deleted: {result.failed.map((f) => `${f.folder} (${f.error})`).join("; ")}.</> : null}
        </div>) : null}
      {res.data ? (
        <div className="panel flush">
          <div className="row" style={{ padding: "10px 16px", flexWrap: "wrap" }}>
            <span className="seg">{["label", "filter", "all"].map((k) => (
              <button key={k} className={kind === k ? "on" : ""} onClick={() => { setKind(k); setSel(new Set()); }}>{k === "label" ? "labelling runs" : k === "filter" ? "filter runs" : "all"}</button>))}</span>
            <button className="btn small" onClick={() => pick([...INVALID])} data-testid="pick-invalid">select broken / corpus missing</button>
            <button className="btn small" onClick={() => pick([...INVALID, ...UNUSED])}>+ older runs</button>
            <button className="btn small ghost" onClick={() => setSel(new Set())}>select none</button>
            <label className="faint" style={{ fontSize: 13 }}><input type="checkbox" checked={allowInUse} onChange={(e) => setAllowInUse(e.target.checked)} /> also folders in use</label>
            <span className="spacer" />
            <button className="btn small danger" disabled={!chosen.length} onClick={() => setConfirming(true)} data-testid="folders-delete">Delete {chosen.length} folder{chosen.length === 1 ? "" : "s"}…</button>
          </div>
          {confirming ? (
            <div className="alert error" style={{ margin: "0 16px 12px" }} data-testid="folders-confirm">
              <strong>Delete these {chosen.length} folder{chosen.length === 1 ? "" : "s"} for good?</strong> {chosen.map(name).join(", ")}
              <div className="row" style={{ marginTop: 8 }}>
                <button className="btn small danger" onClick={del} disabled={busy} data-testid="folders-confirm-yes">{busy ? "Deleting…" : "Yes, delete"}</button>
                <button className="btn small" onClick={() => setConfirming(false)}>Cancel</button>
              </div>
            </div>) : null}
          <div className="table-wrap">
            <table data-testid="folders-table">
              <thead><tr><th /><th>Folder</th><th>Kind</th><th>Status</th><th>Why</th><th>Finished</th><th>Corpus</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.folder}>
                    <td><input type="checkbox" checked={sel.has(name(r))} disabled={!can(r)} onChange={() => toggle(name(r))}
                      title={r.status === "running" ? "running: stop it first" : r.status === "in use" && !allowInUse ? "in use: tick “also folders in use”" : ""} /></td>
                    <td className="mono">{r.kind === "label" && r.status !== "no summary" ? <Link href={href("/label/run", { run: name(r) })}>{name(r)}</Link> : name(r)}</td>
                    <td>{r.kind}</td>
                    <td><span className={`badge ${statusClass(r.status)}`}>{r.status}</span></td>
                    <td className="faint" style={{ fontSize: 12 }}>{r.reason}</td>
                    <td className="mono" style={{ fontSize: 12 }}>{r.finished}</td>
                    <td className="mono" style={{ fontSize: 12 }}>{r.corpus || r.input}</td>
                  </tr>))}
                {!rows.length ? <tr><td colSpan={7} className="muted">no run folders</td></tr> : null}
              </tbody>
            </table>
          </div>
        </div>) : null}
    </>
  );
}

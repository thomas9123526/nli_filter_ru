"use client";
// Browse the corpus of a dataset: folders → files → lines (20 per page). Every line can be read in full and,
// when the dataset is editable, its text field edited (the corpus file, also .zst / .gz, is rewritten).
// Changes can be saved one by one, or collected as pending changes and saved together in one rewrite.
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ApiError, api, useApi } from "@/lib/api";
import { href, num } from "@/lib/format";
import type { CorpusLine } from "@/lib/types";
import { EditHistory, TextEditor } from "./TextEditor";
import { FileChanges, InsertForm, deleteLine, fieldTemplate } from "./LineInsert";
import { TryPanel, type TryControl } from "./TryPanel";
import { LabelLineBox, LabelPagePanel } from "./LabelPagePanel";
import type { LabelLineResult } from "@/lib/types";
import { TryLineResult } from "./TryResult";
import type { TryResult } from "@/lib/types";
import { Crumbs, ErrorBox, Loading } from "./ui";

const PAGE = 20;
const PREVIEW = 600;

export function CorpusView() {
  const sp = useSearchParams();
  const ds = sp.get("ds") || "";
  const dir = sp.get("dir") || "";
  const file = sp.get("file") || "";
  if (!ds) return <div className="alert error">Missing ?ds=</div>;
  // ?line=N: open the page at line N (2 lines of context above), highlight it; &edit=1 also opens its editor
  const target = Math.max(0, Math.floor(Number(sp.get("line")) || 0));
  const start = Number(sp.get("start")) || (target ? Math.max(1, target - 2) : 1);
  return file ? <FileLines ds={ds} file={file} member={sp.get("member") || ""} start={Math.max(1, start)}
    target={target || null} editTarget={sp.get("edit") === "1"} />
    : <Folder ds={ds} dir={dir} />;
}

function pathCrumbs(ds: string, path: string, last?: string) {
  const parts = path ? path.split("/") : [];
  const items: { label: string; href?: string }[] = [
    { label: "Datasets", href: "/" }, { label: ds, href: href("/dataset", { ds }) }, { label: "corpus", href: href("/corpus", { ds }) },
  ];
  parts.forEach((p, i) => {
    const sub = parts.slice(0, i + 1).join("/");
    items.push(i === parts.length - 1 && last === undefined ? { label: p } : { label: p, href: href("/corpus", { ds, dir: sub }) });
  });
  if (last !== undefined) items.push({ label: last });
  return items;
}

function Folder({ ds, dir }: { ds: string; dir: string }) {
  const res = useApi(`browse:${ds}:${dir}`, (s) => api.browse(ds, dir, s));
  const status = useApi(`es:${ds}`, (s) => api.editStatus(ds, "", s));
  return (
    <>
      <div className="page-head">
        <div>
          <Crumbs items={pathCrumbs(ds, dir)} />
          <h1>Corpus{dir ? <span className="mono" style={{ fontSize: 18 }}> · {dir}</span> : null}</h1>
        </div>
      </div>
      <EditBanner status={status.data} />
      <ErrorBox error={res.error} onRetry={res.reload} />
      {res.loading && !res.data ? <Loading what="Listing the folder" /> : null}
      {res.data ? (
        <div className="panel flush">
          <div className="table-wrap">
            <table>
              <thead><tr><th>Name</th><th className="num">Size</th></tr></thead>
              <tbody>
                {dir ? (
                  <tr><td><Link href={href("/corpus", { ds, dir: dir.split("/").slice(0, -1).join("/") })}>‹ up</Link></td><td /></tr>
                ) : null}
                {res.data.entries.map((e) => (
                  <tr key={e.path}>
                    <td className="mono">
                      {e.is_dir
                        ? <Link href={href("/corpus", { ds, dir: e.path })}>{e.name}/</Link>
                        : <Link href={href("/corpus", { ds, file: e.path })}>{e.name}</Link>}
                    </td>
                    <td className="num mono">{e.is_dir ? "" : size(e.size)}</td>
                  </tr>
                ))}
                {res.data.entries.length === 0 ? <tr><td colSpan={2} className="muted">empty folder</td></tr> : null}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </>
  );
}

function EditBanner({ status }: { status: { editable: boolean; problem: string | null; dataset_editable: boolean } | null }) {
  if (!status) return null;
  if (status.editable) return <div className="alert" style={{ marginBottom: 16 }}>Editing is on: the text of a line can be changed with <strong>Edit</strong>. Saving rewrites the corpus file; the original is kept as a backup and every edit can be undone.</div>;
  return <div className="alert" style={{ marginBottom: 16 }}><span className="badge neutral">read-only</span> {status.problem}</div>;
}

type Pending = { text: string; sha1: string; saved: string; id: unknown };

function FileLines({ ds, file, member: wanted, start, target, editTarget }: {
  ds: string; file: string; member: string; start: number; target: number | null; editTarget: boolean;
}) {
  // the target line's editor opens once on arrival, not again after a save or reload
  const [autoEditDone, setAutoEditDone] = useState(false);
  useEffect(() => setAutoEditDone(false), [ds, file, target]);
  const router = useRouter();
  const [version, setVersion] = useState(0);
  const res = useApi(`lines:${ds}:${file}:${wanted}:${start}:${version}`,
    (s) => api.corpusLines(ds, { path: file, member: wanted, start, count: PAGE, preview: PREVIEW }, s));
  const data = res.data;
  const member = data?.member || null;  // .zip / .rar: the member shown (the first one unless chosen)
  const status = useApi(data ? `es:${ds}:${file}:${member || ""}` : null, (s) => api.editStatus(ds, file, s, member));
  const total = data?.total_lines ?? 0;
  const go = (n: number) => router.push(href("/corpus", { ds, file, member: wanted || null, start: Math.min(Math.max(1, n), Math.max(1, total)) }));
  const [jumpTo, setJumpTo] = useState("");
  const folder = file.split("/").slice(0, -1).join("/");
  const name = file.split("/").slice(-1)[0];
  const editable = !!status.data?.editable;

  // unsaved changes of this file (kept while paging), saved together in one rewrite
  const [pending, setPending] = useState<Record<number, Pending>>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<ApiError | null>(null);
  const [savedNote, setSavedNote] = useState<string | null>(null);
  const [inserting, setInserting] = useState<number | null>(null);  // insert after this line (0 = at the top)
  const [changesVersion, setChangesVersion] = useState(0);
  const [tried, setTried] = useState<Record<number, TryResult>>({});  // "Try settings" results by line
  const [tryCtl, setTryCtl] = useState<TryControl | null>(null);
  const [labelled, setLabelled] = useState<{ policy: string; results: Record<number, LabelLineResult> } | null>(null);
  const nPending = Object.keys(pending).length;
  const reload = () => { setInserting(null); setVersion((v) => v + 1); setChangesVersion((v) => v + 1); };
  const lastPage = !!data && start + PAGE > total;
  const structural = editable && !nPending;  // inserting / deleting moves lines: not with unsaved changes
  useEffect(() => { setPending({}); setSavedNote(null); setSaveError(null); }, [ds, file, member]);
  useEffect(() => {
    if (!nPending) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [nPending]);
  // first look at a big file: decision links are prepared in the background; ask again until they are there
  useEffect(() => {
    if (!data?.decisions_pending) return;
    const t = setTimeout(() => setVersion((v) => v + 1), 3000);
    return () => clearTimeout(t);
  }, [data]);

  const stage = (l: CorpusLine, sha1: string, saved: string, text: string) =>
    setPending((p) => {
      const next = { ...p };
      if (text === saved) delete next[l.line];
      else next[l.line] = { text, sha1: p[l.line]?.sha1 ?? sha1, saved, id: l.id };
      return next;
    });
  const discard = (line: number) => setPending((p) => { const n = { ...p }; delete n[line]; return n; });

  async function saveAll() {
    setSaving(true);
    setSaveError(null);
    setSavedNote(null);
    try {
      const changes = Object.entries(pending).map(([line, p]) => ({ line: Number(line), text: p.text, sha1: p.sha1 }));
      const r = await api.editBatch(ds, { path: file, member, changes });
      setPending({});
      setSavedNote(`${r.changed} line${r.changed === 1 ? "" : "s"} saved in ${r.seconds.toFixed(1)} s (one rewrite of the file).`);
      setVersion((v) => v + 1);
    } catch (e) {
      setSaveError(e instanceof ApiError ? e : new ApiError((e as Error).message, 0));
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <div style={{ minWidth: 0 }}>
          <Crumbs items={pathCrumbs(ds, folder, name)} />
          <h1 className="mono" style={{ fontSize: 18 }}>{file}</h1>
          {data?.members ? (
            <div className="row" style={{ margin: "6px 0" }}>
              <span className="muted">archive member</span>
              <select value={member || ""} disabled={nPending > 0} title={nPending ? "save or discard the pending changes first" : ""}
                onChange={(e) => router.push(href("/corpus", { ds, file, member: e.target.value }))} data-testid="member-select">
                {data.members.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
              <span className="faint">{data.members.length} member{data.members.length === 1 ? "" : "s"}</span>
            </div>
          ) : null}
          {data ? <div className="muted">{num(total)} lines · field “{data.text_field}”{data.file_key ? <> · <Link href={href("/file", { ds, f: data.file_key })}>filter results of this file</Link></> : " · no filter results for this file"}</div> : null}
        </div>
      </div>
      <EditBanner status={status.data} />
      {nPending ? (
        <div className="pending-bar" data-testid="pending-bar">
          <strong>{nPending} unsaved change{nPending === 1 ? "" : "s"}</strong>
          <span className="muted">lines {Object.keys(pending).map(Number).sort((a, b) => a - b).slice(0, 12).join(", ")}{nPending > 12 ? ", …" : ""}</span>
          <span className="spacer" />
          <button className="btn primary" onClick={saveAll} disabled={saving}>{saving ? "Saving…" : `Save all ${nPending} to the file`}</button>
          <button className="btn" onClick={() => setPending({})} disabled={saving}>Discard all</button>
        </div>
      ) : null}
      {saveError ? <div className="alert warn" style={{ marginBottom: 12 }}>Nothing was saved: {saveError.message}</div> : null}
      {savedNote ? <div className="alert" style={{ marginBottom: 12 }}>{savedNote}</div> : null}
      <div className="navbar">
        <button className="btn" disabled={start <= 1} onClick={() => go(start - PAGE)}>‹ Previous {PAGE}</button>
        <button className="btn" disabled={!data || start + PAGE > total} onClick={() => go(start + PAGE)}>Next {PAGE} ›</button>
        <span className="muted">{data ? `lines ${num(start)}–${num(Math.min(total, start + PAGE - 1))} of ${num(total)}` : "…"}</span>
        {data?.decisions_pending ? <span className="badge neutral" title="First look at this file: the decision links are being prepared in the background">linking decisions…</span> : null}
        {editable && data && start === 1 ? <button className="btn small" disabled={!structural} title={nPending ? "save or discard the pending changes first" : "insert a new first line"}
          onClick={() => setInserting(0)}>Insert at top</button> : null}
        {editable && data && lastPage && total > 0 ? <button className="btn small" disabled={!structural} title={nPending ? "save or discard the pending changes first" : "add a line after the last one"}
          onClick={() => setInserting(total)}>Add at end</button> : null}
        <span className="spacer" />
        <form className="row" onSubmit={(e) => { e.preventDefault(); if (Number(jumpTo) >= 1) go(Number(jumpTo)); }}>
          <input type="number" min={1} placeholder="line" value={jumpTo} onChange={(e) => setJumpTo(e.target.value)} />
          <button className="btn" type="submit">Go to line</button>
        </form>
      </div>
      <ErrorBox error={res.error} onRetry={res.reload} />
      {res.loading && !data ? <Loading what="Reading the file (a .zst file is decompressed once into the cache)" /> : null}
      {data ? <FileChanges ds={ds} path={file} member={member} version={changesVersion} onChanged={reload} /> : null}
      {data ? <TryPanel ds={ds} path={file} member={member} lines={data.lines.filter((l) => !l.error).map((l) => l.line)}
        lineInfo={Object.fromEntries(data.lines.map((l) => [l.line, { id: l.id, text: l.text, length: l.text_length, extra: l.extra }]))}
        onResults={(r) => setTried(r ? Object.fromEntries(r.results.map((x) => [x.line, x])) : {})}
        onControl={setTryCtl} /> : null}
      {data ? <LabelPagePanel ds={ds} path={file} member={member} lines={data.lines.filter((l) => !l.error).map((l) => l.line)}
        onResults={setLabelled} /> : null}
      {data && inserting !== null && (inserting === 0 || inserting === total) ? (
        <InsertForm ds={ds} path={file} member={member} after={inserting} idField={data.id_field} textField={data.text_field}
          sha1={(inserting === 0 ? data.lines[0]?.sha1 : data.lines[data.lines.length - 1]?.sha1) || ""}
          template={fieldTemplate((inserting === 0 ? data.lines[0] : data.lines[data.lines.length - 1])?.extra)}
          where={inserting === 0 ? "at the top" : `at the end (line ${total + 1})`} onDone={reload} onCancel={() => setInserting(null)} />
      ) : null}
      {data ? (
        <div className="stack" style={{ opacity: res.loading && !data.decisions_pending ? 0.6 : 1 }}>
          {data.lines.map((l) => (<div key={`${member || ""}:${l.line}:${l.sha1}`} className="stack" style={{ gap: 8 }}>
            <LineCard ds={ds} file={file} member={member} fileKey={data.file_key} l={l} editable={editable}
              textField={data.text_field} idField={data.id_field}
              pending={pending[l.line]} onStage={(sha1, saved, text) => stage(l, sha1, saved, text)} onDiscard={() => discard(l.line)}
              onChanged={reload} structural={structural} tried={tried[l.line]}
              labelled={labelled?.results[l.line] ? <LabelLineBox r={labelled.results[l.line]} policy={labelled.policy} ds={ds} path={file} /> : null}
              isTarget={l.line === target} autoEdit={l.line === target && editTarget && !autoEditDone} onAutoEdit={() => setAutoEditDone(true)}
              editProblem={status.data ? status.data.problem : "checking…"}
              onInsertBelow={() => setInserting(l.line)}
              onDelete={async () => { try { if (await deleteLine(ds, file, member, l.line, l.sha1, l.id)) reload(); } catch (e) { setSaveError(e instanceof ApiError ? e : new ApiError((e as Error).message, 0)); } }} />
            {inserting === l.line && l.line !== total ? (
              <InsertForm ds={ds} path={file} member={member} after={l.line} sha1={l.sha1} idField={data.id_field} textField={data.text_field}
                template={fieldTemplate(l.extra)} where={`after line ${l.line}`} onDone={reload} onCancel={() => setInserting(null)} />
            ) : null}
          </div>))}
          {data.lines.length === 0 ? <div className="muted">The file is empty.</div> : null}
          {tryCtl?.ready && data.lines.length > 3 ? (
            <div className="row try-bottom">
              <button className="btn primary" onClick={() => { tryCtl.run(); window.scrollTo({ top: 0, behavior: "smooth" }); }} disabled={tryCtl.running}>
                {tryCtl.running ? "Running…" : `Run on the ${tryCtl.count} line${tryCtl.count === 1 ? "" : "s"} of this page`}</button>
              <span className="faint">with the settings of “Try settings” above</span>
            </div>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

function LineCard({ ds, file, member, fileKey, l, editable, pending, onStage, onDiscard, onChanged, structural, onInsertBelow, onDelete, tried,
  isTarget, autoEdit, onAutoEdit, editProblem, textField, idField, labelled }: {
  labelled?: React.ReactNode;
  ds: string; file: string; member: string | null; fileKey: string | null; l: CorpusLine; editable: boolean; pending?: Pending;
  onStage: (sha1: string, saved: string, text: string) => void; onDiscard: () => void; onChanged: () => void;
  structural: boolean; onInsertBelow: () => void; onDelete: () => void; tried?: TryResult;
  isTarget?: boolean; autoEdit?: boolean; onAutoEdit?: () => void; editProblem?: string | null;
  textField?: string; idField?: string;
}) {
  const [full, setFull] = useState<CorpusLine | null>(null);
  const [mode, setMode] = useState<"view" | "full" | "edit">("view");
  const [error, setError] = useState<ApiError | null>(null);
  const [historyVersion, setHistoryVersion] = useState(0);
  const card = useRef<HTMLDivElement>(null);
  useEffect(() => setFull(null), [l.sha1]);
  useEffect(() => {
    if (isTarget) card.current?.scrollIntoView({ block: "center" });
  }, [isTarget]);
  useEffect(() => {
    // editable comes from a second request: wait for it, then open the editor once
    if (autoEdit && editable && l.text !== null && !pending) {
      onAutoEdit?.();
      load("edit");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoEdit, editable]);

  async function load(next: "full" | "edit") {
    setError(null);
    if (!l.truncated || full) { setMode(next); return; }
    try {
      const r = await api.corpusLines(ds, { path: file, member, start: l.line, count: 1 });
      setFull(r.lines[0]);
      setMode(next);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError((e as Error).message, 0));
    }
  }
  const line = full || l;
  const saved = () => { setMode("view"); setFull(null); setHistoryVersion((v) => v + 1); onChanged(); };

  return (
    <div className={`panel line-card${pending ? " pending" : ""}${isTarget ? " target" : ""}`} data-testid={`line-${l.line}`} ref={card}>
      <div className="row">
        <strong className="mono">line {l.line}</strong>
        {l.id !== null && l.id !== undefined ? <span className="muted mono">id {String(l.id)}</span> : null}
        {(() => {  // the line's label ("expect" field), when it has one
          const e = l.extra?.expect;
          if (e === null || e === undefined || String(e).trim() === "") return null;
          const v = String(e).trim();
          return <span className={`badge ${v === "filter" || v === "keep" ? v : "warn"}`} title="the expect field of this line" data-testid={`expect-${l.line}`}>expect {v}</span>;
        })()}
        {l.edits ? <span className="badge warn">edited {l.edits}×</span> : null}
        {l.inserted ? <span className="badge keep" title="added in the viewer after the filter run: no decision yet">new</span> : null}
        {pending ? <span className="badge accent">unsaved change</span> : null}
        {l.row && fileKey ? <Link className="btn small" href={href("/record", { ds, f: fileKey, row: l.row })}>decision ›</Link> : null}
        {editable && l.text !== null && mode !== "edit" ? <button className="btn small" onClick={() => load("edit")} data-testid={`edit-${l.line}`}>{pending ? "Edit again" : "Edit"}</button> : null}
        {!editable && l.text !== null ? <button className="btn small" disabled title={`Editing is off: ${editProblem || "this file cannot be edited"}`}>Edit</button> : null}
        <span className="spacer" />
        {l.truncated && mode === "view" && !pending ? <button className="btn small ghost" onClick={() => load("full")}>Show all ({num(l.text_length)} chars)</button> : null}
        {mode === "full" ? <button className="btn small ghost" onClick={() => setMode("view")}>Show less</button> : null}
        {pending && mode !== "edit" ? <button className="btn small ghost" onClick={onDiscard}>Discard change</button> : null}
        {editable && mode !== "edit" && !pending ? <>
          <button className="btn small ghost" disabled={!structural} title={structural ? "insert a new line after this one" : "save or discard the pending changes first"} onClick={onInsertBelow}>Insert below</button>
          <button className="btn small ghost danger" disabled={!structural} title={structural ? "delete this line" : "save or discard the pending changes first"} onClick={onDelete}>Delete</button>
        </> : null}
      </div>
      {l.error ? <div className="alert warn">{l.error}{l.raw ? <pre className="json">{l.raw}</pre> : null}</div> : null}
      {mode === "edit" && line.text !== null ? (
        <TextEditor ds={ds} path={file} member={member} line={l.line} text={line.text} sha1={line.sha1} initial={pending?.text}
          fields={line.extra || {}} textField={textField} idField={idField} id={line.id}
          onSaved={() => { onDiscard(); saved(); }} onCancel={() => setMode("view")}
          onStage={(v) => { onStage(line.sha1, line.text as string, v); setMode("view"); }} />
      ) : pending ? (
        <>
          <div className="diff-old">{line.text}</div>
          <div className="diff-new">{pending.text}</div>
        </>
      ) : line.text !== null ? (
        <div className="current-text">{mode === "full" ? line.text : l.text}{mode === "view" && l.truncated ? "…" : ""}</div>
      ) : !l.error ? <div className="muted">(no text field)</div> : null}
      {tried && tried.decision ? <TryLineResult r={tried} /> : null}
      {labelled}
      {error ? <ErrorBox error={error} /> : null}
      {l.edits ? <EditHistory ds={ds} path={file} member={member} line={l.line} version={historyVersion} onChanged={saved} /> : null}
    </div>
  );
}

function size(n: number | null): string {
  if (n === null || n === undefined) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

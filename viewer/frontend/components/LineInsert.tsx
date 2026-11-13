"use client";
// Insert a new corpus line (id + text + the other fields as JSON), delete a line, and the recent changes of a
// file with Undo (the only place a deleted line can be brought back).
import { useEffect, useRef, useState } from "react";
import { ApiError, api, useApi } from "@/lib/api";
import type { EditEntry } from "@/lib/types";

/** Template for the other fields: the neighbour's field names, strings emptied, other values null. */
export function fieldTemplate(extra: Record<string, unknown> | undefined): string {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(extra || {})) out[k] = typeof v === "string" ? "" : null;
  return JSON.stringify(out, null, 2);
}

export function InsertForm({ ds, path, member, after, sha1, idField, textField, template, where, onDone, onCancel }: {
  ds: string; path: string; member: string | null; after: number; sha1: string; idField: string; textField: string;
  template: string; where: string; onDone: () => void; onCancel: () => void;
}) {
  const [id, setId] = useState("");
  const [text, setText] = useState("");
  const [extra, setExtra] = useState(template);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const first = useRef<HTMLInputElement>(null);
  useEffect(() => { first.current?.focus(); }, []);

  async function save() {
    setError(null);
    let fields: Record<string, unknown> = {};
    try {
      const parsed = extra.trim() ? JSON.parse(extra) : {};
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) throw new Error("not a JSON object");
      fields = parsed;
    } catch (e) {
      setError(`Other fields: ${(e as Error).message}`);
      return;
    }
    if (!id.trim()) { setError(`The new line needs an “${idField}”.`); return; }
    setSaving(true);
    try {
      await api.insertLine(ds, { path, member, after, sha1, record: { [idField]: id.trim(), [textField]: text, ...fields } });
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : (e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="panel insert-form" data-testid="insert-form">
      <div className="row"><strong>New line {where}</strong><span className="spacer" /><span className="faint">the lines after it move down by one</span></div>
      <label className="field"><span>{idField}</span>
        <input ref={first} type="text" value={id} onChange={(e) => setId(e.target.value)} placeholder="unique in this file" disabled={saving} />
      </label>
      <label className="field"><span>{textField}</span>
        <div className="editor"><textarea value={text} rows={6} onChange={(e) => setText(e.target.value)} disabled={saving} spellCheck={false} /></div>
      </label>
      <label className="field"><span>other fields (JSON)</span>
        <div className="editor"><textarea className="mono" value={extra} rows={Math.min(10, Math.max(3, extra.split("\n").length))}
          onChange={(e) => setExtra(e.target.value)} disabled={saving} spellCheck={false} /></div>
      </label>
      <div className="row">
        <button className="btn primary" onClick={save} disabled={saving}>{saving ? "Inserting…" : "Insert into the corpus file"}</button>
        <button className="btn" onClick={onCancel} disabled={saving}>Cancel</button>
      </div>
      {error ? <div className="alert warn">{error}</div> : null}
    </div>
  );
}

export async function deleteLine(ds: string, path: string, member: string | null, line: number, sha1: string, id: unknown) {
  const what = id !== null && id !== undefined ? `line ${line} (id ${String(id)})` : `line ${line}`;
  if (!window.confirm(`Delete ${what} from the corpus file?\n\nThe lines after it move up by one. It can be brought back with Undo under “Recent changes in this file”.`)) return false;
  await api.deleteLine(ds, { path, member, line, sha1 });
  return true;
}

const KIND_LABEL: Record<string, string> = { insert: "inserted", delete: "deleted", text: "text" };

/** The latest changes of one file (or archive member), newest first, each with Undo. */
export function FileChanges({ ds, path, member, version, onChanged }: {
  ds: string; path: string; member: string | null; version: number; onChanged: () => void;
}) {
  const res = useApi(`fileedits:${ds}:${path}:${member || ""}:${version}`, (s) => api.edits(ds, { path, member }, s));
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const edits: EditEntry[] = [...(res.data?.edits || [])].reverse().slice(0, 30);
  if (!edits.length) return null;

  async function undo(e: EditEntry) {
    setBusy(e.edit);
    setError(null);
    try {
      await api.undoEdit(ds, e.edit);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError((err as Error).message, 0));
    } finally {
      setBusy(null);
    }
  }

  return (
    <details className="panel file-changes" data-testid="file-changes">
      <summary>Recent changes in this file ({res.data?.edits.length})</summary>
      <table>
        <tbody>
          {edits.map((e) => (
            <tr key={e.edit}>
              <td className="nowrap mono faint">{e.time}</td>
              <td className="nowrap">
                <span className={`badge ${e.kind === "delete" ? "filter" : e.kind === "insert" ? "keep" : "neutral"}`}>{KIND_LABEL[e.kind || "text"]}</span>
                {e.undo_of ? <span className="badge neutral">undo</span> : null}
              </td>
              <td className="nowrap mono">line {e.kind === "delete" ? e.line : (e.current_line ?? `${e.line} (gone)`)}</td>
              <td>
                {e.id !== null && e.id !== undefined ? <span className="muted mono">id {String(e.id)} · </span> : null}
                <span className="faint">{short(e.kind === "delete" ? e.old : e.new)}</span>
              </td>
              <td className="nowrap"><button className="btn small" disabled={busy !== null} onClick={() => undo(e)}>{busy === e.edit ? "Undoing…" : "Undo"}</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      {error ? <div className="alert warn">{error.message}</div> : null}
    </details>
  );
}

function short(t: string, n = 140): string {
  return t.length > n ? `${t.slice(0, n)}…` : t || "(empty)";
}

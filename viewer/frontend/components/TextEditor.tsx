"use client";
// Edit the text field of one corpus line. Saving rewrites the corpus file (also .zst / .gz) on the backend;
// the sha1 of the line as loaded is sent along, so a line changed in the meantime is not overwritten (409).
import { useEffect, useRef, useState } from "react";
import { ApiError, api, useApi } from "@/lib/api";
import type { EditResp } from "@/lib/types";
import { ErrorBox } from "./ui";

export function TextEditor({ ds, path, line, text, sha1, onSaved, onCancel, initial, onStage }: {
  ds: string; path: string; line: number; text: string; sha1: string;
  onSaved: (r: EditResp) => void; onCancel: () => void;
  initial?: string;                    // start from this (an unsaved change) instead of the saved text
  onStage?: (value: string) => void;   // "Add to pending changes": saved later with others in one rewrite
}) {
  const [value, setValue] = useState(initial ?? text);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    box.current?.focus();
  }, []);
  const changed = value !== text;

  async function save() {
    if (!changed || saving) return;
    setSaving(true);
    setError(null);
    try {
      onSaved(await api.editText(ds, { path, line, text: value, sha1 }));
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError((e as Error).message, 0));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="editor" data-testid="text-editor">
      <textarea ref={box} value={value} spellCheck={false} disabled={saving}
        rows={Math.min(30, Math.max(6, Math.ceil(value.length / 90) + value.split("\n").length))}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); save(); }
          else if (e.key === "Escape") { e.preventDefault(); onCancel(); }
        }} />
      <div className="row">
        <button className="btn primary" onClick={save} disabled={!changed || saving}>{saving ? "Saving…" : "Save to corpus file"}</button>
        {onStage ? <button className="btn" onClick={() => onStage(value)} disabled={saving || value === (initial ?? text)}
          title="Keep this change and save it later together with others (one rewrite of the file)">Add to pending changes</button> : null}
        <button className="btn" onClick={onCancel} disabled={saving}>Cancel</button>
        {changed ? <button className="btn ghost small" onClick={() => setValue(text)} disabled={saving}>Reset</button> : null}
        <span className="spacer" />
        <span className="faint">{value.length.toLocaleString("en-US")} characters{changed ? ` (was ${text.length.toLocaleString("en-US")})` : ""} · <span className="kbd">Ctrl</span>+<span className="kbd">Enter</span> save · <span className="kbd">Esc</span> cancel</span>
      </div>
      <div className="faint" style={{ fontSize: 12 }}>
        Saving rewrites <span className="mono">{path}</span> (line {line}, text only; id and other fields stay). The first edit of a file keeps a copy of the original; every edit can be undone.
      </div>
      {error ? (
        error.status === 409
          ? <div className="alert warn">{error.message}</div>
          : <ErrorBox error={error} />
      ) : null}
    </div>
  );
}

/** Edits of one line (newest first) with an Undo button; Undo only works for the line's latest change. */
export function EditHistory({ ds, path, line, version, onChanged }: {
  ds: string; path: string; line: number; version: number; onChanged: (r: EditResp) => void;
}) {
  const res = useApi(`edits:${ds}:${path}:${line}:${version}`, (s) => api.edits(ds, { path, line }, s));
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const edits = [...(res.data?.edits || [])].reverse();
  if (!edits.length) return null;

  async function undo(id: string) {
    setBusy(id);
    setError(null);
    try {
      onChanged(await api.undoEdit(ds, id));
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError((e as Error).message, 0));
    } finally {
      setBusy(null);
    }
  }

  return (
    <details className="edit-history">
      <summary>Edit history of this line ({edits.length})</summary>
      <table>
        <tbody>
          {edits.map((e, i) => (
            <tr key={e.edit}>
              <td className="nowrap mono faint">{e.time}</td>
              <td>
                {e.undo_of ? <span className="badge neutral">undo</span> : null}
                <div className="diff-old" title={e.old}>{short(e.old)}</div>
                <div className="diff-new" title={e.new}>{short(e.new)}</div>
              </td>
              <td className="nowrap">
                {i === 0 ? <button className="btn small" disabled={busy !== null} onClick={() => undo(e.edit)}>{busy === e.edit ? "Undoing…" : "Undo"}</button> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {error ? <div className="alert warn">{error.message}</div> : null}
    </details>
  );
}

function short(t: string, n = 240): string {
  return t.length > n ? `${t.slice(0, n)}… (${t.length.toLocaleString("en-US")} chars)` : t || "(empty)";
}

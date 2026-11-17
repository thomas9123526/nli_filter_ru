"use client";
// Edit one corpus line: its text field and, when `fields` is given, its other fields (expect, category, ...).
// Saving rewrites the corpus file (also .zst / .gz) on the backend; the sha1 of the line as loaded is sent along,
// so a line changed in the meantime is not overwritten (409). The id field cannot be changed here.
import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, useApi } from "@/lib/api";
import type { EditResp, LineChange } from "@/lib/types";
import { ErrorBox } from "./ui";

/** One row of the fields table. orig = the field's name when loaded (null = added here). */
type FieldRow = { key: string; orig: string | null; value: string; json: boolean; removed: boolean };

const asText = (v: unknown) => (typeof v === "string" ? v : JSON.stringify(v));

function fieldRows(fields: Record<string, unknown>): FieldRow[] {
  return Object.entries(fields).map(([k, v]) => ({ key: k, orig: k, value: asText(v), json: typeof v !== "string", removed: false }));
}

/** The rows -> {fields to set, fields to remove, problem}. Unchanged fields are left out. */
function fieldChanges(rows: FieldRow[], fields: Record<string, unknown>, reserved: string[]): { set: Record<string, unknown>; remove: string[]; problem: string | null } {
  const set: Record<string, unknown> = {};
  const remove: string[] = [];
  const seen = new Set<string>();
  for (const r of rows) {
    if (r.removed) { if (r.orig !== null) remove.push(r.orig); continue; }
    const key = r.key.trim();
    if (!key) return { set, remove, problem: "a field needs a name" };
    if (reserved.includes(key)) return { set, remove, problem: `'${key}' cannot be used as another field's name here` };
    if (seen.has(key)) return { set, remove, problem: `the field '${key}' is there twice` };
    seen.add(key);
    let v: unknown = r.value;
    if (r.json) {
      try { v = JSON.parse(r.value); } catch { return { set, remove, problem: `'${key}': not valid JSON (a number, true, false, null, [...] or {...}); untick JSON for plain text` }; }
    }
    if (r.orig !== null && r.orig !== key) remove.push(r.orig);  // renamed
    if (r.orig === key && JSON.stringify(fields[key]) === JSON.stringify(v)) continue;  // unchanged
    set[key] = v;
  }
  return { set, remove: remove.filter((k) => !(k in set)), problem: null };
}

export function TextEditor({ ds, path, member, line, text, sha1, onSaved, onCancel, initial, onStage, fields, textField, idField, id }: {
  ds: string; path: string; member?: string | null; line: number; text: string; sha1: string;
  onSaved: (r: EditResp) => void; onCancel: () => void;
  initial?: string;                    // start from this (an unsaved change) instead of the saved text
  onStage?: (value: string) => void;   // "Add to pending changes": saved later with others in one rewrite
  fields?: Record<string, unknown> | null;  // the line's other fields: editable too (not the id)
  textField?: string; idField?: string; id?: unknown;
}) {
  const [value, setValue] = useState(initial ?? text);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [rows, setRows] = useState<FieldRow[]>(() => fieldRows(fields || {}));
  const box = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    box.current?.focus();
  }, []);
  const fc = useMemo(() => fieldChanges(rows, fields || {}, [textField || "text", idField || "id"]), [rows, fields, textField, idField]);
  const fieldsChanged = Object.keys(fc.set).length > 0 || fc.remove.length > 0;
  const textChanged = value !== text;
  const changed = textChanged || fieldsChanged;
  const setRow = (i: number, p: Partial<FieldRow>) => setRows((rs) => rs.map((r, k) => (k === i ? { ...r, ...p } : r)));

  async function save() {
    if (!changed || saving || fc.problem) return;
    setSaving(true);
    setError(null);
    try {
      if (!fieldsChanged) {
        onSaved(await api.editText(ds, { path, member: member || null, line, text: value, sha1 }));
      } else {
        const change: LineChange = { line, sha1, fields: fc.set, remove: fc.remove, ...(textChanged ? { text: value } : {}) };
        const r = await api.editBatch(ds, { path, member: member || null, changes: [change] });
        onSaved({ ...r.lines[0], changed: r.changed > 0, entry: r.entries[0] });
      }
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
      {fields ? (
        <div className="field-editor" data-testid="field-editor">
          <div className="muted" style={{ fontSize: 12 }}>Other fields</div>
          <table>
            <tbody>
              <tr>
                <td className="mono">{idField || "id"}</td>
                <td className="mono muted" colSpan={3}>{id === undefined || id === null ? "–" : asText(id)} <span className="faint">(cannot be changed: the filter's decisions are linked to it)</span></td>
              </tr>
              {rows.map((r, i) => (
                <tr key={i} className={r.removed ? "removed" : ""}>
                  <td><input type="text" className="mono" value={r.key} placeholder="name" disabled={saving || r.removed}
                    onChange={(e) => setRow(i, { key: e.target.value })} data-testid={`field-key-${i}`} /></td>
                  <td style={{ width: "100%" }}><input type="text" className={r.json ? "mono" : ""} value={r.value} disabled={saving || r.removed}
                    placeholder={r.json ? "JSON: 3, true, null, [..]" : "text"} style={{ width: "100%" }}
                    onChange={(e) => setRow(i, { value: e.target.value })}
                    onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); save(); } }}
                    data-testid={`field-value-${i}`} /></td>
                  <td className="nowrap"><label className="faint" title="the value is JSON (number, true / false, null, list, object) instead of text">
                    <input type="checkbox" checked={r.json} disabled={saving || r.removed} onChange={(e) => setRow(i, { json: e.target.checked })} /> JSON</label></td>
                  <td className="nowrap">{r.orig === null
                    ? <button className="btn small ghost" title="drop this new field" onClick={() => setRows((rs) => rs.filter((_, k) => k !== i))}>✕</button>
                    : <button className="btn small ghost" title={r.removed ? "keep this field" : "remove this field from the line"}
                      onClick={() => setRow(i, { removed: !r.removed })}>{r.removed ? "Keep" : "✕"}</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="row">
            <button className="btn small ghost" disabled={saving} onClick={() => setRows((rs) => [...rs, { key: "", orig: null, value: "", json: false, removed: false }])}
              data-testid="add-field">+ add field</button>
            {fieldsChanged ? <button className="btn small ghost" disabled={saving} onClick={() => setRows(fieldRows(fields))}>Reset fields</button> : null}
            {fc.problem ? <span className="badge warn">{fc.problem}</span> : null}
          </div>
        </div>
      ) : null}
      <div className="row">
        <button className="btn primary" onClick={save} disabled={!changed || saving || !!fc.problem}>{saving ? "Saving…" : "Save to corpus file"}</button>
        {onStage ? <button className="btn" onClick={() => onStage(value)} disabled={saving || value === (initial ?? text) || fieldsChanged}
          title={fieldsChanged ? "changes of other fields are saved at once (Save to corpus file), not as pending changes"
            : "Keep this change and save it later together with others (one rewrite of the file)"}>Add to pending changes</button> : null}
        <button className="btn" onClick={onCancel} disabled={saving}>Cancel</button>
        {textChanged ? <button className="btn ghost small" onClick={() => setValue(text)} disabled={saving}>Reset</button> : null}
        <span className="spacer" />
        <span className="faint">{value.length.toLocaleString("en-US")} characters{textChanged ? ` (was ${text.length.toLocaleString("en-US")})` : ""} · <span className="kbd">Ctrl</span>+<span className="kbd">Enter</span> save · <span className="kbd">Esc</span> cancel</span>
      </div>
      <div className="faint" style={{ fontSize: 12 }}>
        Saving rewrites <span className="mono">{path}</span>{member ? <> (member <span className="mono">{member}</span>)</> : null} (line {line}{fields ? "; the id stays" : ", text only; id and other fields stay"}). The first edit of a file keeps a copy of the original; every edit can be undone.
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
export function EditHistory({ ds, path, member, line, version, onChanged }: {
  ds: string; path: string; member?: string | null; line: number; version: number; onChanged: (r: EditResp) => void;
}) {
  const res = useApi(`edits:${ds}:${path}:${member || ""}:${line}:${version}`,
    (s) => api.edits(ds, { path, line, member: member || null }, s));
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
                {e.kind === "insert" ? <span className="badge keep">inserted</span> : null}
                {e.kind === "insert" ? <div className="diff-new" title={e.new}>{short(e.new)}</div> : e.old !== e.new || !e.fields ? <>
                  <div className="diff-old" title={e.old}>{short(e.old)}</div>
                  <div className="diff-new" title={e.new}>{short(e.new)}</div>
                </> : null}
                {e.fields ? Object.entries(e.fields).map(([k, f]) => (
                  <div key={k} className="mono" style={{ fontSize: 12 }}>
                    {k}: {f.added ? <span className="badge keep">added</span> : <span className="diff-old inline">{asText(f.old)}</span>}
                    {" → "}{f.removed ? <span className="badge filter">removed</span> : <span className="diff-new inline">{asText(f.new)}</span>}
                  </div>
                )) : null}
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

"use client";
// Try page, "Edit cases": change the case set (labels/*cases*.json) in place. Edits stay on the page until Save; Save
// writes the file (the old one goes to labels/.backup/) and rebuilds the case corpus.
import { TextTools } from "./TextTools";
import { useState } from "react";
import type { LabelCase, LabelCaseText } from "@/lib/types";
import { actionClass } from "./LabelRunView";

export const ACTIONS = ["remove", "review", "keep", "pass", "untouched"];

/** The corpus' topic field of a case text: a value from labels/topic_labels.json, or none. "+ new topic…" adds one
 * to the file (onAdd) and selects it. */
export function TopicSelect({ value, topics, onChange, onAdd }: {
  value: string | undefined; topics: string[]; onChange: (t: string | undefined) => void;
  onAdd: (t: string) => Promise<void>;
}) {
  const known = value && !topics.includes(value) ? [value, ...topics] : topics;
  return (
    <select value={value || ""} data-testid="topic-select" title="the corpus' topic field of this text (nli_label.py --topic-field topic)"
      onChange={async (e) => {
        if (e.target.value === "__new__") {
          const t = (window.prompt("New topic (it is added to labels/topic_labels.json)") || "").trim();
          if (t) { await onAdd(t); onChange(t); }
          return;
        }
        onChange(e.target.value || undefined);
      }}>
      <option value="">(no topic)</option>
      {known.map((t) => <option key={t} value={t}>{t}</option>)}
      <option value="__new__">+ new topic…</option>
    </select>
  );
}

export function newText(text: string): LabelCaseText {
  return { text, from: "added in the viewer", labels_yes: [], expected_action: "keep", note: "" };
}

export function newCaseId(cases: LabelCase[], group: string): string {
  const slug = group.split(" (")[0].toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") || "case";
  const ids = new Set(cases.map((c) => c.id));
  let n = 1;
  while (ids.has(`${slug}:${String(n).padStart(2, "0")}`)) n++;
  return `${slug}:${String(n).padStart(2, "0")}`;
}

export function CaseEditor({ c, t, ti, groups, labelKeys, boxText, onCase, onText, onAddText, onDeleteText, onAddCase,
  onDeleteCase, topics, onAddTopic }: {
  c: LabelCase; t: LabelCaseText | undefined; ti: number; groups: string[]; labelKeys: string[]; boxText: string;
  topics: string[]; onAddTopic: (t: string) => Promise<void>;
  onCase: (patch: Partial<LabelCase>) => void; onText: (patch: Partial<LabelCaseText>) => void;
  onAddText: () => void; onDeleteText: () => void; onAddCase: (group: string) => void; onDeleteCase: () => void;
}) {
  const acc = t?.acceptable || [];
  const yes = t?.labels_yes || [];
  return (
    <div className="case-editor" data-testid="case-editor">
      <div className="row"><strong>Case</strong>
        <span className="faint" style={{ fontSize: 12 }}>changing the id breaks links to old runs of this case</span></div>
      <div className="case-editor-grid">
        <label>id<input className="mono" value={c.id} onChange={(e) => onCase({ id: e.target.value })} /></label>
        <label>group<input list="case-groups" value={c.group} onChange={(e) => onCase({ group: e.target.value })} />
          <datalist id="case-groups">{groups.map((g) => <option key={g} value={g} />)}</datalist></label>
        <label>title<input value={c.title} onChange={(e) => onCase({ title: e.target.value })} /></label>
        <label className="wide">what it tests<input value={c.what} onChange={(e) => onCase({ what: e.target.value })} /></label>
      </div>
      {t ? (
        <>
          <div className="row" style={{ marginTop: 8 }}><strong>Text {ti + 1}</strong>
            {boxText !== t.text ? (
              <button className="btn small primary" onClick={() => onText({ text: boxText })} data-testid="store-box"
                title="the text in the box above becomes this case text">Store the box text in text {ti + 1}</button>
            ) : <span className="faint" style={{ fontSize: 12 }}>edit the text in the box above, then store it here</span>}
          </div>
          <div className="case-editor-grid">
            <label>expected
              <select value={t.expected_action || "keep"} onChange={(e) => onText({ expected_action: e.target.value })} data-testid="edit-expected">
                {ACTIONS.map((a) => <option key={a} value={a}>{a}</option>)}
              </select></label>
            <label>topic
              <TopicSelect value={t.topic} topics={topics} onChange={(v) => onText({ topic: v })} onAdd={onAddTopic} /></label>
            <div className="wide">also fine:{" "}
              {ACTIONS.filter((a) => a !== t.expected_action).map((a) => (
                <label key={a} className="faint" style={{ fontSize: 13, marginRight: 8 }}>
                  <input type="checkbox" checked={acc.includes(a)}
                    onChange={(e) => onText({ acceptable: e.target.checked ? [...acc, a] : acc.filter((x) => x !== a) })} /> {a}
                </label>))}
            </div>
            <div className="wide">labels that should be yes:{" "}
              {yes.map((l) => (
                <span key={l} className="chip">{l} <button className="linklike" title="remove" onClick={() => onText({ labels_yes: yes.filter((x) => x !== l) })}>×</button></span>))}
              <select value="" onChange={(e) => e.target.value && onText({ labels_yes: [...yes, e.target.value] })} data-testid="edit-add-label">
                <option value="">+ add a label</option>
                {labelKeys.filter((k) => !yes.includes(k)).map((k) => <option key={k} value={k}>{k}</option>)}
              </select>
            </div>
            <label className="wide">note<input value={t.note || ""} onChange={(e) => onText({ note: e.target.value })} /></label>
            <div className="wide faint" style={{ fontSize: 12 }}>from: {t.from}{t.your_decision ? ` · your first decision: ${t.your_decision}` : ""}</div>
          </div>
        </>
      ) : null}
      <div className="row" style={{ marginTop: 8, flexWrap: "wrap" }}>
        <button className="btn small" onClick={onAddText} data-testid="add-text" title="a new text in this case, from the box above">+ Text (from the box)</button>
        <button className="btn small" onClick={() => onAddCase(c.group)} data-testid="add-case" title="a new case in this group, with the box text">+ Case in “{c.group.split(" (")[0]}”</button>
        <button className="btn small" onClick={() => { const g = window.prompt("Name of the new group"); if (g && g.trim()) onAddCase(g.trim()); }}>+ Case in a new group</button>
        <span className="spacer" />
        <button className="btn small danger" disabled={c.texts.length < 2} onClick={() => window.confirm(`Delete text ${ti + 1} of ${c.id}?`) && onDeleteText()}
          title={c.texts.length < 2 ? "the last text: delete the case instead" : "delete this text"}>Delete text {ti + 1}</button>
        <button className="btn small danger" onClick={() => window.confirm(`Delete the whole case ${c.id} (${c.texts.length} text${c.texts.length > 1 ? "s" : ""})?`) && onDeleteCase()}
          data-testid="delete-case">Delete case</button>
      </div>
      {t ? <div className="faint" style={{ fontSize: 12, marginTop: 4 }}>Expected now: <span className={`badge ${actionClass(t.expected_action || "")}`}>{t.expected_action}</span>{acc.length ? ` (also fine: ${acc.join(", ")})` : ""}</div> : null}
    </div>
  );
}

/** "+ insert here": a new, empty case with default settings; Save puts it at the chosen place and writes the file. */
export function CaseInsertForm({ where, group, groups, labelKeys, existingIds, saving, onCancel, onSave, topics, onAddTopic }: {
  where: string; group: string; groups: string[]; labelKeys: string[]; existingIds: string[]; saving: boolean;
  topics: string[]; onAddTopic: (t: string) => Promise<void>;
  onCancel: () => void; onSave: (c: LabelCase) => void;
}) {
  const [g, setG] = useState(group);
  const [title, setTitle] = useState("");
  const [what, setWhat] = useState("");
  const [id, setId] = useState("");
  const [texts, setTexts] = useState<LabelCaseText[]>([{ ...newText(""), from: "added in the viewer" }]);
  const [err, setErr] = useState<string | null>(null);
  const autoId = newCaseId(existingIds.map((x) => ({ id: x } as LabelCase)), g || "case");
  const setT = (k: number, patch: Partial<LabelCaseText>) => setTexts((ts) => ts.map((t, i) => (i === k ? { ...t, ...patch } : t)));
  const save = () => {
    const cid = (id || autoId).trim();
    if (!g.trim()) return setErr("the group is empty");
    if (!title.trim()) return setErr("the title is empty (it is what the list shows)");
    if (existingIds.includes(cid)) return setErr(`the id ${cid} is used already`);
    if (texts.some((t) => !t.text.trim())) return setErr("a text is empty");
    setErr(null);
    onSave({ id: cid, group: g.trim(), label: null, title: title.trim(), what: what.trim(), texts });
  };
  return (
    <div className="panel case-editor" data-testid="case-insert">
      <div className="row"><strong style={{ fontSize: 16 }}>New case</strong><span className="faint" style={{ fontSize: 13 }}>{where}</span></div>
      <div className="case-editor-grid">
        <label>group<input list="case-groups-new" value={g} onChange={(e) => setG(e.target.value)} data-testid="new-group" />
          <datalist id="case-groups-new">{groups.map((x) => <option key={x} value={x} />)}</datalist></label>
        <label>title (shown in the list)<input value={title} onChange={(e) => setTitle(e.target.value)} data-testid="new-title" /></label>
        <label>id<input className="mono" value={id} placeholder={autoId} onChange={(e) => setId(e.target.value)} /></label>
        <label className="wide">what it tests<input value={what} onChange={(e) => setWhat(e.target.value)} /></label>
      </div>
      {texts.map((t, k) => {
        const acc = t.acceptable || [];
        const yes = t.labels_yes || [];
        return (
          <div key={k} className="case-editor-grid" style={{ borderTop: "1px solid var(--border)", paddingTop: 8 }}>
            <label className="wide">text {k + 1} {t.text.trim() ? <TextTools text={t.text} testid={`case-tools-${k}`} /> : null}
              <textarea className="mono try-text" value={t.text} onChange={(e) => setT(k, { text: e.target.value })} data-testid={`new-text-${k + 1}`} /></label>
            <label>expected
              <select value={t.expected_action || "keep"} onChange={(e) => setT(k, { expected_action: e.target.value, acceptable: acc.filter((a) => a !== e.target.value) })}>
                {ACTIONS.map((a) => <option key={a} value={a}>{a}</option>)}
              </select></label>
            <label>topic
              <TopicSelect value={t.topic} topics={topics} onChange={(v) => setT(k, { topic: v })} onAdd={onAddTopic} /></label>
            <div className="wide">also fine:{" "}
              {ACTIONS.filter((a) => a !== t.expected_action).map((a) => (
                <label key={a} className="faint" style={{ fontSize: 13, marginRight: 8 }}>
                  <input type="checkbox" checked={acc.includes(a)} onChange={(e) => setT(k, { acceptable: e.target.checked ? [...acc, a] : acc.filter((x) => x !== a) })} /> {a}
                </label>))}
            </div>
            <div className="wide">labels that should be yes:{" "}
              {yes.map((l) => <span key={l} className="chip">{l} <button className="linklike" onClick={() => setT(k, { labels_yes: yes.filter((x) => x !== l) })}>×</button></span>)}
              <select value="" onChange={(e) => e.target.value && setT(k, { labels_yes: [...yes, e.target.value] })}>
                <option value="">+ add a label</option>
                {labelKeys.filter((x) => !yes.includes(x)).map((x) => <option key={x} value={x}>{x}</option>)}
              </select>
            </div>
            <label className="wide">note<input value={t.note || ""} onChange={(e) => setT(k, { note: e.target.value })} /></label>
          </div>);
      })}
      <div className="row" style={{ marginTop: 8 }}>
        {texts.length < 2 ? <button className="btn small" onClick={() => setTexts((ts) => [...ts, newText("")])}>+ a second text</button>
          : <button className="btn small ghost" onClick={() => setTexts((ts) => ts.slice(0, 1))}>remove text 2</button>}
        <span className="spacer" />
        <button className="btn small ghost" onClick={onCancel}>Cancel</button>
        <button className="btn small primary" onClick={save} disabled={saving} data-testid="new-save">{saving ? "Saving…" : "Save (insert here)"}</button>
      </div>
      {err ? <div className="alert warn" style={{ marginTop: 6 }}>{err}</div> : null}
    </div>
  );
}

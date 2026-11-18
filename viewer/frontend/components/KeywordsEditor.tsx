"use client";
// Keyword lexicon editor: a table over the keyword file text (comments, blank lines and untouched lines are kept
// exactly as they are), with level / type / gloss / other meanings / exclude per keyword, checks, filters, bulk
// changes and a "Test a text" box that matches like nli_filter.py does. The text stays the saved format.
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

// ---------------------------------------------------------------- the format (same rules as nli_filter.parse_keyword_line)

export type KwEntry = { keyword: string; level: string; type: string; gloss: string; other: string[]; exclude: string[] };
type Item =
  | { kind: "text"; raw: string }                                        // comment / blank line: kept as it is
  | { kind: "kw"; id: number; raw: string; e: KwEntry; dirty: boolean; extra?: number };  // extra: columns beyond 6

const COLS = 6;
const TYPE_RE = /^[a-z][a-z0-9_-]*$/;
export const KNOWN_TYPES = ["country", "demonym", "city", "region", "org", "person", "language", "event", "brand"];

const cell = (v: string | undefined) => { const s = (v || "").trim(); return s === "-" ? "" : s; };
const multi = (v: string | undefined) => cell(v).split(/\s+\|\s+/).map((x) => x.trim()).filter((x) => x && x !== "-");

let nextId = 1;
export function parseText(text: string): Item[] {
  return text.split(/\r?\n/).map((raw): Item => {
    if (!raw.trim() || raw.trimStart().startsWith("#")) return { kind: "text", raw };
    const c = raw.split("\t");
    return {
      kind: "kw", id: nextId++, raw, dirty: false, extra: c.length > COLS ? c.length - COLS : undefined,
      e: { keyword: c[0].trim(), level: (cell(c[1]) || "B").toUpperCase(), type: cell(c[2]).toLowerCase(), gloss: cell(c[3]), other: multi(c[4]), exclude: multi(c[5]) },
    };
  });
}

export function entryLine(e: KwEntry): string {
  const cols = [e.keyword.trim(), e.level || "B", e.type || "-", e.gloss.trim() || "-", e.other.join(" | ") || "-", e.exclude.join(" | ") || "-"];
  while (cols.length > 1 && (cols[cols.length - 1] === "-" || (cols.length === 2 && cols[1] === "B"))) cols.pop();
  return cols.join("\t");
}

export function serialize(items: Item[]): string {
  // a new row without a keyword stays out of the text until it has one
  return items.filter((it) => !(it.kind === "kw" && it.dirty && !it.raw && !it.e.keyword.trim()))
    .map((it) => (it.kind === "kw" && it.dirty ? entryLine(it.e) : it.raw)).join("\n");
}

type Problem = { level: "error" | "warn" | "hint"; field: keyof KwEntry | "line"; msg: string };

function jsRegex(p: string): RegExp | null {
  try { return new RegExp(p, "gi"); } catch { return null; }
}

function check(items: Item[]): Map<number, Problem[]> {
  const out = new Map<number, Problem[]>();
  const seen = new Map<string, string>();
  for (const it of items) {
    if (it.kind !== "kw") continue;
    const e = it.e, p: Problem[] = [];
    if (!e.keyword) p.push({ level: "error", field: "keyword", msg: "the keyword is empty" });
    if (it.extra && !it.dirty) p.push({ level: "error", field: "line", msg: `${COLS + it.extra} tab-separated columns, at most ${COLS}` });
    if (e.level !== "A" && e.level !== "B") p.push({ level: "error", field: "level", msg: `level '${e.level}': use A or B` });
    if (e.type && !TYPE_RE.test(e.type)) p.push({ level: "error", field: "type", msg: `type '${e.type}': one word (letters, digits, _ or -)` });
    for (const x of e.exclude) if (!jsRegex(x)) p.push({ level: "warn", field: "exclude", msg: `the pattern '${x}' is not a valid regex here (check it: nli_filter.py uses Python regex)` });
    const low = e.keyword.toLowerCase();
    if (low && seen.has(low)) p.push({ level: "warn", field: "keyword", msg: `listed twice (also '${seen.get(low)}'): the first one is used` });
    else if (low) seen.set(low, e.keyword);
    if (e.level === "A" && e.other.length) p.push({ level: "hint", field: "other", msg: "level A is filtered without models: other meanings are not used" });
    if (e.level === "B" && ["city", "region", "person", "org"].includes(e.type) && !e.gloss)
      p.push({ level: "hint", field: "gloss", msg: `a ${e.type} without a gloss: the model may not link it to the country (e.g. "a region of Russia")` });
    if (e.keyword.length === 1 && isCjk(e.keyword)) p.push({ level: "warn", field: "keyword", msg: "a single CJK character matches inside ordinary words" });
    if (p.length) out.set(it.id, p);
  }
  return out;
}

// ---------------------------------------------------------------- matching (like nli_filter.KeywordMatcher.find)

function isCjk(ch: string): boolean {
  const c = ch.codePointAt(0) || 0;
  return (0x3040 <= c && c <= 0x30ff) || (0x3400 <= c && c <= 0x4dbf) || (0x4e00 <= c && c <= 0x9fff) || (0xf900 <= c && c <= 0xfaff)
    || (0xac00 <= c && c <= 0xd7af) || (0x1100 <= c && c <= 0x11ff) || (0x3130 <= c && c <= 0x318f) || (0xff66 <= c && c <= 0xff9f);
}
const wordChar = (ch: string | undefined) => !!ch && /[\p{L}\p{N}_]/u.test(ch);
const needsBoundary = (ch: string) => /[\p{L}\p{N}]/u.test(ch) && !isCjk(ch);

export type TestHit = { start: number; end: number; e: KwEntry; excludedBy?: string };

export function findHits(text: string, entries: KwEntry[]): TestHit[] {
  const low = text.toLowerCase();
  if (low.length !== text.length) return [];
  const cands: { s: number; e: number; i: number }[] = [];
  const seen = new Set<string>();
  entries.forEach((en, i) => {
    const k = en.keyword.trim().toLowerCase();
    if (!k || seen.has(k)) return;
    seen.add(k);
    const left = needsBoundary(k[0]), right = needsBoundary(k[k.length - 1]);
    for (let s = low.indexOf(k); s >= 0; s = low.indexOf(k, s + 1)) {
      const e = s + k.length;
      if (left && wordChar(text[s - 1])) continue;
      if (right && wordChar(text[e])) continue;
      cands.push({ s, e, i });
    }
  });
  cands.sort((a, b) => a.s - b.s || b.e - a.e);
  const hits: TestHit[] = [];
  let last = -1;
  for (const c of cands) {
    if (c.s < last) continue;
    last = c.e;
    const en = entries[c.i];
    let excludedBy: string | undefined;
    for (const p of en.exclude) {
      const re = jsRegex(p);
      if (!re) continue;
      for (const m of text.matchAll(re)) {
        const ms = m.index ?? 0, me = ms + m[0].length;
        if (ms < c.e && c.s < me) { excludedBy = p; break; }
      }
      if (excludedBy) break;
    }
    hits.push({ start: c.s, end: c.e, e: en, excludedBy });
  }
  return hits;
}

// ---------------------------------------------------------------- small inputs

function ChipsInput({ values, onChange, placeholder, bad, testid }: {
  values: string[]; onChange: (v: string[]) => void; placeholder: string; bad?: (v: string) => boolean; testid?: string;
}) {
  const [draft, setDraft] = useState("");
  const add = () => { const v = draft.trim(); if (v && !values.includes(v)) onChange([...values, v]); setDraft(""); };
  return (
    <div className="chips-input" data-testid={testid}>
      {values.map((v) => (
        <span key={v} className={`chip${bad?.(v) ? " bad" : ""}`} title={bad?.(v) ? "not a valid regex" : v}>
          <span className="mono">{v}</span>
          <button type="button" className="chip-x" onClick={() => onChange(values.filter((x) => x !== v))} aria-label={`remove ${v}`}>×</button>
        </span>
      ))}
      <input type="text" value={draft} placeholder={values.length ? "" : placeholder} onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") { e.preventDefault(); add(); }
          else if (e.key === "Backspace" && !draft && values.length) onChange(values.slice(0, -1));
        }}
        onBlur={add} />
    </div>
  );
}

function LevelToggle({ value, onChange, testid }: { value: string; onChange: (v: string) => void; testid?: string }) {
  return (
    <span className="seg" data-testid={testid}>
      {["A", "B"].map((l) => (
        <button key={l} type="button" className={value === l ? `on lvl-${l}` : ""} onClick={() => onChange(l)}
          title={l === "A" ? "A: strict - every line with it is filtered, no model" : "B: decided by check 1 / check 2"}>{l}</button>
      ))}
    </span>
  );
}

// ---------------------------------------------------------------- the editor

const PAGE = 150;

export function KeywordsEditor({ text, onChange }: { text: string; onChange: (t: string) => void }) {
  const [mode, setMode] = useState<"table" | "text">(() => {
    try { return (localStorage.getItem("nli-viewer-kw-mode") as "table" | "text") || "table"; } catch { return "table"; }
  });
  useEffect(() => { try { localStorage.setItem("nli-viewer-kw-mode", mode); } catch { /* private window */ } }, [mode]);

  // items follow the text; edits made here produce new text, so a reparse keeps ids only for our own edits
  const [items, setItems] = useState<Item[]>(() => parseText(text));
  const [own, setOwn] = useState(text);
  useEffect(() => { if (text !== own) { setItems(parseText(text)); setOwn(text); } }, [text]);  // eslint-disable-line react-hooks/exhaustive-deps
  const commit = (next: Item[]) => { const t = serialize(next); setItems(next); setOwn(t); onChange(t); };

  const [q, setQ] = useState("");
  const [lvl, setLvl] = useState<"" | "A" | "B">("");
  const [typ, setTyp] = useState("");
  const [onlyProblems, setOnlyProblems] = useState(false);
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [limit, setLimit] = useState(PAGE);
  const [bulkType, setBulkType] = useState("");
  const [test, setTest] = useState("");
  const [showTest, setShowTest] = useState(false);

  const problems = useMemo(() => check(items), [items]);
  const kws = items.filter((i): i is Extract<Item, { kind: "kw" }> => i.kind === "kw");
  const types = useMemo(() => {
    const c: Record<string, number> = {};
    for (const k of kws) c[k.e.type || "-"] = (c[k.e.type || "-"] || 0) + 1;
    return c;
  }, [items]);  // eslint-disable-line react-hooks/exhaustive-deps
  const counts = {
    all: kws.length, A: kws.filter((k) => k.e.level === "A").length, B: kws.filter((k) => k.e.level === "B").length,
    errors: [...problems.values()].filter((p) => p.some((x) => x.level === "error")).length,
    warns: [...problems.values()].filter((p) => p.some((x) => x.level === "warn")).length,
  };

  const ql = q.trim().toLowerCase();
  const visible = (it: Extract<Item, { kind: "kw" }>) =>
    (!lvl || it.e.level === lvl) && (!typ || (it.e.type || "-") === typ)
    && (!onlyProblems || (problems.get(it.id) || []).some((p) => p.level !== "hint"))
    && (!ql || [it.e.keyword, it.e.type, it.e.gloss, ...it.e.other, ...it.e.exclude].some((x) => x.toLowerCase().includes(ql)));
  const filtering = !!(ql || lvl || typ || onlyProblems);

  // rows to show: section headings (comment lines right before keywords) + keywords, filtered
  type Row = { kind: "section"; title: string; at: number } | { kind: "kw"; it: Extract<Item, { kind: "kw" }>; at: number };
  const rows: Row[] = [];
  let shown = 0, total = 0;
  items.forEach((it, at) => {
    if (it.kind === "text") {
      const t = it.raw.trim();
      const next = items[at + 1];
      if (!filtering && /^#\s*\S/.test(t) && next?.kind === "kw") rows.push({ kind: "section", title: t.replace(/^#\s*/, ""), at });
      return;
    }
    if (!visible(it)) return;
    total++;
    if (shown < limit) { rows.push({ kind: "kw", it, at }); shown++; }
  });

  const update = (id: number, p: Partial<KwEntry>) =>
    commit(items.map((it) => (it.kind === "kw" && it.id === id ? { ...it, e: { ...it.e, ...p }, dirty: true } : it)));
  const updateMany = (ids: Set<number>, p: Partial<KwEntry>) =>
    commit(items.map((it) => (it.kind === "kw" && ids.has(it.id) ? { ...it, e: { ...it.e, ...p }, dirty: true } : it)));
  const remove = (ids: Set<number>) => { commit(items.filter((it) => !(it.kind === "kw" && ids.has(it.id)))); setSel(new Set()); };
  const addAfter = (at: number) => {
    // after the section heading / keyword at `at`: below the last keyword of that block
    let i = at + 1;
    while (i < items.length && items[i].kind === "kw") i++;
    const fresh: Item = { kind: "kw", id: nextId++, raw: "", dirty: true, e: { keyword: "", level: "B", type: "", gloss: "", other: [], exclude: [] } };
    const next = [...items.slice(0, i), fresh, ...items.slice(i)];
    setItems(next);  // not committed until it has a keyword (an empty line would be refused)
    setQ(""); setLvl(""); setTyp(""); setOnlyProblems(false);
    setTimeout(() => (document.querySelector(`[data-kwid="${fresh.id}"] input`) as HTMLInputElement | null)?.focus(), 0);
  };
  const setKeyword = (id: number, v: string) => update(id, { keyword: v });

  const testHits = useMemo(() => (showTest && test ? findHits(test, kws.map((k) => k.e)) : []), [showTest, test, items]);  // eslint-disable-line react-hooks/exhaustive-deps
  const allVisibleIds = rows.filter((r): r is Extract<Row, { kind: "kw" }> => r.kind === "kw").map((r) => r.it.id);
  const allSelected = allVisibleIds.length > 0 && allVisibleIds.every((id) => sel.has(id));

  return (
    <div className="kw-editor" data-testid="kw-editor">
      <div className="row kw-toolbar">
        <span className="seg" data-testid="kw-mode">
          <button type="button" className={mode === "table" ? "on" : ""} onClick={() => setMode("table")}>Table</button>
          <button type="button" className={mode === "text" ? "on" : ""} onClick={() => setMode("text")}>Text</button>
        </span>
        {mode === "table" ? <>
          <input type="search" placeholder="search keyword, type, gloss…" value={q} onChange={(e) => { setQ(e.target.value); setLimit(PAGE); }} style={{ width: 200 }} data-testid="kw-search" />
          <span className="seg">
            <button type="button" className={lvl === "" ? "on" : ""} onClick={() => setLvl("")}>all {counts.all}</button>
            <button type="button" className={lvl === "A" ? "on lvl-A" : ""} onClick={() => setLvl("A")}>A {counts.A}</button>
            <button type="button" className={lvl === "B" ? "on lvl-B" : ""} onClick={() => setLvl("B")}>B {counts.B}</button>
          </span>
          <select value={typ} onChange={(e) => setTyp(e.target.value)} title="type">
            <option value="">every type</option>
            {Object.entries(types).sort().map(([t, n]) => <option key={t} value={t}>{t === "-" ? "(no type)" : t} ({n})</option>)}
          </select>
          {counts.errors || counts.warns ? (
            <button type="button" className={`btn small${onlyProblems ? " primary" : ""}`} onClick={() => setOnlyProblems((v) => !v)} data-testid="kw-problems">
              {counts.errors ? <span className="badge filter">{counts.errors} error{counts.errors === 1 ? "" : "s"}</span> : null}
              {counts.warns ? <span className="badge warn">{counts.warns} warning{counts.warns === 1 ? "" : "s"}</span> : null}
            </button>
          ) : <span className="badge keep">no problems</span>}
          <span className="spacer" />
          <button type="button" className={`btn small${showTest ? " primary" : ""}`} onClick={() => setShowTest((v) => !v)} data-testid="kw-test-toggle">Test a text</button>
          <button type="button" className="btn small" onClick={() => addAfter(items.length - 1)} data-testid="kw-add">＋ Keyword</button>
        </> : <span className="faint" style={{ fontSize: 12 }}>Tab between columns: keyword · level · type · gloss · other meanings · exclude (‘-’ = none, ‘ | ’ between values)</span>}
      </div>

      {mode === "text" ? (
        <div className="editor"><textarea className="mono" rows={14} value={text} spellCheck={false} style={{ tabSize: 18 }}
          placeholder={"one keyword per line; empty = the built-in list of the country"}
          onKeyDown={(e) => {  // Tab types a column separator instead of leaving the box
            if (e.key !== "Tab" || e.shiftKey || e.ctrlKey || e.altKey) return;
            e.preventDefault();
            const t = e.currentTarget, a = t.selectionStart, b = t.selectionEnd;
            onChange(t.value.slice(0, a) + "\t" + t.value.slice(b));
            requestAnimationFrame(() => { t.selectionStart = t.selectionEnd = a + 1; });
          }}
          onChange={(e) => onChange(e.target.value)} data-testid="kw-text" /></div>
      ) : (
        <>
          {showTest ? (
            <div className="kw-test" data-testid="kw-test">
              <textarea className="mono" rows={3} value={test} onChange={(e) => setTest(e.target.value)}
                placeholder="paste a text: the keywords it hits (as nli_filter.py would find them) and the hits an exclude pattern drops" />
              {test ? (
                <div className="kw-test-out">
                  <div className="kw-test-text">{(() => {
                    const out: ReactNode[] = [];
                    let pos = 0;
                    testHits.forEach((h, i) => {
                      if (h.start > pos) out.push(test.slice(pos, h.start));
                      out.push(<mark key={i} className={h.excludedBy ? "kw-excluded" : `kw-hit lvl-${h.e.level}`}
                        title={h.excludedBy ? `excluded by ${h.excludedBy}` : `${h.e.keyword} · level ${h.e.level}${h.e.type ? ` · ${h.e.type}` : ""}`}>{test.slice(h.start, h.end)}</mark>);
                      pos = h.end;
                    });
                    out.push(test.slice(pos));
                    return out;
                  })()}</div>
                  <div className="row" style={{ gap: 6 }}>
                    {testHits.length ? testHits.map((h, i) => (
                      <span key={i} className={`chip${h.excludedBy ? " struck" : ""}`}>
                        {h.e.keyword} <span className="faint">{h.e.level}{h.e.type ? ` · ${h.e.type}` : ""}</span>
                        {h.excludedBy ? <span className="faint"> · excluded by <span className="mono">{h.excludedBy}</span></span> : null}
                      </span>
                    )) : <span className="faint">no keyword in this text: kept without any model (no_keyword)</span>}
                    {testHits.length ? (() => {
                      const live = testHits.filter((h) => !h.excludedBy);
                      if (!live.length) return <span className="badge keep">every hit excluded → keep, no model</span>;
                      if (live.some((h) => h.e.level === "A")) return <span className="badge filter">level A hit → filter, no model (strict_keyword)</span>;
                      return <span className="badge neutral">{live.length} hit{live.length === 1 ? "" : "s"} → check 1 / check 2</span>;
                    })() : null}
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}

          {sel.size ? (
            <div className="row kw-bulk" data-testid="kw-bulk">
              <strong>{sel.size} selected</strong>
              <button type="button" className="btn small" onClick={() => updateMany(sel, { level: "A" })}>level A</button>
              <button type="button" className="btn small" onClick={() => updateMany(sel, { level: "B" })}>level B</button>
              <input type="text" list="kw-types" placeholder="type" value={bulkType} onChange={(e) => setBulkType(e.target.value)} style={{ width: 110 }} />
              <button type="button" className="btn small" disabled={!bulkType.trim()} onClick={() => updateMany(sel, { type: bulkType.trim().toLowerCase() })}>set type</button>
              <button type="button" className="btn small danger" onClick={() => { if (window.confirm(`Delete ${sel.size} keyword(s) from the list?`)) remove(sel); }}>Delete</button>
              <button type="button" className="btn small ghost" onClick={() => setSel(new Set())}>clear selection</button>
            </div>
          ) : null}

          <datalist id="kw-types">{[...new Set([...KNOWN_TYPES, ...Object.keys(types).filter((t) => t !== "-")])].map((t) => <option key={t} value={t} />)}</datalist>
          <div className="table-wrap kw-table-wrap">
            <table className="kw-table">
              <thead>
                <tr>
                  <th style={{ width: 24 }}><input type="checkbox" checked={allSelected} onChange={(e) => setSel(e.target.checked ? new Set(allVisibleIds) : new Set())} aria-label="select all shown" /></th>
                  <th>keyword</th>
                  <th title="A: strict, filtered without models · B: check 1 / check 2">level</th>
                  <th>type</th>
                  <th title="what it is; used in the hypotheses: “This text is about {kw}, {gloss}.”">gloss</th>
                  <th title="what else the word can mean; used by check 2: “In this text, {kw} means {other}.” Enter adds one">other meanings</th>
                  <th title="regex patterns (case-insensitive); a hit inside a match is dropped before any model. Enter adds one">exclude</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => r.kind === "section" ? (
                  <tr key={`s${r.at}`} className="kw-section">
                    <td colSpan={7}>{r.title}</td>
                    <td><button type="button" className="btn small ghost" onClick={() => addAfter(r.at)} title="add a keyword to this section">＋</button></td>
                  </tr>
                ) : (() => {
                  const { it } = r, e = it.e;
                  const ps = problems.get(it.id) || [];
                  const bad = (f: Problem["field"]) => ps.some((p) => p.field === f && p.level !== "hint");
                  return (
                    <tr key={it.id} data-kwid={it.id} className={`${sel.has(it.id) ? "selected" : ""}${ps.some((p) => p.level === "error") ? " has-error" : ""}`}>
                      <td><input type="checkbox" checked={sel.has(it.id)} onChange={(ev) => { const s = new Set(sel); if (ev.target.checked) s.add(it.id); else s.delete(it.id); setSel(s); }} aria-label={`select ${e.keyword}`} /></td>
                      <td>
                        <input type="text" className={`mono${bad("keyword") || bad("line") ? " invalid" : ""}`} value={e.keyword} placeholder="keyword" onChange={(ev) => setKeyword(it.id, ev.target.value)} style={{ width: "100%" }} />
                        {ps.length ? <div className="kw-problems">{ps.map((p, i) => <div key={i} className={`kw-p ${p.level}`}>{p.msg}</div>)}</div> : null}
                      </td>
                      <td><LevelToggle value={e.level} onChange={(v) => update(it.id, { level: v })} /></td>
                      <td><input type="text" list="kw-types" className={bad("type") ? "invalid" : ""} value={e.type} placeholder="-" onChange={(ev) => update(it.id, { type: ev.target.value.toLowerCase() })} style={{ width: 96 }} /></td>
                      <td><input type="text" value={e.gloss} placeholder={e.type ? `e.g. a ${e.type} of …` : "-"} onChange={(ev) => update(it.id, { gloss: ev.target.value })} style={{ width: "100%" }} /></td>
                      <td><ChipsInput values={e.other} onChange={(v) => update(it.id, { other: v })} placeholder="+ meaning" /></td>
                      <td><ChipsInput values={e.exclude} onChange={(v) => update(it.id, { exclude: v })} placeholder="+ pattern" bad={(v) => !jsRegex(v)} /></td>
                      <td><button type="button" className="btn small ghost danger" title="delete this keyword" onClick={() => remove(new Set([it.id]))}>×</button></td>
                    </tr>
                  );
                })())}
                {!rows.some((r) => r.kind === "kw") ? <tr><td colSpan={8} className="faint">{kws.length ? "no keyword matches the filter" : "no keywords yet: ＋ Keyword (empty = the built-in list of the country)"}</td></tr> : null}
              </tbody>
            </table>
          </div>
          {total > shown ? (
            <div className="row"><span className="faint">{shown} of {total} shown</span>
              <button type="button" className="btn small" onClick={() => setLimit((l) => l + 500)}>show 500 more</button>
              <button type="button" className="btn small ghost" onClick={() => setLimit(Infinity)}>show all</button></div>
          ) : null}
        </>
      )}
    </div>
  );
}

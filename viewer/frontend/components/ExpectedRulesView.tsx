"use client";
// /label/expected-rules/: labels/expected_rules.json, what "same as expected" means on Expected vs result. Profiles
// (strict, quick ...) with groups of actions that count as equal, aliases for expected values nli_label never gives
// (flag -> remove), the default profile. Checked while typing, saved with a backup (labels/.backup/), refused when the
// file changed since it was loaded; the run pages use a saved change at once (no restart).
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { api, postJSON, useApi } from "@/lib/api";
import { href } from "@/lib/format";
import type { ExpectedRulesData } from "@/lib/types";
import { Crumbs, ErrorBox, Loading } from "./ui";
import { JsonBox, SaveBar, useConfig } from "./ConfigEditors";
import { actionClass } from "./LabelRunView";

const FILE = "labels/expected_rules.json";
const ACTIONS = ["remove", "review", "keep", "pass", "untouched", "none", "kept", "edited", "removed", "error"];
const STARTER: ExpectedRulesData = {
  about: "How Expected vs result decides that a result matches the expected action.",
  default: "strict",
  profiles: { strict: { same: [["pass", "untouched", "none"]], note: "only pass = untouched = none" },
    quick: { same: [["keep", "pass", "untouched", "none"]], note: "text kept = match" } },
  aliases: {},
};

export function ExpectedRulesView() {
  const sp = useSearchParams();
  const run = sp.get("run") || "";
  const c = useConfig<ExpectedRulesData>("expected_rules", "labels", FILE);
  const [tab, setTab] = useState<"form" | "json">("form");
  const [newProfile, setNewProfile] = useState("");
  const [alias, setAlias] = useState<[string, string]>(["", "remove"]);
  const [creating, setCreating] = useState<string | null>(null);
  const info = useApi(`exprules:${run}:${c.raw.data?.sha || ""}`, (s) => api.expectedRules(run || undefined, s));
  const runs = useApi("labelruns:exprules", (s) => api.labelRuns(s));
  const d = c.data;
  const missing = c.list.data && !c.list.data.files.includes(FILE);
  const create = async () => {
    setCreating(null);
    try {
      await postJSON("/api/labels/config/expected_rules/save", { path: FILE, data: STARTER, save_as: FILE });
      window.location.reload();
    } catch (e) { setCreating((e as Error).message); }
  };
  return (
    <>
      <div className="page-head"><div>
        <Crumbs items={[{ label: "Labelling", href: "/label" }, { label: "Expected-result rules" }]} />
        <h1>Expected-result rules</h1>
        <div className="sub">What counts as &quot;as expected&quot; on the Expected vs result panels (detail and simple runs, the
          document page). <code>{FILE}</code>; without the file only pass = untouched = none.</div>
      </div></div>
      {missing ? (
        <div className="panel">
          <div>The file does not exist yet: the built-in strict rule is used.</div>
          <button className="btn small primary" style={{ marginTop: 8 }} onClick={create} data-testid="rules-create">Create it (strict + quick)</button>
          {creating ? <div className="alert error">{creating}</div> : null}
        </div>) : null}
      <ErrorBox error={c.raw.error} onRetry={c.raw.reload} />
      {c.raw.loading && !d ? <Loading what="Loading the rules" /> : null}
      {info.data?.problem ? <div className="alert error">{info.data.problem}</div> : null}
      {d ? (<>
        <SaveBar c={c as never} file={FILE} placeholder="" testid="rules" noSaveAs />
        <div className="panel">
          <div className="row" style={{ flexWrap: "wrap" }}>
            <span className="seg"><button className={tab === "form" ? "on" : ""} onClick={() => setTab("form")}>Form</button>
              <button className={tab === "json" ? "on" : ""} onClick={() => setTab("json")}>JSON</button></span>
            <label>default profile <select value={d.default || ""} data-testid="rules-default"
              onChange={(e) => c.edit((x) => { x.default = e.target.value; })}>
              {Object.keys(d.profiles || {}).map((p) => <option key={p}>{p}</option>)}</select></label>
          </div>
          {tab === "json" ? <JsonBox data={d} onChange={(x) => c.setDraft(x)} /> : (<>
            <h2 style={{ marginTop: 14 }}>Profiles</h2>
            {Object.entries(d.profiles || {}).map(([name, p]) => (
              <div key={name} className="panel" style={{ marginBottom: 10 }} data-testid={`profile-${name}`}>
                <div className="row" style={{ flexWrap: "wrap" }}>
                  <strong>{name}</strong>{d.default === name ? <span className="badge accent">default</span> : null}
                  <input type="text" placeholder="note" value={p.note || ""} style={{ minWidth: 260 }}
                    onChange={(e) => c.edit((x) => { x.profiles[name].note = e.target.value; })} />
                  <span className="spacer" />
                  <button className="btn small ghost" onClick={() => {
                    const nn = window.prompt("New name of the profile", name);
                    if (!nn || nn === name) return;
                    c.edit((x) => {
                      const out: ExpectedRulesData["profiles"] = {};
                      for (const [k, v] of Object.entries(x.profiles)) out[k === name ? nn : k] = v;
                      x.profiles = out;
                      if (x.default === name) x.default = nn;
                    });
                  }}>Rename</button>
                  <button className="btn small ghost danger" disabled={Object.keys(d.profiles).length < 2}
                    onClick={() => c.edit((x) => { delete x.profiles[name]; if (x.default === name) x.default = Object.keys(x.profiles)[0]; })}>Delete</button>
                </div>
                <div className="faint" style={{ fontSize: 12, margin: "6px 0" }}>groups of actions that count as the same result</div>
                {(p.same || []).map((g, gi) => (
                  <div key={gi} className="row" style={{ flexWrap: "wrap", marginBottom: 4 }} data-testid={`group-${name}-${gi}`}>
                    <span className="faint">group {gi + 1}:</span>
                    {ACTIONS.map((a) => (
                      <label key={a} style={{ fontSize: 13 }}><input type="checkbox" checked={g.includes(a)}
                        onChange={(e) => c.edit((x) => {
                          const grp = x.profiles[name].same[gi];
                          if (e.target.checked) {
                            x.profiles[name].same.forEach((o) => { const i = o.indexOf(a); if (i >= 0) o.splice(i, 1); });  // one group per action
                            grp.push(a);
                          } else grp.splice(grp.indexOf(a), 1);
                        })} /> <span className={`badge ${actionClass(a)}`}>{a}</span></label>))}
                    <button className="btn small ghost danger" onClick={() => c.edit((x) => { x.profiles[name].same.splice(gi, 1); })}>remove group</button>
                  </div>))}
                <button className="btn small ghost" onClick={() => c.edit((x) => { (x.profiles[name].same ||= []).push([]); })}>+ group</button>
              </div>))}
            <div className="row">
              <input type="text" placeholder="new profile name" value={newProfile} onChange={(e) => setNewProfile(e.target.value)} data-testid="new-profile" />
              <button className="btn small" disabled={!newProfile.trim() || !!d.profiles[newProfile.trim()]} onClick={() => {
                const n = newProfile.trim(); c.edit((x) => { x.profiles[n] = { same: [["pass", "untouched", "none"]], note: "" }; }); setNewProfile("");
              }}>+ profile</button>
            </div>
            <h2 style={{ marginTop: 16 }}>Aliases</h2>
            <div className="faint" style={{ fontSize: 12 }}>an expected value is replaced before comparing (e.g. the benchmark&apos;s flag → remove); without an alias it stays a mismatch</div>
            <table style={{ maxWidth: 520 }}><tbody>
              {Object.entries(d.aliases || {}).map(([k, v]) => (
                <tr key={k}><td><code>{k}</code></td><td>→</td><td><select value={v} onChange={(e) => c.edit((x) => { x.aliases![k] = e.target.value; })}>
                  {ACTIONS.map((a) => <option key={a}>{a}</option>)}</select></td>
                  <td><button className="btn small ghost danger" onClick={() => c.edit((x) => { delete x.aliases![k]; })}>✕</button></td></tr>))}
              <tr><td><input type="text" placeholder="expected value (flag)" value={alias[0]} onChange={(e) => setAlias([e.target.value, alias[1]])} data-testid="alias-from" /></td><td>→</td>
                <td><select value={alias[1]} onChange={(e) => setAlias([alias[0], e.target.value])}>{ACTIONS.map((a) => <option key={a}>{a}</option>)}</select></td>
                <td><button className="btn small" disabled={!alias[0].trim()} data-testid="alias-add"
                  onClick={() => { c.edit((x) => { (x.aliases ||= {})[alias[0].trim()] = alias[1]; }); setAlias(["", "remove"]); }}>add</button></td></tr>
            </tbody></table>
          </>)}
        </div>
        <div className="panel">
          <div className="row" style={{ flexWrap: "wrap" }}>
            <h2 style={{ margin: 0 }}>Preview</h2>
            <select value={run} data-testid="rules-run" onChange={(e) => window.history.replaceState(null, "", href("/label/expected-rules", { run: e.target.value }))}>
              <option value="">pick a run…</option>
              {(runs.data?.runs || []).map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}</select>
            <span className="faint" style={{ fontSize: 12 }}>lines as expected under every saved profile</span>
            {run ? <Link href={href("/label/run", { run })}>open the run →</Link> : null}
          </div>
          {info.data?.preview ? (
            <table style={{ maxWidth: 520, marginTop: 8 }} data-testid="rules-preview"><tbody>
              {Object.entries(info.data.preview.profiles).map(([p, v]) => (
                <tr key={p}><td>{p}{p === info.data!.preview!.default ? " (default)" : ""}</td>
                  <td className="right mono">{v.ok} / {v.n}</td><td className="right">{v.n ? Math.round(100 * v.ok / v.n) : 0} %</td></tr>))}
            </tbody></table>) : run && info.data ? <div className="faint">this run has no expected results</div> : null}
          {c.dirty ? <div className="faint" style={{ fontSize: 12 }}>the preview uses the saved file: save to see your changes here</div> : null}
        </div>
      </>) : null}
    </>
  );
}

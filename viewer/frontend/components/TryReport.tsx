"use client";
// "Copy for analysis" on the Try page: everything about one Try (text, settings, every label score, the decision and
// why, the policy as used, and the rules that turn scores into a decision) as one Markdown text, ready to paste into
// an AI chat with a question.
import { useState } from "react";
import type { LabelParagraph, LabelTryResp } from "@/lib/types";

export type TryReportInput = {
  text: string;
  res: LabelTryResp;
  policyName: string;            // the file, or "unsaved edits of …"
  settings: { useJudge: boolean; forceGate: boolean; topic?: string | null; topicMode: string };
  docAction: string;             // the action shown on the page (strictest paragraph)
  expected?: { action: string | null; acceptable?: string[]; note?: string; caseId?: string; caseTitle?: string } | null;
  source?: string | null;        // "run out_label_ru_v2, yours__03 line 1, paragraph 1" / "dataset …"
  runGot?: string | null;        // what the stored run decided for this text
};

const RULES = `How nli_label.py decides (one paragraph at a time):
1. Keyword scan: a paragraph is checked only if it has a keyword or marker hit. No hit anywhere → document "untouched".
2. Gate (level 0): the paragraph goes on if a marker term is in it, OR the gate label reaches its threshold, OR (narrative_opens_gate) a level-2 "remove" label reaches its threshold. Otherwise → "pass".
3. Level 1 (subjects) and level 2 (framing) labels are scored independently (run_if lists what makes a level run; the Try page scores every label). A label is POSITIVE when its score ≥ its threshold. Scores in the uncertain band (0.6–0.95 by default) are re-checked by the judge model.
4. Softeners: a positive label with "softens" (e.g. reports_or_debunks) turns the matched remove labels into review.
5. Decision rules, first match wins: (a) a positive level-2 remove label, not softened → remove; (b) a level-1 remove and a keep label both positive → the policy's "conflict"; (c) any positive review label (or a softened remove) → review; (d) a positive keep label → keep; (e) nothing positive → the policy's "no_subject" (keep by default).
6. Exceptions (highest priority first) can then set another action (e.g. a phrase like "our country" → review). A remove by a "protected" label is never lowered ("exception_blocked").
7. Document: a paragraph cut (remove) → document "edited" (or "removed" if < 50 characters remain); else any review → "review"; else "kept" / "pass".`;

const r4 = (v: number | undefined | null) => (v === undefined || v === null ? "–" : v.toFixed(4));

function paragraphBlock(p: LabelParagraph, i: number, text: string, policy: LabelTryResp["policy"]): string {
  const out: string[] = [];
  out.push(`### Paragraph ${i + 1} (characters ${p.span[0]}–${p.span[1]})`);
  out.push("```text\n" + text.slice(p.span[0], p.span[1]) + "\n```");
  out.push(`- **Action: ${p.action}** (reason: \`${p.reason}\`)`);
  out.push(`- Positive labels: ${p.labels.length ? p.labels.map((l) => `\`${l}\``).join(", ") : "none"}`);
  if (p.marker) out.push("- A marker term is in the paragraph: the gate is skipped (open).");
  if (p.opened_by?.length) out.push(`- The gate said no, but ${p.opened_by.join(", ")} opened it (narrative_opens_gate).`);
  if (p.exception) out.push(`- Exception \`${p.exception}\` changed the action from ${p.action_before} to ${p.action}${p.exception_phrases?.length ? ` (phrases found: ${p.exception_phrases.map((x) => `"${x}"`).join(", ")})` : ""}.`);
  if (p.exception_blocked) out.push(`- Exception \`${p.exception_blocked}\` matched but was blocked: a protected label removed the paragraph.`);
  if (p.judged?.length) out.push(`- Re-checked by the judge model: ${p.judged.join(", ")}.`);
  if (p.from_field?.length) out.push(`- Set from the topic field (not the model): ${p.from_field.join(", ")}.`);
  if (p.flags?.length) out.push(`- Flags (do not change the action): ${p.flags.join(", ")}.`);
  out.push("");
  out.push("| label | level | decision | threshold | score | positive | judged |");
  out.push("|---|---|---|---|---|---|---|");
  const keys = Object.keys(policy.labels).sort((a, b) => policy.labels[a].level - policy.labels[b].level);
  for (const k of keys) {
    const l = policy.labels[k];
    const s = p.scores[k];
    const pos = s === undefined || s === null ? "not scored" : s >= l.threshold ? "**yes**" : "no";
    const dec = l.decision + (l.softens?.length ? ` (softens ${l.softens.join(", ")})` : "") + ((l as { protected?: boolean }).protected ? ", protected" : "");
    out.push(`| ${k} | ${l.level} | ${dec} | ${l.threshold} | ${r4(s)} | ${pos} | ${p.judged?.includes(k) ? "yes" : ""} |`);
  }
  const ex = p.exception_scores && Object.keys(p.exception_scores).length ? p.exception_scores : null;
  if (ex) out.push("", `Exception hypothesis scores: ${Object.entries(ex).map(([k, v]) => `${k} ${r4(v)}`).join(", ")}`);
  return out.join("\n");
}

export function buildTryReport(x: TryReportInput): string {
  const { res, text } = x;
  const row = res.rows[0];
  const pol = res.policy as LabelTryResp["policy"] & Record<string, unknown>;
  const paras = row?.paragraphs || [];
  const L: string[] = [];
  L.push("# nli_label.py: one text checked with the Russia-side labelling policy");
  L.push("");
  L.push("I ran this text through a paragraph-level NLI labelling pipeline (zero-shot NLI models score each label's hypothesis; thresholds turn scores into yes/no; rules turn labels into keep / review / remove). Please explain what happened and why, and whether the result looks right.");
  L.push("");
  L.push("## Input");
  if (x.source) L.push(`- Source: ${x.source}`);
  if (x.expected?.caseId) L.push(`- Test case: \`${x.expected.caseId}\`${x.expected.caseTitle ? ` (${x.expected.caseTitle})` : ""}`);
  L.push(`- Policy: \`${x.policyName}\``);
  L.push(`- Models: ${res.models.fast}${res.models.judge ? ` + judge ${res.models.judge}` : " (no judge)"}; ${res.pairs.fast} model pairs${res.pairs.judge ? ` (+${res.pairs.judge} judge)` : ""}; ${res.seconds}s`);
  L.push(`- Try settings: judge ${x.settings.useJudge ? "on" : "off"}; label without a keyword ${x.settings.forceGate ? "on" : "off"}; topic ${x.settings.topic ? `"${x.settings.topic}"` : "none"}; topic mode ${x.settings.topicMode || "policy default"}`);
  L.push("");
  L.push("```text\n" + text + "\n```");
  L.push("");
  L.push("## Result");
  L.push(`- **Document action: ${x.docAction}** (stored document action: ${row?.action || "?"})`);
  if (x.expected?.action) {
    const ok = [...x.expected.action.split(" or "), ...(x.expected.acceptable || [])];
    L.push(`- Expected: ${x.expected.action}${x.expected.acceptable?.length ? ` (also fine: ${x.expected.acceptable.join(", ")})` : ""} → ${ok.includes(x.docAction) || (ok.some((a) => a === "pass" || a === "untouched") && ["pass", "untouched"].includes(x.docAction)) ? "as expected" : "**NOT as expected**"}`);
    if (x.expected.note) L.push(`- Note on the case: ${x.expected.note}`);
  }
  if (x.runGot) L.push(`- The stored run decided: ${x.runGot}`);
  L.push(`- Keyword hits: ${(row?.hits || []).length ? (row?.hits || []).map((h) => `"${h.kw}"${h.rule ? ` (rule ${h.rule})` : ""}`).join(", ") : "none"}`);
  if (row?.markers?.length) L.push(`- Marker terms: ${row.markers.join(", ")}`);
  if (!paras.length) L.push("- No paragraph was checked (no keyword / marker hit, or all hits incidental): no model ran.");
  L.push("");
  paras.forEach((p, i) => { L.push(paragraphBlock(p, i, text, res.policy)); L.push(""); });
  if (res.clean[0] !== undefined && res.clean[0] !== null && res.clean[0] !== text) {
    L.push("## Clean copy (what would be kept for training)");
    L.push("```text\n" + res.clean[0] + "\n```");
    if (res.rewrites[0]?.length) L.push(`Place names rewritten: ${res.rewrites[0].map((r) => `${r.old} → ${r.new}`).join(", ")}`);
    L.push("");
  }
  L.push("## Policy settings used");
  L.push(`- conflict: ${pol.conflict ?? "review"}; no_subject: ${(pol.no_subject as string) ?? "keep"}; narrative_opens_gate: ${String(pol.narrative_opens_gate ?? false)}`);
  L.push(`- run_if: ${JSON.stringify(pol.run_if || {})}`);
  for (const e of pol.exceptions || []) {
    L.push(`- Exception \`${e.key}\`: decision ${e.decision}, priority ${e.priority}, scope ${e.scope}${e.phrases?.length ? `, phrases ${e.phrases.slice(0, 12).map((p) => `"${p}"`).join(", ")}${e.phrases.length > 12 ? ", …" : ""}` : ""}${e.skip_quoted ? ", ignored inside quotes" : ""}${e.hypothesis ? `, hypothesis "${e.hypothesis}" ≥ ${e.threshold}` : ""}`);
  }
  L.push("");
  L.push("Label hypotheses (what the NLI model is asked):");
  for (const [k, l] of Object.entries(res.policy.labels)) L.push(`- \`${k}\`: "${l.hypothesis}"`);
  L.push("");
  L.push("## The decision rules");
  L.push(RULES);
  L.push("");
  L.push("## My question");
  L.push(`Why did this text end up as **${x.docAction}**? Which labels and rules decided it, which scores were close to their thresholds, and what would change the result (threshold, hypothesis wording, exception)?`);
  return L.join("\n");
}

/** The button: copies the report; if the browser refuses the clipboard, shows it selected for Ctrl+C. */
export function CopyReportButton({ make }: { make: () => string }) {
  const [state, setState] = useState<"idle" | "copied">("idle");
  const [fallback, setFallback] = useState<string | null>(null);
  const copy = async () => {
    const t = make();
    try {
      await navigator.clipboard.writeText(t);
      setState("copied"); setFallback(null);
      setTimeout(() => setState("idle"), 2500);
    } catch {
      setFallback(t);
    }
  };
  return (
    <>
      <button className="btn small" onClick={copy} data-testid="copy-report"
        title="copy the text, settings, every score, the decision and the rules as Markdown, to paste into Claude or ChatGPT">
        {state === "copied" ? "Copied ✓" : "Copy for analysis"}</button>
      {fallback !== null ? (
        <div style={{ marginTop: 8, width: "100%" }}>
          <div className="faint" style={{ fontSize: 12 }}>The browser did not allow copying: the text is selected below, press Ctrl+C.
            <button className="btn small ghost" onClick={() => setFallback(null)}>close</button></div>
          <textarea className="mono" readOnly value={fallback} style={{ width: "100%", minHeight: 220, fontSize: 12 }}
            ref={(el) => { if (el) { el.focus(); el.select(); } }} />
        </div>) : null}
    </>
  );
}

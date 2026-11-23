// build_decks.js - the three project decks in cmds/presentations/ (pptxgenjs).
//
//   npm install pptxgenjs@3.12.0          (once, in any folder; then run from that folder or set NODE_PATH)
//   node cmds/presentations/build_decks.js
//
// Writes 01_project_overview.pptx, 02_core_ideas_and_methods.pptx, 03_test_results.pptx next to this file.
// The numbers come from cmds/design/policy_cases_report_2026-11-20.md (A's policy) and cmds/labeling/russia_llm.md
// (Russia-side policy); edit them here when new results exist. Theme colours are written into each deck's theme
// (set APPLY_THEME to the pptx skill's apply_theme.js, or leave it unset to keep pptxgenjs' default theme colours).

const path = require("path");
const pptxgen = require("pptxgenjs");

const OUT = __dirname;
const APPLY_THEME = process.env.APPLY_THEME || null;

const THEME = {
  name: "NLI Policy",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "1B2430", lt1: "FFFFFF", dk2: "3D4B5C", lt2: "EEF2F5",
    accent1: "1F6F8B", accent2: "C2410C", accent3: "B7791F", accent4: "2F855A", accent5: "718096", accent6: "6B46C1",
    hlink: "1F6F8B", folHlink: "6B46C1",
  },
};
const HEX = THEME.colors;
const W = 13.333, M = 0.6;

function newDeck(deckTitle) {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE";
  pres.title = deckTitle;
  pres.author = "nli_filter2 project";
  pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
  const C = pres.SchemeColor;
  pres.defineSlideMaster({
    title: "Title dark", background: { color: C.text1 },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: M + 0.2, y: 2.2, w: W - 2 * M - 0.4, h: 1.6, fontSize: 44, bold: true, color: C.background1, fontFace: THEME.headFontFace, valign: "bottom", align: "left" }, text: "" } },
      { placeholder: { options: { name: "body", type: "body", x: M + 0.2, y: 4.0, w: W - 2 * M - 0.4, h: 1.6, fontSize: 20, color: C.background2, valign: "top", align: "left" }, text: "" } },
    ],
  });
  pres.defineSlideMaster({
    title: "Closing dark", background: { color: C.text1 },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: M + 0.2, y: 0.9, w: W - 2 * M - 0.4, h: 1.2, fontSize: 40, bold: true, color: C.background1, fontFace: THEME.headFontFace, valign: "bottom", align: "left" }, text: "" } },
    ],
  });
  pres.defineSlideMaster({
    title: "Content", background: { color: C.background1 },
    margin: [0.5, 0.6, 0.6, 0.6],
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: M, y: 0.35, w: W - 2 * M, h: 0.85, fontSize: 32, bold: true, color: C.text1, fontFace: THEME.headFontFace, valign: "middle" }, text: "" } },
      { text: { text: deckTitle, options: { x: M, y: 7.0, w: 8, h: 0.3, fontSize: 10, color: C.accent5, margin: 0 } } },
    ],
    slideNumber: { x: W - M - 0.6, y: 7.0, w: 0.6, h: 0.3, fontSize: 10, color: C.accent5, align: "right" },
  });
  return { pres, C };
}

// ---------------------------------------------------------------------------------------------------------------
// helpers (fresh option objects every call: pptxgenjs mutates them)
// ---------------------------------------------------------------------------------------------------------------
function actionColor(C, a) {
  return { remove: C.accent2, review: C.accent3, keep: C.accent4, pass: C.accent5, untouched: C.accent5, exception: C.accent6 }[a] || C.accent1;
}
function titleSlide(pres, title, sub, notes) {
  const s = pres.addSlide({ masterName: "Title dark" });
  s.addText(title, { placeholder: "title" });
  s.addText(sub, { placeholder: "body" });
  if (notes) s.addNotes(notes);
  return s;
}
function closing(pres, title, items, notes) {
  const s = pres.addSlide({ masterName: "Closing dark" });
  s.addText(title, { placeholder: "title" });
  s.addText(bullets(items, 22, pres.SchemeColor.background2), { x: M + 0.2, y: 2.6, w: W - 2 * M - 0.4, h: 4.0, margin: 0, valign: "top", isTextBox: true });
  if (notes) s.addNotes(notes);
  return s;
}
function content(pres, title, notes) {
  const s = pres.addSlide({ masterName: "Content" });
  s.addText(title, { placeholder: "title" });
  if (notes) s.addNotes(notes);
  return s;
}
function pill(s, C, action, x, y, w = 1.15, h = 0.38, label = null) {
  s.addText(label || action, {
    shape: "roundRect", rectRadius: 0.19, x, y, w, h, fill: { color: actionColor(C, action) }, color: C.background1,
    fontSize: 13, bold: true, align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: `pill-${action}`,
  });
}
function circle(s, C, n, x, y, d = 0.55, color = null) {
  s.addText(String(n), {
    shape: "ellipse", x, y, w: d, h: d, fill: { color: color || C.accent1 }, color: C.background1, fontSize: 16, bold: true,
    align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: `num-${n}`,
  });
}
function card(s, C, { x, y, w, h, head, body, fill = null, headColor = null, bodySize = 15, num = null, numColor = null }) {
  s.addShape("rect", { x, y, w, h, fill: { color: fill || C.background2 }, line: { color: fill || C.background2 }, objectName: `card-${head}` });
  let tx = x + 0.25;
  if (num !== null) { circle(s, C, num, x + 0.25, y + 0.25, 0.5, numColor); tx = x + 0.9; }
  s.addText(head, { x: tx, y: y + 0.22, w: w - (tx - x) - 0.25, h: 0.56, fontSize: 19, bold: true, color: headColor || C.text1, fontFace: THEME.headFontFace, valign: "middle", margin: 0, isTextBox: true });
  if (body) {
    s.addText(body, { x: x + 0.25, y: y + 0.95, w: w - 0.5, h: h - 1.15, fontSize: bodySize, color: C.text2, valign: "top", margin: 0, isTextBox: true, paraSpaceAfter: 6 });
  }
}
function bullets(items, size = 16, color = null) {
  return items.map((t, i) => {
    const runs = typeof t === "string" ? { text: t } : t;
    const sub = !!runs.sub;
    return { text: runs.text, options: { bullet: sub ? { indent: 18 } : true, indentLevel: sub ? 1 : 0, breakLine: i < items.length - 1,
      fontSize: sub ? size - 1 : size, paraSpaceAfter: sub ? 10 : 4, bold: !!runs.bold, ...(color ? { color } : {}) } };
  });
}
function arrowRight(s, C, x, y, w) {
  s.addShape("line", { x, y, w, h: 0, line: { color: C.accent5, width: 2, endArrowType: "triangle" } });
}
function arrowDown(s, C, x, y, h) {
  s.addShape("line", { x, y, w: 0, h, line: { color: C.accent5, width: 2, endArrowType: "triangle" } });
}
function stat(s, C, { x, y, w, big, label, color = null, bigSize = 54 }) {
  s.addText(big, { x, y, w, h: 1.1, fontSize: bigSize, bold: true, color: color || C.accent1, fontFace: THEME.headFontFace, margin: 0, valign: "bottom", isTextBox: true });
  s.addText(label, { x, y: y + 1.15, w, h: 0.95, fontSize: 15, color: C.text2, margin: 0, valign: "top", isTextBox: true });
}
function headRow(C, cells) {
  return cells.map((t) => ({ text: t, options: { bold: true, color: C.background1, fill: { color: C.text2 }, fontSize: 14 } }));
}
function actCell(C, a) {
  return { text: a, options: { bold: true, color: actionColor(C, a.replace(" ✗", "").replace(" ✓", "")), fontSize: 14, align: "center" } };
}
function scoreBar(s, C, { x, y, w, label, score, thr, yes }) {
  s.addText(label, { x, y, w: 3.3, h: 0.34, fontSize: 13, color: C.text1, margin: 0, valign: "middle", isTextBox: true, fontFace: "Consolas" });
  const bx = x + 3.4, bw = w - 4.3;
  s.addShape("rect", { x: bx, y: y + 0.07, w: bw, h: 0.2, fill: { color: C.background2 }, line: { color: C.background2 } });
  s.addShape("rect", { x: bx, y: y + 0.07, w: Math.max(0.03, bw * score), h: 0.2, fill: { color: yes ? C.accent1 : C.accent5 }, line: { color: yes ? C.accent1 : C.accent5 } });
  s.addShape("line", { x: bx + bw * thr, y: y, w: 0, h: 0.34, line: { color: C.text1, width: 1.5 } });
  s.addText(score.toFixed(2), { x: bx + bw + 0.1, y, w: 0.8, h: 0.34, fontSize: 13, bold: yes, color: yes ? C.accent1 : C.text2, margin: 0, valign: "middle", isTextBox: true });
}
function chartBase(extra) {
  return {
    catAxisLabelColor: HEX.dk2, valAxisLabelColor: HEX.dk2, catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt",
    catAxisLabelFontSize: 13, valAxisLabelFontSize: 12, dataLabelFontFace: "+mn-lt", dataLabelFontSize: 13, dataLabelColor: HEX.dk1,
    valGridLine: { color: "D9DEE4", size: 0.75 }, catGridLine: { style: "none" }, showValue: true,
    titleFontFace: "+mn-lt", titleFontSize: 15, titleColor: HEX.dk1, ...extra,
  };
}
async function save(pres, name) {
  const file = path.join(OUT, name);
  await pres.writeFile({ fileName: file });
  if (APPLY_THEME) await require(APPLY_THEME).applyTheme(file, THEME);
  console.log("wrote", file);
}

// =================================================================================================================
// Deck 1: project overview
// =================================================================================================================
async function deck1() {
  const { pres, C } = newDeck("Project overview · NLI policy labelling");
  pres.addSection({ title: "Overview" });
  titleSlide(pres, "Labelling LLM training data by policy",
    "Paragraph-level labels for Russia- and Ukraine-related content with zero-shot NLI models\nProject overview · November 2026",
    "This deck: what the project is for, how it works end to end, what is in the repository, and where it stands.");

  let s = content(pres, "Why this project exists",
    "Web corpora mix everything in one document. Each LLM owner has a policy. Hand filtering does not scale, but every decision must stay explainable.");
  const cw = (W - 2 * M - 0.6) / 3;
  [["Web-scale corpora", "Nemotron, Dolma and OLMo data mix science, news, culture and propaganda in the same documents."],
   ["A policy per LLM owner", "Each owner decides what stays, what goes and what a person checks: culture, narratives, hate, opinions, history."],
   ["Auditable at scale", "Billions of tokens rule out hand filtering, yet every decision has to be explainable and reversible."]]
    .forEach(([h, b], i) => card(s, C, { x: M + i * (cw + 0.3), y: 1.55, w: cw, h: 3.4, head: h, body: b, num: i + 1, bodySize: 17 }));
  s.addText([{ text: "Goal: ", options: { bold: true, color: C.accent1 } },
    { text: "turn a written policy into per-paragraph labels, without ever deleting the raw data.", options: { color: C.text1 } }],
    { x: M, y: 5.35, w: W - 2 * M, h: 0.8, fontSize: 22, margin: 0, isTextBox: true, fontFace: THEME.headFontFace });

  s = content(pres, "Two projects, one tool",
    "The same code, viewer and workflow serve two LLM owners with different policies. Only the policy file, keyword lists and test cases differ.");
  const pw = (W - 2 * M - 0.4) / 2;
  [["A's LLM · Ukraine side", "Labels Russia-related content paragraph by paragraph: removes Russian culture, lifestyle and Kremlin narratives, keeps science, geography and factual war reporting, rewrites place names (Kiev → Kyiv).", C.accent1],
   ["Russia's LLM · Russia side", "Labels Russia- and Ukraine-related content: removes hate and calls for violence against either people, sends opinions (both directions), history and known false claims to review, keeps facts whoever they hurt.", C.accent6]]
    .forEach(([h, b, col], i) => {
      const x = M + i * (pw + 0.4);
      s.addShape("rect", { x, y: 1.55, w: pw, h: 3.7, fill: { color: C.background2 }, line: { color: C.background2 } });
      s.addText(h, { x: x + 0.3, y: 1.75, w: pw - 0.6, h: 0.6, fontSize: 22, bold: true, color: col, fontFace: THEME.headFontFace, margin: 0, isTextBox: true });
      s.addText(b, { x: x + 0.3, y: 2.5, w: pw - 0.6, h: 2.6, fontSize: 17, color: C.text1, margin: 0, valign: "top", isTextBox: true });
    });
  s.addText("Shared: nli_label.py · the viewer · labels stored as columns · raw data never deleted · every change measured on test cases",
    { x: M, y: 5.6, w: W - 2 * M, h: 0.6, fontSize: 16, color: C.text2, margin: 0, isTextBox: true, italic: true });

  s = content(pres, "How a document flows through the pipeline",
    "Left to right: the corpus is read from any storage; cheap keyword matching picks candidate documents; documents are split into paragraphs; the NLI models answer the policy's questions level by level; exceptions are checked; each paragraph gets an action; outputs are written next to the data.");
  const steps = [["Corpus", "local, FTP, SFTP, S3, MinIO"], ["Keywords", "country lists + marker terms"], ["Paragraphs", "200–2,000 characters"],
    ["NLI labels", "level 0 gate · 1 subject · 2 framing"], ["Decision", "exceptions first, then the rules"], ["Outputs", "labels, clean copy, review queue, report"]];
  const bw = 1.72, gap = (W - 2 * M - 6 * bw) / 5;
  steps.forEach(([h, b], i) => {
    const x = M + i * (bw + gap);
    s.addShape("rect", { x, y: 1.7, w: bw, h: 2.5, fill: { color: i === 3 ? C.accent1 : C.background2 }, line: { color: i === 3 ? C.accent1 : C.background2 } });
    circle(s, C, i + 1, x + bw / 2 - 0.25, 1.9, 0.5, i === 3 ? C.text1 : C.accent1);
    s.addText(h, { x: x + 0.1, y: 2.55, w: bw - 0.2, h: 0.5, fontSize: 17, bold: true, align: "center", color: i === 3 ? C.background1 : C.text1, margin: 0, isTextBox: true });
    s.addText(b, { x: x + 0.12, y: 3.05, w: bw - 0.24, h: 1.05, fontSize: 14, align: "center", valign: "top", color: i === 3 ? C.background1 : C.text2, margin: 0, isTextBox: true });
    if (i < 5) arrowRight(s, C, x + bw + 0.05, 2.95, gap - 0.1);
  });
  s.addText("Every paragraph ends with one action:", { x: M, y: 4.65, w: 6, h: 0.45, fontSize: 18, bold: true, color: C.text1, margin: 0, isTextBox: true });
  [["remove", "cut from clean copy"], ["review", "a person decides"], ["keep", "related, and stays"], ["pass", "incidental keyword"]]
    .forEach(([a, t], i) => {
      const x = M + i * 3.05;
      pill(s, C, a, x, 5.3);
      s.addText(t, { x: x + 1.27, y: 5.25, w: 1.75, h: 0.5, fontSize: 14, color: C.text2, margin: 0, valign: "middle", isTextBox: true, fit: "shrink" });
    });

  s = content(pres, "What is in the repository",
    "The main tool is nli_label.py. nli_filter.py is the earlier document-level filter, kept for comparison. The viewer shows runs, explains each decision, and lets you try the policy on single texts.");
  const parts = [["nli_label.py", "Policy labels per paragraph: run, sample, eval, review, redecide"],
    ["nli_filter.py", "The earlier document-level country filter (keep / filter)"],
    ["nli_names.py", "Place-name rewrite (Kiev → Kyiv) with an exception list"],
    ["viewer/", "Web UI: runs, the flow of every paragraph, Try the policy, review queues"],
    ["nli_playground.py", "Model service behind the viewer's Try pages"],
    ["policy/ · labels/", "Policies (A's v1–v5, Russia side v1–v2), test cases, hand labels"]];
  const gw = (W - 2 * M - 0.6) / 3;
  parts.forEach(([h, b], i) => card(s, C, { x: M + (i % 3) * (gw + 0.3), y: 1.5 + Math.floor(i / 3) * 2.6, w: gw, h: 2.3, head: h, body: b, bodySize: 16 }));

  s = content(pres, "Two policies side by side",
    "The policies differ in what they remove and review. Both keep facts and never delete the raw data.");
  const rows = [
    headRow(C, ["", "A's LLM (Ukraine side)", "Russia's LLM (Russia side)"]),
    [{ text: "Removes", options: { bold: true } }, "Russian culture, celebrities, lifestyle, cost of living; Kremlin narratives (16 labels)", "Hate and calls for violence against Russians or Ukrainians"],
    [{ text: "Review", options: { bold: true } }, "Literature and art, Soviet history, sport, values", "Opinions about Russia or Ukraine (both directions), history, known false claims, an unnamed \"our country\""],
    [{ text: "Keeps", options: { bold: true } }, "Science, geography, politics, war facts, economy", "Facts, whoever they hurt"],
    [{ text: "Place names", options: { bold: true } }, "Kiev → Kyiv (48 names, with exceptions)", "Not rewritten"],
    [{ text: "Test set", options: { bold: true } }, "149 texts in 78 cases", "43 texts in 23 cases"],
  ];
  s.addTable(rows, { x: M, y: 1.5, w: W - 2 * M, colW: [1.9, 5.05, 5.18], fontSize: 15, color: C.text1, border: { type: "solid", pt: 0.75, color: "D9DEE4" }, valign: "middle", rowH: 0.78, margin: 0.1 });

  s = content(pres, "Built for real corpora",
    "Scale features: any storage, many GPUs, shards across machines, resume after interruption. Passwords are never written to output files.");
  [["Any storage", "Local folders, FTP, SFTP, S3 and MinIO; passwords stay in ${VAR} form, never in outputs"],
   ["Many GPUs", "--device cuda:0,cuda:1 with --inflight; --shard K/N splits files across machines"],
   ["Resumable", "Finished files are skipped; progress.json for the viewer; download retries"],
   ["Pays only for what it needs", "Later levels run only when an earlier one says so (the cascade)"]]
    .forEach(([h, b], i) => {
      const y = 1.6 + i * 1.2;
      circle(s, C, i + 1, M, y, 0.6);
      s.addText(h, { x: M + 0.85, y: y - 0.05, w: 6.6, h: 0.4, fontSize: 19, bold: true, color: C.text1, margin: 0, isTextBox: true });
      s.addText(b, { x: M + 0.85, y: y + 0.38, w: 6.6, h: 0.6, fontSize: 15, color: C.text2, margin: 0, valign: "top", isTextBox: true });
    });
  s.addShape("rect", { x: 8.4, y: 1.6, w: W - M - 8.4, h: 4.6, fill: { color: C.text1 }, line: { color: C.text1 } });
  s.addText("0", { x: 8.7, y: 1.9, w: 3.8, h: 1.6, fontSize: 96, bold: true, color: C.background1, fontFace: THEME.headFontFace, margin: 0, isTextBox: true });
  s.addText("raw lines deleted. Labels are columns next to the data; a clean copy is written separately, and a policy change is re-applied from stored scores.",
    { x: 8.7, y: 3.6, w: 3.75, h: 2.4, fontSize: 17, color: C.background2, margin: 0, valign: "top", isTextBox: true });

  s = content(pres, "People stay in the loop",
    "Thresholds come from hand labels, not guesses. Uncertain paragraphs go to a review queue. A changed policy is re-applied from stored scores in seconds, without models.");
  const loop = [["Sample", "pick paragraphs of a run to label"], ["Hand-label", "tools/label_tool.html"], ["Evaluate", "precision, recall, thresholds, CRC"], ["Run + review", "review queue for people"]];
  const pos = [[M + 0.3, 1.6], [W - M - 5.0, 1.6], [W - M - 5.0, 4.35], [M + 0.3, 4.35]];
  loop.forEach(([h, b], i) => {
    const [x, y] = pos[i];
    card(s, C, { x, y, w: 4.7, h: 1.9, head: h, body: b, num: i + 1, bodySize: 16 });
  });
  arrowRight(s, C, M + 5.1, 2.55, W - 2 * M - 10.2);
  arrowDown(s, C, W - M - 2.65, 3.6, 0.65);
  s.addShape("line", { x: M + 5.1, y: 5.3, w: W - 2 * M - 10.2, h: 0, line: { color: C.accent5, width: 2, beginArrowType: "triangle" } });
  s.addShape("line", { x: M + 2.65, y: 3.6, w: 0, h: 0.65, line: { color: C.accent5, width: 2, beginArrowType: "triangle" } });
  s.addText("redecide: a new policy from stored scores, no models", { x: 4.17, y: 3.65, w: 5.0, h: 0.55, fontSize: 14, italic: true, color: C.accent1, align: "center", margin: 0, isTextBox: true });

  s = content(pres, "Where we are",
    "Headline numbers. The case texts were written by us; real-corpus hand labels are the next measurement.");
  stat(s, C, { x: M, y: 1.7, w: 3.8, big: "83 %", label: "A's policy v5 + judge on 149 test texts; nothing A keeps was removed" });
  stat(s, C, { x: M + 4.15, y: 1.7, w: 3.8, big: "91 %", label: "Russia-side policy v2 on 43 test texts; all 5 facts kept, all hate removed", color: C.accent6 });
  stat(s, C, { x: M + 8.3, y: 1.7, w: 3.8, big: "93 vs 68", label: "% handled correctly: nli_label.py vs the old nli_filter.py on the same cases", color: C.accent4 });
  s.addShape("rect", { x: M, y: 4.6, w: W - 2 * M, h: 1.4, fill: { color: C.background2 }, line: { color: C.background2 } });
  s.addText("The test texts were written for these policies, so they show the policies do what was designed. How well they do on real data is the next measurement: hand labels from a real corpus sample.",
    { x: M + 0.3, y: 4.75, w: W - 2 * M - 0.6, h: 1.1, fontSize: 17, color: C.text1, margin: 0, valign: "middle", isTextBox: true });

  pres.addSection({ title: "Next" });
  s = closing(pres, "Next steps", [
    "Check the 182 seed drafts, then eval: the first real thresholds per label",
    "Run both policies on a real corpus sample and size the review queues",
    "Compliance decisions: review labels, conflicts, place names, \"our country\"",
    "Later: more countries, each with its own tier of rules",
  ], "Concrete next steps; each one has a command in cmds/labeling.");
  await save(pres, "01_project_overview.pptx");
}

// =================================================================================================================
// Deck 2: core idea, principles, methods
// =================================================================================================================
async function deck2() {
  const { pres, C } = newDeck("Core idea, principles and methods");
  pres.addSection({ title: "Idea" });
  titleSlide(pres, "Core idea, principles and methods", "How a written policy becomes paragraph labels\nNovember 2026",
    "This deck explains the method: zero-shot NLI, the cascade, the decision rules, how hypotheses and thresholds are chosen, and the safety rules.");

  let s = content(pres, "Ask a model whether a sentence follows from the text",
    "Natural language inference: the paragraph is the premise, the policy sentence is the hypothesis. The model gives the probability that the hypothesis follows. No training is needed, and a policy change is a sentence change.");
  s.addText("Premise: the paragraph", { x: M, y: 1.45, w: 6.5, h: 0.4, fontSize: 15, bold: true, color: C.accent5, margin: 0, isTextBox: true });
  s.addText("\"The Russian animated series 'Masha and the Bear' has become one of the most-watched cartoons in the world. Each short episode follows a mischievous little girl…\"",
    { x: M, y: 1.9, w: 6.5, h: 1.6, fontSize: 17, color: C.text1, fill: { color: C.background2 }, margin: 12, valign: "middle", isTextBox: true });
  s.addText("Hypothesis: one policy label", { x: M, y: 3.75, w: 6.5, h: 0.4, fontSize: 15, bold: true, color: C.accent5, margin: 0, isTextBox: true });
  s.addText("\"This text describes Russian music, films, TV shows or entertainment.\"",
    { x: M, y: 4.2, w: 6.5, h: 1.0, fontSize: 17, color: C.text1, fill: { color: C.background2 }, margin: 12, valign: "middle", isTextBox: true });
  arrowRight(s, C, 7.35, 3.4, 0.8);
  s.addShape("rect", { x: 8.35, y: 1.9, w: W - M - 8.35, h: 3.3, fill: { color: C.text1 }, line: { color: C.text1 } });
  s.addText("0.99", { x: 8.6, y: 2.05, w: 3.9, h: 1.2, fontSize: 66, bold: true, color: C.background1, fontFace: THEME.headFontFace, margin: 0, isTextBox: true });
  s.addText("entailment ≥ threshold 0.8\n→ culture_entertainment = yes\n→ policy decision: remove", { x: 8.6, y: 3.35, w: 3.9, h: 1.6, fontSize: 17, color: C.background2, margin: 0, valign: "top", isTextBox: true });
  s.addText("Zero-shot: no training data needed. Changing the policy means changing a sentence.", { x: M, y: 5.6, w: W - 2 * M, h: 0.5, fontSize: 18, italic: true, color: C.accent1, margin: 0, isTextBox: true });

  s = content(pres, "Three models, three roles",
    "All three are zero-shot NLI classifiers (two classes: entailment / not entailment). The fast model scores everything; the judge re-scores only uncertain scores; bge-m3 is the multilingual option.");
  const mw = (W - 2 * M - 0.6) / 3;
  [["ModernBERT-large", "Fast model", "Scores every (paragraph, hypothesis) pair. zeroshot-v2.0, 8k context."],
   ["DeBERTa-v3-large", "Judge", "Re-scores only scores in the uncertain band 0.60–0.95. Slower, more accurate."],
   ["bge-m3", "Multilingual", "For Russian and Ukrainian text; the same two-class output."]]
    .forEach(([h, role, b], i) => {
      const x = M + i * (mw + 0.3);
      s.addShape("rect", { x, y: 1.6, w: mw, h: 3.9, fill: { color: C.background2 }, line: { color: C.background2 } });
      s.addText(role.toUpperCase(), { x: x + 0.3, y: 1.85, w: mw - 0.6, h: 0.4, fontSize: 13, bold: true, color: C.accent1, charSpacing: 2, margin: 0, isTextBox: true });
      s.addText(h, { x: x + 0.3, y: 2.3, w: mw - 0.6, h: 0.6, fontSize: 22, bold: true, color: C.text1, fontFace: THEME.headFontFace, margin: 0, isTextBox: true });
      s.addText(b, { x: x + 0.3, y: 3.1, w: mw - 0.6, h: 2.2, fontSize: 16, color: C.text2, margin: 0, valign: "top", isTextBox: true });
    });
  s.addText("Measured on A's 149 test texts: the judge turned 2 wrong removals into 0.", { x: M, y: 5.8, w: W - 2 * M, h: 0.5, fontSize: 17, color: C.text1, margin: 0, isTextBox: true });

  pres.addSection({ title: "Principles" });
  s = content(pres, "Principle 1 · Label, never delete",
    "Every decision is a column next to the original line. The clean copy is a separate file. Because scores are stored, a new threshold or decision is re-applied without models (redecide).");
  s.addText("A row of labels.jsonl", { x: M, y: 1.5, w: 6.6, h: 0.4, fontSize: 15, bold: true, color: C.accent5, margin: 0, isTextBox: true });
  s.addText('{"line": 12, "action": "edited",\n "paragraphs": [{"span": [300, 1120],\n   "action": "remove",\n   "labels": ["culture_entertainment"],\n   "scores": {"involves_russia": 0.97,\n              "culture_entertainment": 0.91}}],\n "tokens": 1630, "tokens_removed": 205}',
    { x: M, y: 1.95, w: 6.6, h: 2.8, fontSize: 15, fontFace: "Courier New", color: C.text1, fill: { color: C.background2 }, margin: 12, valign: "top", isTextBox: true });
  s.addText("What this allows", { x: 7.7, y: 1.5, w: 5, h: 0.4, fontSize: 15, bold: true, color: C.accent5, margin: 0, isTextBox: true });
  s.addText(bullets(["Audit: every removed paragraph shows which label and score removed it",
    "Change your mind: redecide applies a new policy from stored scores, no models",
    "Count the cost: tokens removed per label (the composition report)",
    "Filter later: build any training set from the columns"], 17), { x: 7.7, y: 1.95, w: W - M - 7.7, h: 3.9, margin: 0, valign: "top", isTextBox: true });

  s = content(pres, "Principle 2 · Subject and framing are separate questions",
    "The same subject can be a fact or propaganda. Level 1 asks what the paragraph is about; level 2 asks how it is framed. Here both paragraphs are about Crimea.");
  const ew = (W - 2 * M - 0.4) / 2;
  [["\"Crimea is a peninsula on the northern coast of the Black Sea, connected to the mainland by the narrow Perekop Isthmus…\"", "pass", "Geography. No narrative fires: the text stays as it is."],
   ["\"Crimea is Russian and always will be. The peninsula returned home in 2014, when its people voted overwhelmingly to reunite with Russia…\"", "remove", "Framing: narr_annexation 0.98 ≥ 0.8. A narrative wins over any keep subject."]]
    .forEach(([t, a, why], i) => {
      const x = M + i * (ew + 0.4);
      s.addShape("rect", { x, y: 1.55, w: ew, h: 4.3, fill: { color: C.background2 }, line: { color: C.background2 } });
      s.addText(t, { x: x + 0.3, y: 1.8, w: ew - 0.6, h: 2.2, fontSize: 17, italic: true, color: C.text1, margin: 0, valign: "top", isTextBox: true });
      pill(s, C, a, x + 0.3, 4.25, 1.3, 0.42);
      s.addText(why, { x: x + 1.8, y: 4.15, w: ew - 2.1, h: 1.5, fontSize: 15, color: C.text2, margin: 0, valign: "top", isTextBox: true });
    });

  s = content(pres, "The cascade: each level runs only when it is needed",
    "Level 0 asks whether the paragraph is about the country at all. Only then are subjects (level 1) and framing (level 2) scored. Exceptions are checked last but win first.");
  const lv = [["Level 0 · gate", "\"This text mentions Russia…\" ≥ threshold, or a marker term (\"Kiev regime\", \"СВО\")", C.accent5],
    ["Level 1 · subject", "culture, celebrities, science, geography, history, sport … (one idea each)", C.accent1],
    ["Level 2 · framing", "Kremlin narratives, hate, opinions, the debunk guard", C.accent6],
    ["Exceptions", "top-priority rules, e.g. an unnamed \"our country\" → review", C.accent3],
    ["Decision", "remove · review · keep · pass", C.text1]];
  lv.forEach(([h, b, col], i) => {
    const y = 1.45 + i * 1.07;
    s.addShape("rect", { x: M, y, w: 3.4, h: 0.85, fill: { color: col }, line: { color: col } });
    s.addText(h, { x: M + 0.2, y, w: 3.0, h: 0.85, fontSize: 18, bold: true, color: C.background1, margin: 0, valign: "middle", isTextBox: true });
    s.addText(b, { x: M + 3.65, y, w: W - 2 * M - 3.65, h: 0.85, fontSize: 17, color: C.text1, margin: 0, valign: "middle", isTextBox: true });
    if (i < lv.length - 1) arrowDown(s, C, M + 1.7, y + 0.86, 0.2);
  });

  s = content(pres, "How the action is decided",
    "Rules in order; the first that applies decides. Flag labels never change the action. In A's policy the conflict rule sends remove + keep to review.");
  const rr = [headRow(C, ["#", "Situation", "Action"]),
    ["1", "Gate below its threshold and no marker term: the keyword was incidental", actCell(C, "pass")],
    ["2", "A level-2 remove label is yes and nothing softens it (narratives win)", actCell(C, "remove")],
    ["3", "A remove label and a keep label are both yes (conflict)", actCell(C, "review")],
    ["4", "A remove label is yes", actCell(C, "remove")],
    ["5", "A review label is yes, or a softened narrative", actCell(C, "review")],
    ["6", "A keep label is yes, or the gate is yes with no subject", actCell(C, "keep")],
    ["★", "An exception matches (checked before the result is final; never lowers a protected removal)", actCell(C, "exception")]];
  s.addTable(rr, { x: M, y: 1.45, w: W - 2 * M, colW: [0.7, 9.6, 1.83], fontSize: 15, color: C.text1, border: { type: "solid", pt: 0.75, color: "D9DEE4" }, rowH: 0.62, valign: "middle", margin: 0.1 });

  pres.addSection({ title: "Methods" });
  s = content(pres, "Writing hypotheses that work",
    "Rules from the guide, then measured. The biolabs label went from 0.38 to 0.96 on its own test text with a more concrete sentence.");
  s.addText(bullets([{ text: "One idea per sentence", bold: true }, { text: "split \"insults or illegitimate\" into two labels", sub: true },
    { text: "Concrete words, content not intent", bold: true }, { text: "\"accuses the United States of making biological weapons in Ukraine\"", sub: true },
    { text: "Test 2–3 wordings on every case text", bold: true }, { text: "catch false alarms before they reach real data", sub: true }], 17),
    { x: M, y: 1.5, w: 5.6, h: 4.6, margin: 0, valign: "top", isTextBox: true });
  s.addChart(pres.ChartType.bar, [
    { name: "v4 wording", labels: ["yes text 1", "yes text 2"], values: [0.38, 0.01] },
    { name: "v5 wording", labels: ["yes text 1", "yes text 2"], values: [0.96, 0.13] }],
  chartBase({ x: 6.6, y: 1.4, w: W - M - 6.6, h: 4.9, barDir: "col", barGrouping: "clustered", chartColors: [HEX.accent5, HEX.accent1],
    showTitle: true, title: "narr_biolabs score on its yes texts", valAxisMaxVal: 1, valAxisMinVal: 0, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.00",
    showLegend: true, legendPos: "b", legendFontFace: "+mn-lt", legendFontSize: 13, legendColor: HEX.dk2 }));

  s = content(pres, "Guard: a fact-check is not propaganda",
    "reports_or_debunks softens narrative labels: a paragraph that reports or refutes a claim goes to review instead of being removed. Measured on A's case texts with ModernBERT only.");
  s.addChart(pres.ChartType.bar, [{ name: "wrongly removed", labels: ["no guard", "guard at 0.8", "guard at 0.6", "0.6 + judge"], values: [6, 4, 2, 0] }],
    chartBase({ x: M, y: 1.4, w: 7.4, h: 4.9, barDir: "col", chartColors: [HEX.accent2], showTitle: true, title: "Texts A keeps that were removed",
      valAxisMinVal: 0, valAxisMaxVal: 7, dataLabelPosition: "outEnd", showLegend: false }));
  s.addText(bullets(["The guard reads \"This text reports or refutes what someone else claimed.\"",
    "Without it, news quoting a Kremlin claim is removed with the claim",
    "Threshold 0.6 halves the wrong removals; the judge removes the rest"], 17), { x: 8.4, y: 1.7, w: W - M - 8.4, h: 4.4, margin: 0, valign: "top", isTextBox: true });

  s = content(pres, "Thresholds with a guarantee",
    "Every label has its own threshold. They start as guesses (0.8) and are replaced by values from hand labels. CRC gives a statistical bound on misses.");
  [["Start", "0.8 for every label, 0.12 for the gate: guesses until hand labels exist"],
   ["eval", "precision, recall and F1 per label from hand labels; suggests the best-F1 threshold and the threshold for a target recall"],
   ["CRC", "Conformal risk control on randomly picked items: expected miss rate ≤ 5 % for that label, if the corpus is like the sample"]]
    .forEach(([h, b], i) => card(s, C, { x: M + i * ((W - 2 * M - 0.6) / 3 + 0.3), y: 1.6, w: (W - 2 * M - 0.6) / 3, h: 3.3, head: h, body: b, num: i + 1, bodySize: 17 }));
  s.addText("python nli_label.py eval labels\\seed.jsonl --policy policy\\russia_policy_v5.json", { x: M, y: 5.3, w: W - 2 * M, h: 0.6, fontSize: 15, fontFace: "Courier New", color: C.text1, fill: { color: C.background2 }, margin: 12, valign: "middle", isTextBox: true });

  s = content(pres, "Measure every change",
    "Each policy change is run on all case texts before it is kept. Two of my own changes made things worse and were caught only this way.");
  const lp = ["Change the policy", "Run the cases", "Compare with expected", "Keep or drop"];
  lp.forEach((t, i) => {
    const x = M + i * 3.1;
    s.addText(t, { shape: "roundRect", rectRadius: 0.15, x, y: 1.55, w: 2.7, h: 0.9, fill: { color: C.accent1 }, color: C.background1, fontSize: 17, bold: true, align: "center", valign: "middle", margin: 0, isTextBox: true });
    if (i < 3) arrowRight(s, C, x + 2.75, 2.0, 0.3);
  });
  card(s, C, { x: M, y: 3.0, w: (W - 2 * M - 0.4) / 2, h: 3.0, head: "v3: a longer gate sentence", body: "Adding \"or the war between Russia and Ukraine\" dropped the gate score of a plain Moscow Zoo text from 0.62 to 0.04. Dropped.", bodySize: 17 });
  card(s, C, { x: M + (W - 2 * M - 0.4) / 2 + 0.4, y: 3.0, w: (W - 2 * M - 0.4) / 2, h: 3.0, head: "v4: narrative keywords", body: "Ukraine words sent ordinary Ukraine paragraphs through the whole pipeline: 4 texts broke. Fixed with the narrative-only rule.", bodySize: 17 });

  s = content(pres, "Exceptions and protected labels",
    "Exceptions are policy rules with priority. They can make a decision stricter or looser, but a protected label (hate, violence) is never lowered.");
  s.addText('"exceptions": [{\n  "key": "ambiguous_our_country",\n  "decision": "review",\n  "priority": 100,\n  "skip_quoted": true,\n  "match": {"phrases": ["our country",\n            "наша страна", "наша країна"]}\n}]',
    { x: M, y: 1.5, w: 6.2, h: 3.2, fontSize: 15, fontFace: "Courier New", color: C.text1, fill: { color: C.background2 }, margin: 12, valign: "top", isTextBox: true });
  s.addText(bullets(["Match by exact phrases or by an NLI hypothesis",
    "Highest priority wins; the same priority: file order",
    "skip_quoted: \"Zelensky said: 'Our country…'\" names the speaker, so it does not count",
    "Only Russia/Ukraine paragraphs: \"Our country has the best beaches\" is untouched",
    "Protected labels: a hate removal stays removed"], 17), { x: 7.3, y: 1.6, w: W - M - 7.3, h: 4.5, margin: 0, valign: "top", isTextBox: true });

  s = content(pres, "Russia-side principles: symmetric by design",
    "The Russia-side policy applies the same rule in both directions. It does not remove or review text because it favours one side.");
  const sr = [headRow(C, ["Content", "Action"]),
    ["Hate or calls for violence against Russians or Ukrainians", actCell(C, "remove")],
    ["Opinions about Russia or Ukraine: praise and criticism alike", actCell(C, "review")],
    ["History (a review topic; more can be added)", actCell(C, "review")],
    ["Known false claims (e.g. \"Ukraine has joined NATO\")", actCell(C, "review")],
    ["An unnamed \"our country\" (exception)", actCell(C, "review")],
    ["Facts, including war facts, whoever they hurt", actCell(C, "keep")]];
  s.addTable(sr, { x: M, y: 1.45, w: 8.3, colW: [6.5, 1.8], fontSize: 15, color: C.text1, border: { type: "solid", pt: 0.75, color: "D9DEE4" }, rowH: 0.66, valign: "middle", margin: 0.1 });
  s.addShape("rect", { x: 9.3, y: 1.45, w: W - M - 9.3, h: 4.6, fill: { color: C.text1 }, line: { color: C.text1 } });
  s.addText("Not done", { x: 9.55, y: 1.7, w: 3.0, h: 0.5, fontSize: 20, bold: true, color: C.background1, fontFace: THEME.headFontFace, margin: 0, isTextBox: true });
  s.addText("Removing or reviewing text because it is unfavourable to Russia or favourable to Ukraine. That would teach a model one side's view as the whole truth.",
    { x: 9.55, y: 2.3, w: W - M - 9.8, h: 3.5, fontSize: 16, color: C.background2, margin: 0, valign: "top", isTextBox: true });

  pres.addSection({ title: "Summary" });
  s = closing(pres, "The principles in one slide", ["Label, never delete; the clean copy is separate",
    "Paragraphs, not documents; subject and framing apart",
    "One idea per hypothesis; every wording measured",
    "Thresholds from hand labels, with a CRC bound",
    "Guards and protected labels before speed",
    "Facts are kept, whoever they hurt"], "Recap of the principles.");
  await save(pres, "02_core_ideas_and_methods.pptx");
}

// =================================================================================================================
// Deck 3: sample data and test results
// =================================================================================================================
async function deck3() {
  const { pres, C } = newDeck("Sample data and test results");
  pres.addSection({ title: "Method" });
  titleSlide(pres, "Sample data and test results", "Case texts, expected actions and what the policies did\nA's policy v1–v5 · Russia-side policy v1–v2 · November 2026",
    "Every number here comes from runs on the case texts (labels/cases_v5.json and labels/russia_llm_cases_v1.json).");

  let s = content(pres, "How we test a policy",
    "Each label gets a yes case and a near-miss case (looks related, but the label is no). Each text has an expected action. tools/compare_cases.py and the viewer's Try page compare a run with it.");
  s.addText(bullets(["Every label: a yes case and a near-miss case", "Edge cases: conflicts, fact-checks, scientists' names, prices in tech news",
    "Each text has an expected action (and sometimes \"also fine\")", "Runs on CPU in minutes; repeated after every policy change"], 17),
    { x: M, y: 1.55, w: 6.4, h: 3.6, margin: 0, valign: "top", isTextBox: true });
  stat(s, C, { x: 7.4, y: 1.5, w: 2.6, big: "149", label: "texts in 78 cases\nA's policy" });
  stat(s, C, { x: 10.2, y: 1.5, w: 2.5, big: "43", label: "texts in 23 cases\nRussia side", color: C.accent6 });
  s.addText("python tools\\compare_cases.py out_label_ru_v2 --corpus test_corpus_cases_ru", { x: M, y: 4.3, w: W - 2 * M, h: 0.6, fontSize: 13, fontFace: "Courier New", color: C.text1, fill: { color: C.background2 }, margin: 12, valign: "middle", isTextBox: true });

  pres.addSection({ title: "A's policy" });
  s = content(pres, "A's policy improved version by version",
    "Share of case texts that got exactly the expected action. The case set grew from 125 to 149 texts as harder cases were added (v4), which explains the small dip.");
  s.addChart(pres.ChartType.bar, [{ name: "as expected (%)", labels: ["v1", "v2", "v3", "v4", "v5", "v5 + judge"], values: [65, 66, 82, 80, 82, 83] }],
    chartBase({ x: M, y: 1.4, w: 8.2, h: 5.0, barDir: "col", chartColors: [HEX.accent1], showTitle: true, title: "Case texts with the expected action (%)",
      valAxisMinVal: 0, valAxisMaxVal: 100, dataLabelPosition: "outEnd", showLegend: false }));
  s.addText(bullets([{ text: "v3: cascade fixes", bold: true }, { text: "gate threshold 0.12, level 2 for every gated paragraph", sub: true },
    { text: "v4: Kremlin accusations", bold: true }, { text: "5 new narrative labels, narrative keywords", sub: true },
    { text: "v5: measured wordings", bold: true }, { text: "debunk guard 0.6, leader labels split", sub: true },
    { text: "Judge", bold: true }, { text: "0 texts wrongly removed", sub: true }], 16), { x: 9.2, y: 1.6, w: W - M - 9.2, h: 4.8, margin: 0, valign: "top", isTextBox: true });

  s = content(pres, "nli_label.py vs the old nli_filter.py, same 149 texts",
    "The old filter decides per document whether it is about Russia. It cannot tell geography from culture, or a fact-check from propaganda.");
  s.addChart(pres.ChartType.bar, [
    { name: "nli_filter.py", labels: ["wrongly removed", "missed (should remove)"], values: [21, 26] },
    { name: "nli_label.py v5", labels: ["wrongly removed", "missed (should remove)"], values: [1, 6] }],
  chartBase({ x: M, y: 1.4, w: 7.6, h: 5.0, barDir: "col", barGrouping: "clustered", chartColors: [HEX.accent5, HEX.accent1], showTitle: true, title: "Texts handled wrongly",
    valAxisMinVal: 0, valAxisMaxVal: 30, dataLabelPosition: "outEnd", showLegend: true, legendPos: "b", legendFontFace: "+mn-lt", legendFontSize: 13, legendColor: HEX.dk2 }));
  stat(s, C, { x: 8.7, y: 1.6, w: 4.0, big: "93 %", label: "handled correctly by nli_label.py" });
  stat(s, C, { x: 8.7, y: 4.0, w: 4.0, big: "68 %", label: "by nli_filter.py: geography, politics and fact-checks removed", color: C.accent5 });

  s = content(pres, "Sample results · A's policy v5",
    "Real lines from the v5 + judge run. Expected = what A's policy wants; got = what the tool did.");
  const ar = [headRow(C, ["Text (start)", "Expected", "Got", "Why"]),
    ["The Russian animated series 'Masha and the Bear' has become one of the most-watched cartoons…", actCell(C, "remove"), actCell(C, "remove"), "culture_entertainment 0.99"],
    ["The Volga is the longest river in Europe, flowing about 3,530 km through western Russia…", actCell(C, "keep"), actCell(C, "keep"), "geography"],
    ["CatBoost is an open-source gradient boosting library developed by engineers at Yandex…", actCell(C, "keep"), actCell(C, "keep"), "science_technology"],
    ["Crimea is a peninsula on the northern coast of the Black Sea…", actCell(C, "pass"), actCell(C, "pass"), "only a narrative keyword; no narrative fires"],
    ["Crimea is Russian and always will be. The peninsula returned home in 2014…", actCell(C, "remove"), actCell(C, "remove"), "narr_annexation 0.98"],
    ["FACT CHECK: Did Ukraine run secret US-funded bioweapons labs? No…", actCell(C, "keep"), actCell(C, "keep"), "reports_or_debunks 0.97"],
    ["Russian pop singer … has co-founded a technology startup in Moscow…", actCell(C, "review"), actCell(C, "review"), "celebrities (remove) + science (keep): conflict"]];
  s.addTable(ar, { x: M, y: 1.4, w: W - 2 * M, colW: [6.6, 1.3, 1.3, 2.93], fontSize: 14, color: C.text1, border: { type: "solid", pt: 0.75, color: "D9DEE4" }, rowH: 0.66, valign: "middle", margin: 0.08 });

  s = content(pres, "Inside one decision",
    "One paragraph through the cascade, with the real scores of the v5 + judge run. The black tick is each label's threshold.");
  s.addText("\"Crimea is Russian and always will be. The peninsula returned home in 2014, when its people voted overwhelmingly to reunite with Russia…\"",
    { x: M, y: 1.35, w: W - 2 * M, h: 0.75, fontSize: 16, italic: true, color: C.text1, margin: 0, valign: "middle", isTextBox: true });
  const steps3 = [["Level 0", [["involves_russia", 0.99, 0.12, true]]],
    ["Level 1", [["values_mindset", 0.59, 0.8, false], ["history_soviet", 0.19, 0.8, false], ["geography", 0.03, 0.8, false]]],
    ["Level 2", [["narr_annexation", 0.98, 0.8, true], ["narr_russian_greatness", 0.82, 0.8, true], ["reports_or_debunks", 0.15, 0.6, false]]]];
  let yy = 2.25;
  steps3.forEach(([lvl, rowsL]) => {
    s.addText(lvl, { x: M, y: yy, w: 1.2, h: 0.34, fontSize: 15, bold: true, color: C.accent1, margin: 0, valign: "middle", isTextBox: true });
    rowsL.forEach(([k, sc, th, y1]) => { scoreBar(s, C, { x: M + 1.3, y: yy, w: 8.3, label: k, score: sc, thr: th, yes: y1 }); yy += 0.42; });
    yy += 0.18;
  });
  s.addShape("rect", { x: 10.0, y: 2.25, w: W - M - 10.0, h: 3.9, fill: { color: C.text1 }, line: { color: C.text1 } });
  pill(s, C, "remove", 10.3, 2.55, 1.4, 0.45);
  s.addText("A level-2 narrative is yes and the guard is no: the narrative wins. narr_russian_greatness was checked by the judge.",
    { x: 10.3, y: 3.2, w: W - M - 10.6, h: 2.8, fontSize: 15, color: C.background2, margin: 0, valign: "top", isTextBox: true });

  s = content(pres, "Where A's policy still fails",
    "The open problems from the report, with the case that shows each one.");
  [["\"…so-called Kiev regime … only denazification can bring peace\"", "Expected remove, got keep: the debunk guard fired on propaganda (a false alarm)."],
   ["A study of Ukrainians called 'vermin' on Russian TV", "Expected keep, got review: the hostility label fires on a reported slur."],
   ["narr_nazi yes text: fast 0.95, judge 0.64", "Missed: 0.95 is the top of the judge's band. Next test: band 0.6–0.9."],
   ["Crimea geography, no judge", "narr_annexation 0.90: no better wording found yet."]]
    .forEach(([h, b], i) => card(s, C, { x: M + (i % 2) * ((W - 2 * M - 0.3) / 2 + 0.3), y: 1.5 + Math.floor(i / 2) * 2.45, w: (W - 2 * M - 0.3) / 2, h: 2.2, head: h, body: b, bodySize: 16, num: i + 1, numColor: C.accent2 }));

  pres.addSection({ title: "Russia side" });
  s = content(pres, "Russia-side policy v2, by group",
    "Texts per group that got the expected action (or an accepted one). Hate, opinions, exceptions, false claims and facts are all right; the misses are history and three of your examples.");
  const groups = ["Exceptions", "Hate", "Opinions", "False claims", "Facts", "History", "Your examples"];
  s.addChart(pres.ChartType.bar, [
    { name: "as expected", labels: groups, values: [6, 5, 4, 2, 5, 3, 14] },
    { name: "not as expected", labels: groups, values: [0, 0, 0, 0, 0, 1, 3] }],
  chartBase({ x: M, y: 1.4, w: 8.6, h: 5.0, barDir: "bar", barGrouping: "stacked", chartColors: [HEX.accent4, HEX.accent2], showTitle: true, title: "Case texts per group (v2, ModernBERT)",
    dataLabelPosition: "ctr", dataLabelColor: "FFFFFF", dataLabelFormatCode: "0;-0;;", showLegend: true, legendPos: "b", legendFontFace: "+mn-lt", legendFontSize: 13, legendColor: HEX.dk2, catAxisOrientation: "maxMin" }));
  stat(s, C, { x: 9.6, y: 1.6, w: 3.1, big: "39 / 43", label: "texts as expected (91 %); the same with the judge", color: C.accent6, bigSize: 46 });
  stat(s, C, { x: 9.6, y: 4.0, w: 3.1, big: "0", label: "texts wrongly removed", color: C.accent4, bigSize: 46 });

  s = content(pres, "Sample results · Russia-side policy v2",
    "Your examples and a few written for the cases. The last row is one of the four misses.");
  const rr3 = [headRow(C, ["Text", "Expected", "Got", "Why"]),
    ["Russia was under Mongol rule for 200 years, from the 13th to the 15th century.", actCell(C, "review"), actCell(C, "review"), "history"],
    ["Russia's election law lacks democracy.", actCell(C, "review"), actCell(C, "review"), "opinion_about_russia"],
    ["Ukrainian people are very kind.", actCell(C, "review"), actCell(C, "review"), "opinion_about_ukraine"],
    ["Russian troops crossed into Ukraine on 24 February 2022.", actCell(C, "keep"), actCell(C, "keep"), "war fact"],
    ["Ukraine has joined NATO.", actCell(C, "review"), actCell(C, "review"), "claim_ukraine_in_nato"],
    ["Russia is currently seeking … diplomatic relations with our country.", actCell(C, "review"), actCell(C, "review"), "exception: our country"],
    ["Moscow responded after Zelensky said: \"Our country will never give up…\"", actCell(C, "keep"), actCell(C, "keep"), "quoted: no exception"],
    ["Every Russian is guilty for this war, and every Russian family deserves to suffer.", actCell(C, "remove"), actCell(C, "remove"), "hostility_russians"],
    ["Ukraine's economy is developed.", actCell(C, "review"), { text: "keep ✗", options: { bold: true, color: C.accent2, fontSize: 14, align: "center" } }, "evaluation worded as a fact"]];
  s.addTable(rr3, { x: M, y: 1.35, w: W - 2 * M, colW: [6.9, 1.3, 1.3, 2.63], fontSize: 14, color: C.text1, border: { type: "solid", pt: 0.75, color: "D9DEE4" }, rowH: 0.5, valign: "middle", margin: 0.08 });

  s = content(pres, "v1 vs v2: the lower score is the better policy",
    "v1 scored 40/43 but its history label fired on recent war facts and on opinions. v2 scores 39/43 with every fact kept.");
  const hw = (W - 2 * M - 0.4) / 2;
  [["v1 · 40 / 43", "\"This text is about the history of Russia or Ukraine.\"", "Fired on \"Russian troops crossed into Ukraine on 24 February 2022\" (0.95) and on the Kherson text (0.97): war facts sent to review. Two opinions were caught only by this accident.", C.accent5],
   ["v2 · 39 / 43", "\"…describes historical events from centuries ago in Russia, Ukraine or the Soviet Union.\"", "No false alarm on any case text. All 5 facts kept. Chosen from 9 wordings tested against every text.", C.accent1]]
    .forEach(([h, hyp, b, col], i) => {
      const x = M + i * (hw + 0.4);
      s.addShape("rect", { x, y: 1.5, w: hw, h: 4.7, fill: { color: C.background2 }, line: { color: C.background2 } });
      s.addText(h, { x: x + 0.3, y: 1.7, w: hw - 0.6, h: 0.6, fontSize: 24, bold: true, color: col, fontFace: THEME.headFontFace, margin: 0, isTextBox: true });
      s.addText(hyp, { x: x + 0.3, y: 2.45, w: hw - 0.6, h: 1.1, fontSize: 16, italic: true, color: C.text1, margin: 0, valign: "top", isTextBox: true });
      s.addText(b, { x: x + 0.3, y: 3.65, w: hw - 0.6, h: 2.4, fontSize: 16, color: C.text2, margin: 0, valign: "top", isTextBox: true });
    });

  s = content(pres, "Open problems",
    "What the case runs do not handle yet, and what would show whether it matters on real data.");
  [["Evaluations worded like facts", "\"Russia's vaccination is world-class\", \"Ukraine's economy is developed\": kept instead of review. Six more wordings did worse."],
   ["Recent history", "\"In 1991 Ukraine declared independence from the Soviet Union\" scores 0.02 even for \"…about the Soviet Union\"."],
   ["Opinions about works", "\"Swan Lake … does not suit the present era\": no opinion wording reached 0.6."],
   ["Review queue size", "Unknown until a real corpus sample is run; opinions are common in web text."],
   ["Our own test texts", "They show the design works; real-corpus hand labels will show how well."]]
    .forEach(([h, b], i) => {
      const y = 1.45 + i * 1.03;
      circle(s, C, i + 1, M, y + 0.1, 0.55, C.accent3);
      s.addText(h, { x: M + 0.8, y: y + 0.1, w: 3.6, h: 0.8, fontSize: 18, bold: true, color: C.text1, margin: 0, valign: "top", isTextBox: true });
      s.addText(b, { x: M + 4.5, y: y + 0.12, w: W - 2 * M - 4.5, h: 0.8, fontSize: 15, color: C.text2, margin: 0, valign: "top", isTextBox: true });
    });

  pres.addSection({ title: "Summary" });
  s = closing(pres, "Takeaways", ["A's policy v5 + judge: 83 % exact, 0 wrongly removed on 149 texts",
    "Russia-side v2: 91 %, all hate removed, all facts kept on 43 texts",
    "nli_label.py beats the old document filter: 93 % vs 68 %",
    "Next: hand labels from a real corpus for real thresholds"], "Summary of the results.");
  await save(pres, "03_test_results.pptx");
}

(async () => { await deck1(); await deck2(); await deck3(); })().catch((e) => { console.error(e); process.exit(1); });

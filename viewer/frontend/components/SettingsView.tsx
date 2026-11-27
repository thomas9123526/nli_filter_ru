"use client";
// /settings: every setting of the Labelling side (Russia LLM) in one place, as cards with an icon, what it is for and
// the file it changes; a card opens the page where that setting is shown and edited. The tools (Try, Experiment,
// Compare, clean-up, keyword statistics) stay on /label.
import Link from "next/link";
import { Crumbs } from "./ui";

type Item = { key: string; href: string; title: string; text: string; file: string; icon: keyof typeof ICONS; testid: string };

const ICONS = {
  policy: <><path d="M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6l7-3z" /><path d="M9 12l2 2 4-4" /></>,
  rules: <><rect x="4" y="4" width="16" height="16" rx="2" /><path d="M8 12l2.5 2.5L16 9" /></>,
  tag: <><path d="M3 12V4h8l10 10-8 8L3 12z" /><circle cx="7.5" cy="7.5" r="1.5" /></>,
  globe: <><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z" /></>,
  table: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 10h18M9 10v9M15 10v9" /></>,
  translate: <><path d="M4 5h9M8.5 3v2M6 5c.8 3 2.8 5.5 5 7M11 5c-.8 3.5-3.2 6.5-6 8" /><path d="M13 21l4-9 4 9M14.5 18h5" /></>,
  docs: <><path d="M6 3h8l4 4v14H6V3z" /><path d="M14 3v4h4M9 12h6M9 16h6" /></>,
  cases: <><path d="M9 6h11M9 12h11M9 18h11" /><path d="M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2" /></>,
};

const GROUPS: { title: string; items: Item[] }[] = [
  { title: "Policy and keywords", items: [
    { key: "policy", href: "/label/policy", title: "Labelling policy", icon: "policy", testid: "policy-link",
      text: "Labels and their hypotheses, thresholds and decisions; gates, run_if, markers, exceptions. Checked while you type.",
      file: "policy/*.json" },
    { key: "files", href: "/label/files", title: "Keywords & place names", icon: "tag", testid: "files-link",
      text: "The keyword lists that pick the paragraphs to label, and the place-name tables (the files a policy names).",
      file: "keywords/*.txt and place-name files" },
    { key: "non-english", href: "/label/non-english", title: "Non-English keywords", icon: "globe", testid: "non-english-link",
      text: "Keywords in other languages and what a paragraph with one gets.", file: "policy/non_english.json" },
  ] },
  { title: "Results", items: [
    { key: "expected-rules", href: "/label/expected-rules", title: "Expected-result rules", icon: "rules", testid: "expected-rules-link",
      text: "Which actions count as the same when a result is checked against the expected one (strict / quick profiles, aliases).",
      file: "labels/expected_rules.json" },
    { key: "output", href: "/label/output", title: "Simple-mode output", icon: "table", testid: "output-link",
      text: "The fields and rows a simple-mode run writes (the schema).", file: "output/simple_schema.json" },
  ] },
  { title: "Test sets", items: [
    { key: "cases", href: "/label/try", title: "Case sets", icon: "cases", testid: "cases-link",
      text: "Short test texts with their expected actions, edited and run on the Try page.", file: "labels/*cases*.json" },
    { key: "docs", href: "/label/docs", title: "Documents test set", icon: "docs", testid: "docs-link",
      text: "Whole test documents (several paragraphs) with the expected action of each.", file: "labels/*docs*.json" },
  ] },
  { title: "Viewer", items: [
    { key: "translate", href: "/label/translate", title: "Translation", icon: "translate", testid: "translate-link",
      text: "The translation models behind the language buttons: add, remove, order, test.", file: "viewer/viewer_config.json" },
  ] },
];

export function SettingsIcon({ name, size = 22 }: { name: keyof typeof ICONS; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{ICONS[name]}</svg>);
}

export function SettingsView() {
  return (
    <>
      <div className="page-head"><div>
        <Crumbs items={[{ label: "Settings" }]} />
        <h1>Settings</h1>
        <div className="sub">Everything the labelling uses that you can change. Click a setting to see and edit it; every page checks
          the change and keeps a backup of the old file.</div>
      </div></div>
      {GROUPS.map((g) => (
        <section key={g.title} style={{ marginBottom: 18 }}>
          <h2 className="settings-group">{g.title}</h2>
          <div className="settings-grid">
            {g.items.map((it) => (
              <Link key={it.key} href={it.href} className="settings-card" data-testid={it.testid}>
                <span className="settings-icon"><SettingsIcon name={it.icon} /></span>
                <span className="settings-body">
                  <strong>{it.title}</strong>
                  <span className="settings-text">{it.text}</span>
                  <code className="settings-file">{it.file}</code>
                </span>
                <span className="settings-go" aria-hidden="true">›</span>
              </Link>))}
          </div>
        </section>))}
    </>
  );
}

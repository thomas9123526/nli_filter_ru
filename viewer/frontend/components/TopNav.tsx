"use client";
// The header's areas; the one the current page belongs to is highlighted. The setting pages (linked from /settings)
// live under /label/… but count as Settings.
import Link from "next/link";
import { usePathname } from "next/navigation";

export const SETTING_PAGES = ["/label/policy", "/label/files", "/label/non-english", "/label/expected-rules", "/label/output",
  "/label/docs", "/label/translate"];

export function TopNav() {
  const path = (usePathname() || "/").replace(/\/$/, "") || "/";
  const under = (p: string) => path === p || path.startsWith(p + "/");
  const isSetting = under("/settings") || SETTING_PAGES.some(under);
  const on = (p: string) => (p === "/settings" ? (isSetting ? "on" : "") : under(p) && !isSetting ? "on" : "");
  return (
    <nav className="topnav" data-testid="topnav">
      <Link className={on("/label")} href="/label">Labelling (Russia LLM)</Link>
      <Link className={on("/filter")} href="/filter">Filter</Link>
      <Link className={on("/settings")} href="/settings" data-testid="nav-settings">Settings</Link>
    </nav>
  );
}

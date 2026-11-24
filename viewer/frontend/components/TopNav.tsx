"use client";
// The header's two areas; the one the current page belongs to is highlighted.
import Link from "next/link";
import { usePathname } from "next/navigation";

export function TopNav() {
  const path = usePathname() || "/";
  const on = (p: string) => (path === p || path.startsWith(p + "/") ? "on" : "");
  return (
    <nav className="topnav" data-testid="topnav">
      <Link className={on("/label")} href="/label">Labelling (Russia LLM)</Link>
      <Link className={on("/filter")} href="/filter">Filter</Link>
    </nav>
  );
}

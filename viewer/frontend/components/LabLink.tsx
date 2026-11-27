"use client";
// A link to the Experiment page that remembers where it was opened from: ?back=<this page's URL, its view state> is
// added when it is clicked, so the Experiment page's "◂ Back to …" returns here in one click (however many Prev / Next
// steps were taken there).
import Link from "next/link";
import { useRouter } from "next/navigation";
import { href } from "@/lib/format";
import type { Params } from "@/lib/api";
import { backHere } from "@/lib/urlState";

export function LabLink({ params, line, className, title, testid, children }: {
  params: Params; line?: number; className?: string; title?: string; testid?: string; children: React.ReactNode;
}) {
  const router = useRouter();
  return (
    <Link className={className} title={title} data-testid={testid} href={href("/label/lab", params)}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;   // a new tab: no back needed
        e.preventDefault();
        router.push(href("/label/lab", { ...params, back: backHere(line) }));
      }}>{children}</Link>);
}

/** Where "◂ Back to …" goes and what it says. */
export function backTarget(back: string | null, run: string): { url: string; label: string } {
  if (back) {
    const path = back.split("?")[0].replace(/\/$/, "");
    const q = new URLSearchParams(back.split("?")[1] || "");
    if (path === "/label/doc") return { url: back, label: `line ${q.get("line") || ""}`.trim() };
    if (path === "/label/run") return { url: back, label: "the run" };
    if (path === "/label/compare") return { url: back, label: "the comparison" };
    if (path === "/label/corpus") return { url: back, label: "the corpus" };
    if (path === "/label") return { url: back, label: "Labelling" };
    return { url: back, label: "the previous page" };
  }
  return run ? { url: href("/label/run", { run }), label: "the run" } : { url: "/label", label: "Labelling" };
}

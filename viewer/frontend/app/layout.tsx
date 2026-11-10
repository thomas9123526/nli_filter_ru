import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { ThemeToggle } from "@/components/ui";

export const metadata: Metadata = {
  title: "NLI Result Viewer",
  description: "Browse nli_filter.py decisions next to the original corpus lines",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="topbar">
          <Link href="/" className="brand"><span className="brand-mark">N</span>NLI Result Viewer</Link>
          <span className="spacer" />
          <a className="btn small ghost" href="/docs" target="_blank" rel="noreferrer">API docs</a>
          <ThemeToggle />
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}

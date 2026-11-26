"use client";
// The view state of a list page kept in the URL (file, filters, page offset, opened rows ...), so browser Back and a
// copied link show exactly the same view, plus the scroll position restored once the rows are on the page.
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef } from "react";

export type UrlState = Record<string, string>;

/** Read `keys` from the URL (defaults when missing); `set({k: v})` replaces the URL (no new history entry). Values equal
 * to their default are left out of the URL, so links stay short and old links keep working. */
export function useUrlState<K extends string>(defaults: Record<K, string>): [Record<K, string>, (patch: Partial<Record<K, string>>) => void] {
  const sp = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const vals = {} as Record<K, string>;
  for (const k of Object.keys(defaults) as K[]) vals[k] = sp.get(k) ?? defaults[k];
  const spRef = useRef(sp);
  spRef.current = sp;
  const defRef = useRef(defaults);
  defRef.current = defaults;
  const set = useCallback((patch: Partial<Record<K, string>>) => {
    const q = new URLSearchParams(spRef.current.toString());
    for (const [k, v] of Object.entries(patch) as [K, string | undefined][]) {
      if (v === undefined || v === null || v === "" || v === defRef.current[k]) q.delete(k);
      else q.set(k, String(v));
    }
    const s = q.toString();
    router.replace(`${pathname}${s ? `?${s}` : ""}${typeof window !== "undefined" ? window.location.hash : ""}`, { scroll: false });
  }, [router, pathname]);
  return [vals, set];
}

/** A set of numbers kept in one URL value ("12,15"), capped so the URL stays short. */
export const MAX_OPEN = 20;
export function parseSet(v: string): Set<number> {
  return new Set(v.split(",").map((x) => parseInt(x, 10)).filter((x) => Number.isFinite(x)));
}
export function formatSet(s: Set<number>): string {
  return Array.from(s).slice(-MAX_OPEN).join(",");
}

const SCROLL_KEY = "nli.scroll:";

/** Remember the scroll position of this URL while the page is open; restore it once `ready` (the rows are rendered).
 * When it cannot be restored (the page got shorter), scroll to `#line-N` / the element with data-line=N if the URL
 * names one (?from_line=N) and mark it briefly. */
export function useRestoreScroll(ready: boolean) {
  const sp = useSearchParams();
  const pathname = usePathname();
  const key = `${SCROLL_KEY}${pathname.replace(/\/$/, "")}?${sp.toString()}`;
  const restored = useRef<string | null>(null);
  const keyRef = useRef(key);
  keyRef.current = key;
  useEffect(() => {
    let t: ReturnType<typeof setTimeout> | null = null;
    // saved only while the browser still shows this page's URL: when a link is followed, the next page scrolls to
    // the top before this one is gone, and that must not overwrite the position
    const here = () => `${SCROLL_KEY}${window.location.pathname.replace(/\/$/, "")}?${new URLSearchParams(window.location.search).toString()}` === keyRef.current;
    const save = () => { if (!here()) return; try { sessionStorage.setItem(keyRef.current, String(Math.round(window.scrollY))); } catch { /* no storage */ } };
    const onScroll = () => { if (t) clearTimeout(t); t = setTimeout(save, 120); };
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("pagehide", save);
    return () => { window.removeEventListener("scroll", onScroll); window.removeEventListener("pagehide", save); if (t) clearTimeout(t); };
  }, []);
  useEffect(() => {
    if (!ready || restored.current === key) return;
    restored.current = key;
    let y: number | null = null;
    try { const v = sessionStorage.getItem(key); y = v === null ? null : parseInt(v, 10); } catch { /* no storage */ }
    const fromLine = sp.get("from_line") || (typeof window !== "undefined" && window.location.hash.startsWith("#line-") ? window.location.hash.slice(6) : "");
    requestAnimationFrame(() => {
      if (y !== null && y > 0 && document.documentElement.scrollHeight >= y + 50) {
        window.scrollTo(0, y);
        return;
      }
      if (fromLine) {
        const el = document.querySelector(`[data-line="${CSS.escape(fromLine)}"]`) || document.getElementById(`line-${fromLine}`);
        if (el) {
          el.scrollIntoView({ block: "center" });
          el.classList.add("flash-row");
          setTimeout(() => el.classList.remove("flash-row"), 2000);
        }
      }
    });
  }, [ready, key, sp]);
}

/** The current URL (path + query) of this page, to pass as ?back= so a page opened from here can link back to the
 * same view. */
export function currentUrl(): string {
  if (typeof window === "undefined") return "";
  return `${window.location.pathname}${window.location.search}`;
}

/** This page's URL with ?from_line=N, for a link to a document page whose "back" returns here at that row. */
export function backHere(line?: number): string {
  if (typeof window === "undefined") return "";
  const q = new URLSearchParams(window.location.search);
  if (line !== undefined) q.set("from_line", String(line));
  const s = q.toString();
  return `${window.location.pathname}${s ? `?${s}` : ""}`;
}

/** A ?back= value is used only when it is a page of this viewer (no other site). */
export function safeBack(v: string | null): string | null {
  return v && /^\/[a-z]/.test(v) && !v.startsWith("//") ? v : null;
}

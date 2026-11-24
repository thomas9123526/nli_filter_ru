"use client";
// The old flat URLs (/labelrun/, /dataset/, /corpus/, …) forward to their place under /label/… or /filter/….
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { api } from "@/lib/api";
import { Loading } from "./ui";

function query(): string {
  return typeof window === "undefined" ? "" : window.location.search + window.location.hash;
}

export function Forward({ to }: { to: string }) {
  const router = useRouter();
  useEffect(() => { router.replace(to + query()); }, [router, to]);
  return <Loading what={`Moved to ${to}`} />;
}

/** /corpus/?ds=… : a labelling dataset (its output is an nli_label run) goes to /label/corpus/, any other to /filter/corpus/. */
export function CorpusForward() {
  const router = useRouter();
  const sp = useSearchParams();
  const ds = sp.get("ds") || "";
  useEffect(() => {
    let off = false;
    const go = (area: "label" | "filter") => { if (!off) router.replace(`/${area}/corpus/` + query()); };
    if (!ds) { go("filter"); return; }
    api.datasets()
      .then((r) => go(r.datasets.some((d) => d.name === ds && d.label_run) ? "label" : "filter"))
      .catch(() => go("filter"));
    return () => { off = true; };
  }, [ds, router]);
  return <Loading what="Opening the corpus" />;
}

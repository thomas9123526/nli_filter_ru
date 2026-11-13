"use client";
// Small typed client for the nli_viewer backend + a data-loading hook.
import { useCallback, useEffect, useRef, useState } from "react";
import type {
  BatchResp, BrowseEntry, CorpusLines, DatasetInfo, DecisionsResp, EditEntry, EditResp, EditStatus, FileRow, FindMatch, Overview,
  RecordResp, SimResp,
} from "./types";

// Same origin by default (backend serves the UI, or `next dev` forwards /api). Override for a remote backend.
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE || "").replace(/\/$/, "");

export type Params = Record<string, string | number | boolean | null | undefined>;

export function query(params: Params = {}): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

export async function getJSON<T>(path: string, params?: Params, signal?: AbortSignal): Promise<T> {
  return request<T>(`${API_BASE}${path}${query(params)}`, { signal, headers: { Accept: "application/json" } });
}

/** POST for editing: JSON body + the X-Viewer-Edit header the backend requires for every change. */
export async function postJSON<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(`${API_BASE}${path}`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json", "X-Viewer-Edit": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

async function request<T>(url: string, init: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(`Cannot reach the viewer backend (${(e as Error).message}). Is it running?`, 0);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(detail || `HTTP ${res.status}`, res.status);
  }
  return res.json() as Promise<T>;
}

const enc = encodeURIComponent;

export const api = {
  datasets: (s?: AbortSignal) => getJSON<{ datasets: DatasetInfo[] }>("/api/datasets", undefined, s),
  overview: (ds: string, s?: AbortSignal) => getJSON<Overview>(`/api/datasets/${enc(ds)}`, undefined, s),
  files: (ds: string, p: Params, s?: AbortSignal) => getJSON<{ files: FileRow[] }>(`/api/datasets/${enc(ds)}/files`, p, s),
  decisions: (ds: string, p: Params, s?: AbortSignal) => getJSON<DecisionsResp>(`/api/datasets/${enc(ds)}/decisions`, p, s),
  record: (ds: string, p: Params, s?: AbortSignal) => getJSON<RecordResp>(`/api/datasets/${enc(ds)}/record`, p, s),
  find: (ds: string, id: string, s?: AbortSignal) =>
    getJSON<{ matches: FindMatch[] }>(`/api/datasets/${enc(ds)}/find`, { id }, s),
  simulate: (ds: string, p: Params, s?: AbortSignal) => getJSON<SimResp>(`/api/datasets/${enc(ds)}/simulate`, p, s),
  browse: (ds: string, path: string, s?: AbortSignal) =>
    getJSON<{ root: string; path: string; entries: BrowseEntry[] }>(`/api/datasets/${enc(ds)}/browse`, { root: "corpus", path }, s),
  corpusLines: (ds: string, p: Params, s?: AbortSignal) => getJSON<CorpusLines>(`/api/datasets/${enc(ds)}/corpus/lines`, p, s),
  editStatus: (ds: string, path: string, s?: AbortSignal) =>
    getJSON<EditStatus>(`/api/datasets/${enc(ds)}/corpus/edit-status`, { path }, s),
  edits: (ds: string, p: Params, s?: AbortSignal) => getJSON<{ edits: EditEntry[] }>(`/api/datasets/${enc(ds)}/corpus/edits`, p, s),
  editText: (ds: string, body: { path: string; line: number; text: string; sha1: string }) =>
    postJSON<EditResp>(`/api/datasets/${enc(ds)}/corpus/edit`, body),
  editBatch: (ds: string, body: { path: string; changes: { line: number; text: string; sha1: string }[] }) =>
    postJSON<BatchResp>(`/api/datasets/${enc(ds)}/corpus/edit-batch`, body),
  undoEdit: (ds: string, edit: string) => postJSON<EditResp>(`/api/datasets/${enc(ds)}/corpus/edits/${enc(edit)}/undo`),
};

export type Loaded<T> = { data: T | null; error: ApiError | null; loading: boolean; reload: () => void };

/** Load data whenever `key` changes; older requests are cancelled. `key` null = do nothing. */
export function useApi<T>(key: string | null, load: (signal: AbortSignal) => Promise<T>): Loaded<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);
  const loader = useRef(load);
  loader.current = load;
  useEffect(() => {
    if (key === null) return;
    const ctl = new AbortController();
    setLoading(true);
    setError(null);
    loader
      .current(ctl.signal)
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch((e: Error) => {
        if (e.name === "AbortError") return;
        setError(e instanceof ApiError ? e : new ApiError(e.message, 0));
        setLoading(false);
      });
    return () => ctl.abort();
  }, [key, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

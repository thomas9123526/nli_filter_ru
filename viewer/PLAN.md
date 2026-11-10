# NLI result viewer: plan and status

Goal: pick any decision in an `nli_filter.py` output folder and see it next to the original corpus line
(text with keyword hits, rule marks, check-1 / check-2 windows, hypotheses, scores, models), without
decompressing anything by hand. Corpus and output may be on local disk, FTP or S3/MinIO.

## Architecture

```
 Browser ──> Next.js frontend (static export, served by the backend or by `next dev`)
                  │  JSON over HTTP
                  ▼
 FastAPI backend  (python -m nli_viewer serve)
   api.py ─── results.py (Dataset: output folder <-> corpus folder) ── explain.py (highlights, verdict)
                  │                                    │
               lines.py (random access to lines of .jsonl/.gz/.zst/.zip, disk cache + SQLite index)
                  │
               storage.py (LocalStorage | FTPStorage | S3Storage, chosen by URI)
```

Each module is usable on its own (no web framework below `api.py`); a CLI (`python -m nli_viewer ...`)
gives the same answers in a terminal.

## Decisions

| Choice | Why |
|---|---|
| FastAPI instead of Django | No database or admin needed; small; automatic API docs at `/docs` |
| Next.js static export | One process in production (`nli_viewer serve` serves UI + API); `next dev` for UI work |
| Disk cache of decompressed files + offset index | `.zst`/`.gz` have no random access; decompress once, then jump to any line instantly |
| SQLite index per decisions file | filter / sort / paginate decisions (decision, reason, score, id) without rescanning |
| Storage by URI | `D:\data`, `file:///data`, `ftp://user:pass@host/path`, `s3://bucket/prefix?endpoint=http://minio:9000` |

## Steps

- [x] 1. Backend package skeleton, venv, requirements
- [x] 2. `storage.py`: Local, FTP, S3/MinIO + tests (pyftpdlib server, moto S3 server)
- [x] 3. `lines.py`: line reader with cache + offset index for plain/.gz/.zst/.zip + tests
- [x] 4. `results.py`: dataset model (runs, file list, decisions index, corpus mapping) + tests
- [x] 5. `explain.py`: highlight segments, hypothesis/score tables, verdict text + tests
- [x] 6. `config.py` + `api.py` (FastAPI) + `cli.py` + API tests
- [x] 7. Next.js frontend: datasets, dataset overview, file decisions table, record detail
- [x] 8. Static export served by the backend; one-command start scripts; README; cmds/viewer/viewer.md
- [x] 9. End-to-end on test_corpus / out_test_corpus over local disk, FTP and S3 (`verify`: 568/568
      consistent on each), browser screenshots (light, dark, narrow)
- [x] 10. Extras:
  - tests for nli_filter.py / nli_models.py (59, `tests/`), automated UI test in headless Chrome
  - threshold tuning page (`/tune`, `/api/.../simulate`): decisions recomputed from stored scores
  - `verify` command: every decision checked against its corpus line
  - scale test: 100,000-line file, see README "Cache"

## Fixed along the way

- nli_filter.py: a check-2 window cut out of a long sentence lost the sentence's last words (word-boundary
  snapping also moved an edge that already sat on the sentence end). Found by the new tests.
- Decision index build 7x faster (10.2 s -> 1.4 s per 100k decisions): no journal / fsync for the cache DB.
- Open line indexes and decision indexes are kept in LRU caches (128 / 64), so memory stays bounded.

- Record page: long texts now scroll to the deciding window / first hit on load; click a hit or score row to
  jump to it; text box sized so it fits on a 1080p screen.
- Decisions queries: one SQLite connection per thread (record lookups 100x faster: 35 s -> 0.3 s for 568).
- Rewritten output files (nli_filter.py --overwrite while the viewer runs) are re-indexed automatically.
- Datasets page probes every server in parallel (5 s limit) and shows why one is unavailable.
- Narrow screens: grid items no longer overflow.

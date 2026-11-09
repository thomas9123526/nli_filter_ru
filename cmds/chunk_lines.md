# `--chunk-lines`

The number of input lines read and processed together as one unit of work. It does **not** change any decision.

## What happens per chunk (e.g. `--chunk-lines 16`)

1. Read 16 lines.
2. Keyword search + rules on all 16.
3. Send the NLI pairs of all 16 lines to the model together (in batches of `--batch-size`).
4. Write the 16 decisions.
5. Next 16 lines.

## Small vs large

| | Small (e.g. 16) | Large (default 512) |
|---|---|---|
| Progress line | updates soon | only after 512 lines (minutes on CPU) |
| Model efficiency | batches often not full: slower on GPU | full batches: efficient |
| Memory | low | higher, still small |
| Decisions | same | same |

- The progress line updates only when a chunk is finished: with `--limit 60` and the default 512 nothing shows until the end.
- In `thread` / `process` mode several chunks run at once (`--inflight`, default 2 per worker); chunks that are too small leave workers waiting.

## Recommendation

| Run | Setting |
|---|---|
| Small tests on CPU | `--chunk-lines 16` |
| Big runs, GPU | default `512`, or higher, e.g. `--chunk-lines 2048` on the H200 |

```powershell
python .\nli_filter.py test_corpus --device cpu --judge-model none --limit 60 --chunk-lines 16 --output-dir out_test_corpus
```

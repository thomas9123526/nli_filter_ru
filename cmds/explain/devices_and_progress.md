# Devices, processes and progress of `nli_filter.py`

## Progress in the viewer (any way you start the run)

`nli_filter.py` rewrites `<output-dir>/progress/<run id>.json` every 60 s. The viewer reads that folder and
shows it under **Runs in progress**. It does not matter whether the run was started from a command prompt,
from the viewer or on another machine.

- `--output-dir` must be the `output` folder of a dataset in `viewer\viewer_config.json`.
- `--no-progress-file` turns it off.
- `--progress-every 10` updates faster (default 60 s).
- A running file not updated for max(120 s, 3 x `--progress-every`) is shown as stale (run killed, crashed,
  or its command prompt window closed).
- Finished runs stay listed for 24 h. Sharded copies (`--shard`) each write a file; the viewer adds them up.

## Device and process options

| Option | Values | Meaning |
|---|---|---|
| `--device` | `auto`, `cpu`, `cuda`, `cuda:0,cuda:1` or `0,1`, `cpu*4` | `auto` = every GPU, else CPU; `cpu*4` = 4 CPU workers |
| `--mode` | `auto`, `single`, `thread`, `process` | `process` = one child process per worker, own model copy. `auto` = `single` for one device, else `thread` (never `process`) |
| `--workers-per-device` | default 1 | workers on each device |
| `--cpu-threads` | number | torch threads per CPU worker |
| `--inflight` | default 2 x workers | chunks processed at once |
| `--chunk-lines` | default 512 | lines per chunk |
| `--shard K/N` | e.g. `0/4` | this copy takes every N-th file starting at K (other machines or other GPUs) |

Workers = devices x `--workers-per-device`. The fast model and the judge use the same settings, so every
worker loads both models.

```powershell
# 4 CPU processes, 4 torch threads each (keep processes x threads <= physical cores)
python nli_filter.py <input> --device cpu*4 --mode process --cpu-threads 4 --output-dir out

# one process per GPU
python nli_filter.py <input> --device cuda:0,cuda:1 --mode process --output-dir out

# 2 processes on one GPU
python nli_filter.py <input> --device cuda:0 --workers-per-device 2 --mode process --output-dir out
```

## How well it scales

Good:
- All workers take batches from one shared queue (length-sorted batches), so fast devices simply do more.
- Several chunks are in flight, so GPUs are kept busy while other chunks wait for the judge.
- `process` mode uses `spawn` (needed for CUDA) and limits each GPU worker to 4 CPU threads.
  Tokenizing happens in the workers.
- Many machines: `--shard`, remote files are downloaded ahead, finished files are skipped on a rerun.

Limits:
1. **One main process** reads, decompresses, parses JSON, matches keywords, builds pairs and writes output
   (Python threads, GIL). With 8 fast GPUs it can become the bottleneck. Sign: GPUs well under full use and
   the main process at about one core. Fix: several shards on one machine, each with its own GPUs.
2. **Files one at a time.** At the end of each file the workers wait briefly. Costs time with thousands of
   small files; shards help.
3. **Batches are sorted only inside a chunk**, so judge batches can be small. A bigger `--chunk-lines`
   (e.g. 2048) gives fuller batches.
4. **Both models in every worker.** With `cpu*N --mode process`: N copies of each model in RAM.
5. **A dead worker** (e.g. out of memory) stops the run. A rerun continues from the last finished file.

## Suggested settings

| Machine | Settings |
|---|---|
| Up to about 4 GPUs | default (`thread` mode) |
| 8 GPUs | `--mode process`, or better 2-4 shards with 2-4 GPUs each |
| Many CPU cores | `--device cpu*N --mode process --cpu-threads T`, N x T <= physical cores |
| Several machines | `--shard K/N` |

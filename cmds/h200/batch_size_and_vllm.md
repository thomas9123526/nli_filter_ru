# 8 x H200 and RTX 5090: batch size, and why not vLLM

## Batch size

A "pair" = one text window + one hypothesis, up to 512 tokens (`--max-length`). The batch size = pairs one GPU
scores in one step.

| Option | Default | Model |
|---|---|---|
| `--batch-size` | 32 | fast model (ModernBERT): scores every pair |
| `--judge-batch-size` | = `--batch-size` | judge (DeBERTa): only the uncertain pairs |
| `--max-batch-tokens` | off | also caps a batch by its total tokens |

Pairs are sorted by length before batching. A batch that runs out of GPU memory is halved and retried, so a value
that is too big only costs a little time.

### Start with

```bash
./run_shards.sh "/data/corpus/**/*.zst" /data/nli_out 2 \
    --batch-size 256 --judge-batch-size 128 --max-batch-tokens 65536 --write-split
```

- `2` = 2 copies per GPU = 16 copies. More important than the batch size: one run's main process does the reading
  and keyword matching on one CPU core and cannot keep 8 H200s busy; 16 copies split that work.
- DeBERTa is slower (no fast attention): smaller batch.
- `--max-batch-tokens 65536` = 256 pairs x 256 tokens on average; keeps batches of long pairs from growing too big.
- bfloat16 is used automatically on GPU.

### Tune

1. Run on a sample (`--limit 200000`, a test output folder); note lines/s (viewer "Runs in progress", or the log).
2. Watch `nvidia-smi -l 2`:
   - GPU use low, memory free: the CPU side is the limit. Add copies (3 per GPU), not batch size.
   - GPU use high, lots of free memory: try `--batch-size 512 --judge-batch-size 256`, compare lines/s.
3. Stop when lines/s no longer improves; bigger batches then only use more memory.

## vLLM for the three models

| Model | Architecture | vLLM (check its supported-models list for your version) |
|---|---|---|
| `modernbert` (ModernBERT-large-zeroshot-v2.0) | ModernBERT classifier | supported in recent versions |
| `bge-m3` (bge-m3-zeroshot-v2.0) | XLM-RoBERTa classifier | supported |
| `deberta` (deberta-v3-large-zeroshot-v2.0) | DeBERTa-v2 classifier | **not supported** |

Not recommended here:

- The default judge (DeBERTa) cannot run on it: changing the judge changes accuracy.
- Little to gain: vLLM's big win is text generation; these models read a pair and give one score. Its packing of
  variable-length inputs is about what the length-sorted batches already do.
- It does not fix the real limit (the CPU side: reading, decompressing, keyword matching); sharding does.
- The H200 machine is offline; vLLM brings its own torch and many packages (separate environment, new wheels).
- Scores can shift slightly: thresholds (0.8, band 0.6-0.95) would need checking again.
- `nli_models.py` would need a second scoring backend (new code).

## More speed instead

1. Sharding (above), 2-3 copies per GPU.
2. Tuned batch sizes.
3. A trial with `--judge-model none` to see what DeBERTa costs on your data.
4. Still low GPU use: change the code to keep the GPUs busy across file boundaries
   (`cmds/explain/devices_and_progress.md`, limits 1 and 2).

## RTX 5090 (one GPU, 32 GB)

| | 8 x H200 | RTX 5090 |
|---|---|---|
| GPUs | 8 | 1 |
| Memory per GPU | 141 GB | 32 GB |
| torch | CUDA build | **cu128 or newer** (Blackwell: older builds do not support the card) |
| Precision | bfloat16 | bfloat16 (automatic) |

Check torch: `python -c "import torch; print(torch.__version__, torch.cuda.get_device_name(0))"`
(`torch 2.11.0+cu128` as in `../setup/offline_wheels.md`).

### Batch size

Each model in bfloat16 needs under 1 GB; most memory goes to the pairs being scored.

Start with `--batch-size 128 --judge-batch-size 64 --max-batch-tokens 32768`, then tune as above:
sample run (`--limit 50000`), `nvidia-smi -l 2`; GPU use high and memory under ~70%: try 256 / 128; keep it only
if lines/s improves.

### 2 copies on the one GPU

Same CPU limit as on the H200: two copies share the GPU, each takes half of the files (same `--output-dir`).

Windows, two command prompts:

```powershell
python nli_filter.py <corpus> --device cuda:0 --shard 0/2 --batch-size 128 --judge-batch-size 64 --max-batch-tokens 32768 --output-dir <out>
python nli_filter.py <corpus> --device cuda:0 --shard 1/2 --batch-size 128 --judge-batch-size 64 --max-batch-tokens 32768 --output-dir <out>
```

Ubuntu:

```bash
NLI_DEVICES="0" ./run_shards.sh "<corpus>/**/*.zst" <out> 2 --batch-size 128 --judge-batch-size 64 --max-batch-tokens 32768
```

Each copy loads both models (~2 GB). The viewer adds up the copies' progress. GPU use still well below full: try 3.

### vLLM

Same reasons as above, and vLLM runs only on Linux: on the Windows 5090 machine it would need WSL. Not worth it.

## The options used above

### `--limit N`: stop after N lines

- Counts lines across all files together; `--limit 50000` stops after the first 50,000 lines, even inside a file.
- For test runs: the speed (lines/s) in minutes instead of the whole corpus.
- A file cut short is marked "partial"; a later run without `--limit` redoes it.
- Give each test its own output folder (`--output-dir out_test1`): results do not mix, each try starts fresh.

### `--write-split`: also write the cleaned corpus

- Without it: only the decisions (`*.decisions.jsonl`): filter or keep for each line, and why.
- With it: also `*.kept.jsonl.zst` (lines to keep) and `*.filtered.jsonl.zst` (removed lines), the original lines.
- Disk: kept + filtered are about **as big as the corpus** (6 TB corpus: about 6 TB more). Off for test runs.

### `--max-batch-tokens N`: limit a batch by its size

Memory depends on the **longest pair in the batch x number of pairs** (shorter pairs are padded to the longest).
Tokens are estimated as characters / 4 (at most 512 per pair); a batch closes when longest x count would pass the
cap. With `--batch-size 128 --max-batch-tokens 32768`:

| Pairs in the batch | Size | Pairs per batch |
|---|---|---|
| short, ~100 tokens | 128 x 100 = 12,800 | **128** (batch size limits) |
| long, 512 tokens | 128 x 512 = 65,536: too big | **64** (token cap limits: 64 x 512 = 32,768) |

So a big batch size works for the many short pairs, and long pairs do not run out of memory.

## Reading nvidia-smi

In a second window while the test run goes (Windows and Ubuntu):

```
nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv -l 2
```

```
utilization.gpu [%], memory.used [MiB], memory.total [MiB]
96 %, 14210 MiB, 32607 MiB
94 %, 15022 MiB, 32607 MiB
```

- **utilization.gpu** ("GPU use"): how much of the time the GPU computes. 90-100% = always working; 30% = waiting
  most of the time.
- **memory.used / memory.total**: how full the GPU memory is (15,022 / 32,607 = about 46%).

"GPU use high and memory under 70%" = the GPU is busy and has memory left: bigger batches may give it a little more
work per step. Under 70% leaves room for batches of long pairs, which use more than average.

| What you see | Meaning | Do |
|---|---|---|
| use 90-100%, memory < 70% | busy, memory to spare | try a bigger batch, compare lines/s |
| use 90-100%, memory > 85% | busy and nearly full | keep the batch size |
| use < 60% | **GPU waits for the CPU** (reading, keyword matching) | add a copy (`--shard`), not batch size |
| use jumps 0% <-> 100% | CPU feeds work in bursts | add a copy |

## Worked example (RTX 5090; made-up numbers)

Each try: fresh test output folder, `--limit 50000`.

| Try | Settings | GPU use | Memory | lines/s | Next |
|---|---|---|---|---|---|
| 1 | 1 copy, batch 128 / judge 64 | 45% | 30% | 900 | low use: GPU waits for CPU, add a copy |
| 2 | 2 copies (`--shard 0/2`, `1/2`) | 92% | 45% | 1,700 | busy, memory free: bigger batches |
| 3 | 2 copies, batch 256 / judge 128 | 95% | 62% | 1,780 | +5%: keep |
| 4 | 2 copies, batch 512 / judge 256 | 96% | 84% | 1,790 | no gain, more memory: **back to try 3** |

Use try 3 for the real run. lines/s: viewer "Runs in progress" (add up the copies) or the log's progress lines.
A try that crashes or gets very slow at a bigger batch: memory was too full, go back one step.

See also `linux_h200.md`, `h200_readiness.md`.

#!/usr/bin/env bash
# run_label_shards.sh - run nli_label.py as several copies side by side, one GPU each, then print one report.
#
# Like run_shards.sh (which runs nli_filter.py): one process reads, decompresses, keyword-scans and splits paragraphs
# at roughly 40 MB/s on one CPU core, which cannot keep 8 H200 GPUs busy. This script starts
# COPIES_PER_GPU x (number of GPUs) copies of `nli_label.py run`, each with its own --shard K/N (a disjoint subset of
# the files) and its own GPU, all into the same output folder, and finally prints `nli_label.py report`.
#
# Usage:
#   ./run_label_shards.sh INPUT OUTPUT_DIR [COPIES_PER_GPU] [extra nli_label.py run options ...]
#
# Examples:
#   ./run_label_shards.sh /data/corpus /data/label_out 2 --policy policy/russia_llm_policy_v2.json --write-clean
#   ./run_label_shards.sh /data/corpus /data/label_out 2 --policy policy/russia_policy_v5.json --batch-size 256
#   ./run_label_shards.sh /data/corpus /data/label_try 2 --policy policy/russia_llm_policy_v2.json --limit 20000
#   NLI_DEVICES="cpu cpu" ./run_label_shards.sh dataset/test_corpus_cases_ru /tmp/lab 1 --judge-model none
#
# Environment:
#   PYTHON=python3            interpreter (default: python)
#   NLI_DEVICES="0 1 2 3"     GPUs to use (default: all that torch sees); "cpu cpu" works for a CPU test
#
# Re-running the same command skips finished files (resume). Logs: OUTPUT_DIR/logs/shard-K.log
# Guide: cmds/h200/nli_label_h200.md
set -uo pipefail

if [ $# -lt 2 ]; then
    sed -n '2,24p' "$0"
    exit 2
fi
INPUT=$1
OUT=$2
PER_GPU=${3:-2}
if [ $# -ge 3 ]; then shift 3; else shift $#; fi
PYTHON=${PYTHON:-python}
HERE=$(cd "$(dirname "$0")" && pwd)

if [ -n "${NLI_DEVICES:-}" ]; then
    read -r -a DEVICES <<< "$NLI_DEVICES"
else
    NGPU=$("$PYTHON" -c "import torch; print(torch.cuda.device_count() if torch.cuda.is_available() else 0)") || exit 1
    if [ "$NGPU" -eq 0 ]; then
        echo "error: torch sees no CUDA GPU (driver 570+ and a +cu128 torch build needed); set NLI_DEVICES to override" >&2
        exit 1
    fi
    DEVICES=()
    for ((g = 0; g < NGPU; g++)); do DEVICES+=("$g"); done
fi

N=$(( ${#DEVICES[@]} * PER_GPU ))
mkdir -p "$OUT/logs"
echo "$(date '+%F %T') starting $N copies of nli_label.py (${PER_GPU} per device on: ${DEVICES[*]}) -> $OUT"

PIDS=()
for ((k = 0; k < N; k++)); do
    dev=${DEVICES[$((k % ${#DEVICES[@]}))]}
    [[ "$dev" =~ ^[0-9]+$ ]] && dev="cuda:$dev"
    "$PYTHON" "$HERE/nli_label.py" run "$INPUT" --device "$dev" --shard "$k/$N" --output-dir "$OUT" "$@" \
        > "$OUT/logs/shard-$k.log" 2>&1 &
    PIDS+=($!)
done

trap 'echo "stopping..."; kill "${PIDS[@]}" 2>/dev/null; exit 130' INT TERM

FAILED=0
for ((k = 0; k < N; k++)); do
    if wait "${PIDS[$k]}"; then
        echo "$(date '+%F %T') shard $k/$N finished"
    else
        echo "$(date '+%F %T') shard $k/$N FAILED (see $OUT/logs/shard-$k.log)" >&2
        FAILED=$((FAILED + 1))
    fi
done

# every shard writes summary.json from all files finished so far: the last one to end wrote the complete one
"$PYTHON" "$HERE/nli_label.py" report "$OUT"
if [ "$FAILED" -gt 0 ]; then
    echo "$FAILED of $N copies failed; fix the cause and run the same command again (finished files are skipped)" >&2
    exit 1
fi

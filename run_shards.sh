#!/usr/bin/env bash
# run_shards.sh - run nli_filter.py as several copies side by side, one GPU each, then print one report.
#
# One nli_filter.py process reads/parses/keyword-scans at roughly 40 MB/s, which cannot keep 8 H200 GPUs busy.
# This script starts COPIES_PER_GPU x (number of GPUs) copies, each with its own --shard K/N (a disjoint
# subset of the files) and its own GPU, and finally runs `nli_filter.py --report`.
#
# Usage:
#   ./run_shards.sh INPUT OUTPUT_DIR [COPIES_PER_GPU] [extra nli_filter.py options ...]
#
# Examples:
#   ./run_shards.sh "/data/corpus/**/*.zst" /data/nli_out
#   ./run_shards.sh /data/corpus /data/nli_out 2 --write-split --batch-size 256 --judge-batch-size 128
#   ./run_shards.sh dataset/test_corpus dataset/out_test_corpus 1 --judge-model none
#
# Environment:
#   PYTHON=python3            interpreter (default: python)
#   NLI_DEVICES="0 1 2 3"     GPUs to use (default: all that torch sees); "cpu cpu" works for a CPU test
#
# Re-running the same command skips finished files (resume). Logs: OUTPUT_DIR/logs/shard-K.log
set -uo pipefail

if [ $# -lt 2 ]; then
    sed -n '2,22p' "$0"
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
echo "$(date '+%F %T') starting $N copies (${PER_GPU} per device on: ${DEVICES[*]}) -> $OUT"

PIDS=()
for ((k = 0; k < N; k++)); do
    dev=${DEVICES[$((k % ${#DEVICES[@]}))]}
    [[ "$dev" =~ ^[0-9]+$ ]] && dev="cuda:$dev"
    "$PYTHON" "$HERE/nli_filter.py" "$INPUT" --device "$dev" --shard "$k/$N" --output-dir "$OUT" "$@" \
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

"$PYTHON" "$HERE/nli_filter.py" --report --output-dir "$OUT"
if [ "$FAILED" -gt 0 ]; then
    echo "$FAILED of $N copies failed; fix the cause and run the same command again (finished files are skipped)" >&2
    exit 1
fi

# nli_filter.py: filter JSONL lines that are about the country; writes decisions + summary.
# Run from D:\hkc\nli_filter2 with the venv active (see 00_setup.ps1).
# Default input: test_russia.jsonl. Default output folder: .\nli_filter_out
# Reference file: copy the command you need. The `return` below stops the file if it is run as a whole.
return

# ---- test_russia.jsonl ---------------------------------------------------------------------------

# Default: ModernBERT for all scores + DeBERTa judge for scores between 0.6 and 0.95 (~2 min on CPU)
python .\nli_filter.py --device cpu --chunk-lines 16

# ModernBERT only (no judge)
python .\nli_filter.py --judge-model none --device cpu --chunk-lines 16

# Same, with every option written out
python .\nli_filter.py D:\hkc\nli_filter2\test_russia.jsonl --fast-model modernbert --judge-model none --device cpu --output-dir out_modernbert --chunk-lines 16

# DeBERTa only (slower)
python .\nli_filter.py --fast-model deberta --judge-model none --device cpu --chunk-lines 16

# bge-m3 only (multilingual)
python .\nli_filter.py --fast-model bge-m3 --judge-model none --device cpu --chunk-lines 16

# Own output folder, print up to 30 mistakes
python .\nli_filter.py D:\hkc\nli_filter2\test_russia.jsonl --device cpu --output-dir out_test --chunk-lines 16 --show 30

# ---- nested test corpus of .zst files (make_test_corpus.py) -------------------------------------

# Build dataset\test_corpus\ : 5 folders x 3 sub folders x 1-2 .zst files, 20-40 lines each, from test_russia.jsonl
python .\make_test_corpus.py
# Rebuild it (replace the old one), other sizes, other seed
python .\make_test_corpus.py --force --folders 5 --subfolders 3 --files 1-2 --lines 20-40 --seed 7
# Filter it (all .zst files under the folder are found automatically)
python .\nli_filter.py dataset/test_corpus --device cpu --judge-model none --output-dir dataset/out_test_corpus
# Quick trial: first 60 lines only
python .\nli_filter.py dataset/test_corpus --device cpu --judge-model none --limit 60 --output-dir dataset/out_test_corpus

# ---- other files (replace the example paths) ---------------------------------------------------

# One file
python .\nli_filter.py D:\data\some.jsonl --device cpu --output-dir out_test

# All .zst files under a folder, also write the kept / filtered lines
python .\nli_filter.py "D:\data\corpus\**\*.zst" --device cpu --write-split --output-dir out_corpus

# A folder (searched recursively for .jsonl .json .gz .zst .zip), first 250 lines only
python .\nli_filter.py D:\data\corpus --device cpu --judge-model none --limit 250 --write-split --output-dir out_corpus

# Parallel modes on CPU (for testing): worker threads / worker processes
python .\nli_filter.py D:\data\corpus --mode thread --device "cpu*2" --judge-model none --limit 250 --cpu-threads 3 --output-dir out_thread
python .\nli_filter.py D:\data\corpus --mode process --device "cpu*2" --judge-model none --limit 250 --cpu-threads 3 --output-dir out_process

# Split the files over several runs/machines: run 0/2 and 1/2
python .\nli_filter.py D:\data\corpus --shard 0/2 --device cpu --output-dir out_corpus
python .\nli_filter.py D:\data\corpus --shard 1/2 --device cpu --output-dir out_corpus

# Running the same command again skips finished files (they have a .summary.json); redo them with --overwrite
python .\nli_filter.py D:\data\corpus --device cpu --output-dir out_corpus --overwrite

# Another country: China has a built-in keyword list
python .\nli_filter.py "shards\**\*.zst" --country China --device cpu
# Any other country needs the adjective and keywords
python .\nli_filter.py D:\data\corpus --country Japan --country-adj Japanese --keywords-file keywords\japan.txt --device cpu

# ---- GPU machines ------------------------------------------------------------------------------

# H200: all GPUs, one process per GPU and model
python .\nli_filter.py "D:\data\corpus\**\*.zst" --device cuda --mode process --write-split --output-dir out_corpus

# RTX 5090: one GPU
python .\nli_filter.py "D:\data\corpus\**\*.zst" --device cuda:0 --write-split --output-dir out_corpus

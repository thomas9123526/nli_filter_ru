# nli_models.py: load the models and score texts against hypotheses (no keywords, rules or filter decision).
# Run from D:\hkc\nli_filter2 with the venv active (see 00_setup.ps1).
# Reference file: copy the command you need. The `return` below stops the file if it is run as a whole.
return

# Show the three models and whether they are found in .\models
python .\nli_models.py --list-models

# Load each model on CPU and score three sample pairs (~30 s)
python .\nli_models.py --check all --device cpu

# Score two texts directly
python .\nli_models.py --model modernbert --device cpu --text "The Kremlin announced new sanctions." --text "Set display language to Russian." --labels "Russia,a language setting" --template "This text is about {}."

# Score every line of test_russia.jsonl with ModernBERT
python .\nli_models.py --model modernbert --input test_russia.jsonl --hypothesis "This text is about Russia." --device cpu --out out_modernbert\scores.jsonl

# Several labels with DeBERTa over a folder (.jsonl/.gz/.zst/.zip), compressed output
python .\nli_models.py --model deberta --input corpus\ --labels "film,song,history" --template "This text is about a Russian {}." --device cpu --out scores.jsonl.zst

# Threshold: also list the hypotheses scoring >= 0.8; two CPU worker threads; first 12 lines only
python .\nli_models.py --model deberta --device "cpu*2" --mode thread --input corpus\web --limit 12 --hypothesis "This text is about Russia." --threshold 0.8 --out scores.jsonl.zst

# GPU machine (H200 / RTX 5090): all GPUs, one process per GPU
python .\nli_models.py --model modernbert --input "shards\*.zst" --hypothesis "This text is about Russia." --device cuda --mode process --batch-size 64 --out scores.jsonl.zst

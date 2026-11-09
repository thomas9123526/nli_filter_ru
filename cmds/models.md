# Model choice in `nli_filter.py`

## How the models are picked

| Option | Default | Role |
|---|---|---|
| `--fast-model` | `modernbert` | Scores **every** pair (text window × hypothesis) |
| `--judge-model` | `deberta` | Re-scores **only** pairs whose fast score is inside `--uncertain-band` (default 0.6–0.95); its score replaces the fast one. `none` = off |

```
final = judge(pair) if judge is on and 0.6 <= fast(pair) <= 0.95 else fast(pair)
decision uses final >= threshold (0.8)
```

## Why two models

- ModernBERT: fast, slightly less accurate. DeBERTa: most accurate, slow.
- Most scores are clear (near 0 or 1); only scores near the threshold need a second opinion.
- Result: close to DeBERTa's accuracy at a fraction of its cost. Test run: 210 fast pairs, 14 (6.7 %) went to the judge.

| Setup | Speed | Use |
|---|---|---|
| `--judge-model none` | fastest | quick trials |
| default (ModernBERT + DeBERTa judge) | ~1.5× ModernBERT alone (estimate) | recommended for full runs |
| `--fast-model deberta --judge-model none` | slowest (~2.5×, estimate) | reference / comparison |

## The three models

| Name | Strength | Note |
|---|---|---|
| `modernbert` | speed, English | default fast model |
| `deberta` | accuracy, English, max 512 tokens | default judge |
| `bge-m3` | 100+ languages | fallback; weaker on English, missed the hard company-name check pair |

## Commands (venv active, from `D:\hkc\nli_filter2`)

```powershell
# ModernBERT only
python .\nli_filter.py --judge-model none --device cpu --chunk-lines 16 --output-dir out_modernbert
# Default cascade
python .\nli_filter.py --device cpu --chunk-lines 16 --output-dir out_cascade
# DeBERTa only
python .\nli_filter.py --fast-model deberta --judge-model none --device cpu --chunk-lines 16 --output-dir out_deberta

# bge-m3 only
python .\nli_filter.py --fast-model bge-m3 --judge-model none --device cpu --chunk-lines 16 --output-dir out_bge
# ModernBERT + bge-m3 judge
python .\nli_filter.py --judge-model bge-m3 --device cpu --chunk-lines 16 --output-dir out_modernbert_bge
# bge-m3 + DeBERTa judge
python .\nli_filter.py --fast-model bge-m3 --judge-model deberta --device cpu --chunk-lines 16 --output-dir out_bge_deberta
# bge-m3 scores only (no filter logic)
python .\nli_models.py --model bge-m3 --input test_russia.jsonl --hypothesis "This text is about Russia." --device cpu --out out_bge\scores.jsonl
# bge-m3 on test_corpus, first 60 lines
python .\nli_filter.py test_corpus --fast-model bge-m3 --judge-model none --device cpu --limit 60 --chunk-lines 16 --output-dir out_tc_bge
```

## Tips

- Use a separate `--output-dir` per setup (finished files are skipped otherwise), then compare accuracy / precision / recall in the summaries.
- Try `bge-m3` mainly if the CJK test lines (`cjk_about`, `cjk_incidental`) do badly with the English models.
- The band is tunable: `--uncertain-band 0.5 0.97` sends more pairs to the judge (slower, possibly more accurate).

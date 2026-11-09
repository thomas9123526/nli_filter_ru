# How long texts are handled

The models never get the whole text; `nli_filter.py` sends small windows around the keyword hits.

## What each stage sees

| Stage | Part of the text |
|---|---|
| Keyword search | **whole** text (CPU, fast) |
| Cheap rules (language menu, locale code, …) | **whole** text, around each hit |
| Check 1 (about the country?) | up to **2 windows** (`--max-windows`) of **~1000 characters** (`--check1-chars`, ~250 tokens), around the first hits not resolved by the rules |
| Check 2 (only incidental?) | per remaining hit: the **sentence** holding it, max **300 characters** (`--check2-chars`) |
| Model limit | window + hypothesis cut to **512 tokens** (`--max-length`) |

- Text ≤ 1000 characters: the whole text is one check-1 window.
- Longer text (5 KB or 1 MB): same model cost, at most 2 check-1 windows + one short window per remaining hit. Only keyword search and rules grow with text size.
- `nli_models.py` is different: it scores the whole `text` field, cut at 512 tokens (≈ the first 2000 characters).

## Limitation

Only the first 2 windows are checked. A 1 MB page with passing mentions near the top and a real paragraph about the country further down can be **kept by mistake**, if both windows land on the passing mentions.

## Wider check (more model time, only for long texts with many hits)

```powershell
python .\nli_filter.py --max-windows 5 --check1-chars 1500 --device cpu
```

## Possible code improvements

- Spread the windows over the whole text instead of taking the first hits.
- Check windows one after another and stop at the first one that is about the country.

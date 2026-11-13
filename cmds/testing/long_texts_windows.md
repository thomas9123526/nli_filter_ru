# Long texts with many keywords: test file and the window options

## The problem in one picture

Check 1 does not read a long text whole. It reads **windows** of about 1,000 characters around the keywords,
**at most 2 per text** (`--max-windows 2`, the default). A text of 13,000 characters with "Russia" at 2000,
4000, 6000, 8000, 10000 and 12000:

```
text:     |----R----R----R----R----R----R-|      R = keyword
check 1:      [==] [==]                          only the first two are read
```

If the two windows are not about Russia (e.g. "Russian roulette", "White Russian") and the real Russia
passage is at 10000, the text is **kept by mistake**. (Keywords the cheap rules settle, e.g. "Russian" in a
language menu, get no window, so they do not use up the two.)

## The four options, simply

| | Option | Like ... | Effect |
|---|---|---|---|
| 1 | **More windows** (`--max-windows 6`, works now) | reading every marked spot instead of the first two | no Russia passage is missed; costs one more model call per extra window, only for long texts with many keywords |
| 2 | **Spread the windows** (code change) | still reading only two spots, but the first and the last instead of the first two | same cost as now; a passage at the end is caught, one in the middle can still be missed |
| 3 | **Stop at the first "yes"** (code change) | reading the marked spots one after another and stopping as soon as one is clearly about Russia | with option 1: texts about Russia usually stop after the first window, so the extra cost falls mostly on texts that are not about Russia |
| 4 | **Nearby keywords share a window** (already done) | one look covers several marks that are close together | keywords within ~1,000 characters cost one window, not several |

Recommended: **1 + 3**. Option 1 can be tested right now with the file below.

## The test file: test_russia_long.jsonl

16 texts of 12,600-12,950 characters, 8 test cases x 2 (different wording and filler), with `expect` labels:

| Category | Expect | Russia content | Default (2 windows) reaches the Russia passage? |
|---|---|---|---|
| `long_about_first` | filter | about passage at the start | yes |
| `long_about_last` | filter | 2 incidental mentions (~1500, ~3500), about passage near the end (~11500) | **no** |
| `long_about_middle` | filter | 2 incidental mentions (~2000, ~4000), about passage at ~8000 | **no** |
| `long_incidental_only` | keep | 6 incidental mentions (~2000 ... ~12000), nothing about Russia | - (more windows must not make it "filter") |
| `long_menu_then_about` | filter | language menus (rules settle them), about passage near the end | yes |
| `long_no_keyword` | keep | no keyword | - (no model call) |
| `long_about_everywhere` | filter | about passages at ~2000 ... ~12000 | yes |
| `long_about_then_incidental` | filter | about passage at ~2000, incidental mentions later | yes (check 2 must not rescue it) |

"Incidental mentions" = Russian roulette, White Russian, Russian blue (cat), Russian River Brewing Company,
Russian twists, Russian dolls. Which keyword sits where was checked with the real keyword search and window
code (no model).

## Commands: default against option 1

```powershell
cd D:\hkc\nli_filter2
python .\nli_filter.py test_russia_long.jsonl --judge-model none --device cpu --output-dir out_long_w2
python .\nli_filter.py test_russia_long.jsonl --judge-model none --device cpu --max-windows 6 --output-dir out_long_w6
```

(Russia is the default country. CPU, ModernBERT only: a few minutes each.)

What to compare in the two summaries:

- the evaluation table by category: `long_about_last` and `long_about_middle` are expected to be missed
  (FN) with 2 windows and caught with 6;
- `long_incidental_only` must stay correct (TN) with 6 windows;
- "NLI pairs fast": the extra model work of 6 windows.

The same without any model, to see the window counts first:

```powershell
python .\nli_filter.py test_russia_long.jsonl --keywords-report --output-dir out_long_kw2
python .\nli_filter.py test_russia_long.jsonl --keywords-report --max-windows 6 --output-dir out_long_kw6
```

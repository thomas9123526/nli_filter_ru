# Check a keyword list before the GPU run: --keywords-report

Runs only the keyword search and the cheap rules (language menus, labels) over the input. **No model is
loaded**, so it runs on any PC and reads tens of MB per second. Use it to clean a big keyword list (e.g. 10,000
words) and to estimate the model work of the real run.

```powershell
python .\nli_filter.py D:\corpus --country Germany --country-adj German --keywords-report --output-dir out_kw_de
python .\nli_filter.py D:\corpus --country Germany --country-adj German --keywords-report --limit 200000 --output-dir out_kw_de   # a sample
python .\nli_filter.py 'sftp://download:${SFTP_PASSWORD}@192.168.170.200/<corpus>' --country Germany --country-adj German --keywords-report --limit 200000 --output-dir out_kw_de
```

Same input forms as a normal run (folder, files, patterns, server URLs) and the same keyword options
(`--keywords-file`, `--keyword`, `--exclude-pattern`, `--company-names-file`). `--show N` sets how many keywords
are printed (default 20).

## What it shows (example: test_germany.jsonl)

```
 lines                         99
 with a keyword                74   74.7%
   kept by the rules           10   10.1%   (language menus / labels, no model)
   go to the models            64   64.6%
 estimated model work: check 1 65 pairs (65 windows x 1 hypotheses), check 2 at most 224 pairs

   keyword                      lines  to models  only this  rule hits
   German                          38         31         18          8
      e.g. The [German] chancellor met business leaders in Frankfurt to d...
   Germany                         17         17          5          0
 ...
 keywords without any hit: 11 (Bundesrat, Bundesrepublik Deutschland, deutsche, ...)
```

| Column | Meaning |
|---|---|
| lines | lines that contain the keyword |
| to models | of those, lines the rules do not settle: they go to the models |
| only this | lines that go to the models **only** because of this keyword: removing the keyword saves exactly these |
| rule hits | hits the cheap rules explained (e.g. "German" in a language menu) |

## Files in --output-dir

| File | Content |
|---|---|
| `keywords_report.tsv` | one row per keyword (all of them, also unused), sorted by "to models", with one example; opens in Excel |
| `keywords_report.json` | totals, the estimate, every keyword with up to 3 examples (file, line, text around the hit in `[...]`), the unused keywords |

## Cleaning a big list

1. Run the report on a sample (`--limit 200000` lines or one sub folder).
2. Open `keywords_report.tsv`, sort by `only_this_keyword`. Look at the examples of the top rows: a word with an
   everyday meaning (Bad, Mark, Gift, Hamburger ...) shows it at once.
3. Remove it from the keyword file, or keep it and add an `--exclude-pattern` for the wrong meaning.
4. Run the report again: "go to the models" and the estimate drop.

The numbers equal what a real run sends to the models (checked by the tests). The check-2 estimate is an upper
bound: check 2 only runs for lines that pass check 1.

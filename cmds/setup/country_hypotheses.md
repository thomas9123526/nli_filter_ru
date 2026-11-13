# Changing the country, keywords, hypotheses and labels

> Since 2026-11-13 hypotheses can also live in a file: `hypotheses\<name>.json`, used with
> `--hypotheses-file`, or automatically as `hypotheses\<country>.json`. Try and save them on the viewer's
> Corpus page ("Try settings"): see `cmdsiewer	ry_settings.md`.

There are two ways to change these: with command-line options for one run, or by editing the defaults at
the top of `nli_filter.py` to make the change permanent.

## 1. Country

**A built-in country** (`russia`, `china`) only needs its name:

```powershell
python .\nli_filter.py test_corpus --country China
```

**Any other country** needs the adjective and the keywords:

```powershell
python .\nli_filter.py test_corpus --country Japan --country-adj Japanese `
  --keyword Japan --keyword Japanese --keyword Tokyo --keyword 日本 --keyword ニッポン
```

**Keywords from a file:** create `keywords\japan.txt` with one keyword per line (lines starting with `#`
are ignored). The script picks it up automatically for `--country Japan`, or you can point to any file with
`--keywords-file`:

```
# keywords\japan.txt
Japan
Japanese
Tokyo
日本
Япония
```

- A keyword file **replaces** the built-in list. `--keyword X` **adds** to it, so you can add Moscow
  suburbs for Russia this way without touching the code.
- `--exclude-pattern "regex"` ignores hits inside a match. For example, China excludes `中国地方`, which
  is a region of Japan.

**To make a country permanent**, add it to `COUNTRIES` in `nli_filter.py`:

```python
"japan": {"name": "Japan", "adj": "Japanese", "exclude": [],
          "keywords": ["Japan", "Japanese", "Tokyo", "日本", "Япония"]},
```

## 2. Hypotheses (topics)

The filter makes two checks, and each one has its own hypotheses. `{country}` and `{country_adj}` are
replaced with the country name and adjective, for example "Russia" and "Russian".

| Check | Question | Default hypotheses |
|---|---|---|
| Check 1 | Is the text **about** the country? Score ≥ 0.8 means filter | `topic`: "This text is about {country}, a {country_adj} person, a {country_adj} film, a {country_adj} song, the lyrics of a {country_adj} song, or the history of {country}." |
| Check 2 | Is a hit only an **incidental mention**? Score ≥ 0.8 means the line is kept | `company_name`, `language_setting` |

**Replace or extend them with `--check1-hyp` / `--check2-hyp KEY=TEXT`**, which you can repeat:

```powershell
python .\nli_filter.py test_corpus `
  --check1-hyp "topic=This text is about {country} or {country_adj} people." `
  --check1-hyp "politics=This text is about the politics or government of {country}." `
  --check1-hyp "food=This text is about {country_adj} food or cuisine." `
  --check2-hyp "company_name=This text mentions {country} only as part of a company or brand name." `
  --check2-hyp "dish_name=This text mentions {country_adj} only in the name of a dish or drink."
```

- Giving any `--check1-hyp` **replaces all** default check-1 hypotheses, and the same is true for check 2.
  To extend the defaults, repeat the default text alongside your new ones.
- Each line is scored against every hypothesis and **the highest score wins**. Adding hypotheses therefore
  makes the filter catch more lines, but each one also costs one more model call per window.
- `--no-check2` skips check 2 entirely.
- **To make them permanent**, edit `DEFAULT_CHECK1` / `DEFAULT_CHECK2` in `nli_filter.py`.
- Afterwards, the viewer's **Tune thresholds** page shows how the new results trade precision against
  recall.

## 3. Language names (cheap rules)

`LANGUAGE_NAMES` in `nli_filter.py` decides when a hit like "Russian" in a list such as
"English, Russian, French" is treated as a language menu and the line is kept without using a model. For a
new country, check that its adjective is in that list. "Japanese" already is; add others, such as
"Mongolian", if needed.

## 4. Labels in `nli_models.py` (scoring only, no filtering)

```powershell
# Turn labels into hypotheses with a template
python .\nli_models.py --model deberta --input test_russia.jsonl `
  --labels "Russia,China,sports,politics,music" --template "This text is about {}." --threshold 0.8

# Or write the hypotheses out in full
python .\nli_models.py --model deberta --text "Putin met Xi in Beijing." `
  --hypothesis "This text is about Russia." --hypothesis "This text is about trade."
```

- `--single-label` makes the label scores add up to 1, which means "pick one topic".
- `--threshold` lists the labels that score at or above it.

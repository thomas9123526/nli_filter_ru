# Filtering Germany with a large keyword list (10,000+ words)

Germany is not a built-in country, so give the adjective and a keyword file. All commands run from
`D:\hkc\nli_filter2` (Linux: the project folder on the H200 machine) with the venv active.

## 1. Prepare

**Keyword file** `keywords\germany.txt`: UTF-8, one keyword or phrase per line, `#` starts a comment.
With `--country Germany` it is picked up automatically.

```
# keywords\germany.txt
Germany
German
Germans
Deutschland
deutsch
deutsche
deutschen
deutscher
Bundesrepublik Deutschland
Bundestag
Berlin
...
```

How keywords match:

- Case-insensitive, whole words only: `deutsch` does not match `deutsche`, so **list every inflected
  form** you need. CJK keywords (ドイツ, 德国) match anywhere.
- Duplicates (also differing only in case) are dropped automatically. When keywords overlap, the longest
  match wins.

**Install `pyahocorasick`.** With 10,000 keywords it is about 6x faster (measured: 31.6 MB/s with it,
5.6 MB/s without):

```powershell
pip install pyahocorasick
```

The start of a run prints which engine is used (`aho-corasick` or `regex`).

**Clean the list.** Every keyword that also has an everyday meaning sends many lines to the model and adds
false positives. Remove such words, or keep them and add an exclude pattern or a check-2 hypothesis
(section 3):

| Risky keyword | Everyday meaning |
|---|---|
| Hamburger, Frankfurter, Berliner, Wiener | food |
| German shepherd, German measles, German chocolate cake | dog, illness, cake |
| Essen, Bad, Mark, Hof, Weil, Most | ordinary German / English words |

**Mixed-language keywords in an English corpus** (keywords mostly English, some German / Chinese /
Japanese) work as they are. Tested results:

| Text | Hits |
|---|---|
| `Germany's chancellor spoke in Berlin.` | Germany, Berlin |
| `This argument is germane to the case.` | none (whole words only) |
| `He visited MÜNCHEN and the Bundestag.` | MÜNCHEN, Bundestag (case-insensitive, umlauts fine) |
| `The sign said Strasse, not Straße.` | only Straße: list spelling variants (Strasse, Muenchen) too |
| `The anime fan wrote 德国 and ドイツ in the title.` | 德国, ドイツ |
| `A lesson on 道德 (morality) in class.` | 德 if the single character 德 is a keyword: avoid single CJK characters |
| `Languages: English \| Deutsch \| German \| French` | German, kept by the language-menu rule |
| `Audio: ドイツ語, 英語, 日本語` | ドイツ, kept by the language-menu rule |

- CJK keywords match anywhere (no spaces between words in CJK), so use whole words: 德国, 德國, ドイツ,
  独逸, not 德 or 独 (they appear inside 道德, 独立, ...). A run warns about single-character CJK keywords.
- In an English corpus, German keywords that are also English words (Bad, Hof, Mark, Gift, Rat, Bank,
  Kind, Art, Boot, Hell, Rock) match everywhere: leave them out.
- The models only see English text with a few foreign words, so the default cascade (ModernBERT +
  DeBERTa) is the right choice; bge-m3 is only needed if many lines are mostly non-English.

## 2. Commands for each purpose

```powershell
# a) Quick check on 200 lines: does everything load, are the hits sensible?
python .\nli_filter.py dataset/test_corpus --country Germany --country-adj German --limit 200 --output-dir out_de_try -v

# b) Measure accuracy on a labelled sample (lines with "expect": "filter"/"keep" and optional "category")
python .\nli_filter.py germany_sample.jsonl --country Germany --country-adj German --output-dir out_de_eval

# c) Fast first pass, one model only
python .\nli_filter.py D:\corpus --country Germany --country-adj German --judge-model none --output-dir out_de_fast

# d) Best accuracy (default cascade: ModernBERT + DeBERTa judge), also write kept / filtered lines
python .\nli_filter.py D:\corpus --country Germany --country-adj German --write-split --output-dir out_de

# e) Corpus with German-language (or other non-English) texts: the multilingual model
python .\nli_filter.py D:\corpus --country Germany --country-adj German --fast-model bge-m3 --judge-model none --output-dir out_de_m3

# f) Catch more (higher recall, more false positives) or fewer (higher precision)
python .\nli_filter.py D:\corpus --country Germany --country-adj German --check1-threshold 0.7 --output-dir out_de_07
python .\nli_filter.py D:\corpus --country Germany --country-adj German --check1-threshold 0.9 --output-dir out_de_09

# g) Use another keyword file
python .\nli_filter.py D:\corpus --country Germany --country-adj German --keywords-file D:\lists\de_10k.txt --output-dir out_de
```

On the 8 x H200 machine:

```bash
./run_shards.sh /data/corpus /data/nli_out_de 2 --country Germany --country-adj German --write-split \
    --batch-size 256 --judge-batch-size 128
```

Re-running the same command skips finished files.

## 3. Fewer false positives

```powershell
python .\nli_filter.py D:\corpus --country Germany --country-adj German `
  --exclude-pattern "(?i)\bhamburgers?\b" `
  --exclude-pattern "(?i)german (shepherd|measles|chocolate cake)" `
  --check2-hyp "company_name=This text mentions {country} or {country_adj} only as part of a company or brand name." `
  --check2-hyp "language_setting=This text mentions the {country_adj} language only as a language option or setting." `
  --check2-hyp "food_name=This text mentions {country_adj} only in the name of a food, dish or drink." `
  --output-dir out_de
```

- `--exclude-pattern`: hits inside a match are ignored, with no model call (cheapest). The regex is
  case-sensitive unless it starts with `(?i)`.
- `--check2-hyp`: the model decides whether a hit is only incidental. Giving any `--check2-hyp` replaces the
  defaults, so the two default hypotheses are repeated above.
- "German" and "Deutsch" are already in the language-name list, so language menus such as
  "English | Deutsch | Français" are kept without a model.

## 4. Review the result

Add the output folder to `viewer\viewer_config.json` and start the viewer (`cmds\viewer\viewer.md`):

```json
{"name": "germany", "title": "Germany", "corpus": "D:/corpus", "output": "D:/hkc/nli_filter2/out_de"}
```

- The File page's reason filters show which kinds of lines were filtered or kept.
- The Tune thresholds page shows how check-1 thresholds of 0.7 or 0.9 would change the result, without
  running the models again.

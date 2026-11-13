# Germany: compare hypothesis sets (higher recall)

Step 1 (`cmds\testing\germany_test.md`) with the default hypothesis: precision 1.000, **recall 0.795**. The 9
missed lines are about cities, football, cars, beer and literature; the default check-1 hypothesis only names
country, person, film, song and history. Below: three sets to run one after the other on `test_germany.jsonl`
and compare. Same settings as step 1 (ModernBERT only, CPU) so only the hypotheses differ.

Run from `D:\hkc\nli_filter2` with the venv active. Each run takes about a minute; more hypotheses = more
model calls (shown as "NLI pairs fast" in the summary).

## Set A: the default (baseline, = step 1)

```powershell
python .\nli_filter.py test_germany.jsonl --country Germany --country-adj German --judge-model none --device cpu --output-dir out_de_hypA
```

## Set B: default + places, sport, economy, culture

```powershell
python .\nli_filter.py test_germany.jsonl --country Germany --country-adj German --judge-model none --device cpu --output-dir out_de_hypB `
  --check1-hyp "topic=This text is about {country}, a {country_adj} person, a {country_adj} film, a {country_adj} song, the lyrics of a {country_adj} song, or the history of {country}." `
  --check1-hyp "place=This text is about a city, region, building or place in {country}." `
  --check1-hyp "sport=This text is about {country_adj} sport, a {country_adj} team or a {country_adj} athlete." `
  --check1-hyp "economy=This text is about the economy of {country}, a {country_adj} company or {country_adj} products." `
  --check1-hyp "culture=This text is about {country_adj} culture, food, drink, literature, music or art."
```

## Set C: set B + one more check-2 rescue for fixed expressions

Broader check-1 hypotheses may also score lines like "German shepherd" or "German measles" as being about
Germany. Set C gives check 2 one more way to keep them:

```powershell
python .\nli_filter.py test_germany.jsonl --country Germany --country-adj German --judge-model none --device cpu --output-dir out_de_hypC `
  --check1-hyp "topic=This text is about {country}, a {country_adj} person, a {country_adj} film, a {country_adj} song, the lyrics of a {country_adj} song, or the history of {country}." `
  --check1-hyp "place=This text is about a city, region, building or place in {country}." `
  --check1-hyp "sport=This text is about {country_adj} sport, a {country_adj} team or a {country_adj} athlete." `
  --check1-hyp "economy=This text is about the economy of {country}, a {country_adj} company or {country_adj} products." `
  --check1-hyp "culture=This text is about {country_adj} culture, food, drink, literature, music or art." `
  --check2-hyp "company_name=This text mentions {country} or {country_adj} only as part of a company or brand name." `
  --check2-hyp "language_setting=This text mentions the {country_adj} language only as a language option or setting." `
  --check2-hyp "fixed_expression=This text uses the word {country_adj} only in the name of an animal, a plant, a disease, a dish or a common expression, not about {country}."
```

(Giving any `--check1-hyp` / `--check2-hyp` replaces all defaults of that check, so the default ones are
repeated above.)

## Compare

| Set | accuracy | precision | recall | NLI pairs fast | seconds |
|---|---|---|---|---|---|
| A (default) | 0.909 | 1.000 | 0.795 | 221 | 64 |
| B | | | | | |
| C | | | | | |

(Row A: the step-1 run of 2026-11-10.) Fill in from each run's summary. What to look at:

- **recall up, precision still 1.000**: the new hypotheses catch the missed lines without new mistakes.
- **precision down**: look at the mistakes list at the end of the summary; if they are fixed expressions
  (German shepherd ...), set C should win them back.
- **NLI pairs**: set B/C ask about 5 x as many check-1 questions; on the H200 that is affordable, on a CPU it
  is slow.

In the viewer, the File page's "wrong vs expected" filter lists the mistakes with their scores and the Tune page
shows how another threshold would change the result. A run on `test_germany.jsonl` (which lies in the project
folder) is added to `viewer\viewer_config.json` like this:

```json
    {"name": "de_hypB", "title": "Germany, hypotheses B", "corpus": "..", "output": "../out_de_hypB"}
```

Then the best set with the judge model (default cascade):

```powershell
python .\nli_filter.py test_germany.jsonl --country Germany --country-adj German --device cpu --output-dir out_de_hypBest <the --check1-hyp / --check2-hyp lines of the best set>
```

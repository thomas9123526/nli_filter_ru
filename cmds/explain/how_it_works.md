# How a line is filtered: keywords, country, hypotheses, output

Examples are from the Germany test run `out_de_step1` (see `cmds\testing\germany_test.md`).

## The path of one line

```
text ──► 1. keyword search ──► 2. cheap rules ──► 3. check 1 (model) ──► 4. check 2 (model) ──► decision
          keywords\germany.txt    language menus      "about Germany?"      "only incidental?"
          no hit → keep           all hits explained  score < 0.8 → keep   every hit incidental → keep
                                  → keep                                    otherwise → FILTER
```

## 1. The keyword file

- **Loading:** `--country Germany` makes the script look for `keywords\<country lowercased>.txt`, or the
  file named with `--keywords-file`. Empty lines and `#` lines are skipped. Keywords that differ only in
  case count once.
- **Searching:** `KeywordMatcher` searches every line for all keywords at once (Aho-Corasick).
  - It ignores case and matches whole words only, except Chinese/Japanese keywords, which match anywhere.
  - When keywords overlap, the longest wins: "East Germany" is one hit.
- **The keywords never go to the model.** They do three things:
  1. **Gate:** a line with no hit is kept at once as `no_keyword`, with no model call.
  2. **Choose what the model reads:** the model sees the text around the hits (section 3).
  3. **Record the hits** in the output: `{"kw": "Bundesliga", "span": [22, 32]}`, where `span` is the
     start and end character position in `text`.

## 2. Country name and adjective

| Value | From | Used for |
|---|---|---|
| `Germany` | `--country` | `{country}` in the hypotheses; the keyword file name `germany.txt` |
| `German` | `--country-adj` | `{country_adj}` in the hypotheses; added to the language-name list for the cheap rules |

The country name is **not** searched for automatically; "Germany" is found only because it is in
`germany.txt`.

The **cheap rules** (`IncidentalRules`) look at hits that are language names ("German", "Deutsch"). Such a
hit is explained without a model when:

- **`language_label`:** it follows a label like `Language:`, `Subtitles:`, `言語:`;
- **`locale_code`:** a locale code like `de-DE` is within 80 characters;
- **`language_menu`:** it is in a list of 3 or more language names.

If every hit of a line is explained, the line is kept as `rules_incidental`.

## 3. The model, hypotheses and scores

The model gets a pair, a **premise** (a piece of the text) and a **hypothesis** (a sentence), and returns
**P(entailment)**: the probability that the text supports the sentence, from 0 to 1.

The hypotheses of the Germany run (from `summary.json`):

```
check1  topic            "This text is about Germany, a German person, a German film, a German song,
                          the lyrics of a German song, or the history of Germany."
check2  company_name     "This text mentions Germany or German only as part of a company or brand name."
        language_setting "This text mentions the German language only as a language option or setting."
```

**Check 1: is the text about the country?**

- **Premise:** the whole line if it is at most 1,000 characters; for a longer line, up to 2 windows of
  about 1,000 characters around the first hits not explained by a rule.
- **Pairs:** each window x each check-1 hypothesis. The best score counts; below 0.8 the line is kept as
  `check1_negative`.
- **The judge:** with a judge model on, every score between 0.6 and 0.95 is scored again by the judge, and
  the judge's score replaces the fast model's.

**Check 2: is each hit only incidental?** Only for lines that pass check 1.

- **Premise:** the sentence containing the hit, at most 300 characters.
- **Pairs:** each sentence x each check-2 hypothesis; a best score of 0.8 or more marks the hit incidental.
- **Result:** every remaining hit incidental → kept as `check2_incidental`; otherwise **filtered** as
  `about_country`.

**Example `mixed-002`:**

> German Street Capital LLC sponsored the lecture. The speaker discussed Germany's hyperinflation of 1923
> and the collapse of the mark.

1. **Keywords:** hits `German` (characters 0–6) and `Germany` (71–78).
2. **Check 1:** the whole line against `topic` scores **0.971**: about Germany.
3. **Check 2:** sentence 1 with "German": `company_name` **0.887**, incidental; sentence 2 with "Germany":
   best 0.038, not incidental.
4. **Decision:** one hit is not incidental → **filtered**.

**A miss, `about-015`:** "Bayern Munich won the Bundesliga title again ..." scored **0.022** on `topic`:
the hypothesis names country, person, film, song and history, not sport. Broader hypotheses or the judge
model raise recall.

## 4. The output folder

```
out_de_step1\
├── summary.json                     the whole run
├── test_germany.summary.json        one per input file
└── test_germany.decisions.jsonl     one line per input line
```

For a folder corpus the input's sub folders are repeated, one set of files per input file, e.g.
`wikipedia\part-01\shard-00002.decisions.jsonl.zst`. Compressed input gives `.zst` output.

**`*.decisions.jsonl`:** one JSON object per input line, in the same order.

| Field | Meaning |
|---|---|
| `line` | line number in the input file (1-based) |
| `id`, `expect` | copied from the input line (`expect` only if present) |
| `decision` | `filter` or `keep` |
| `reason` | `no_text`, `no_keyword`, `rules_incidental`, `check1_negative`, `check2_incidental`, `about_country` (plus `blank`, `bad_json`) |
| `check1` | `score` (best), `positive`, the `hyp` and `window` that gave it, and `pairs`: every window x hypothesis with `fast`, `judge` and final `score` |
| `hits` | each hit: `kw`, `span`, plus `rule` if a cheap rule explained it, or `check2` (window, hyp, scores, `incidental`) if the model checked it |

The **text itself is not copied**: the decision points to the original by `line` and `span`, which is how
the viewer shows them side by side. `--decisions candidates` writes only lines with keyword hits,
`--decisions none` writes no decisions file.

**`<name>.summary.json`:** per-file counts and `complete: true/false`. An incomplete file (e.g. after
`--limit`) is redone on the next run.

**`summary.json`:** the country, all keywords, the filled-in hypotheses, thresholds and settings, the models,
timing, the list of files, totals and evaluation, and the exact `command`.

**With `--write-split`:** the original lines are also written to `<name>.kept.jsonl` and
`<name>.filtered.jsonl`: the cleaned corpus.

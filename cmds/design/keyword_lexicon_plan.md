# Plan: keyword lexicon, strict (A) keywords, templated hypotheses, review

Status: agreed 2026-11-17. Built one step at a time; each step is marked when done.

## Why

- The keyword list will grow to 5000+ words. One global set of hypotheses cannot describe them all:
  Siberia needs "a region of Russia", Tolstoy "a Russian writer", Muscovite "not the mineral".
- The tests on `longtest` showed the model only links a word to the country when the hypothesis says it
  (`sib_baikal`: "This text is about Russia." 0.019; "…Siberia, Moscow, … or another region or city of Russia." 0.919).
- Some words mean the country in every context; running models on them wastes time.
- The policy (what counts as "about the country") will change a little over time, so it must live in data
  files, not in code.

## Policy lives in data

| policy part | where | to change it |
|---|---|---|
| topics that count as "about the country" | check-1 hypotheses | edit / add / delete a hypothesis |
| uses that are only incidental (nature, brand, idiom, …) | check-2 hypotheses | edit / add / delete a hypothesis |
| a topic moves from filter to keep | move its hypothesis from check 1 to check 2 | data only |
| meaning, other meanings, exclusions of a word | keyword lexicon | edit its line |
| strict or decided by the models | the lexicon's `level` column | edit one letter |
| how sure the models must be | thresholds | Tune page, no rerun |

The filter / keep policy itself is written by the user (a short list of topics on each side); the hypotheses
follow it.

## Keyword levels

- **A (strict):** any line with an A word (after exclusions) is **filtered**, reason `strict_keyword`,
  with **no model call**. **Absolute by default**: rules (language menu / label / locale code / company name)
  do not change it. A switch can let rules apply to A hits (off by default).
- **B (default):** decided by check 1 / check 2 as today.
- A and B in the same line: A wins.
- A is only for words that mean the country in almost every context (e.g. "Russian Federation", "Россия").
  "Russia" / "Russian" stay B (country lists, language menus, "Russian roulette").

Decision order for a line:
1. Match keywords (Aho-Corasick: cost depends on the text length, not on the number of keywords).
2. Drop hits removed by the keyword's exclusion patterns.
3. Any A hit left → filter (`strict_keyword`).
4. Only B hits → check 1 / check 2.

## The lexicon format

The keyword file gets optional tab-separated columns; a plain one-word line stays valid (level B, no type).

```
# keyword            level  type     gloss                   other meanings                         exclude
Russian Federation   A      country  -                       -                                      -
Russia               B      country  -                       -                                      -
Siberia              B      region   a region of Russia      a brand name | a figure of speech      Siberian husky | Siberia 800
Muscovite            B      demonym  a person from Moscow    a mineral (mica)                       muscovite mica
St. Petersburg       B      city     a city in Russia        St. Petersburg, Florida                St\.? Petersburg,? (FL|Florida)
```

- **type**: a few fixed classes (country, demonym, region, city, person, org, brand, language, event, …).
- **gloss**: the fact the model does not know.
- **other meanings**: feed check 2.
- **exclude**: phrase patterns that remove the hit before any model (cheap).

## Templated hypotheses

Templates per type with placeholders `{kw}`, `{gloss}`, `{other}` (besides `{country}`, `{country_adj}`):

```json
{
  "check1": {
    "*":      { "country": "This text is about {country}." },
    "region": { "place":   "This text is about {kw}, {gloss}." },
    "person": { "person":  "This text is about {kw}, {gloss}." }
  },
  "check2": {
    "*":      { "nature": "This text is only about nature, wildlife, climate or landscape.",
                "brand":  "In this text, {kw} is part of a company, product or brand name." },
    "@other": { "sense":  "In this text, {kw} means {other}." }
  }
}
```

- A window gets the `*` hypotheses plus those of the types / keywords in it, capped
  (e.g. at most 3 keyword-specific hypotheses per window), so the cost stays bounded.
- Today's flat files (`check1` / `check2` as name → text) keep working: they are the `*` set.

## Review

- **Model reviewer (judge):** only the uncertain band, as now; keep the band narrow (0.6–0.97): the judge
  over-scores loose hypotheses.
- **Per-keyword stats** in the viewer: hits, % filtered / kept, mistakes per keyword (A and B).
- **Audit mode** (`--audit-strict`): on a sample, run the models on A lines too and store the scores without
  changing the decision; shows A words that are too broad.
- **Review queue:** lines whose best score was in the band, or decided by a single keyword.
- **Golden set per type:** at least 3 filter + 3 keep lines per type and per risky keyword.
- **Replay:** with every hypothesis score stored (early stop off), recompute decisions after removing / moving
  hypotheses or changing thresholds without the models.
- **Regression:** `test_russia.jsonl` + the golden set after every change, accuracy compared with the last run.

## Build order

1. [x] Lexicon format: level, type, gloss, other meanings, exclude; plain lines still work (level B).
   Done 2026-11-17: `nli_filter.KeywordEntry`, `parse_keywords`, `load_lexicon`; every hit knows its keyword
   (`Hit.kw`, `KeywordMatcher.entry(hit)`); per-keyword exclude patterns (case-insensitive) drop a hit before
   any model; bad lines are refused with their line numbers (CLI and Try); `summary.json` / keywords report
   have `lexicon` counts, the report has level and type per keyword; Tab types a tab in the Try keywords box.
   Level A is read and stored but does not change decisions yet (step 2). Tests: `tests/test_lexicon.py`.
2. [x] The A path: `strict_keyword` reason, shown in the viewer and in Copy for chat; switch to let rules apply.
   Done 2026-11-17: a line with a level-A hit (after exclude patterns) is filtered, reason `strict_keyword`, no
   rule and no model; the decision has `strict: [keywords]`, A hits carry `level: "A"`. `--strict-rules`
   (Try: "rules apply to A", off by default) lets the rules clear an A hit first. Keywords report:
   `lines_strict` and `strict_lines` per keyword. Viewer: reason label, hit state "strict" (outlined red),
   explanation step, Try score table "A: …". Tune (simulate) leaves these lines unchanged (no scores).
   Tests: `tests/test_lexicon.py`, `viewer/backend/tests/test_explain_strict.py`.
3. [x] Templated hypotheses: `{kw}`, `{gloss}`, `{other}` per type, with the cap.
   Done 2026-11-17: hypothesis files may add `check1_types` / `check2_types` (type → key → template; `*` = every
   keyword; `@other` = check 2, once per other meaning). The flat `check1` / `check2` stay as they are.
   Check 1: a window gets the templates of the keywords hit inside it; check 2: a hit gets those of its keyword
   (hits of different keywords in one sentence are scored apart when they have own templates). A template with
   `{gloss}` is skipped for keywords without a gloss. `--max-keyword-hyps` (default 4) caps them per window / hit.
   Built hypotheses have keys `<key>:<keyword>` (`sense:Moscow/2` for the 2nd other meaning) and their text is
   stored in the decision (`text`), so the viewer shows them. Try: "built from the matched keyword" editors under
   each check. Starter file: `hypotheses/russian_kw.json`. Tests: `tests/test_keyword_hyps.py`.
4. [x] Viewer: per-keyword stats, audit view, review queue.
   Done 2026-11-18 (night): **Keywords** page (per keyword: hits, lines, % filtered / kept, by rules, lines with
   only this keyword, mistakes, level-A audit, flags: mostly kept / mostly rules / mistakes / A too broad / A not
   audited / no hits; a row opens its lines). `--audit-strict SHARE` (Try: "audit A") runs a sample of level-A
   lines through the rules and models too and stores the result in `decision.audit` (the decision stays filter).
   **Review** page with queues (close to a threshold, one keyword decides, level-A audit would keep, decided by
   the judge, mistakes); lines open in place and get a filter / keep label for the **golden set**
   `golden/<dataset>.jsonl` (a test file; the corpus is never changed). Record page: audit box + golden label.
   Docs: `cmds/viewer/review_tools.md`.
5. [x] Replay mode and golden-set regression.
   Done 2026-11-18 (night): `nli_compare.py A B` (two runs line by line: accuracy, changed lines better / worse,
   reasons, what differs in settings / hypotheses / keywords) and `nli_replay.py RUN --drop-check1 KEY
   --check1-threshold T --output-dir NEW` (decisions recomputed from stored scores, no models; lines that
   depend on scores early stop left out are marked estimated). Regression = run the golden set + compare.
   Docs: `cmds/testing/compare_and_replay.md`.

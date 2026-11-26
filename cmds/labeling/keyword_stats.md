# Keyword and marker statistics (`nli_label.py kwstats`)

Which of the terms nli_label searches for actually hit, how often and where, which never hit, and how long the GPU run
will take. No models, CPU only. Code: `nli_kwstats.py`; page: `/label/kwstats/` in the viewer.

## Running it

    python nli_label.py kwstats CORPUS --policy policy/russia_llm_policy_v2.json --output-dir dataset/kwstats_<name>
        [--topic-field FIELD] [--group-by folder|file] [--shard K/N] [--limit N]
    python nli_kwstats.py CORPUS ...          (the same, without nli_label.py)

- **CORPUS:** files, folders, globs or server addresses, as for `run` (`.jsonl`, `.jsonl.zst`, `.parquet` …).
- **`--topic-field`:** a field per line used as a second kind of unit, the **topic** (the benchmark's `case` or
  `group`; later a topic classifier's output). Lines without it count as `(none)`. Real corpus lines have only `id`
  and `text`, so there the units are folders or files.
- **`--group-by folder`** (default): the unit is the file's folder below the input folder (`russian/companies`).
  The page can cut it to a level (level 1 = `russian`, the side). **`--group-by file`:** one unit per file.
- **`--shard K/N`:** only every N-th file, starting at K, like `run`. Each shard writes
  `kwstats.part.shardKofN.json` into the same `--output-dir`; the last one to finish merges all N parts into
  `kwstats.json` (seconds). `--merge` merges the parts that are there by hand.
- **`--limit N`:** the first N lines of each file, for a quick look. Use `--corpus-lines` to scale the forecast.
- **Forecast settings:** `--gpus` (default 8, one 8 × H200 machine), `--pairs-per-second 3000,5000` (ModernBERT
  pairs/s per GPU, an estimate: `cmds/h200/nli_label_h200.md` section 4), `--corpus-lines N` (scale to the whole
  corpus when you scanned a sample).
- `--no-rules` (as `run --no-rules`), `--text-field`, `--no-suggest` (skip the "terms to add" word count).

From the viewer: `/label/kwstats/` (linked from `/label/`), form "Keyword statistics of a corpus". It starts the
scan through the model service like the Start-a-run form; `python nli_playground.py --no-models` is enough.

**Speed:** the matcher is Aho-Corasick (pyahocorasick; a regex when it is missing), so 10,000 terms cost about the
same as 100. Paragraph and sentence splitting run on every line. The 10,000-term test (1,500 lines of ~1 KB, each
with ~20 hits) takes a few seconds. For 4 TB of parquet on 5 machines, expect the reading time of the files plus the
scan: roughly 30–60 minutes with `--shard`.

## Outputs

| File | What |
|---|---|
| `kwstats.json` | everything the page shows |
| `terms.csv` | one row per term (the columns below) |
| `report.md` | the written report (the same text as on the page) |
| `kwstats.part[.shardKofN].json` | the raw counts of one scan, to merge shards |

## What each number means

**The same matching as a run.** The terms are the policy's keyword files (`keywords_file`, e.g.
`keywords/russia_v3.txt` + `keywords/ukraine.txt`), its `markers` and its `narrative_keywords`. Every line is
matched with `nli_label.build_matchers` (the same KeywordMatcher, exclude patterns, longest match wins) and the same
cheap rules (language menus, locale codes, company names). So "gated lines" is exactly the number of lines a run marks
`gate: true`, and "paragraphs to label" the paragraphs it sends to the models.

Per term:

| Column | Meaning |
|---|---|
| `hits` | every match in the corpus, incidental ones included |
| `incidental`, `incidental_share` | hits a cheap rule marks incidental (they do not open the gate) |
| `lines`, `line_share` | lines with at least one hit; share of all lines with text |
| `gate_lines` | lines where this term opens the gate (a hit that is not incidental) |
| `paragraphs` | paragraphs with a hit, split with the policy's paragraph rules (`min_chars`, `max_chars`) |
| `sentences` | sentences with a hit (split at `. ! ? …` + space, `。！？`, and line breaks) |
| `files` | files with a hit |
| `units_hit` | units (folders or files) with a hit |
| `co_terms` | the top 5 terms found in the same paragraph, with the number of paragraphs |
| `kind`, `list` | keyword / marker / narrative; the list file it comes from (a word in two lists: the first one) |

Per unit (folder / file / topic): lines, lines with a hit, gated lines, paragraphs, paragraphs to label, hits; per
term the hits and lines per unit, stored only where not zero.

Corpus:
- lines, paragraphs, sentences; lines with any hit and gated lines;
- histograms of hits per line and of distinct terms per line (0 … 99, then 100+);
- concentration: the share of all hits made by the top 10 terms and by the top 1 % of terms;
- co-occurring pairs: two terms in the same paragraph. Every pair is counted; a shard part keeps the top 50,000 and
  `kwstats.json` the top 1,000 (so with shards, rare pairs can be missing from the merged count);
- never-hit terms overall (per unit on the page and in the report);
- duplicates: a word listed more than once (in one file, in two files, or as keyword and marker);
- overlaps: one term is a whole-word part of another (`Kremlin` in `pro-Kremlin`). Where the longer term matches,
  only it is counted, so the inner term's count is lower than a plain text search would say;
- suggested words: capitalised words that are in at least 3 gated lines, at least 5 times more frequent (per line) in
  gated lines than in the others, and not a term or part of one. Only a hint for "terms to add".

## The forecast

    model pairs = paragraphs to label × pairs per paragraph
    time        = model pairs / (pairs per second per GPU × GPUs)

Pairs per paragraph come from the policy: when the gate passes, gate + level 1 + level 2 (+ hypothesis exceptions);
when it does not, gate (+ exceptions, + the level-2 "remove" labels when `narrative_opens_gate`). The upper number
assumes every paragraph passes the gate, the lower one that none does; the truth is in between. Not included: reading
and the keyword scan (CPU), and the judge's extra pairs for uncertain scores. For the Russia-side v2 policy:
15 / 5 pairs per paragraph.

## Reading the page

1. **Rank-frequency:** every term by rank (x) and hits (y, log scale). A steep start means a few terms make most hits;
   the red band at the end is the never-hit terms. Hover shows any term; a click opens it. Colour = kind.
2. **Top 50 and bottom 50:** the same with names.
3. **Terms:** the table, paged, searchable, sortable by every count, with a CSV download (the filtered rows).
4. **Heatmap:** the top N terms (or the filtered ones) × units: folder (any level), file or topic. Hatched cells with 0
   = no hit there. "per 1,000 lines" divides by the unit's lines, for units of different size.
5. **Never-hit terms:** overall, or in one unit; CSV.
6. **Histograms:** hits per line and distinct terms per line (lines without a hit hidden by default).
7. **Co-occurring pairs:** the top pairs; search for one term's pairs. Duplicates and overlaps below.
8. **Report:** coverage, dominant terms, dead terms, mostly incidental terms, spread over units, duplicates and
   overlaps, the GPU-time forecast, suggestions. Copy as Markdown, or `report.md` from the folder.

Each chart downloads as SVG or PNG (buttons at the top right).

## Example: `dataset/corpus_benchmark` (2026-11-25)

    python nli_label.py kwstats dataset/corpus_benchmark --policy policy/russia_llm_policy_v2.json \
        --output-dir dataset/kwstats_benchmark --topic-field case

288 lines, 151 gated (52 %: russian side 57 of 136, ukrainian side 94 of 152), 19 of 92 terms hit, 163 paragraphs to
label. Kyiv 75 hits and Moscow 53 make 62 % of all hits. "Russia" / "Russian" never hit: the benchmark texts name
Russian things without the country name. Hand count: Kyiv 75 hits in 66 lines, Lviv 18 / 17, orcs 9 / 7 (a plain
search agrees); Moscow 55 by plain search, 53 counted, because the keyword's exclude pattern drops "Moscow, Idaho".

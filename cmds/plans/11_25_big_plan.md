# 11_25_big_plan: simple-run expected results, keyword statistics

Planned 2026-11-25, to be built when the user says so ("do 11_25_big_plan", "I'm leaving", …). The work is in the
viewer's Labelling area (`/label/…`), for the Russia-side policy (`policy\russia_llm_policy_v2.json`). The background
is the conversation of 2026-11-25 (`cmds\conversation\2026-11-25.md`, "why is Expected vs result missing on the simple
run's page"), and "keyword and marker statistics over a corpus".

The estimate is about 3½–4 hours: task 1 about 30 min, task 2 about 3–3½ h.

## Tasks

### 1. "Expected vs result" for simple-mode runs (about 30 min)

**Why.** The panel exists only for detail runs (`/label/run/?run=out_label_ru_v2`). A simple run such as
`out_label_benchmark_simple` has no labels files, only `<name>.decisions.jsonl.zst`. Its page (`SimpleRunView`) skips
the expected check, so there is no total and no filter for mismatches. The benchmark schema puts `expected` next to
`decision` in every row, but only as raw text.

**What.**
- **Backend** (`viewer\backend\nli_viewer\labels.py`): the expected summary for a simple run.
  - Read each file's decisions rows through the run's schema (the `line` field, plus `level` or `decision`).
  - Read `expected_action` / `acceptable` from the run's input file, as for detail runs (`LabelRuns.expected`).
  - Compare at line level:
    - line unit: the row's decision;
    - paragraph unit: the line's strictest level (`level`, or the document action mapped to remove / review / keep /
      pass).
  - Use the same rule as detail runs: "also fine" actions count, and pass = untouched = none.
  - Return n / ok and the wrong lines (file, line, id, expected, got, note).
  - Rows needed by the schema:
    - Without a `line` field in the schema, there is no panel, with a note.
    - Without `untouched` in `include`, untouched lines have no row, so they count as "untouched".
- **API:** the existing `GET /api/labels/{name}/expected` also answers for simple runs. `simple_rows` gets
  `expect=wrong|right`, and each row gets its verdict.
- **Frontend** (`SimpleRunView.tsx`):
  - the same "Expected vs result" panel as on detail runs: n / ok with a percentage, and the wrong lines with
    expected / got / note;
  - a click on a wrong line opens it (text, evidence, Explain this line);
  - a filter "not as expected / as expected" in the lines table, and an expected / got badge per row.
- **A corpus without expected results** must work as on detail runs: no panel, no filter, no error. Two known limits
  of today's detection (in `LabelRuns.expected` / `expected_summary`) should be fixed at the same time:
  - **The file check:** only the run's **first** file is checked for expected fields. If that file has none, there is
    no panel, even when other files do. Check every file instead, until one has expected fields.
  - **The line check:** a file counts as "no expected results" when none of its first 3 lines has
    `expected_action` / `expected_doc_action`. If only later lines have them, they are missed. Keep that shortcut
    for big real corpora, but say so in the docs.
- **Line level only.** With `evidence: decided` or `all`, a per-paragraph check would be possible later, for test
  documents with `expected_paragraphs`. It is not part of this task.
- **Tests:**
  - backend: a simple run on a small corpus with `expected_action`, in both units;
  - `include` without `untouched`;
  - a schema without `line`;
  - a rendered-page check of the panel and the filter.
- **Docs:** `cmds\viewer\labels_pages.md` (simple run page) and `cmds\labeling\output_modes.md` (the "what a simple run
  can show" table).
- **Done when:** `/label/run/?run=out_label_benchmark_simple` shows "Expected vs result", with the same counts as a
  detail run of the same corpus and unit, and the mismatching lines can be listed and opened.

### 2. Keyword and marker statistics over a corpus (about 3–3½ h)

**Why.**
- **What the user wants to see:** which of the terms nli_label searches for actually hit, how often and where, and
  which never hit. Also how the hits spread over sentences, paragraphs, lines, files and topics. It is shown as charts
  and a written report in the viewer.
- **What exists does not cover it:**
  - `nli_filter.py --keywords-report` and `/filter/keywords` belong to A's tool.
  - An nli_label run keeps only 50 hits per line and has no sentence counts.
- **Also a forecast:** the share of lines with a hit decides the GPU time of the labelling run, so the scan tells
  before the GPU run how long it will take.

**Scale.** The keyword lists will grow to **5,000–10,000+ terms**, so everything is designed for that.
- **The search is not slowed:** Aho-Corasick, measured 0.27 ms vs 0.30 ms per 5 KB line for 100 vs 10,000 words.
- **What changes is the size of the results and the views.**

**What.**

**A scan command** (no models; CPU only), in nli_label.py:

    nli_label.py kwstats CORPUS --policy policy/russia_llm_policy_v2.json --output-dir dataset/kwstats_<name>
        [--topic-field FIELD] [--group-by folder|file] [--shard K/N] [--limit N]

- **Terms and hits:**
  - the terms are the policy's keyword files and markers;
  - the same matcher and cheap rules as a run, so the counts match what a run would gate.
- **Per term:**
  - hits;
  - lines, paragraphs (the policy's paragraph rules) and sentences with the term, and files;
  - the share of lines;
  - hits the cheap rules mark incidental;
  - counts per unit (folder / file / topic), stored only where not zero;
  - the top 5 co-occurring terms;
  - the kind: keyword or marker, and which list file (Russia / Ukraine).
- **Corpus:**
  - lines, paragraphs and sentences in total;
  - lines with a hit;
  - a histogram of hits per line and of distinct terms per line;
  - concentration: the share of the top 10 / top 1 % of terms;
  - the top co-occurring pairs (capped);
  - the never-hit terms, overall and per unit;
  - terms listed twice, or overlapping (e.g. one term inside another).
- **Topics:** from `--topic-field` (e.g. the benchmark's `case` / `group`), else from the folder structure. Later a
  topic classifier's output (e.g. WebOrganizer) can be joined in as a field. Real corpus lines have only `id` and
  `text`.
- **Output:**
  - `kwstats.json` plus per-shard parts, merged in seconds;
  - a CSV of all terms;
  - shards like `run` (`--shard`), so 5 machines can split a big corpus.
  - Expected time on 5 machines for 4 TB of parquet: about 30–60 min.
- **The forecast:** the paragraphs with a hit × the policy's pairs per paragraph → an estimate of the labelling run's
  model pairs and time, at a given speed per GPU.

**A viewer page** `/label/kwstats/?run=…`, linked from `/label/`:
1. **Rank-frequency chart** of all terms (rank × hits, log scale), with bars and names for the top 50 and bottom 50.
   Hover shows any term; colour by kind / list.
2. **The term table:** paged, searchable, sortable by every count, with a CSV download.
3. **Heatmap** of terms × units (topic / folder), with zero cells marked. The top N terms or a filtered selection.
4. **Never-hit terms:** overall and per unit, filterable, with a CSV.
5. **Histograms:** hits per line, distinct terms per line.
6. **Co-occurring pairs:** the top ones, and per term.

Each chart can be downloaded as PNG / SVG.

**A written report** on the page, generated from the numbers:
- coverage;
- the dominant terms and their share;
- dead terms;
- terms that are mostly incidental;
- uneven spread over topics;
- duplicates and overlaps;
- the GPU-time forecast;
- suggestions: which terms to drop, fix or add.

The same report is saved as `report.md` in the output folder.

**A start form:** on `/label/`, start a kwstats scan for a corpus folder (like the Start-a-run form).

**Tests:**
- counts on a small corpus (hits, lines, paragraphs, sentences, incidental, per unit, never-hit);
- shard merge = single run;
- 10,000 terms: speed and the size of the output;
- the API and the rendered page.

**Docs:** `cmds\labeling\keyword_stats.md` (what each number means, how to read the charts, the forecast), and a
section in `cmds\viewer\labels_pages.md`.

**Done when:** for `dataset\corpus_benchmark`, the page shows the chart, the table, the heatmap by side / topic, the
never-hit terms and the report, and the numbers match a hand count on a few terms.

## Offered today but not in this plan

These were offered on 2026-11-25 but not asked for. Add them here only if the user says so.

- **Schema sources:** one list in `nli_simple.py` that the editor reads from the backend, plus new sources
  (`decided_label`, `action`, `scores`, `gate_score`, `flags`, `non_english`, `exception_blocked`, `paragraph_count`,
  `removed_paragraphs`, `keywords`). About 45 min.
- **Schema editor:** show the keys the policy can produce, and mark vocabulary entries that never match. About 15 min.
- **`--shard` for `export` and `redecide`**, so they run as several copies on big runs. About 20 min.
- **Start-a-run form:** boxes for `--decision-unit` and `--output-mode` / `--schema`.
- **Speed:**
  - `flash_attention_2` for ModernBERT;
  - `--compile` and `--max-batch-tokens` in nli_label;
  - tokenizing in the background;
  - reading parquet text straight from Arrow.

  About 1–1½ hours, then a sizing run on the H200.
- **A data-quality report for cut documents:** quality before and after, coherence at the cuts, topic mix. A plan
  would come first.

## Rules while working alone

The same as `11_24_big_plan.md`:
- Do the work task by task, with backend tests, a frontend build and a rendered-page check for each.
- Don't change the meaning of the Russia-side policy or the test sets' expectations.
- Commit or push only if the user said so. Otherwise leave the work uncommitted and give a short report at the end.

# 11_25_big_plan: simple-run expected results, keyword statistics, translation

Planned 2026-11-25, to be built when the user says so ("do 11_25_big_plan", "I'm leaving", …). The work is in the
viewer's Labelling area (`/label/…`), for the Russia-side policy (`policy\russia_llm_policy_v2.json`). The background
is the conversation of 2026-11-25 (`cmds\conversation\2026-11-25.md`, "why is Expected vs result missing on the simple
run's page"), and "keyword and marker statistics over a corpus".

The estimate is about 17–19 hours:
- task 1: about 30 min;
- task 2: about 3–3½ h;
- task 3 (translation): about 3–3½ h;
- task 4 (expected rules): about 1–1½ h;
- task 5 (Back returns to where you were): about 1–1½ h;
- task 6 (copy button on every text): about 45 min – 1 h;
- task 7 (multiple gates, OR): about 2–2½ h;
- task 8 (Experiment page, saved only on confirm): about 3½–4 h. Do it after task 7;
- task 9 (beginner's guide to Docker, docs only): about 45 min – 1 h.

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

### 3. Translate texts in the viewer: Qwen endpoint first, Hunyuan-MT-7B when it fails (about 3–3½ h)

**Why.** Sometimes a source text must be read in another language, at first **Chinese or Russian**. Decided on
2026-11-25:
- **First:** the user's **Qwen 35B** service (the user's words: Qwen 3.5 / 3.6 35B), an **OpenAI-compatible**
  endpoint.
- **When it fails:** **Hunyuan-MT-7B** (https://huggingface.co/tencent/Hunyuan-MT-7B), run locally (RTX 5090, or the
  offline H200).
- Translation is **for reading only**: labels and decisions always come from the original text.

**What.**

**Settings in `viewer_config.json`** (new `"translate"` block):

    "translate": {
      "targets": ["zh", "ru"],
      "providers": [
        {"name": "qwen", "kind": "openai", "base_url": "http://<host>:<port>/v1", "model": "<served model name>",
         "api_key_env": "QWEN_API_KEY", "timeout": 60, "no_think": true},
        {"name": "hunyuan", "kind": "openai", "base_url": "http://127.0.0.1:8001/v1", "model": "Hunyuan-MT-7B",
         "prompt": "hunyuan", "timeout": 120}
      ]
    }

- The **key** is read from the named environment variable: never stored in the config, never logged.
- The **providers are tried in order.** The next one is used when a provider fails: no connection, timeout, an HTTP
  error, an empty answer.
- The page shows which provider answered.

**Backend** (`POST /api/translate {texts | paragraphs, target}`):
- Calls the OpenAI-compatible `/v1/chat/completions`.
- **Qwen prompt:** "Translate to {language}. Keep names, numbers, line breaks and paragraph breaks. Output only the
  translation." Thinking is off (`enable_thinking: false` / `/no_think`). Any `<think>` block left in the answer is
  removed.
- **Hunyuan-MT prompt:** its own template from the model card. For Chinese: "把下面的文本翻译成中文，不要额外解释。" + text.
  For other targets: "Translate the following segment into Russian, without additional explanation." + text. Use the
  card's recommended sampling settings.
- **Long texts** are translated paragraph by paragraph (also for alignment), within the model's context.
- **A cache** in `.viewer_cache/translate/`, keyed by (text, target, provider, model), so a second view is instant.
- **Errors:** both providers failing → a clear message (which one failed and why), never a crash.

**Hunyuan-MT-7B locally** (the fallback):
- **Download** to `models/Hunyuan-MT-7B` (about 16 GB in bf16). Add it to the pkgs / offline notes for the H200.
- **Serve it OpenAI-compatible:**
  - with **vLLM** on Linux / WSL (`vllm serve models/Hunyuan-MT-7B --port 8001 …`);
  - on Windows without WSL, through the model service (`nli_playground.py`) with transformers, as a second way
    (`"kind": "local"`).

  The docs give the commands for both.
- **Licence:** read Tencent's licence file first and note the result in the docs. If it does not fit,
  Seed-X-PPO-7B (OpenMDW) uses the same setup.

**Frontend:**
- **A Translate button (中文 / Русский) on every text the viewer shows in the Labelling area** (the user asked for
  this on 2026-11-25). One shared component, so a new page gets it too:
  - the document page (per paragraph, with the remove / review / keep colours kept);
  - the run page's ▸ line text;
  - the simple run's line view;
  - the Try page (the text, and each case text);
  - the compare page's changed lines;
  - the documents test set editor and the case editor (the texts being edited);
  - the corpus page (each line).
- **The translation shows** below or side by side, with "translated by qwen / hunyuan (fallback)" and a "show
  original" switch.
- **Settings page or panel:** the providers, a test button per provider ("translate a sample"), and which one is
  reachable now.

**Tests:**
- a fake OpenAI-compatible server: the first provider fails → the fallback answers;
- both fail → a clear error;
- the cache;
- no key in logs or responses;
- `<think>` stripping;
- paragraph alignment;
- the rendered pages.

**Docs:** `cmds\viewer\translate.md`:
- the settings;
- serving Hunyuan-MT-7B (vLLM / model service), on this PC and on the H200;
- the licence check.

**Done when:**
- with the Qwen endpoint up, a benchmark line translates to Chinese and Russian on the document page;
- with it stopped, the same works through Hunyuan-MT-7B, and the page says so.

**Test endpoint on this PC** (given by the user on 2026-11-25): `http://192.168.170.108:8000/v1`.

Checked that day:
- `GET /v1/models` answers; the server is vLLM.
- It serves **`qwen3-4b`** (`./Qwen3-4B`), not a 35B model. Context 32,768 tokens.
- **No API key** was needed.
- A test chat completion took 0.5 s.
- `chat_template_kwargs.enable_thinking: false` works (0 reasoning tokens).

**What the test found:** asked for **Chinese**, it answered in **Russian**, with mistakes ("щи" → "Щич", cabbage soup →
"салат"). So:
- **Put the target language in the user message too**, not only in the system message: "Translate the following text
  into Chinese (简体中文): …".
- **Check the answer's language** by script: Chinese → mostly CJK characters; Russian → mostly Cyrillic. A wrong
  language counts as a **failure**: retry once with a stricter prompt, then use the next provider (Hunyuan-MT-7B).
- **The model name is a setting.** The test uses `qwen3-4b`; the 35B one replaces it when it is served (`GET /v1/models`
  shows the name). The settings panel's test button lists the served models.
- A small model is expected to be weaker. Compare the quality on ~20 benchmark texts once the 35B model is up.

**Open questions:**
- The 35B endpoint's address, model name and key (if any).
- Whether the H200 machines can reach it.

### 4. Configurable "same as expected" rules for Expected vs result (about 1–1½ h)

**Why.** On `/label/run/?run=out_label_benchmark_detail` the panel compares each line's result with the corpus'
`expected_action`. What counts as a match is **hard-coded** today (`viewer\backend\nli_viewer\labels.py`, `_same()`):
`pass`, `untouched` and `none` are the same; everything else must match exactly, or be listed in the line's
`acceptable`.
- **For a quick review** the user wants `keep`, `untouched` and `pass` to count as the same: all three leave the text
  in.
- **The rule must live in a file**, edited through the viewer, not in code.
- **The same file can settle values nli_label never gives:** the benchmark's 14 lines with `decision: "flag"`.

**What.**

**A rules file** `labels\expected_rules.json`, next to the test sets:

    {
      "about": "How Expected vs result decides that a result matches the expected action.",
      "default": "strict",
      "profiles": {
        "strict": {"same": [["pass", "untouched", "none"]]},
        "quick":  {"same": [["keep", "pass", "untouched", "none"]], "note": "text kept = match"}
      },
      "aliases": {"flag": "remove"}
    }

- **`same`:** groups of actions that count as equal, in that profile.
- **`aliases`:** an expected value is replaced before comparing (e.g. `flag` → `remove`; leave it out to keep `flag`
  as a mismatch).
- **Profiles:** as many as wanted. `default` is used when the page does not choose one.
- **Checks:** the actions known to nli_label (`remove`, `review`, `keep`, `pass`, `untouched`, `none`; document actions
  `kept`, `edited`, `removed`, `error`), with no action in two groups of one profile. A bad file is refused with a
  message; a missing file means today's built-in `strict` rule.

**Backend:**
- `_same()` and the verdict read the rules (cached, reloaded when the file changes) and take a `profile`.
- Applies to:
  - every Expected vs result: the run page panel and per-row verdicts, `expect=wrong|right` filter;
  - test documents' paragraphs;
  - simple runs (task 1);
  - the compare page, where expected results are shown.
- API:
  - `GET /api/labels/expected-rules` (the file, its check);
  - `POST …/check`, `POST …/save` (backup in `labels\.backup\`, refused when the file changed since it was loaded);
  - a `profile=` parameter on the expected endpoints.

**Frontend:**
- **On the Expected vs result panel:** a profile switch (strict / quick / …). The counts and the wrong lines change
  at once. The verdict says which rule matched ("keep ≈ pass (quick)").
- **An editor page** `/label/expected-rules/`, linked from the panel and from `/label/`:
  - the profiles (add, rename, delete);
  - per profile the "same" groups (add an action to a group, new group);
  - the aliases table;
  - the default profile;
  - a JSON tab;
  - checked while typing, saved with a backup.
- **A short preview:** for a chosen run, how many lines match under each profile.

**Tests:**
- strict = today's results (no change unless a profile is chosen);
- quick turns keep / pass / untouched into matches;
- the `flag` → `remove` alias;
- a bad file (unknown action, an action in two groups) is refused;
- the editor's check / save / conflict;
- the rendered panel with the switch.

**Docs:** `cmds\viewer\labels_pages.md` (Expected vs result: profiles, the file, the editor).

**Done when:** on `out_label_benchmark_detail` the panel shows strict and quick counts with one click, and a change
saved in the editor (e.g. the `flag` alias) shows in the counts without a restart.

### 5. Back button returns to where you were (about 1–1½ h)

**Why.**
- **What happens today** (reported 2026-11-25): on `/label/run/?run=…`, open a line's text (▸) → "open the document
  page" → browser **Back**. The run page comes back, but at the top, with the first file, no filters, the first page
  of rows and nothing opened.
- **Why** (`LabelRunView.tsx`): only `run` and the first `file` are in the URL. The file chosen later, the filters
  (action, label, paragraph action, expected), the page offset and the opened ▸ lines are only in React state, which
  is lost on navigation.
- **The scroll is lost too:** the rows load after the browser restored the scroll position, so there is nothing to
  scroll to yet.

**What.**
- **The run page's view state in the URL** (`router.replace`, no new history entry per change): `file`, `action`,
  `label`, `para_action`, `expect`, `offset`, and the opened lines (`open=12,15`). A link to that URL shows exactly
  the same view. It is shareable too.
- **The scroll restored after the rows load:**
  - remember the scroll position per URL (sessionStorage) when leaving the page;
  - restore it once the rows are rendered;
  - if that fails, scroll to the row of the document just visited and mark it briefly (`?from_line=`, or an `#line-N`
    anchor added when opening the document page).
- **The same for the other list pages** of the Labelling area:
  - the simple run page (file, decision / reason / keyword filters, offset, the opened line);
  - the compare page (change filter, offset);
  - the Expected vs result panel's choice (wrong / right, and the profile from task 4);
  - the corpus page (file, position).
- **One shared hook** (`useUrlState` + `useRestoreScroll`), so new pages get it too.
- **The document page's "back to the run" link** (breadcrumb) also returns to the same view, not the bare run.

**Tests:**
- rendered pages: open with a full state URL → the same filters, offset and opened lines are shown;
- a back navigation (headless browser) lands on the same row;
- the URL stays short (lists of opened lines capped);
- old links without the new parameters still work.

**Docs:** a line in `cmds\viewer\labels_pages.md`: "the URL keeps the view; Back returns to it".

**Done when:** run page → filter + page 2 + open a line → document page → Back = the same filter, page, open line
and scroll position. The same on the simple run page.

### 6. Copy button on every text shown (about 45 min – 1 h)

**Why.** The user wants to copy a line's text with one click wherever the viewer shows it (asked 2026-11-25). Today
only the Try page has a copy button ("Copy for analysis").

**What.**
- **One shared component** for a shown text. It is the same place as task 3's Translate button, so both sit together:
  `[Copy ▾] [中文] [Русский]`.
- **Copy menu:**
  - **text:** the line's text as it is;
  - **paragraph:** on the document page, the selected paragraph;
  - **with source:** the text plus `file · line · id`, for pasting into notes or a question;
  - **row (JSON):** the labels or simple-mode row of that line;
  - **translation:** when one is shown.
- **Where:**
  - the run page's ▸ line text;
  - the document page (the whole text, each paragraph);
  - the simple run's line view (the text, the row, the evidence);
  - the corpus page (each line);
  - the Try page (each case text);
  - the compare page's changed lines;
  - the documents and case editors.
- **Works on every address:**
  - `navigator.clipboard` where the browser allows it (127.0.0.1 / localhost);
  - a fallback (select + copy command) when the viewer is opened from another computer by a plain `http://` address,
    where the clipboard API is blocked.
- **Feedback:** "Copied (1,234 characters)" for a moment. A very long text is still copied whole.

**Tests:**
- rendered pages show the button on each place;
- a unit test of the "with source" format;
- the fallback path (no clipboard API).

**Docs:** a line in `cmds\viewer\labels_pages.md`.

**Done when:** on the run page, document page, simple run page and corpus page, one click copies the line's text, and
the "with source" copy carries file, line and id.

### 7. Multiple gates, OR-combined (about 2–2½ h)

**Why.** One gate label is not enough for some cases; the user needs a second one now and wants the code to allow any
number (asked 2026-11-25). Several gates combine with **OR**: the paragraph passes the gate when **any** gate label
reaches its own threshold, or a marker / a narrative opens it, as today.

**Today** (`nli_label.py`): the policy check refuses more than one level-0 label ("only one level-0 (gate) label is
allowed"). `Policy.gate` is a single label, used in:
- `resolve()` (pass / gate_negative);
- `action_from_labels()` (hand labels);
- `Labeller.process()` (gate scoring, the narrative check of gate-negative paragraphs);
- `decision_scores()` (narrative-keyword paragraphs ignore the gate);
- the flow output (`opened_by`).

The viewer's flow views (document page `Flow`, Try `TryTrace`) and the flow diagram show one gate.

**What.**
- **Policy:**
  - any number of level-0 labels, each with its own threshold and hypothesis;
  - `Policy.gates` (a list, in file order); `Policy.gate` kept as the first one, for old code paths;
  - the check allows 0..N gates.
- **Gate rule:** open = marker, or any gate label ≥ its threshold, or (`narrative_opens_gate`) a narrative. Closed
  → `pass`, reason `gate_negative`.
- **Scoring, in order, to save pairs:** gate 1 on every candidate paragraph; gate 2 only on paragraphs still closed
  after gate 1 (no marker); and so on. Gate 2 costs little: it runs only where gate 1 said no.
  - The paragraph records which gate opened it (`opened_by_gate`).
  - `--all-labels` still scores every gate everywhere.
- **`run_if`:** any gate key works, as today. A new token **`@gate`** means "any gate open", so `run_if` does not have
  to list every gate. The Russia-side policy can switch to `["@gate", "@marker"]`, with the same meaning as today.
- **Everywhere the single gate is used:**
  - `resolve()`, `action_from_labels()` (unknown only if every gate label is unknown), `decision_scores()`,
    `levels_used()`;
  - the narrative check of gate-negative paragraphs (closed = no gate open);
  - `redecide` (stored scores of every gate; a gate added later counts as missing);
  - `eval` / `sample` (per gate label, as for any label);
  - the simple-mode `gate_negative` reason.
- **Viewer:**
  - **policy editor:** add a second (third …) gate at level 0, with `@gate` in the Run-if editor;
  - **document page `Flow` and Try `TryTrace`:** every gate with its score bar, "opened by gate X" or "all gates
    below threshold";
  - **flow diagram** (`cmds\labeling\russia_policy_flow.html`): gate step with N gates, OR.
- **Backward compatible:** a policy with one gate gives exactly today's results. The test sets, the benchmark and
  `out_label_ru_v2` redecided must be unchanged.

**Tests:**
- 0 / 1 / 2 / 3 gates;
- OR: gate 1 no + gate 2 yes → open;
- the second gate scored only on closed paragraphs (pair count);
- `@gate` in `run_if`;
- marker and narrative still open it;
- `redecide` with a gate added (missing scores reported);
- one-gate results identical to today (a whole test-set run);
- the viewer flow with 2 gates (rendered page).

**Docs:**
- `cmds\labeling\russia_llm.md` (how to add a gate);
- `cmds\labeling\output_modes.md` (`gate_negative` = all gates below);
- the flow diagram.

**Done when:**
- a policy with 2 gates runs: a paragraph that only gate 2 accepts is checked by L1 / L2;
- the viewer shows which gate opened it;
- a one-gate policy gives the same results as before.

### 8. Experiment page: a full-settings sandbox, saved only on confirm (about 3½–4 h)

**Why.**
- "Try this paragraph" (document page) and "Try" (run page) open `/label/try/`: the case-testing page built around
  the case sets (`labels/*.json`).
- The user wants a **separate page** where every setting of the policy and the run can be changed for an experiment:
  - add or remove hypotheses (labels, gates), change thresholds, levels, decisions, `run_if`, softeners, exceptions,
    `no_subject`, `conflict`;
  - the models, the judge band, the unit.
- **Nothing is saved unless the user explicitly confirms.**
- Doing this on the Try page would mix with the case-set testing (asked 2026-11-25).

**What.**
- **New page `/label/lab/`** ("Experiment"):
  - **Opened from:** "Experiment with this paragraph / line" on the document page, the run page rows, the simple run's
    line view and the corpus page (next to the existing Try buttons, which stay as they are).
  - **The text:** the line or paragraph that opened it. More lines can be added: paste, or pick from a run (e.g. its
    wrong lines from Expected vs result).
  - **The base:** the policy the run recorded (`policy_data`), else the policy file.
- **The draft settings** (left side), a working copy of the base:
  - **labels and gates:** add, remove, edit level, decision, threshold, hypothesis, softens, protected;
  - `run_if` (with `@gate`, task 7), exceptions, markers, `no_subject`, `conflict`, `narrative_opens_gate`;
  - **run settings:** fast model, judge on / off, uncertain band, `--decision-unit`, `--review-as`, the non-English
    setting.
  - Checked while typing with nli_label.py's rules, as in the policy editor.
- **Results** (right side), for each text:
  - the result with the **draft** and with the **base**, side by side through the model service: paragraph actions,
    scores, the flow trace (`TryTrace`);
  - **what changed** (keep → review …) highlighted;
  - a new or reworded hypothesis is scored fresh; unchanged ones can reuse cached scores.
- **Diff:** the draft against the base, as a readable list ("added label X, threshold of Y 0.8 → 0.7, removed Z").
- **The draft stays only in this browser** (it survives a reload; "Discard draft" starts again).
- **Saving only on explicit confirm:**
  - "Save as new policy…" (a name; never overwrites);
  - or "Replace policy/<file>…" with a confirm dialog that shows the diff and asks to type the file name. Backup in
    `policy\.backup\`, refused if the file changed since.
  - Never saved automatically, never on leaving the page.
- **On the whole run** (optional, from the page): "Apply the draft to this run" → `redecide` into a new folder (stored
  scores; new hypotheses counted as missing, with the note) and then the compare page.
- **Different from `/label/try/`:** the Try page keeps the case sets and their expected actions. The Experiment page
  has no case sets; it works on real lines and the draft policy.

**Tests:**
- API: the draft check;
- run on texts with draft and base (fake model service);
- save-as-new and replace-with-confirm (backup, conflict 409, no save without the confirm flag);
- rendered page: opened from a document page with its paragraph, the draft editor, the side-by-side results, the
  diff.

**Docs:** `cmds\viewer\labels_pages.md` (the Experiment page: what it is for, how saving works, how it differs from
Try).

**Order:** after task 7, so the draft can add gates.

**Done when:**
- from a document page, "Experiment" opens the paragraph;
- a new hypothesis is added and a threshold changed;
- the result with draft and base shows side by side with the changes marked;
- nothing reaches `policy\` until "Save as new" or a confirmed replace.

### 9. A beginner's guide to Docker for this project, docs only (about 45 min – 1 h)

**Why.** The user is new to Docker and wants to understand it first (asked 2026-11-25). **Nothing is implemented:** no
Dockerfile, no image, no change to how the project runs. Background in `cmds\conversation\2026-11-25.md` ("do we need
Docker?"):
- not needed for nli_label now;
- recommended later for serving a translation model with vLLM;
- maybe later for identical setups on the 5 offline H200 machines.

**What.** One page, `cmds\setup\docker_beginner.md`, written for someone who has never used Docker:
1. **The ideas, in plain words:** image, container, tag / version, volume (a folder shared with the container), port,
   registry; how Docker differs from a Python venv; what the NVIDIA Container Toolkit does (GPUs inside a container).
   One small picture: machine → Docker → container → GPU, models folder, port.
2. **Which parts of this project could use it:** the table from the conversation (nli_label, the translation server,
   the viewer, the model service, the Windows PC), with the reason for each.
3. **Is it allowed on the target machines?** A checklist with the exact commands and what their output means:
   - Docker installed;
   - the user in the `docker` group;
   - the NVIDIA Container Toolkit (`docker run --gpus all … nvidia-smi`);
   - a shared cluster → Apptainer instead, with the equivalent commands.
4. **Offline:**
   - pull on a machine with internet → `docker save` to a .tar → copy (with the SHA-256) → `docker load`;
   - the image sizes to expect;
   - where the disk space goes, and how to clean it: `docker system df`, `docker system prune`, and on Windows the WSL
     disk file and how to shrink it (the 70 GB `docker_data.vhdx` found on 2026-11-25).
5. **A worked example, explained line by line:** serving Hunyuan-MT-7B (or Qwen) with the official
   `vllm/vllm-openai` image:
   - `docker run --gpus all -p 8001:8000 -v …:/models … --model /models/Hunyuan-MT-7B`;
   - checking it with `curl http://<machine>:8001/v1/models` and one chat completion;
   - stopping, restarting and logs (`docker ps`, `docker logs`, `docker stop`);
   - how the viewer's translation setting (task 3) points to it.
6. **On the Windows PC (RTX 5090):** Docker Desktop + WSL2, GPU support, the disk-file growth, when not to use it.
7. **Common problems:** "could not select device driver" (no toolkit), port in use, permission denied on the socket,
   out of disk, a model folder not visible in the container (volume path).
8. **Glossary and links:** the official Docker, NVIDIA Container Toolkit, vLLM and Apptainer docs.

**Rules:**
- The commands are examples to read, marked "not run here".
- The versions are written as `<version>`, with how to choose one.
- No passwords or keys in the page.

**Done when:** the page explains the ideas, the checks and the offline steps well enough to decide whether to use
Docker on the H200 machines. The worked vLLM example can be followed step by step, with no step needing outside
knowledge.

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

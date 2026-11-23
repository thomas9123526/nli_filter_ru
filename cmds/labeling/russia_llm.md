# The Russia-side project: labelling data for Russia's LLM

**In one sentence:** this project labels training data for Russia's LLM paragraph by paragraph. It finds
Russia- and Ukraine-related content, removes hate and calls for violence against either people, sends opinions (in
both directions), history and known false claims to human review, keeps facts whoever they hurt, and never deletes
the original data.

It uses the same tool (`nli_label.py`), viewer and workflow as A's project (`README.md` in this folder). Only the
policy, the keyword lists and the cases are new.

## The agreed principles (2026-11-23)

| Content | Action | Why |
|---|---|---|
| Hate or dehumanising language against Russians **or** Ukrainians ("orcs", "subhuman", collective guilt) | **remove** | Hate, whoever the target is |
| Calls for violence against either people | **remove** | |
| Opinions or judgements about Russia **or** Ukraine, praise **and** criticism | **review** | A human decides; the same rule in both directions |
| History (e.g. Mongol rule, Kievan Rus, Peter the Great) | **review** | A review topic; more can be added |
| Known false claims (e.g. "Ukraine has joined NATO") | **review** | The models cannot check truth: each known claim is its own label |
| "our country" without naming it | **review** (exception, top priority) | The model could learn a national voice nobody can identify |
| Facts (war, geography, demography, sport, travel) | **keep** | Facts stay, whoever they hurt |

What this project deliberately does **not** do: remove or review text *because* it is unfavourable to Russia or
favourable to Ukraine. Opinions go to review in both directions ("Russia's vaccination is world-class" goes to
review just like "Ukraine's economy is developed"). Reporting on the war, including what Russia did, is kept.

## Files

| File | What |
|---|---|
| `policy\russia_llm_policy_v2.json` | **The policy to use** (v1 = the first draft, kept for comparison) |
| `keywords\ukraine.txt` | Ukraine keywords (English, Russian, Ukrainian); used with `keywords\russia_v3.txt` |
| `labels\russia_llm_cases_v1.json` | 43 test texts in 23 cases: your 17 examples + exceptions, hate, history, opinions, false claims, facts |
| `tools\build_russia_llm_cases.py` | Writes the cases file (edit the texts there, then rerun) |
| `tools\compare_cases.py` | A run on a cases corpus vs the expected actions |
| `dataset\test_corpus_cases_ru\` | The cases as a corpus (not in git; rebuild with the command below) |

## Commands

```powershell
# the cases as a corpus, label them, compare with what is expected
python tools\build_russia_llm_cases.py
python tools\build_cases_corpus.py --cases labels\russia_llm_cases_v1.json --out dataset/test_corpus_cases_ru
python nli_label.py run dataset/test_corpus_cases_ru --policy policy\russia_llm_policy_v2.json --output-dir out_label_ru_v2
python tools\compare_cases.py out_label_ru_v2 --corpus dataset/test_corpus_cases_ru          # --details: every text

# a real corpus (local folder or a server address, as for A's project)
python nli_label.py run <corpus> --policy policy\russia_llm_policy_v2.json --output-dir out_label_ru_xxx --write-clean

# the human-review queue of a run (opinions, history, exceptions, false claims)
python nli_label.py review out_label_ru_xxx --out labels\review_ru_xxx.jsonl
```

In the viewer: **Labelling runs** shows the runs; on the **Try** page (`/labeltry/`), pick
`labels/russia_llm_cases_v1.json` in the **cases** list. It shows your first decision next to the expected one where
they differ.

## The policy (v2)

| Level | Label | Decision | Hypothesis |
|---|---|---|---|
| 0 | `involves_russia_ukraine` | gate 0.3 | "This text mentions Russia, Ukraine, Russians or Ukrainians." |
| 1 | `history` | review | "…describes historical events from centuries ago in Russia, Ukraine or the Soviet Union." |
| 1 | `politics`, `war`, `economy`, `culture` | keep | for the composition report only |
| 2 | `opinion_about_russia` | review 0.7 | "…expresses the writer's opinion about Russia or something Russian." |
| 2 | `opinion_about_ukraine` | review 0.7 | "…expresses the writer's opinion about Ukraine or something Ukrainian." |
| 2 | `hostility_russians`, `hostility_ukrainians` | remove, **protected** | "…insults or dehumanizes Russians or Russian-speaking people." / "…Ukrainians." |
| 2 | `violence_call` | remove, **protected** | "…calls for violence against Russians or Ukrainians." |
| 2 | `claim_ukraine_in_nato` | review | "…states that Ukraine is a member of NATO." |
| 2 | `reports_or_debunks` | keep 0.6, guard | softens hostility and violence: news that *quotes* a slur goes to review, not removal |

Other settings: place names are rewritten to their Russian form (next section);
`"narrative_opens_gate": true` (hate that never names a country still reaches the hate labels); markers are common
slurs on both sides ("orcs", "рашисты", "хохлы", "укропы" …), so a paragraph with one always gets the full check.

### Place names: Ukrainian romanisation → Russian form

In the clean copy, `policy\place_names_ru.csv` rewrites Kyiv → Kiev, Kharkiv → Kharkov, Odesa → Odessa, Lviv → Lvov,
Zaporizhzhia → Zaporozhye, Dnipro → Dnepr … (41 names, variants included). The policy names its own table:

```json
"rewrite_place_names": true,
"place_names_file": "policy/place_names_ru.csv",
"place_name_exceptions_file": "policy/place_name_exceptions_ru.txt"
```

- **Spelling only.** Four cities were renamed in 2016 (Bakhmut, Pokrovsk, Kropyvnytskyi, Lyman). Their Russian forms
  in the table (Artemovsk, Krasnoarmeysk, Kirovograd, Krasny Liman) are the old Soviet names, not spellings: rewriting
  them changes the name, and the model would use names that are no longer official. They are in the table but
  switched off (`# ` in front of the line). Remove the `# ` to switch one on; that is a decision for the compliance
  team.
- **Exceptions** (`policy\place_name_exceptions_ru.txt`): official names keep their spelling: *Kyiv Independent*,
  *Kyiv Post*, *Kyiv-Mohyla*, *Kyiv School of Economics*, "… National University", *Dynamo Kyiv*, *Shakhtar
  Donetsk*, and Odesa, Texas. Links, e-mail addresses and code are never touched.
- Case is kept: "KYIV" → "KIEV". Whole words only. Every change is logged in `<name>.rewrites.jsonl`.
- Try it without a run: `python nli_names.py --table policy\place_names_ru.csv --exceptions policy\place_name_exceptions_ru.txt --text "Missiles hit Kyiv and Kharkiv."`
- A's policy is unchanged: it still rewrites the other way (`policy\place_names.csv`, Kiev → Kyiv). v1 of the
  Russia-side policy does not rewrite (it is the baseline).

### Exceptions (checked first)

```json
"exceptions": [
  {"key": "ambiguous_our_country", "decision": "review", "priority": 100, "skip_quoted": true, "scope": "keyword",
   "match": {"phrases": ["our country", "наша страна", "нашей страной", "наша країна", "..."]}}
]
```

- **Phrases** are matched like keywords (case-insensitive, whole words). A **hypothesis** can be used instead for
  meaning that is worded many ways: `"match": {"hypothesis": "This text speaks for an unnamed country.",
  "threshold": 0.8}`.
- **Priority**: if several exceptions match, the highest number wins (same number: the first in the file).
- **`skip_quoted`**: a phrase inside quotation marks does not count. `Zelensky said: "Our country will never give
  up"` names the speaker, so it is not ambiguous.
- **`scope`**: `keyword` (default) = every Russia/Ukraine paragraph, also when the gate says "incidental"; `gate` =
  only paragraphs past the gate. A text without any Russia/Ukraine keyword is never touched ("Our country has the
  best beaches" stays as it is).
- **Protected labels** (`"protected": true`, the hate and violence labels): an exception can make a decision
  stricter, but never lowers their removal. If it tries, the paragraph stays removed and shows
  `exception_blocked` in `labels.jsonl`.
- Switching "our country" from review to remove later is one word in the policy (`"decision": "remove"`). Do it
  after the review queue shows that nearly every hit really is ambiguous.

### The corpus' topic field (optional)

Some corpora already have a topic per document (e.g. WebOrganizer-style "History", "Politics", "Entertainment").
The policy maps those values to level-1 subjects:

```json
"topic_field": null,
"topic_mode": "hint",
"topic_map": {"History": "history", "Politics": "politics", "Entertainment": "culture", "Literature": "culture"}
```

```powershell
python nli_label.py run <corpus> --policy policy\russia_llm_policy_v2.json --topic-field topic --output-dir out_x
python nli_label.py run <corpus> ... --topic-field metadata.topic      # nested field: a dot path
python nli_label.py run <corpus> ... --topic-field topic --topic-mode off   # record and compare only
```

| Mode | What it does |
|---|---|
| `hint` (default) | The field says History → `history` is yes without the model; every other subject is scored by the model |
| `trust` | Every subject in `topic_map` is decided by the field only (yes or no); subjects **not** in `topic_map` are always scored by the model |
| `off` | The field is recorded and compared with the model, but not used |

- **Robust per line**: a missing, empty or unknown topic (not in `topic_map`) means the models decide every subject
  for that line, exactly as without a topic field. A list of topics is fine (`["History", "Politics"]`).
- **Visible**: `labels.jsonl` has `"topic"` per line and `"from_field"` per paragraph (the subjects the field
  answered); the viewer marks those scores "topic field".
- **Measure before you trust it**: run with `--topic-mode off`; the report ends with a table "topic field vs
  model" per subject (agree / field only / model only). `eval` on hand labels also compares the field with your
  labels when the items carry a topic (`sample` keeps it). Switch to `trust` only for subjects where the field
  agrees well.
- The topic is per **document**, the labels are per **paragraph**: a travel article can have one history
  paragraph. `trust` would miss it; this is why `hint` is the default.
- Adding a subject (e.g. `religion`, `language`) is one block in `"labels"`, in every mode. Mapping it in
  `topic_map` is optional.

## Results on the 43 case texts (2026-11-23, CPU)

| Run | OK | Wrongly removed | Missed hate | Facts kept |
|---|---|---|---|---|
| v1, ModernBERT | 40 / 43 (93 %) | 0 | 0 | 3 / 5 |
| **v2, ModernBERT** | 39 / 43 (91 %) | 0 | 0 | **5 / 5** |
| v2 + DeBERTa judge | 39 / 43 (91 %) | 0 | 0 | 5 / 5 |

v1 scores higher, but for the wrong reason. Its `history` wording ("the history of Russia or Ukraine") also fired
on 2022 war facts (sent to review, against "keep facts") and on many opinions. Two opinions were sent to review
only because `history` fired on them by accident. v2's wording ("historical events from centuries ago…") was chosen
by testing five wordings against every case text: it had no false alarm.

Per group (v2): exceptions 6/6, hate 5/5, opinions 4/4, false claims 2/2, facts 5/5, history 3/4, your examples
14/17.

**The 4 texts v2 gets wrong (all "should be review, got keep"):**

| Text | Why |
|---|---|
| "In 1991 Ukraine declared independence from the Soviet Union." | Recent history: not "centuries ago"; even "This text is about the Soviet Union" scores 0.02 on it |
| "Swan Lake … does not suit the present era." | An opinion about a Russian *work*: every opinion wording tested scored it ≤ 0.52 |
| "Russia's vaccination is at a world-class level of development." | An evaluation worded like a fact |
| "Ukraine's economy is developed." | The same |

Evaluations worded like facts are the main open problem. Six more wordings ("…says that something in Russia is good
or bad", "…rates how good or advanced…", "…evaluates the quality of…") all did worse. The next things to try are
the DeBERTa or bge-m3 model as the *fast* model for the opinion labels, and real-corpus hand labels to see how
common such sentences are.

## Multi-paragraph test documents

The case texts are one or two sentences each. To test paragraph-level decisions (one paragraph removed, the others
kept), `tools\build_russia_llm_docs.py` builds **13 documents with 36 paragraphs** from the agreed sample sentences:
each sentence starts a paragraph of 2–3 sentences of the same kind, and paragraphs of different kinds are mixed (an
opinion next to a fact, a hate paragraph inside a war report, a weather paragraph without any keyword, a document in
Russian, a document that is only hate). Every paragraph is at least 200 characters, so it is labelled on its own
(shorter pieces are joined to the next one); the builder checks the split.

Like `dataset\test_corpus_cases_ru`, the corpus has one folder per kind of document and one `.jsonl.zst` file per
document:

| Folder | Files (one document each) |
|---|---|
| `opinions_and_facts` | `history_and_ballet`, `rights_and_elections`, `ukraine_economy`, `life_in_ukraine` |
| `facts_and_false_claims` | `sport_and_geography`, `vaccines_and_nato` |
| `exceptions` | `diplomacy`, `russian_language` |
| `hate_in_context` | `war_report`, `kyiv_and_hate`, `only_hate` |
| `no_keyword` | `no_keyword`, `garden_recipe` |

```powershell
py -3.12 tools\build_russia_llm_docs.py          # labels\russia_llm_docs_v1.json + dataset\test_corpus_docs_ru\<folder>\<doc>.jsonl.zst
py -3.12 nli_label.py run dataset\test_corpus_docs_ru --policy policy\russia_llm_policy_v2.json --output-dir dataset\out_label_docs_ru_judge --write-clean
py -3.12 tools\compare_docs.py dataset\out_label_docs_ru_judge --corpus dataset\test_corpus_docs_ru   # --details: every paragraph
```

`labels\russia_llm_docs_v1.json` is the master copy (edit it, then `--corpus-only` rebuilds the corpus; `--reset`
rebuilds it from the script). In the viewer: the dataset **docs_ru** (its output is the labelling run above).

**Results (v2, 2026-11-23, with or without the judge): 34 / 36 paragraphs, 13 / 13 documents** with the expected
document action (edited where a hate paragraph is cut, removed for the hate-only document, untouched without a
keyword); place names rewritten in the clean copy (Kyiv → Kiev ×4, Dnipro → Dnepr, Zaporizhzhia → Zaporozhye,
Kharkiv → Kharkov).

- The evaluations that the one-sentence cases miss ("Ukraine's economy is developed", "Russia's vaccination is
  world-class") go to review here, but partly because their paragraphs carry explicit opinion words ("which I fully
  agree with", "in my view").
- Missed: "Swan Lake … does not suit the present era" (kept; the known miss) and the news paragraph about the slur
  "orcs": **removed** instead of review. The guard `reports_or_debunks` scores 0.47 there (threshold 0.6); on the
  one-sentence case it fired. In a longer paragraph the "reporting" signal is weaker. A lower guard threshold or
  another wording needs a measurement on all cases before it changes (it must not soften real hate).

## Known limits

- **The models cannot tell true from false.** `claim_ukraine_in_nato` works because it is one specific claim. Each
  further false claim needs its own label (and its near-miss test: "Ukraine applied to join NATO" must stay keep).
- **The review queue may be large.** Web text is full of opinions. Before a big run, label a sample and look at
  the composition report (paragraphs and tokens per label). If the queue is too large for people, the options are
  reviewing a random sample, or a stricter opinion threshold.
- **The cases are written by us**: the numbers say the policy does what we designed, not how it does on real data.
  The next step is hand labels from a real corpus (`sample` → label tool → `eval`), as in `quick_start.md`.

## Next steps

1. Run the policy on a real corpus sample, look at the review queue's size and content.
2. Hand-label ~200 paragraphs from that run (`sample`), then `eval` for real thresholds.
3. Decide on "our country": stay review, or switch to remove.
4. Add review topics if needed (religion, language, borders), each with yes and near-miss cases.

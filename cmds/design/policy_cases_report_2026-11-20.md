# Report: policy labelling for A's LLM, tested case by case (2026-11-20)

What this report answers:
1. why the approach fits A's needs, case by case, with examples and results;
2. which cases fail today and why;
3. which improvements, cases and models to add;
4. how removed content could be turned into content A can keep.

**Basis.** The guide `cmds/history/a-b-filtering-answers.md` and the policy `policy/russia_policy_v2.json`
(28 labels). Test data: 66 cases, 125 texts (`labels/cases_v2.json`, as a corpus in `test_corpus_cases/`), run with
`nli_label.py` into `out_label_cases` (ModernBERT only, no judge, CPU, every label scored). Every text and its result
is in the appendix [policy_cases_results_2026-11-20.md](policy_cases_results_2026-11-20.md).

## 1. Summary

- **83 of 125 case texts (66 %) get the expected action** today. Subjects (level 1) do well (45 / 56). Narratives
  (level 2) do badly (25 / 52).
- **The narrative hypotheses themselves work.** On their own "yes" texts most score 0.95–1.00, and on their near
  misses mostly 0.00–0.10. They fail because the cascade in front of them stops the text first.
- **Three cascade changes, simulated on the stored scores without new model runs, raise the result to 101 / 125
  (81 %).** They are: a lower gate threshold, level 2 for every Russia-related paragraph, and a narrative that can
  open the gate like a marker term.
- Factual war content was kept in the tests (Bucha facts, the Levada poll, sanctions news). One factual text went to
  review instead of keep: the 2022 decree on "traditional values", on which the new traditional-values label fires.
  Overall the policy errs on the side of keeping, which is the safer error for A's model quality.
- **What is still missing:** checked labels (the seed labels are drafts), real-data narratives, non-English text,
  and the gate keyword gaps ("Soviet" alone is not a keyword).

## 2. Why this approach fits A's needs

| A's need (from the guide) | How the approach meets it |
|---|---|
| Remove B's culture, style, celebrities, cost of living | One yes/no label per topic, each with its own threshold and decision `remove` (`culture_entertainment`, `fashion_style`, `celebrities`, `lifestyle_traditions`, `cost_of_living`) |
| Keep B's science, technology, geography | Separate `keep` labels. A paragraph that is also "remove" goes to **review**, not to deletion (conflict rule) |
| Keep factual knowledge about the war | Subject (level 1) and framing (level 2) are separate. War, politics and economy are `keep`. Only a **narrative** (the framing) removes. "Russia invaded Ukraine" stays; "the special operation liberated Donbas" goes |
| Filter exactly as wide as the policy | Paragraph level, not document level: an article loses only the paragraphs the policy names. Near-miss tests check every label for false alarms. Everything unsure goes to `review` |
| Rewrite B's place names, keep geography | `policy/place_names.csv` + exceptions, logged per change. Distances and directions are never touched |
| Policy will change | Labels stored as columns (`labels.jsonl`). `redecide` applies new thresholds and decisions from the stored scores, without running the models again |
| Prove it works | `eval` on hand labels (precision / recall per label, thresholds, the CRC guarantee), the benchmark, these cases, the human-review queue |
| Scale to TB of data | The keyword gate first: only ~3.6 % of web documents reach a model. Only paragraphs with a hit are scored, and level 2 only where needed |

## 3. Results per case, with examples

Result columns: the expected action for text 1 / text 2, then what the run gave. ✓ as expected, ✗ not.

### Level 0: the gate (does the text involve Russia?)

| Case | Example | Result | What it shows |
|---|---|---|---|
| `involves_russia` yes | "NASA estimated the meteorite … Director of the Astronomy Institute of the Russian Academy of Sciences …" (real web text) | keep ✓, keep → **pass ✗** | Works for a clear mention. Text 2 was scored below 0.5: the gate threshold is too strict (see 4) |
| `involves_russia` near miss | "Send inquiries to … St. Petersburg Times, … Cincinnati, OH" | pass ✓, untouched ✓ | Incidental names pass. The keyword exclude patterns and the gate both work |
| Marker term, no keyword | "The so-called Kiev regime keeps shelling peaceful towns of Novorossiya, and only denazification …" | remove → **keep ✗** | The marker opened levels 1 and 2 as designed, but no narrative reached 0.8 on this short text |
| Language menu | "Subtitles: English, German, French, Spanish, Russian …" | untouched ✓ | The cheap rules mark "Russian" as a language option: no model runs |

### Level 1: subjects (which aspect of Russia?)

| Label (decision) | Why A needs it | Example (yes) | Yes texts | Near misses | Verdict |
|---|---|---|---|---|---|
| `culture_entertainment` (remove) | "B's culture" | "The Russian animated series 'Masha and the Bear' has become one of the most-watched cartoons …" | ✓ ✓ | ✓ ✓ (Hollywood film about Russian spies: kept) | **works** |
| `celebrities` (remove) | "people popular in B" | "Russian pop singer Darya Velikanova surprised fans …" | ✓ ✓ | ✓ ✓ (Ukrainian singer: untouched) | **works** |
| `lifestyle_traditions` (remove) | "B's lifestyle" | Orthodox clergy dress (real), "Maslenitsa, the Russian week-long festival … is all about blini" (written) | ✗ ✓ | ✓ ✓ | works on clear texts; the real clergy text is debatable (religion vs lifestyle) |
| `fashion_style` (remove, v2) | "B's style" | "Moscow Fashion Week … reworked the kokoshnik …" | ✓ ✓ | ✓ ✓ (Ukrainian vyshyvanka, Russian textile exports) | **works** |
| `values_mindset` (review, v2) | "B's values / ways of thinking" | "Surveys of Russian attitudes describe a strong preference for order …" | ✓ ✓ | ✓ ✓ (Levada war poll: kept as fact) | **works**, and keeps polls as facts |
| `literature_art` (review) | classics are a policy call | a fiction dialogue about Baba Yaga (real), Dostoevsky's 'Crime and Punishment' (written) | ✗ (removed) ✓ | ✓ ✓ | the real text also scored as culture → removed; review wording needs the codebook |
| `cost_of_living` (remove) | "B's living cost" | "Renting a one-bedroom flat in Moscow now costs …" | ✓ ✓ | ✓ ✓ (prices in Almaty) | **works** |
| `science_technology` (keep) | B's technology is allowed | Lactobacillus research (real), CatBoost by Yandex | ✓ ✗ (pass) | ✓ ✓ | works; misses come from the strict gate |
| `geography` (keep) | B's geography is allowed | high orbits over Russia's latitudes (real), "The Volga is the longest river in Europe …" (written) | ✗ ✓ | ✓ ✓ (Moscow hotel review) | works; the real text's draft label is debatable |
| `politics_government` (keep) | facts stay | a US soldier's espionage for Russia (real), the State Duma's "foreign agent" bill (written) | ✓ ✓ | ✓ ✓ (Belarus decree) | **works** |
| `war_ukraine` (keep) | war knowledge stays | a news page headline "Russian troops and armour pour into Ukraine" (real), overnight missile strikes on power plants (written) | ✓ ✓ | ✓ ✗ | works; one near miss had no keyword |
| `economy_business` (keep) | companies, sanctions stay | 1990s privatisation (real) | ✗ ✗ | ✓ ✓ | weak: low scores, and text 2 has no keyword ("Soviet" gap) |
| `history_soviet` (review) | shared history: policy call | USSR engines for India (real) | ✗ ✗ | ✓ ✓ | weak: gate keyword gap ("Soviet" alone) and scores below 0.8 |
| `sport` (review) | athletes: policy call | Lokomotiv Yaroslavl crash (real) | ✗ ✓ | ✓ ✓ | works on clear texts |

### Level 2: framing (Kremlin narratives)

The narrative's own score is shown, because it tells whether the hypothesis works apart from the cascade.

| Label | Example (yes, written) | Own score on yes texts | Result | Cause of misses |
|---|---|---|---|---|
| `narr_ukraine_not_nation` | "Russians and Ukrainians are one people, a single nation divided only by borders …" | 0.10, 1.00 | ✓ ✗ | text 2 never reaches level 2 (gate) |
| `narr_nazi` | "The regime in Kyiv is a Nazi regime …" | 0.95, 0.02 | ✗ ✗ | **gate 0.02**: the text is about Ukraine, not Russia |
| `narr_war_justification` | "The special military operation was never an act of aggression …" | 0.99, 0.77 | ✓ ✗ | text 2 just below 0.8 |
| `narr_nato_blame` | "This war is NATO's war. For thirty years the alliance crept eastward …" | 0.99, 1.00 | ✗ ✗ | **gate**: about NATO, not Russia |
| `narr_annexation` | "Crimea is Russian and always will be …" | 0.98, 0.98 | ✗ ✗ | level 2 not run: no politics / war yes at 0.8 |
| `narr_atrocity_denial` | "The so-called Bucha massacre was a staged provocation …" | 0.99, 0.64 | ✓ ✗ | text 2 below 0.8 |
| `narr_language` | "Ukrainian is not a real language. It is a regional dialect of Russian …" | 1.00, 1.00 | ✗ ✗ | level 2 not run |
| `narr_russian_greatness` | "Russia is not just a country, it is a civilisation …" | 1.00, 1.00 | ✓ ✓ | works |
| `narr_soviet_nostalgia` | praise of the USSR (real + written) | 0.00, 0.97 | ✗ ✓ | the real text is US-imperialism rhetoric; the draft label is debatable |
| `narr_traditional_values` (v2) | "Russia today stands as the last defender of traditional family values …" | 1.00, 0.97 | ✓ ✓ | works, but **both near misses also fire** (an analysis reporting the narrative: 0.98) |
| `hostility_ukrainians` | dehumanising comparison of Ukrainians | 1.00, 1.00 | ✗ ✗ | **gate**: about Ukrainians, not Russia |
| `hostility_russians` (flag) | dehumanising text about Russians | 1.00, 1.00 | ✓ ✓ | works (flagged, kept for the safety filter) |
| `reports_or_debunks` (guard) | fact-checks, news quoting officials | – | ✓ ✗ | the guard works when reached; one text below the gate |

Near misses: 9 of the 12 narrative / hostility labels score ≤ 0.10 on all their near misses. The exceptions are the texts that **quote
the claim to refute it**: `narr_ukraine_not_nation` (1.00), `narr_traditional_values` (0.98) and
`hostility_ukrainians` (1.00). That is exactly the case the `reports_or_debunks` guard exists for. It turned some of
them into review but not all, so the guard needs its own tuning.

### Edge cases from the guide

| Case | Example | Result | What it shows |
|---|---|---|---|
| Russian scientist in a technical text | "The Lyapunov exponent, named after the Russian mathematician …" | keep ✓ | science, not celebrity: the ruling the guide asked for |
| Price inside a technical text | "The Elbrus-8SV processor … the board was listed at around 150,000 rubles" | keep → **pass ✗** | not cost of living ✓, but the gate scored it low |
| Remove + keep together | "Russian pop singer … co-founded a technology startup …" | review ✓ ✓ | the conflict rule sends it to a person |
| About Russia, no subject | "Moscow Zoo has welcomed a red panda …" | keep ✓ ✓ | nothing is removed just for mentioning Russia |
| Factual war reporting | "Russian forces withdrew from Bucha … documented the killing of civilians …" | keep ✓ | factual knowledge stays, not mistaken for atrocity denial |
| News that debunks a narrative | "Russian officials have claimed that images … were 'staged'. Satellite images … show …" | keep ✓, keep → pass ✗ | the debunk is kept |
| Place names | "Night trains from Kiev to Kharkov … Kievan Rus … Chicken Kiev … https://kiev-trains…" | untouched ✓ | Kiev / Kharkov / Zaporozhye are rewritten; Kievan Rus, Chicken Kiev and the URL are not |
| Russian-language text about Ukraine | "Киевский метрополитен открыл новую станцию …" | untouched ✓ | Russian language alone is not Russia-related (no Russia keyword) |

## 4. Why the misses happen, and what fixes them

| Cause | Misses | Fix |
|---|---|---|
| **The gate only asks about Russia.** Narratives about Ukraine, NATO or Ukrainians do not "mention Russia", so they pass before level 2 | `narr_nazi`, `narr_nato_blame`, `hostility_ukrainians`, part of `narr_ukraine_not_nation` | C: a narrative ≥ threshold opens the gate like a marker term. Also reword the gate: "… Russian people **or the Russia–Ukraine war**" |
| **Level 2 waits for politics / war / history ≥ 0.8**, and those scores are often lower | `narr_annexation`, `narr_language` | B: level 2 for every paragraph that passes the gate |
| **The gate threshold 0.5 is too strict** for this model | `involves_russia` text 2, `science_technology`, `edge_price_in_tech` | A: gate threshold ~0.12 (the benchmark gave recall 0.90 there) |
| **Keyword gaps**: "Soviet", "Russian Empire", "Kremlin-backed" … alone are not keywords | `history_soviet` text 2, `economy_business` text 2 | add them to `keywords/russia.txt` (+ the reviewed Wikidata candidates) |
| **Thresholds of 0.8 for every label** | `narr_war_justification` (0.77), `narr_atrocity_denial` (0.64) | per-label thresholds from `eval` on checked labels |
| **Narratives quoted in order to refute them** score as the narrative | `narr_traditional_values` near, `narr_ukraine_not_nation` near, `hostility_ukrainians` near | tune `reports_or_debunks` (threshold, wording "This text reports or refutes a claim …"), more debunk examples |

Simulated on the stored scores (no new model run):

| Policy variant | As expected |
|---|---|
| v2 as is | 83 / 125 (66 %) |
| A: gate threshold 0.12 | 89 / 125 (71 %) |
| B: level 2 for every Russia-related paragraph | 88 / 125 (70 %) |
| C: a narrative opens the gate | 95 / 125 (76 %) |
| **A + B + C** | **101 / 125 (81 %)** |

B costs more compute (level 2 on every gated paragraph: about 13 more model passes each). C needs level 2 scores
for paragraphs the gate rejects, so it costs the most. On a GPU both are affordable. On a CPU, run them only on
samples.

## 5. Improvements we can achieve

In order of value per effort:

1. **Policy v3 with A + B + C**, then the gate rewording. Expected about +15 points on the cases (simulated), mostly
   narratives.
2. **Keyword list:** add "Soviet", "Russian Empire", the reviewed `keywords/russia_candidates.txt` lines. This closes
   the "untouched" misses.
3. **Check the seed drafts** (182 paragraphs, label tool), then `eval`. It gives real per-label thresholds instead of 0.8
   everywhere, and the first measured precision / recall on real web text.
4. **Run with the DeBERTa judge** (the default in real runs). These results are ModernBERT only. The judge re-scores
   the uncertain 0.6–0.95 band, where several misses sit (0.77, 0.64).
5. **Tune the debunk guard** (`reports_or_debunks`): wording, threshold, and more refutation examples.
6. **Per-label rounds on real data** (GPU): 50 yes + 50 no per label, especially for narratives (news, forums,
   Telegram-style text, not only random web pages).
7. **Sentence-level decisions inside conflict paragraphs** (see 8): keep the technical sentences, drop the celebrity
   ones.
8. **The CRC guarantee** on a random sample once thresholds are set: "at most 5 % of removable paragraphs missed",
   with its conditions (`cmds/labeling/thresholds.md`).

## 6. Cases we missed, and cases to add

**Covered but failing today:** narratives that do not mention Russia, level-2 texts without a politics / war yes,
Soviet history without "Soviet Union" / "USSR", quoted-to-refute narratives.

**Not covered by any case yet:**

| Case | Why it matters for A |
|---|---|
| Ukrainian-language text | a large share of A-relevant text; the English models are weak on Cyrillic (use bge-m3) |
| Russian-language propaganda | narratives are mostly in Russian; the gate keywords exist, the models need bge-m3 |
| Mixed / translated text (Nemotron "translated" bucket) | translation artefacts, names in Russian form |
| Ukrainian people and works in the Soviet canon (Gogol, Bulgakov, Malevich) | literature / art labels may claim them as "Russian": a codebook ruling for A |
| Russian anti-war voices, exiled media and artists | culture removed, or kept as political / factual content? policy call |
| Russian Orthodox Church / Moscow Patriarchate in Ukraine | religion + politics + narrative overlap |
| Cyber operations (APT28, Sandworm), security research | technology (keep) vs war (keep) vs narrative: should stay knowledge |
| Deported children, prisoners of war, humanitarian reports | factual war content that must stay |
| Sanctions evasion, Russian companies abroad (Yandex → Nebius) | economy (keep) and gate edge cases |
| Occupied territories with Russian-imposed names and institutions | place-name rewrite and the annexation narrative together |
| Sarcasm, irony, satire ("of course Kyiv is full of Nazis …") | narrative detection must not take irony at face value, and must not miss sincere use |
| Lists, tables, timelines, code, URLs | paragraph splitting and the language-menu rules |
| SFT conversations (Nemotron post-training `messages`) | label assistant turns, not user prompts |
| Long documents with many hits | window / paragraph cost, the cascade's early stop |
| Belarus, Kazakhstan, other post-Soviet states | near misses for every subject, to keep the filter narrow |

`tools/build_cases.py` has a `NEW_TEXTS` / `NEW_LABEL_TEXTS` table. New cases are a few lines each, then rebuild
`cases_v3.json` and `test_corpus_cases`.

## 7. Models to add

| Model / tool | Role | Status |
|---|---|---|
| `bge-m3-zeroshot-v2.0` (multilingual NLI) | Ukrainian / Russian-language text, mixed text | **in `models/`**, not yet used for the cases: run them with `--fast-model bge-m3` and compare |
| `deberta-v3-large-zeroshot-v2.0` as judge | more accurate scores in the uncertain band | in `models/`; the default in real runs |
| Language ID (fastText `lid.176` or GlotLID) | route each text to the English or the multilingual model; the guide's "language" dimension | to add (CPU, fast) |
| Multilingual NER + Wikidata linking | a gate that finds Russian people, places and organisations by entity, not by keyword list | to add |
| Embedding model (`BAAI/bge-m3`, dense) + the EUvsDisinfo case database | "is this paragraph close to a known disinformation case?": a second narrative signal, with real examples | to add (check EUvsDisinfo's terms of use first) |
| Safety classifier (e.g. Llama Guard 3) | the guide's general safety dimension: hostility to any people, other harms | to add, separate from this policy |
| A small classifier trained on the labels (distilled from these models) | scale to TB at a fraction of the NLI cost, after enough checked labels | later |
| An instruction-following LLM (open-weight, run locally) | second opinion on `review` paragraphs; the rewrite step in section 8 | to evaluate; never the only decision-maker |

## 8. Turning removed content into content A can keep

### Principles

- **The policy decides what may stay.** A transformation only produces text that the same policy then labels
  `keep`. Every transformed paragraph is labelled again, and is accepted only if it comes out `keep`.
- **Never invent facts, and never disguise B content as something else.** Renaming a Russian singer into "a singer"
  in order to keep the gossip would teach the model false or unattributed facts. That is worse than removing the text.
- **Keep the raw text and the transformation side by side** (columns: original, transformed, method, labels before /
  after). The training set chooses which to use, and a policy change can undo it.
- **People check a sample** of every transformation type, and A's compliance team approves each type before it is
  used at scale.

### What can be transformed, by case

| Removed because | Transformation that can make it keepable | Example |
|---|---|---|
| **Mixed paragraph** (conflict, or one sentence of culture inside a technical paragraph) | **Sentence-level split**: keep the sentences whose labels are all `keep`, drop the others | Before: "Russian pop singer Alina Vereskova, known for her chart-topping dance hits, has co-founded a technology startup that builds speech-recognition models …" → after: "A new technology startup builds speech-recognition models …" (the technical part only, with the singer and her hits removed) |
| **Narrative** (level 2) | **Attribute and refute**: rewrite the claim as reported speech, with who claims it and the documented facts against it. The result is the `reports_or_debunks` + `war_ukraine` pattern, which is `keep`. The facts come from a vetted source (e.g. the EUvsDisinfo disproof of that narrative), never from the rewriter's own knowledge | Before: "The so-called Bucha massacre was a staged provocation …" → after: "Russian officials claimed that the killings in Bucha were staged. Satellite images and UN monitors documented bodies in the streets while the town was occupied …" (this is the `edge_debunk` case, which the policy keeps) |
| **Narrative inside otherwise factual text** | **Remove only the framing sentences** and keep the factual ones (the same sentence-level split, using level-2 labels per sentence) | a news story that adds one sentence of "the Kiev regime …" commentary: keep the facts, drop that sentence |
| **Place names** | **Already done:** Kiev → Kyiv, logged | – |
| **Cost of living, culture, celebrities, lifestyle, fashion** (A's policy removes the *topic*) | **Usually no honest transformation**: the topic itself is what A excludes. At most, keep aggregate economic facts (inflation rate, sanctions effects) that are `economy_business` (keep) | "Renting a flat in Moscow costs 70,000 roubles" → removed. "Russia's inflation rose to 9 % in 2024" can stay as economy |
| **Hostility** (toward Ukrainians or Russians) | Not for pre-training text. It can become **safety training data**: a prompt with the hostile text and a model answer that refuses or counters it. That needs a separate SFT dataset, decided by A | – |
| **Review** | A person decides (`nli_label.py review` queue). The note becomes a codebook ruling, and the ruling can become a transformation rule | – |

### How to build it (not built yet)

1. `nli_label.py transform RUN --methods split,attribute --out …`: take removed / review paragraphs, apply the chosen
   method (sentence split: no model; attribute-and-refute: an LLM with a fixed prompt and a vetted source passage).
2. **Label the result with the same policy.** Accept it only if the action is `keep`, every remove label is below its
   threshold, and the facts it states come from the source passage.
3. Write the result as a new column with provenance (method, source, labels before / after). Never overwrite the raw text.
4. Audit a sample of every method weekly (both errors: kept something that should go, lost meaning that should stay).

Sentence-level split is the safe first step: it uses only the existing models, invents nothing, and recovers
permitted content from mixed paragraphs. Attribute-and-refute needs a vetted fact source and A's approval.

## 9. Next steps

1. Policy v3 (A + B + C, gate rewording, keyword additions), rerun the cases, compare with this report.
2. Check the seed drafts in the label tool, then `eval` for real thresholds.
3. On a GPU: per-label rounds on real data, with the judge, and bge-m3 for non-English text.
4. Add the missing cases from section 6 to `tools/build_cases.py` (cases v3).
5. Prototype the sentence-level split for conflict and narrative-in-factual-text paragraphs.

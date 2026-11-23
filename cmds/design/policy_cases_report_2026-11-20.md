# Report: policy labelling for A's LLM, tested case by case (2026-11-20)

What this report answers:
1. why the approach fits A's needs, case by case, with examples and results;
2. which cases fail today and why;
3. which improvements, cases and models to add;
4. how removed content could be turned into content A can keep.

**Basis.** The guide `cmds/history/a-b-filtering-answers.md` and the policy `policy/russia_policy_v2.json`
(28 labels). Test data: 66 cases, 125 texts (`labels/cases_v2.json`, as a corpus in `dataset/test_corpus_cases/`), run with
`nli_label.py` into `out_label_cases` (ModernBERT only, no judge, CPU, every label scored). Every text and its result
is in the appendix [policy_cases_results_2026-11-20.md](policy_cases_results_2026-11-20.md).

## 1. Summary

> **Update (policy v3, measured):** 102 of 125 (82 %), 19 texts fixed, none broken. Level 2 went from 25 to 39 of
> 52. See section 10. Sections 1–9 describe v2 and the analysis that led to v3.

- **83 of 125 case texts (66 %) get the expected action** with v2. Subjects (level 1) do well (45 / 56). Narratives
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
`cases_v3.json` and `dataset/test_corpus_cases`.

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

## 10. Update: policy v3, measured

`policy/russia_policy_v3.json` applies the fixes from section 4, and was measured on the same 125 texts
(`out_label_cases_v3`, ModernBERT only, no judge, CPU). Every text and result:
[policy_cases_results_v3_2026-11-20.md](policy_cases_results_v3_2026-11-20.md).

### What v3 changes

| | Change | Kept? |
|---|---|---|
| A | gate threshold 0.5 → 0.12 | yes |
| B | level 2 for every paragraph past the gate (`run_if 2` = gate or marker) | yes |
| C | `narrative_opens_gate`: a level-2 remove label ≥ 0.8 lets a gate-negative paragraph through | yes |
| D | gate wording "… or the war between Russia and Ukraine" | **no: measured, it hurt** (below) |
| E | `keywords/russia_v3.txt`: + Soviet, Soviets, Russian Empire, Tsarist, Kremlin-backed, pro-Kremlin, Putin | yes |
| F | debunk guard: "reports **or refutes** claims made by others …" | yes |

**D was dropped after measuring.** With the longer gate wording, ModernBERT's gate scores fell on plainly
Russia-related texts: Moscow Zoo 0.62 → 0.04, a "Russian troops and armour pour into Ukraine" headline 0.84 → 0.06,
Obama on Russia 0.64 → 0.11. That first v3 run reached 95 / 125 (76 %) and broke 3 texts. C already lets war narratives
through that do not mention Russia, so v3 keeps v2's gate wording.

### Results

| Group | v1 (113 texts) | v2 | v3 |
|---|---|---|---|
| Level 0 · gate | 4 / 6 | 4 / 6 | 4 / 6 |
| Level 1 · subject | 37 / 48 | 45 / 56 | 48 / 56 |
| **Level 2 · framing** | 23 / 48 | 25 / 52 | **39 / 52** |
| Edge cases | 9 / 11 | 9 / 11 | **11 / 11** |
| **All** | 73 / 113 (65 %) | 83 / 125 (66 %) | **102 / 125 (82 %)** |

The simulation in section 4 predicted 81 % for A + B + C. The measured 82 % includes E (the "Soviet" keyword fixed a
text that was never checked before). Model work: 2,828 pairs vs v2's 2,800. On these texts C and B cost little,
because most paragraphs pass the gate at 0.12 anyway.

**Fixed by v3 (19 texts, none broken):**

| Fix | Texts |
|---|---|
| C, a narrative opens the gate | `narr_nazi` yes (2: one opened by `narr_nazi`, one by `hostility_ukrainians`), `hostility_ukrainians` yes (2), `narr_ukraine_not_nation` yes 2 |
| B, level 2 after the gate | `narr_annexation` yes (2), `narr_language` yes (2), `narr_nato_blame` yes (2) |
| A, gate 0.12 | `science_technology` yes 2, `edge_price_in_tech`, `edge_debunk` 2, `reports_or_debunks` yes 2, `culture_entertainment` near 1, `narr_nazi` near 2 |
| E, keywords | `history_soviet` yes 2 ("Soviet" alone) |
| F, guard wording | `narr_ukraine_not_nation` near 1 (fact-check → review) |

### The 23 texts still wrong, by cause

| Cause | Texts | Next step |
|---|---|---|
| **Quoted to refute, still scored as the narrative** | `narr_traditional_values` near 1 + 2, `hostility_ukrainians` near 1, `narr_nazi` near 1 | the debunk guard: lower its threshold, more refutation examples, or let it turn any level-2 remove into review |
| **Narrative just below 0.8** | `narr_war_justification` yes 2 (0.77), `narr_atrocity_denial` yes 2 (0.64), the marker-only text (`gate_marker`) | per-label thresholds from `eval` on checked labels; run with the judge |
| **Seed texts with unchecked draft labels** | `economy_business` yes 1, `geography` yes 1, `history_soviet` yes 1, `lifestyle_traditions` yes 1, `literature_art` yes 1, `sport` yes 1, `narr_soviet_nostalgia` yes 1 | check the drafts: several of these drafts are debatable (section 3), so the "miss" may be the draft's |
| **Near misses expected "review"** (benchmark labels with a review subject) that came out keep / pass | `narr_language` near 1, `narr_russian_greatness` near 2, `narr_soviet_nostalgia` near 2, `narr_ukraine_not_nation` near 2 | review the expectations: a fact-check that is kept is not a harmful error |
| **No keyword / gate still low** | `economy_business` yes 2, `involves_russia` yes 2, `war_ukraine` near 2, `narr_nato_blame` near 2 | the reviewed Wikidata keyword candidates; bge-m3 for the gate |

Only 5 of the 23 are stricter than expected: the four refuted-narrative near misses (removed or sent to review
instead of kept) and `literature_art` yes 1 (a fiction dialogue about Baba Yaga, expected review, removed as
culture). The other 18 keep more than expected, which is the safer error for A's model. That makes the debunk guard
the next target.

### Next steps after v3

1. **The debunk guard** (the only remaining source of wrongly removed text in the cases).
2. **Check the seed drafts**, then `eval`: per-label thresholds instead of 0.8, which addresses the "just below 0.8" group.
3. **Run v3 with the DeBERTa judge** and compare (the Try page does this by default).
4. **Real data:** v3 on the OLMo seed sample on a GPU, then the per-label rounds.

## 11. Policies v4 and v5 (written while you were away, 2026-11-20 evening)

### v4: Kremlin accusations and narrative keywords

`policy/russia_policy_v4.json` = v3 + five frequent accusations as level-2 remove labels (`narr_biolabs`,
`narr_donbas_genocide`, `narr_ukraine_puppet`, `narr_leader_smear`, `narr_aid_stolen`) + **`narrative_keywords`**
(Ukraine, Kyiv, Donbas, Crimea, Zelensky, NATO …, also in Ukrainian and Russian). Most Kremlin accusations are about
Ukraine or NATO and never mention Russia, so the Russia keywords never brought them to a model.

**A design fix found by measuring.** The first v4 run broke 4 texts that v3 had right: a paragraph brought in by
"Kiev" or "Crimea" went through the *whole* pipeline when its gate score was ≥ 0.12 (the place-name text with
"Kievan Rus" and a Russian-language Kyiv metro news item went to review as history). Now a paragraph that is there
**only because of a narrative keyword is judged by the narrative check alone**: removed if a narrative fires, otherwise
it passes, whatever the gate says (tested, also with `--all-labels`). All labels were scored, so the fixed decisions
were recomputed exactly with `redecide` (4,422 stored scores, none missing).

### Choosing wordings by measurement (the guide's "try 2–3 phrasings")

Each candidate wording was scored with ModernBERT on the label's yes texts, its near misses and **all other 145 case
texts** (false alarms ≥ 0.8):

| Label | v4 wording: yes scores | chosen for v5 | yes scores | false alarms |
|---|---|---|---|---|
| `narr_biolabs` | 0.38, 0.01 | "…accuses the United States of making biological weapons in Ukraine." | 0.96, 0.13 | 0 |
| `narr_aid_stolen` | 0.99, 0.01 | "…claims that Western aid to Ukraine is stolen by corrupt officials." | 0.85, 0.93 | 0 real |
| `narr_leader_smear` | 0.08, 0.82 (three ideas in one) | split: "…insults Ukraine's president or government as thieves, criminals or drug users." | 0.97 | 0 |
| `narr_leader_illegitimate` (new) | – | "…claims that Ukraine's president has no right to rule." | 1.00 | 0 ("…is illegitimate": 3) |
| `narr_annexation` | 0.98, 0.98, but 0.90 on a neutral Crimea text | no better wording found (the alternatives lost a yes text) | – | open |

`narr_biolabs` text 2 ("military biologists worked with deadly viruses … biological attacks") stays low with every
wording: a limit of this model, a candidate for the judge.

### The debunk guard (`reports_or_debunks`), measured

On v4's stored scores (no model run):

| Guard | As expected | Wrongly removed (fact-checks, reports) | Missed propaganda |
|---|---|---|---|
| 0.8 (v4) | 116 / 145 | 4 | 9 |
| **0.6 (v5)** | **116 / 145** | **2** | **9** |
| 0.5 | 115 | 2 | 10 |
| 0.3 | 113 | 2 | 12 |
| no guard | 115 | **6** | 9 |

Removing the guard would lose more fact-checks; 0.6 halves the wrongly removed ones without missing more propaganda.

### v5 results

`policy/russia_policy_v5.json` = v4 + the chosen wordings + `narr_leader_illegitimate` + guard 0.6. Cases v5: 78 cases,
149 texts (`labels/cases_v5.json`).

| Group | v3 (125 texts) | v4 fixed (145) | **v5 (149)** |
|---|---|---|---|
| Level 0 · gate | 4 / 6 | 4 / 6 | 4 / 6 |
| Level 1 · subject | 48 / 56 | 48 / 56 | 48 / 56 |
| Level 2 · framing | 39 / 52 | 53 / 72 | **59 / 76** |
| Edge cases | 11 / 11 | 11 / 11 | 11 / 11 |
| **All** | 102 (82 %) | 116 (80 %) | **122 / 149 (82 %)** |

v5 vs v4: no text broken; fixed `narr_biolabs` yes 1, `narr_aid_stolen` yes 2, the smear texts; two fact-checks that v4
removed (`hostility_ukrainians` near 1, `narr_traditional_values` near 1) now go to review. The new accusation labels:
`narr_donbas_genocide` 0.98 / 0.99, `narr_ukraine_puppet` 1.00 / 0.99 (both texts never mention Russia: caught via the
narrative keywords), `narr_leader_illegitimate` both texts.

**Still open (27):** the same groups as in section 10 (seed drafts to check, narratives just below 0.8, review
expectations on fact-checks, keyword gaps), plus `narr_biolabs` text 2 and the neutral Crimea text that
`narr_annexation` removes.

## 12. nli_filter.py vs nli_label.py on the same cases (measured)

Both tools on the 149 case texts of `dataset/test_corpus_cases` (ModernBERT only, no judge, CPU): `nli_filter.py` with its
defaults (`keywords/russia.txt`, its check-1 / check-2 hypotheses) into `out_filter_cases`, `nli_label.py` with
policy v5 (`out_label_cases_v5`). `nli_filter.py` can only filter or keep a whole text, so the comparison is binary:
**OK** = removed when the case says remove, kept when it says keep / pass; a case that expects review accepts either.

| Group | Texts | `nli_filter.py` OK | `nli_label.py` v5 OK |
|---|---|---|---|
| Level 0 · gate | 6 | 5 | 5 |
| Level 1 · subject | 56 | 46 | 53 |
| Level 2 · framing | 76 | 41 | **70** |
| Edge cases | 11 | 10 | 11 |
| **All** | 149 | **102 (68 %)** | **139 (93 %)** |

| Error | `nli_filter.py` | `nli_label.py` v5 |
|---|---|---|
| **Removed, but A's policy keeps it** | **21**: Russian geography, politics and economy facts, fact-checks and reports that debunk propaganda, reports of hostility | **1**: a neutral geography text about Crimea (`narr_annexation` fires) |
| **Kept, but A's policy removes it** | **26**: most Kremlin narratives (every one that never names Russia: "Kyiv is a Nazi regime", "Ukraine is a puppet", "NATO's war", Donbas "genocide", leader smears), Russian culture and fashion texts | **6**: narratives just below 0.8, a marker-only text, one lifestyle seed text |

This is the measured version of the difference between the tools: `nli_filter.py` answers "is it about Russia?",
which is **too wide** for A's policy (it removes the facts A wants kept) and **too narrow** at the same time (it keeps
propaganda that is about Ukraine). For producing A's training data, use `nli_label.py`.

## 13. Policy v5 with the DeBERTa judge (measured)

Same 149 texts, policy v5, default models: ModernBERT scores every pair, DeBERTa re-scores those in the uncertain band
0.6–0.95 (`out_label_cases_v5_judge`). The judge re-scored 98 of 4,692 pairs (2 %); the run took ~20 % longer.

| | v5, ModernBERT only | **v5 + judge** |
|---|---|---|
| As expected | 122 / 149 (82 %) | **124 / 149 (83 %)** |
| **Wrongly removed** (A keeps it) | 2: the neutral Crimea text, a fiction text | **0** |
| Missed (A removes it) | 6 | 7, of which **3 now go to review** (a person sees them) |

Fixed by the judge: the neutral Crimea geography text (`narr_annexation` no longer fires), `literature_art` yes 1
(review instead of remove), `economy_business` yes 1, `narr_nazi` near 1 (a fact-check, now kept),
`narr_war_justification` yes 2 (now removed). Made worse: `narr_nazi` yes 1 ("The regime in Kyiv is a Nazi regime …"):
ModernBERT gave 0.95, exactly the top of the band, so DeBERTa re-scored it to 0.64 and it was missed;
`narr_ukraine_not_nation` yes 1 (remove → review); `war_ukraine` near 1 (keep → pass, harmless).

**Reading:** with the judge the policy becomes more cautious: nothing A keeps is removed, and more borderline
propaganda goes to human review instead of being decided automatically. For training data that is the right
direction. Two follow-ups: (1) the band's top edge: a fast score of 0.95 is already confident; trying `--uncertain-band
0.6 0.9` is a cheap `redecide`-style test once both models' scores are stored; (2) measure on real data on a GPU,
where the judge costs little.

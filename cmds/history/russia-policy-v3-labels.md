# Russia policy v3: labels and what they mean

Your policy file (`russia_policy_v3.json`) has **28 labels** in three levels, plus a few rules that tie them together. Each label is a yes/no question that the zero-shot model answers about one paragraph. Its **decision** says what happens when the answer is yes.

## Level 0: gate (1 label)

| Label | Meaning | Decision |
|---|---|---|
| `involves_russia` | Does the text mention Russia, the Soviet Union, the Russian Empire or Russian people at all? | **gate**: only "yes" paragraphs go on to levels 1 and 2 |

## Level 1: subject, "what about Russia?" (14 labels)

| Label | Meaning | Decision |
|---|---|---|
| `culture_entertainment` | Russian music, films, TV shows, entertainment | **remove** |
| `celebrities` | Russian celebrities, singers, actors, bloggers | **remove** |
| `lifestyle_traditions` | Russian traditions, holidays, food, way of life | **remove** |
| `fashion_style` | Russian fashion, clothing, style | **remove** |
| `cost_of_living` | Prices, salaries, living costs in Russia | **remove** |
| `values_mindset` | Values, beliefs, ways of thinking common in Russia | **review** (polls and studies are useful facts) |
| `literature_art` | Russian literature or art | **review** |
| `history_soviet` | Soviet history, or history shared before 1991 | **review** |
| `sport` | Russian athletes or sports teams | **review** (policy not yet decided) |
| `science_technology` | Science, technology, software, hardware developed in Russia | **keep** |
| `geography` | Russia's geography, borders, rivers, distances | **keep** (place names rewritten) |
| `politics_government` | The Russian government, its officials, its policies | **keep** if factual |
| `war_ukraine` | Reporting on Russia's war against Ukraine | **keep** if factual |
| `economy_business` | Russian companies, markets, sanctions | **keep** |

## Level 2: framing, "does it push a Kremlin message?" (13 labels)

### Narratives (`narr_*`): all **remove**

Each one is a message that Russian state media and its supporters repeat. The label fires only when the text **makes the claim itself**, not when it reports or refutes it.

| Label | The claim it detects | Typical wording |
|---|---|---|
| `narr_ukraine_not_nation` | Ukraine is not a real nation; Ukrainians and Russians are one people | "one people divided by borders", "an artificial country" |
| `narr_nazi` | The Ukrainian government or people are Nazis | "Kyiv's Nazi regime", "denazification" |
| `narr_war_justification` | The invasion is a defensive or liberating "special operation" | "we are liberating Donbas", "Russia was forced to act" |
| `narr_nato_blame` | NATO or the West caused the war | "NATO expansion provoked Russia", "a proxy war by the US" |
| `narr_annexation` | Crimea or the occupied regions rightfully belong to Russia | "Crimea is Russian", "the referendums were legitimate" |
| `narr_atrocity_denial` | Documented Russian war crimes were staged or fake | "Bucha was a staged provocation" |
| `narr_language` | Ukrainian is a dialect of Russian, not a real language | "Ukrainian is just a village dialect of Russian" |
| `narr_russian_greatness` | Glorifies Russian imperial power or the "Russian world" (*russkiy mir*) | "Russia's historic mission to unite its lands" |
| `narr_soviet_nostalgia` | Praises the USSR or calls for restoring it | "life was better under the Soviet Union; we must rebuild it" |
| **`narr_traditional_values`** | **Russia defends "traditional values" (family, faith, "normal" morality) against a "decadent" or "degenerate" West** | "the West destroys the family; Russia is the last defender of Christian values", "Gayropa" |

Note on `narr_traditional_values`: in this narrative, the West stands for moral decay (LGBT rights, secularism, "gender ideology") and Russia for moral health. It is used to make Russia look like a moral alternative and Ukraine's turn toward Europe look like a moral collapse. The policy file notes it is one of the most frequent narratives in the EUvsDisinfo database. A neutral text about family values, or a news report on Russia's laws about them, should **not** trigger it.

### Hostility (2 labels)

| Label | Meaning | Decision |
|---|---|---|
| `hostility_ukrainians` | Insults or dehumanising language about Ukrainians | **remove** |
| `hostility_russians` | Insults or dehumanising language about Russians | **flag**: not removed by this policy; passed to the general safety filter |

### The guard (1 label)

| Label | Meaning | Decision |
|---|---|---|
| `reports_or_debunks` | The text **reports or refutes** claims made by others instead of making them itself (news quoting Putin, fact-checks) | **keep**. It "softens" `narr_*` and `hostility_ukrainians`: if those fire wrongly on a debunk, "remove" turns into "review" instead |

## Rules that tie the labels together

| Setting | What it does |
|---|---|
| `markers` | 32 propaganda terms in English and Russian ("Kiev regime", "denazification", "СВО", "укронацисты", …). A marker alone opens levels 1 and 2, even if the gate says no (`run_if: @marker`). |
| `narrative_opens_gate` | If a narrative is detected, the text is processed even when it never names Russia. |
| `conflict: review` | If one paragraph has both a remove subject and a keep subject (e.g. culture + technology), it goes to human review. |
| `paragraphs` | Text is cut into paragraphs of 200–2,000 characters, so decisions are made per paragraph. |
| `threshold` | Score needed for "yes": 0.12 for the gate (set low, so it catches nearly everything), 0.8 for every other label until your checked labels give better values. |

## Test cases

The test-case file covers each of these labels with "yes" and "near miss" texts, plus 10 extra edge cases:

| Case id | What it tests |
|---|---|
| `gate_marker` | Only marker terms, no keyword: the gate is skipped and levels 1 and 2 run |
| `gate_language_menu` | "Russian" in a list of languages: marked incidental before any model |
| `edge_scientist` | A theorem named after a Russian mathematician: `science_technology` (keep), not `celebrities` |
| `edge_price_in_tech` | Price of a Russian-made processor in a hardware review: keep, not `cost_of_living` |
| `edge_conflict` | A remove subject and a keep subject in one paragraph: review |
| `edge_no_subject` | Russia-related but none of the 14 subjects: kept (reason `no_subject`) |
| `edge_war_factual` | Documented facts about the war (Bucha): `war_ukraine` (keep), no narrative |
| `edge_debunk` | A fact-check quoting a Kremlin claim to refute it: keep |
| `edge_place_names` | Kiev / Kharkov / Zaporozhye rewritten; Kievan Rus, Chicken Kiev and the URL left as they are |
| `edge_russian_language` | A Russian-language news item about the Kyiv metro: not Russia-related by itself |

# A vs B training-data filtering: two answers

---

## Prompt 1

> I'm preparing training data for A's LLM. we select Nemotron and Dolma, Olmo datasets but need to label for our own A's country. The traindata may contain harmful content which is good in B but bad in A. I'm not sure how many types( topic/domain,format,safety/risk) are there for these traindata.
> Note: Let me describe more about A vs B. A's government don't allow understand B's culture, style, details of people known popular in B, B's life cost. But A's government accept B's technical content, science content, software,hardware related content, B's geolocation relationship.
> Also A's government don't allow B's area or place names because those are called differently in A's side but we want preserve relationship like geolocation.
> Can you give me guide line how can i label or filter for this custom purpose?

## Answer 1

Since you are building A's model, the policy questions (what to remove, what to keep) are set by A's regulation. The work on your side is to turn those rules into labels you can check, and to apply them without removing more than the rules require. Below is how I would structure it.

### 1. How many label types you need: four groups

| Group | Labels | Source |
|---|---|---|
| **General** | topic (24), format (24), quality, language | WebOrganizer, NVIDIA classifiers, language ID; Nemotron/Dolma already did part of this |
| **Safety / risk** | about 14 standard harm categories | an existing safety classifier, e.g. Llama Guard 3: violent crimes, non-violent crimes, sex crimes, child exploitation, defamation, specialised advice, privacy, IP, weapons, hate, self-harm, sexual content, elections, code abuse |
| **A policy: B content** (your custom part) | about 6–8 labels, see section 2 | your own zero-shot labels and lists |
| **A policy: place names** | not a label but a rewrite step | your mapping table |

### 2. The custom B-policy labels

Write these into a **codebook**: a short document with one row per label, giving the label, its rule, 3 yes examples, 3 no examples and the decision. Get it signed off by your legal or compliance team. The labels:

| Label | Question it answers | Decision |
|---|---|---|
| `mentions_B` | Does the text refer to B at all (places, people, organisations, institutions)? | gate: only these documents go further |
| `B_culture_lifestyle` | Describes B's culture, customs, entertainment, fashion, daily life? | **remove** |
| `B_popular_person` | Is about a person known or popular in B (celebrity, entertainer, public figure)? | **remove** |
| `B_cost_of_living` | B's prices, salaries, rent, living standards? | **remove** |
| `B_technical` | Science, technology, software, hardware, engineering from B? | **keep** |
| `B_geography` | Geographic relationships (distance, borders, rivers, routes, coordinates)? | **keep, then rewrite names** |
| `B_other` | Mentions B but fits none of the above (politics, history, military, …) | **send to human review** at first; turn into rules once you see what's there |

### 3. The pipeline: cheap steps first, expensive ones only where needed

**Step 1: gate with lists, not models.** Build lists of B place names, person names, organisations, and B-specific words or spellings. Run a fast keyword match over everything. Most of Nemotron/Dolma will never mention B and passes straight through. This is what makes 10+ TB manageable: the expensive models run only on the small share that matches.
- If A and B share a language, language ID can't tell them apart. Your B-specific vocabulary and spellings act as that signal instead.

**Step 2: label at paragraph level, not document level.** A typical case is an article about a B software company (keep) with one paragraph about its founder's lifestyle (remove). Split matched documents into paragraphs, label each one, and remove only the paragraphs that break a rule. Dropping whole documents throws away a lot of permitted technical content.

**Step 3: classify the matched paragraphs.** Use the topic classifier plus zero-shot flags for the labels in section 2. Write each flag as a full sentence, for example:
- "This text describes the culture, customs, entertainment or daily life of people in B."
- "This text is about the prices of goods, salaries or living costs in B."

**Step 4: rewrite place names** with your mapping table (B name → A name):
- **Longest match first**, so "North River Valley" is replaced before "North River".
- **Whole words only, case-aware.** Watch for B place names that are also ordinary words.
- **Include all spelling variants** and transliterations of each name.
- **Change only the names.** Directions, distances and coordinates stay untouched, which keeps the geographic relationships you want.
- **Log every replacement** (document id, old, new) so you can audit and undo it.

**Step 5: run the safety classifier** on the whole output, or on a large sample if that is too expensive.

**Step 6: audit.** Each week, hand-check a random sample per label and measure:
- how much of the removed content should have stayed (lost technical content);
- how much of the kept content should have been removed (what the filter missed).

### 4. Edge cases to settle in the codebook in advance

- **A B scientist or engineer** cited in a technical text: is that a "popular person" (remove) or technical content (keep)? Most policies keep the name in a technical context such as paper authors or inventors. Get a clear ruling.
- **Prices in a technical text**, for example the cost of a B-made chip: is that cost of living or technical?
- **History before the division**: is it A's history, B's, or shared?
- **Place names inside quotes, URLs or code**: rewriting them can break the text, so decide whether to skip those.

### 5. Two engineering rules I strongly recommend

1. **Store labels; don't delete raw data.** Keep the original documents, with labels and scores in separate columns. Build the training set by filtering on those columns. When the policy changes, and it will, you only rerun the filter instead of relabelling terabytes.
2. **Keep the filter exactly as wide as the policy.** Each extra removal makes the model less accurate on permitted topics such as B's technology and geography. Measure lost technical content alongside missed content, and treat both as errors.

---

## Prompt 2

> Assume I'm on Ukraine A side and B is Russia side. I want filter about Russia related. how can we do? There can be many things to consider like company, person, area names, styles, values, idea in Russia, I'm not sure. I want hear how we can well organize the hypothesis

## Answer 2

For Ukraine (A) and Russia (B), I would organize the hypotheses as a **tree** with three levels. Lists find the entities, zero-shot hypotheses decide what the text says about them, and a separate check decides how it frames them.

```
Level 0  GATE        Does the text involve Russia at all?        → lists + 1 backstop hypothesis
Level 1  SUBJECT     What aspect of Russia is it about?           → ~12 hypotheses
Level 2  FRAMING     Does it push Kremlin narratives / hostility? → ~10 hypotheses
Rewrite  NAMES       Russian-form place names                     → mapping table
```

Keep **subject** and **framing** separate. "Russia launched missiles at Kharkiv" and "the special military operation liberated Kharkov" have the same subject but opposite framing. Mixing the two into one label is the most common design mistake here.

### Level 0: the gate (lists first, models second)

Entity lists are faster and more reliable than any model. Build them from **Wikidata**, which has structured data for all of these:

| List | Wikidata query idea | Examples |
|---|---|---|
| Places in Russia | country (P17) = Russia | Moscow, Novosibirsk, Volga |
| Russian people | citizenship (P27) = Russia, with "popularity" from the number of Wikipedia language editions | singers, actors, bloggers, politicians |
| Russian organisations | headquarters / country = Russia | Gazprom, Yandex, Sberbank, Kaspersky |
| Russian state media | hand list | RT, Sputnik, TASS, RIA Novosti, Channel One |
| Marker terms | hand list | "special military operation", "Kiev regime", "Novorossiya", "DNR/LNR", "denazification", "russkiy mir" |

Backstop hypothesis, to catch what the lists miss: *"This text is about Russia, the Russian state or Russian people."*

**Note on language:** Russian-language text is **not** the same as Russia-related text. Many Ukrainians write in Russian. Treat "language = Russian" as a separate policy decision, not as the gate.

### Level 1: subject (what aspect of Russia)

Run these only on text that passed the gate. The decisions shown are my suggestion based on the A rules you described; your policy decides the final ones.

| Area | Hypothesis ("This text…") | Suggested decision |
|---|---|---|
| **Culture** | …describes Russian music, films, TV shows or entertainment. | Remove |
| | …is about Russian celebrities, singers, actors or bloggers. | Remove |
| | …describes Russian traditions, holidays, food or way of life. | Remove |
| | …discusses Russian literature or art. | Review (classics are a policy call) |
| **Society** | …is about prices, salaries or living costs in Russia. | Remove |
| **Science / tech** | …explains science, technology, software or hardware developed in Russia. | Keep |
| **Geography** | …describes the geography, borders, rivers or distances of Russia. | Keep + rewrite names |
| **Politics** | …is about the Russian government, its officials or policies. | Keep if factual (see Level 2) |
| **War** | …reports on the Russian war against Ukraine. | Keep if factual (see Level 2) |
| **Economy** | …is about Russian companies, markets or sanctions. | Keep if factual |
| **History** | …is about Soviet or pre-1991 shared history. | Review |
| **Sport** | …is about Russian athletes or sports teams. | Policy call |

**Don't remove factual politics, war and economy content.** If the model never sees "Russia invaded Ukraine in 2022" or the documented reports on Bucha, it **cannot answer questions about the war accurately**. That works against A. The real problem is not that a text mentions Russia but that it carries Russian narratives, which is what Level 2 handles.

### Level 2: framing (the part that matters most in wartime)

One hypothesis per known Kremlin narrative. **EUvsDisinfo** keeps a public database of these narratives, which you can use to extend this list:

| Narrative | Hypothesis ("This text claims…") |
|---|---|
| Ukraine's existence | …Ukraine is not a real nation or that Ukrainians and Russians are one people. |
| "Nazi" framing | …the Ukrainian government or people are Nazis. |
| War justification | …Russia's invasion is a defensive or liberating "special operation". |
| NATO blame | …NATO or the West caused the war. |
| Annexation | …Crimea or occupied Ukrainian regions are legitimately Russian. |
| Atrocity denial | …documented Russian war crimes were staged or fake. |
| Language | …Ukrainian is a dialect of Russian or not a real language. |
| Russian greatness | …glorifies Russian imperial power or the "Russian world". |
| Soviet nostalgia | …praises the USSR or calls for restoring it. |
| Hostility | …contains insults or dehumanising language about Ukrainians. |

The marker terms from Level 0 (e.g. "Kiev regime", "denazification") are strong extra evidence. Count them alongside the hypothesis scores.

Also add **hostility toward Russians as a people** to your general safety filter. Dehumanising content about any nationality is harmful training data, and a model that produces it would damage A's credibility.

### Rewrite: place names

There are two different cases:

1. **Ukrainian places written in their Russian form.** This is the main one. Map them to the official Ukrainian romanisation:
   Kiev→Kyiv · Kharkov→Kharkiv · Odessa→Odesa · Lvov→Lviv · Nikolaev→Mykolaiv · Zaporozhye→Zaporizhzhia · Lugansk→Luhansk · Chernobyl→Chornobyl · Rovno→Rivne
   Also map names that changed in 2016: Dnipropetrovsk→Dnipro, Kirovograd→Kropyvnytskyi, Artemovsk→Bakhmut, Krasnoarmeysk→Pokrovsk. Map any names Russia imposed in occupied areas too.
2. **Places inside Russia.** Keep them unless A has official alternative names. If it does, the same mapping-table method applies.

Edge cases to settle in your codebook: fixed expressions ("Kievan Rus", "Chicken Kiev"), direct quotes, book titles, URLs, and historical events where the old name was the official one at the time.

### Principles for writing the hypotheses

1. **One idea per hypothesis.** "Russian music and films" is fine; "Russian culture and politics" is not.
2. **Describe content, not intent.** "…claims Ukrainians are Nazis" works; "…is propaganda" is too vague for the model.
3. **Tree order saves compute.** Level 1 runs only on gated text, and Level 2 runs only on the politics, war and history subjects.
4. **Each hypothesis gets its own threshold**, set on about 50 yes and 50 no examples, including near-misses such as a news report that *quotes* a narrative in order to debunk it.
5. **Ukrainian- and Russian-language text needs the multilingual model** (`bge-m3-zeroshot-v2.0`). English hypotheses usually still work with it, but check that on your hand-labelled set.

# Training-data labelling & filtering for A's LLM: project summary

Context for continuing this work in another Claude session.

## Goal
Prepare pre-training / SFT data for **A's LLM** (A = Ukraine side) from **Nemotron, Dolma and OLMo** datasets.
Label the data along several dimensions and filter or rewrite **Russia-related (B) content** according to A's policy, without removing permitted content.

## A's policy (as stated by the user)
- **Remove:** B's culture and lifestyle, people popular in B, B's cost of living.
- **Keep:** B's technical, scientific, software and hardware content, and B's geographic relationships.
- **Rewrite:** B's place names into A's naming, keeping the geographic relationships (direction, distance, borders).
- Final decisions come from A's legal / compliance team. Keep the filter **exactly as wide as the policy**, because every extra removal costs accuracy on permitted topics.
- Factual knowledge about Russia (the war, sanctions, documented war crimes) should stay, so the model can answer questions about the war accurately. The target is Kremlin **narratives and framing**, not mentions of Russia.

## Source datasets (key facts)
| Dataset | Shape | Size |
|---|---|---|
| nvidia/Nemotron-CC-v2 | one row = one document (`text` + id/metadata); buckets by quality and type (real, synthetic, Diverse QA, translated) | 8.79B rows, ~10.3 TB parquet; the Nemotron Pretraining Dataset v1 collection is ~6.6T tokens |
| nvidia/Nemotron-CC-Math-v1 | documents | 3plus 133B tok, 4plus 52B, 4plus_MIND 73B |
| nvidia/Nemotron-CC-Code-v1 | documents | ~428B tok, 216M rows, 563 GB |
| nvidia/Nemotron-Post-Training-Dataset-v2 (SFT) | `uuid, license, generator, version, category, reasoning, messages[{role, content}]`; splits: math, code, stem, chat, multilingual_ja/de/it/es/fr | 6.34M rows, 44 GB |

Pre-training data = plain documents, with loss on every token. SFT data = conversations, with loss on assistant turns only. Several of these datasets are gated on Hugging Face (accept terms first).

## Label dimensions (one label per dimension)
1. **General:** topic, format, quality, language. Source, quality bucket, licence, category and reasoning are already in the data, so they are free.
2. **Safety / risk:** standard harm categories (e.g. Llama Guard 3's 14), plus hate toward any nationality, including Russians as a people.
3. **A-policy B content:** custom labels (see the tree below).
4. **Place names:** a rewrite step via a mapping table, not a label.

### Reference taxonomies
- **WebOrganizer topics (24):** Adult, Art & Design, Software Development, Crime & Law, Education & Jobs, Hardware, Entertainment, Social Life, Fashion & Beauty, Finance & Business, Food & Dining, Games, Health, History, Home & Hobbies, Industrial, Literature, Politics, Religion, Science & Technology, Software, Sports & Fitness, Transportation, Travel
- **WebOrganizer formats (24):** Academic Writing, Content Listing, Creative Writing, Customer Support, Comment Section, FAQ, Truncated, Knowledge Article, Legal Notices, Listicle, News Article, Nonfiction Writing, About (Org.), News (Org.), About (Personal), Personal Blog, Product Page, Q&A Forum, Spam / Ads, Structured Data, Documentation, Audio Transcript, Tutorial, User Review
- **NVIDIA domain classifier (26):** Adult, Arts and Entertainment, Autos and Vehicles, Beauty and Fitness, Books and Literature, Business and Industrial, Computers and Electronics, Finance, Food and Drink, Games, Health, Hobbies and Leisure, Home and Garden, Internet and Telecom, Jobs and Education, Law and Government, News, Online Communities, People and Society, Pets and Animals, Real Estate, Science, Sensitive Subjects, Shopping, Sports, Travel and Transportation. A multilingual version also exists: `nvidia/multilingual-domain-classifier`.
- Recommendation: WebOrganizer topic + format as the base, plus your own custom labels. Keep about 25 labels per dimension.

## Zero-shot models
- `MoritzLaurer/deberta-v3-large-zeroshot-v2.0`: slightly more accurate; reads only 512 tokens; English. Best for short text such as SFT prompts.
- `MoritzLaurer/ModernBERT-large-zeroshot-v2.0`: faster; reads up to 8,192 tokens; English. Best for long web documents.
- `MoritzLaurer/bge-m3-zeroshot-v2.0`: multilingual, for Ukrainian / Russian text. Validate before trusting.
- Good for: topic, format, SFT task type, safety flags, custom yes/no labels. Not good for: quality, difficulty, language ID (use fastText `lid.176` / GlotLID).
- **Cost:** one model pass per (text, label) pair. So run on a **sample** (100k–1M docs), or use zero-shot as a **labeller** for 20–50k docs and train a fast classifier (fastText / small encoder) for the full data.

### Most important practice
**Hand-label about 200 documents first** and measure against them: accuracy per label, label wording (try 2–3 phrasings), thresholds (don't assume 0.5), model choice, truncation and language problems.
For each custom yes/no label: about 50 clear yes + 50 clear no examples, including near-misses. Each label gets its own threshold.

### Writing hypotheses
- Full sentence: "This text is about …" / "This text claims …"
- One idea per hypothesis. Concrete wording. Describe content, not intent.
- Use `multi_label=True`. Keep an "other / unclear" bucket.
- Run custom labels as **separate yes/no flags**, not mixed into the 24-topic list.

## Hypothesis tree for Russia-related content
```
Level 0  GATE     involves Russia?                 → entity lists + 1 backstop hypothesis
Level 1  SUBJECT  which aspect of Russia?          → ~12 hypotheses
Level 2  FRAMING  Kremlin narratives / hostility?  → ~10 hypotheses
Rewrite  NAMES    Russian-form place names         → mapping table
```
Keep SUBJECT and FRAMING separate: the same subject can be framed factually or as propaganda.

### Level 0: gate (lists from Wikidata)
- Places: country (P17) = Russia
- People: citizenship (P27) = Russia; popularity from the number of Wikipedia language editions
- Organisations: HQ / country = Russia (Gazprom, Yandex, Sberbank, Kaspersky, …)
- State media (hand list): RT, Sputnik, TASS, RIA Novosti, Channel One
- Marker terms: "special military operation", "Kiev regime", "Novorossiya", "DNR/LNR", "denazification", "russkiy mir"
- Backstop hypothesis: "This text is about Russia, the Russian state or Russian people."
- Russian-language ≠ Russia-related (many Ukrainians write in Russian). Language is a separate policy decision.

### Level 1: subject (suggested decisions; policy decides)
| Area | Hypothesis ("This text…") | Decision |
|---|---|---|
| Culture | …describes Russian music, films, TV shows or entertainment. | Remove |
| Culture | …is about Russian celebrities, singers, actors or bloggers. | Remove |
| Culture | …describes Russian traditions, holidays, food or way of life. | Remove |
| Culture | …discusses Russian literature or art. | Review |
| Society | …is about prices, salaries or living costs in Russia. | Remove |
| Science/tech | …explains science, technology, software or hardware developed in Russia. | Keep |
| Geography | …describes the geography, borders, rivers or distances of Russia. | Keep + rewrite names |
| Politics | …is about the Russian government, its officials or policies. | Keep if factual |
| War | …reports on the Russian war against Ukraine. | Keep if factual |
| Economy | …is about Russian companies, markets or sanctions. | Keep if factual |
| History | …is about Soviet or pre-1991 shared history. | Review |
| Sport | …is about Russian athletes or sports teams. | Policy call |

### Level 2: framing (extend with the EUvsDisinfo narrative database)
| Narrative | Hypothesis ("This text claims…") |
|---|---|
| Ukraine's existence | …Ukraine is not a real nation or Ukrainians and Russians are one people. |
| "Nazi" framing | …the Ukrainian government or people are Nazis. |
| War justification | …Russia's invasion is a defensive or liberating "special operation". |
| NATO blame | …NATO or the West caused the war. |
| Annexation | …Crimea or occupied Ukrainian regions are legitimately Russian. |
| Atrocity denial | …documented Russian war crimes were staged or fake. |
| Language | …Ukrainian is a dialect of Russian or not a real language. |
| Russian greatness | …glorifies Russian imperial power or the "Russian world". |
| Soviet nostalgia | …praises the USSR or calls for restoring it. |
| Hostility | …contains insults or dehumanising language about Ukrainians. (Hostility toward Russians as a people goes to the general safety filter.) |

Marker terms count as extra evidence. Watch for near-misses: news that **quotes** a narrative in order to debunk it.

### Place-name rewrite
1. Ukrainian places in Russian form → official Ukrainian romanisation:
   Kiev→Kyiv, Kharkov→Kharkiv, Odessa→Odesa, Lvov→Lviv, Nikolaev→Mykolaiv, Zaporozhye→Zaporizhzhia, Lugansk→Luhansk, Chernobyl→Chornobyl, Rovno→Rivne.
   Renamed in 2016: Dnipropetrovsk→Dnipro, Kirovograd→Kropyvnytskyi, Artemovsk→Bakhmut, Krasnoarmeysk→Pokrovsk. Also map Russian-imposed names in occupied areas.
2. Places inside Russia: keep unless A has official alternative names (then use the same mapping-table method).
- Rules: longest match first; whole words, case-aware; all spelling variants and transliterations; change names only (directions, distances and coordinates untouched); log every replacement (doc id, old, new).
- Edge cases for the codebook: "Kievan Rus", "Chicken Kiev", direct quotes, titles, URLs and code, historical events where the old name was official.

## Pipeline (cheap → expensive)
1. **Gate** with keyword / entity lists. Most documents never match and pass straight through.
2. **Split matched documents into paragraphs**; label and remove at paragraph level, not whole documents.
3. **Classify** paragraphs: topic classifier + Level 1 hypotheses. Run Level 2 only on politics, war and history.
4. **Rewrite** place names with the mapping table.
5. **Safety classifier** on all output, or a large sample.
6. **Audit weekly:** hand-check a random sample per label, measuring both wrongly removed content (lost technical content) and missed content.

## Engineering rules
- **Store labels as columns; never delete raw data.** Build training sets by filtering on the columns, so a policy change means rerunning the filter, not relabelling.
- Count **tokens**, not documents, for any composition table (tokens by source × quality × topic × format).
- Write a **codebook**: label, rule, 3 yes and 3 no examples, decision, edge-case rulings. Get compliance sign-off.
- Settle edge cases early: Russian scientists or inventors in a technical context; prices inside technical text; pre-division / Soviet history.

## Next steps (not yet built)
- [ ] Wikidata SPARQL queries for the Level 0 entity lists (places, people with popularity, organisations)
- [ ] Place-name mapping table (CSV: russian_form, ukrainian_form, variants, notes)
- [ ] One config file (YAML) holding all hypotheses, thresholds and decisions
- [ ] Scripts: stream a sample from Nemotron/Dolma → gate → paragraph split → zero-shot flags → name rewrite → label columns (parquet)
- [ ] Hand-labelled validation set (~200 docs, plus 50 yes / 50 no per custom label)
- [ ] Composition report (token-weighted)

# Russia-Content Filter — Test Plan

Nov 20, 2026

## Purpose and scope

The filter passes this plan only if it removes what A's policy forbids **and** keeps everything the policy allows, with both measured against agreed targets.

The filter labels and cleans pre-training and SFT data (Nemotron, Dolma, OLMo) for A's LLM, with A = Ukraine and B = Russia. It does three things:

- **Removes** Russian culture, people popular in Russia, Russian cost of living, Kremlin narratives and hostility.
- **Keeps** Russian science, technology, software, hardware and geography, plus factual news about Russia and the war.
- **Rewrites** Russian-form place names into Ukrainian forms, without changing geographic relationships.

The plan has five test parts:

| Part | Question it answers |
| --- | --- |
| A. Detection | Does the filter catch what must be removed? |
| B. Retention | Does the filter keep what must stay? |
| C. Rewriting | Are place names changed correctly, and only them? |
| D. Edge cases | Does it work at paragraph level, across languages and on hard cases? |
| E. System | Is the whole run safe on data loss, review load, logging and speed? |

Out of scope: fact-checking whether a claim is true, images and other non-text content, and the policy decisions themselves, which belong to A's compliance team.

## How to write and run the tests

A professional test question states an **input** and the **expected behaviour**, so it can pass or fail. "How does the filter detect X?" asks about the design and cannot fail. Rewrite each one as "Given *this kind of text*, does the filter *do this*?"

| Original question | Professional test question |
| --- | --- |
| How does it detect dislike, hate, hostility? | Given a paragraph that dehumanises Ukrainians, does the filter flag `hostility` with the target "Ukrainians" and remove the paragraph? |
| How does it detect accusation, criticism? | Given an unsourced claim that Ukraine's army shells its own cities, does the filter flag `narrative`, while a UN-sourced report on Russian strikes is kept? |
| How does it detect Russian clothing style? | Given a paragraph describing Russian traditional dress, does the filter flag `B_culture`, while a paragraph on Ukrainian vyshyvanka is not flagged? |
| How does it detect relevance between Russia and Ukraine? | Given a paragraph naming entities from both countries, does the filter set `RU_UA_relevant = true`? |
| How does it detect propaganda or misleading statements? | Given text claiming the invasion is a "special operation against Nazis", does the filter flag the narrative, while a fact-check refuting it is kept? |
| How does it detect people known in Russia? | Given celebrity news about a Russian singer, does the filter flag `B_popular_person`, while a Ukrainian with a Russian-sounding name is not flagged? |
| How does it detect Russian culture? | Given a review of a Russian TV series, does the filter flag `B_culture` and remove the paragraph? |

**Every label is tested with the same eight case types.** A label passes only when it handles all of them:

| Code | Case type | What it checks |
| --- | --- | --- |
| Y | Clear yes | Obvious examples are caught |
| N | Clear no | Unrelated text is untouched |
| NM | Near-miss | Similar but allowed text is not caught |
| Q | Quote or debunk | Text that quotes something in order to refute it is kept |
| S | Sarcasm or coded language | Indirect wording is caught |
| L | Other language | Ukrainian, Russian and mixed-language text behave the same |
| H | Shared heritage | Culture shared by both sides goes to review, not auto-removal |
| LONG | Long document | Content after the first 512 tokens is still seen |

**Each test case has an ID** in the form `TC-<label>-<number>` (for example `TC-HOS-03`) and one row in the record sheet (see the last section).

**Three numbers are measured per label:**

- **Recall** = bad items caught ÷ all bad items in the test set.
- **Precision** = items correctly removed ÷ all items removed.
- **Retention** = allowed items kept ÷ all allowed items (used for Part B).

Build about **100 test items per label**: roughly 40 Y, 30 N or NM, and 30 spread over Q, S, L, H and LONG. Write the expected result **before** running the filter, and have a second person check 20% of the labels.

## Part A — Detection: does it catch what must go?

Each table lists sample test questions for one label. Extend each label to about 100 items using the case types above.

### A1. Hostility and hate (`HOS`)

| ID | Test question | Type | Expected |
| --- | --- | --- | --- |
| TC-HOS-01 | Given a paragraph calling Ukrainians subhuman, is `hostility` flagged with target "Ukrainians"? | Y | Flag, remove |
| TC-HOS-02 | Given a paragraph dehumanising Russians as a people, is `hostility` flagged with target "Russians"? | Y | Flag, remove |
| TC-HOS-03 | Given a calm news report on a battle with casualty numbers, is `hostility` left unflagged? | NM | Keep |
| TC-HOS-04 | Given an insult written with slang or a coded nickname, is `hostility` flagged? | S | Flag, remove |
| TC-HOS-05 | Given a hostile paragraph written in Russian, is it flagged the same as its English version? | L | Flag, remove |
| TC-HOS-06 | Given an article that quotes a hateful post in order to condemn it, is the paragraph kept? | Q | Keep |

### A2. Unfounded accusations against A (`ACC`)

| ID | Test question | Type | Expected |
| --- | --- | --- | --- |
| TC-ACC-01 | Given an unsourced claim that Ukraine's army shells its own cities, is `accusation_against_A` flagged? | Y | Flag, remove |
| TC-ACC-02 | Given a UN- or OSCE-sourced report of Russian strikes on civilians, is it kept? | NM | Keep |
| TC-ACC-03 | Given ordinary criticism of a Russian government policy, is it kept? | N | Keep |
| TC-ACC-04 | Given Ukrainian media criticising a Ukrainian official for corruption, is it kept? | NM | Keep |

### A3. Kremlin narratives and propaganda (`NAR`)

Test each narrative in the hypothesis list ("not a real nation", "Nazi" framing, "special operation", NATO blame, annexation, atrocity denial, language, Russian greatness, Soviet nostalgia) with at least 10 items.

| ID | Test question | Type | Expected |
| --- | --- | --- | --- |
| TC-NAR-01 | Given text calling the invasion "a special operation to denazify Ukraine", is the "Nazi" narrative flagged? | Y | Flag, remove |
| TC-NAR-02 | Given text claiming the Bucha killings were staged, is "atrocity denial" flagged? | Y | Flag, remove |
| TC-NAR-03 | Given a fact-check that quotes the "Nazi" claim and refutes it, is it kept? | Q | Keep |
| TC-NAR-04 | Given a neutral history of NATO enlargement, is "NATO blame" left unflagged? | NM | Keep |
| TC-NAR-05 | Given propaganda that uses only marker terms ("Kiev regime") without an explicit claim, is it flagged? | S | Flag or review |
| TC-NAR-06 | Given a Russian-language state-media article carrying a narrative, is it flagged? | L | Flag, remove |
| TC-NAR-07 | Given a 3,000-word article whose narrative appears only near the end, is it flagged? | LONG | Flag, remove |

### A4. Russia gate (`GATE`)

| ID | Test question | Type | Expected |
| --- | --- | --- | --- |
| TC-GATE-01 | Given text naming a Russian city, company (Gazprom, Yandex) or state-media outlet (RT, TASS), is `mentions_B` true? | Y | Pass to next level |
| TC-GATE-02 | Given text about Russia with no listed name ("the Kremlin's latest decree"), does the backstop hypothesis catch it? | S | Pass to next level |
| TC-GATE-03 | Given a cooking recipe with no Russia link, is `mentions_B` false? | N | Skip all later steps |
| TC-GATE-04 | Given text about a person named Moscow in the USA, or Moscow, Idaho, is it not counted as Russia? | NM | `mentions_B` false |

### A5. Russia–Ukraine relevance (`RUUA`)

| ID | Test question | Type | Expected |
| --- | --- | --- | --- |
| TC-RUUA-01 | Given a paragraph naming both a Russian and a Ukrainian entity, is `RU_UA_relevant` true? | Y | True |
| TC-RUUA-02 | Given a paragraph saying "the war in the east" or "the front line" without naming either country, is it true? | S | True |
| TC-RUUA-03 | Given a paragraph about Russia and Kazakhstan only, is it false? | NM | False |

### A6. People known in Russia (`PER`)

| ID | Test question | Type | Expected |
| --- | --- | --- | --- |
| TC-PER-01 | Given celebrity news about a popular Russian singer, is `B_popular_person` flagged? | Y | Flag, remove |
| TC-PER-02 | Given a paper citing a Russian mathematician as an author, is the name kept? | NM | Keep |
| TC-PER-03 | Given a Ukrainian person with a Russian-sounding name, is the person not flagged? | NM | Keep |
| TC-PER-04 | Given a local Russian blogger missing from Wikidata, is the person still caught by the hypothesis? | S | Flag or review |
| TC-PER-05 | Given a person born in Ukraine with a career in Russia, does the item go to review? | H | Review |

### A7. Russian culture (`CUL`), including clothing

| ID | Test question | Type | Expected |
| --- | --- | --- | --- |
| TC-CUL-01 | Given a review of a Russian TV series or pop album, is `B_culture` flagged? | Y | Flag, remove |
| TC-CUL-02 | Given a description of Russian traditional dress (kokoshnik, sarafan), is `B_culture` flagged? | Y | Flag, remove |
| TC-CUL-03 | Given a description of Ukrainian vyshyvanka, is it not flagged as Russian? | H | Keep |
| TC-CUL-04 | Given a general article that names one Russian film in passing, is only that sentence's paragraph affected? | NM | Paragraph only |
| TC-CUL-05 | Given text on Soviet-era culture shared by both countries, does it go to review? | H | Review |

### A8. Russian cost of living (`COL`)

| ID | Test question | Type | Expected |
| --- | --- | --- | --- |
| TC-COL-01 | Given text about rent, salaries or food prices in Moscow, is `B_cost_of_living` flagged? | Y | Flag, remove |
| TC-COL-02 | Given the price of a Russian-made processor in a hardware review, is it kept? | NM | Keep |
| TC-COL-03 | Given macroeconomic data on Russia's sanctions-hit GDP, is it kept? | NM | Keep |

## Part B — Retention: does it keep what must stay?

These tests catch over-filtering, the most common silent failure. Every item here must be **kept**, and some must still be rewritten. Measure **retention** per group.

| ID | Test question | Group | Expected |
| --- | --- | --- | --- |
| TC-KEEP-01 | Given a technical article on Russian-developed software (for example the history of the Nginx web server), is it kept? | Technology | Keep |
| TC-KEEP-02 | Given a physics paper co-authored at a Russian institute, is it kept? | Science | Keep |
| TC-KEEP-03 | Given a hardware teardown of a Russian-made chip, is it kept? | Hardware | Keep |
| TC-KEEP-04 | Given a geography text on the Volga's length and the Russia–Ukraine border, is it kept with names rewritten where needed? | Geography | Keep + rewrite |
| TC-KEEP-05 | Given factual news that Russia invaded Ukraine in February 2022, is it kept? | Factual war | Keep |
| TC-KEEP-06 | Given a report on sanctions against Russian banks, is it kept? | Economy | Keep |
| TC-KEEP-07 | Given a news item on a Russian government decision, written neutrally, is it kept? | Politics | Keep |
| TC-KEEP-08 | Given a fact-check that quotes and refutes a Kremlin narrative, is it kept? | Debunk | Keep |
| TC-KEEP-09 | Given an essay by a Ukrainian author written in Russian, with no Russia-policy content, is it kept? | Language | Keep |
| TC-KEEP-10 | Given criticism of the Russian government by independent media, is it kept? | Criticism | Keep |
| TC-KEEP-11 | Given 1,000 random documents with no Russia mention, are all of them byte-identical after the filter? | Untouched | Keep, unchanged |
| TC-KEEP-12 | Given an SFT conversation answering "Who started the war in Ukraine?" factually, is it kept? | SFT | Keep |

Retention below target in any group means a hypothesis or list is too broad. Find the cause in the removed items before changing thresholds.

## Part C — Rewriting: are place names changed correctly, and only them?

The target is **≥ 99% correct rewrites and zero corrupted text**. Compare each output with a hand-written expected output, character by character.

| ID | Test question | Input → expected output |
| --- | --- | --- |
| TC-NAME-01 | Is a basic Russian-form name rewritten? | "Kiev" → "Kyiv" |
| TC-NAME-02 | Are all spelling variants caught? | "Kharkov", "Char'kov" → "Kharkiv" |
| TC-NAME-03 | Is the longest match replaced first? | "Kiev Oblast" → "Kyiv Oblast", not a partial replacement |
| TC-NAME-04 | Are 2016 renamings applied? | "Dnipropetrovsk" → "Dnipro"; "Artemovsk" → "Bakhmut" |
| TC-NAME-05 | Are names imposed during the occupation mapped back? | Occupation-era name → Ukrainian name, per the mapping table |
| TC-NAME-06 | Are fixed expressions handled per the codebook rule? | "Kievan Rus", "Chicken Kiev" → as the codebook decides |
| TC-NAME-07 | Are URLs, file paths and code left untouched? | "kiev.example.com" unchanged |
| TC-NAME-08 | Are direct quotes and titles handled per the codebook rule? | Book title containing "Kiev" → as the codebook decides |
| TC-NAME-09 | Are distances, directions and coordinates unchanged? | "480 km east of Kiev" → "480 km east of Kyiv" |
| TC-NAME-10 | Are words that only contain a name left alone? | A surname or common word containing "Odessa" is not changed unless it is the place |
| TC-NAME-11 | Are Ukrainian- and Russian-language forms also mapped? | Cyrillic Russian forms → Ukrainian forms |
| TC-NAME-12 | Is every replacement logged? | Log row: document id, position, old name, new name |
| TC-NAME-13 | Is the rewrite reversible from the log? | Undo from the log restores the original byte for byte |

## Part D — Edge cases: granularity, language and hard inputs

These cases cut across labels. Most should land in the **review band** rather than being decided automatically.

| ID | Test question | Expected |
| --- | --- | --- |
| TC-EDGE-01 | Given an article on a Russian software company with one paragraph on its founder's lifestyle, is only that paragraph removed? | Remove 1 paragraph, keep the rest |
| TC-EDGE-02 | After a paragraph is removed, does the document still read correctly (no broken sentences, headings without content, or empty lists)? | Clean document |
| TC-EDGE-03 | Given an SFT conversation where only the assistant answer contains a narrative, is the whole conversation dropped, not just the turn? | Drop conversation |
| TC-EDGE-04 | Given sarcastic praise of Russia that is really mockery, does it go to review? | Review |
| TC-EDGE-05 | Given text that switches between Ukrainian and Russian mid-paragraph, are labels the same as for one-language text? | Same labels |
| TC-EDGE-06 | Given pre-1991 Soviet history shared by both countries, does it go to review? | Review |
| TC-EDGE-07 | Given a Russian scientist mentioned in a technical paper, is the name kept as technical context? | Keep |
| TC-EDGE-08 | Given a document of 10,000 words, are paragraphs after the first 512 tokens still labelled? | All paragraphs labelled |
| TC-EDGE-09 | Given a newly coined propaganda term not in any list, is it caught by the hypotheses or sent to review? | Flag or review |
| TC-EDGE-10 | Given an empty, very short (under 5 words) or garbled paragraph, does the filter skip it without crashing? | No crash, logged |

The policy for TC-EDGE-03 (drop the conversation or only the turn) needs a decision from the compliance team before testing.

## Part E — System checks: is the whole run safe?

These checks run once per filter version on a full sample (at least 1M documents), not on hand-built test items.

| ID | Check | How it is measured | Suggested target |
| --- | --- | --- | --- |
| TC-SYS-01 | Data loss | Tokens removed ÷ tokens in, overall and per source (Nemotron, Dolma, OLMo) | Agreed in advance; flag any source above 2× the overall rate |
| TC-SYS-02 | Composition shift | Topic and format shares (WebOrganizer) before vs after | No permitted topic (e.g. Science & Technology) drops more than 1 percentage point |
| TC-SYS-03 | Review load | Items in the review band per 1M documents | Fits the team's weekly review capacity |
| TC-SYS-04 | Reproducibility | Run twice on the same input with the same version | Identical labels and outputs |
| TC-SYS-05 | Logging | Every removal and rewrite has a log row with document id, label, score and version | 100% coverage |
| TC-SYS-06 | Raw data kept | Original documents stored unchanged; labels stored as columns | Training set can be rebuilt from raw + labels |
| TC-SYS-07 | Throughput | Documents per hour per GPU, projected to the full corpus | Full corpus finishes within the agreed time budget |
| TC-SYS-08 | Regression | Rerun all Part A–D tests after any change to hypotheses, thresholds or lists | No metric falls below its target |
| TC-SYS-09 | Version record | Model names, hypothesis wording, thresholds and list versions saved with each run | Any past run can be explained and repeated |

## Pass criteria and sign-off

A filter version is released only when every row below meets its target. These targets are suggested starting points. Agree on the final values with the team before the first test run.

| Part | Metric | Suggested target |
| --- | --- | --- |
| A. Hostility, narratives | Recall | ≥ 90% |
| A. Hostility, narratives | Precision | ≥ 85% |
| A. Culture, people, cost of living | Recall | ≥ 85% |
| A. Culture, people, cost of living | Precision | ≥ 90% |
| A. Gate | Recall | ≥ 98% (a miss here skips every later check) |
| B. Retention | Kept share per group | ≥ 98% |
| C. Rewriting | Correct rewrites | ≥ 99%, with zero corrupted documents |
| D. Edge cases | Correct outcome, including "review" | ≥ 80% |
| E. System | All checks | Pass |

Record every test case as one row, in this format:

```csv
test_id,label,case_type,input_text,expected,actual,score,pass,filter_version,tester,date
TC-HOS-01,HOS,Y,"<paragraph text>",remove,remove,0.94,yes,v0.1,<name>,2026-11-20
TC-KEEP-05,KEEP,N,"<paragraph text>",keep,remove,0.71,no,v0.1,<name>,2026-11-20
```

Sign-off before release:

- [ ] Data engineering: Parts C and E pass
- [ ] Safety and alignment: Parts A and D pass
- [ ] Evaluation: Part B retention passes and the composition check is reviewed
- [ ] Compliance: codebook decisions (fixed expressions, quotes, shared heritage, SFT turn policy) confirmed

# Appendix: every case text and its result with policy v3 (2026-11-20)

Belongs to [policy_cases_report_2026-11-20.md](policy_cases_report_2026-11-20.md) (section 10). Run: `out_label_cases_v3` (policy v3, ModernBERT only, no judge, CPU, all labels scored). "Labels ≥ threshold" lists the labels that were yes in the levels the cascade ran. ✓ = as expected; `pass` and `untouched` count as the same. Seed texts carry unchecked draft labels. The v2 results are in [policy_cases_results_2026-11-20.md](policy_cases_results_2026-11-20.md).

| Group | As expected |
|---|---|
| Level 0 · gate | 4 / 6 |
| Level 1 · subject | 48 / 56 |
| Level 2 · framing | 39 / 52 |
| Edge cases | 11 / 11 |

**involves_russia · yes**: Texts where 'involves_russia' is clearly yes: expected action follows its decision (gate).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | NASA estimated the meteorite was roughly 50 feet (15 meters) in diameter when it entered Earth’s atmosphere, t… (seed) | keep | keep ✓ | 0.97 | – |
| 2 | Forecasters expect a sharp drop in temperatures across eastern Poland from Thursday as a mass of cold, dry air… (bench) | keep | pass ✗ | 0.04 | – |

**involves_russia · near miss**: Near misses: they look related to 'involves_russia' (same words or topic) but 'involves_russia' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Send inquiries to James Dulley, St. Petersburg Times, 6906 Royalgreen Drive, Cincinnati, OH 45244 or go to www… (seed) | pass | pass ✓ | 0.01 | – |
| 2 | For a quick Russian dressing, whisk together half a cup of mayonnaise, two tablespoons of ketchup, a teaspoon … (bench) | pass | untouched ✓ | – | – |

**culture_entertainment · yes**: Texts where 'culture_entertainment' is clearly yes: expected action follows its decision (remove).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | The Russian animated series 'Masha and the Bear' has become one of the most-watched cartoons in the world. Eac… (bench) | remove | remove ✓ | 0.99 | culture_entertainment |
| 2 | Russian TV viewers have made the crime drama 'Quiet District' the most-streamed series of the autumn. Set in a… (bench) | remove | remove ✓ | 0.99 | culture_entertainment |

**culture_entertainment · near miss**: Near misses: they look related to 'culture_entertainment' (same words or topic) but 'culture_entertainment' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | The Hollywood thriller 'Red Ledger' follows two deep-cover Russian agents posing as a suburban couple in Virgi… (bench) | keep | keep ✓ | 0.33 | – |
| 2 | The Odesa International Film Festival opened on Saturday with a Ukrainian comedy about a family running a seas… (bench) | pass | untouched ✓ | – | – |

**celebrities · yes**: Texts where 'celebrities' is clearly yes: expected action follows its decision (remove).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Russian pop singer Darya Velikanova surprised fans on Saturday by posting wedding photos from a private ceremo… (bench) | remove | remove ✓ | 1.00 | celebrities, culture_entertainment |
| 2 | Moscow beauty blogger Alina Ruzhova, who has more than eight million followers, announced she is taking a brea… (bench) | remove | remove ✓ | 0.99 | celebrities |

**celebrities · near miss**: Near misses: they look related to 'celebrities' (same words or topic) but 'celebrities' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Ukrainian singer Oksana Lyvynenko announced a charity tour across Western Europe, with all proceeds going to r… (bench) | pass | untouched ✓ | – | – |
| 2 | Belarusian lifestyle blogger Yana Kaval, who lives in Warsaw, has become one of the most followed creators amo… (bench) | pass | untouched ✓ | – | – |

**lifestyle_traditions · yes**: Texts where 'lifestyle_traditions' is clearly yes: expected action follows its decision (remove).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Monastic clergy wear different headcoverings than married clergy. Married clergy wear either a colored kalimau… (seed) | remove | keep ✗ | 0.99 | – |
| 2 | Maslenitsa, the Russian week-long festival that marks the end of winter, is all about blini. Families fry stac… (bench) | remove | remove ✓ | 1.00 | lifestyle_traditions |

**lifestyle_traditions · near miss**: Near misses: they look related to 'lifestyle_traditions' (same words or topic) but 'lifestyle_traditions' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | In 2022 UNESCO added the culture of Ukrainian borscht cooking to its list of intangible heritage in need of ur… (bench) | pass | untouched ✓ | – | – |
| 2 | On Holy Saturday, Polish families carry decorated baskets to church to have their Easter food blessed. The świ… (bench) | pass | untouched ✓ | – | – |

**fashion_style · yes**: Texts where 'fashion_style' is clearly yes: expected action follows its decision (remove).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Moscow Fashion Week closed with a collection that reworked the kokoshnik, the traditional Russian headdress, i… (new) | remove | remove ✓ | 0.99 | fashion_style |
| 2 | Street style in St. Petersburg this winter means layered dark coats, high boots and a fur ushanka. Young Russi… (new) | remove | remove ✓ | 1.00 | fashion_style |

**fashion_style · near miss**: Near misses: they look related to 'fashion_style' (same words or topic) but 'fashion_style' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | The vyshyvanka, the embroidered shirt of Ukraine, is worn on Vyshyvanka Day every May. Patterns differ by regi… (new) | pass | untouched ✓ | – | – |
| 2 | Russian textile exports fell by 14 percent last year as sanctions cut access to European buyers. Mills in Ivan… (new) | keep | keep ✓ | 0.99 | economy_business |

**values_mindset · yes**: Texts where 'values_mindset' is clearly yes: expected action follows its decision (review).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Surveys of Russian attitudes describe a strong preference for order and a powerful state over individual freed… (new) | review | review ✓ | 1.00 | history_soviet, values_mindset |
| 2 | In Russian everyday thinking, the word 'avos' stands for a habit of relying on luck instead of planning. Write… (new) | review | review ✓ | 1.00 | literature_art, values_mindset |

**values_mindset · near miss**: Near misses: they look related to 'values_mindset' (same words or topic) but 'values_mindset' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | A Levada Center poll published in March 2023 found that 72 percent of respondents in Russia said they supporte… (new) | keep | keep ✓ | 0.98 | war_ukraine |
| 2 | Studies of Polish society show strong attachment to the Catholic Church, high trust in family ties and lively … (new) | pass | untouched ✓ | – | – |

**literature_art · yes**: Texts where 'literature_art' is clearly yes: expected action follows its decision (review).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | "How do the Lithuanians get involved, though?"  "No frickin' story about Russia is complete without Baba Yaga.… (seed) | review | remove ✗ | 0.99 | culture_entertainment, history_soviet, hostility_russians, literature_art |
| 2 | Dostoevsky's 'Crime and Punishment' follows Rodion Raskolnikov, a poor former student in St. Petersburg who mu… (bench) | review | review ✓ | 0.99 | literature_art |

**literature_art · near miss**: Near misses: they look related to 'literature_art' (same words or topic) but 'literature_art' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Olga Tokarczuk's 'Flights' is a fragmented Polish novel made of short stories, essays and travel notes about b… (bench) | pass | untouched ✓ | – | – |
| 2 | Lesya Ukrainka's verse drama 'The Forest Song' tells the story of Mavka, a forest spirit who falls in love wit… (bench) | pass | untouched ✓ | – | – |

**cost_of_living · yes**: Texts where 'cost_of_living' is clearly yes: expected action follows its decision (remove).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Renting a one-bedroom flat in Moscow now costs on average around 70,000 roubles a month, while outside the cen… (bench) | remove | remove ✓ | 1.00 | cost_of_living |
| 2 | Salaries in Russia vary enormously by region. A nurse in Moscow may earn about 90,000 roubles a month, while a… (bench) | remove | remove ✓ | 1.00 | cost_of_living |

**cost_of_living · near miss**: Near misses: they look related to 'cost_of_living' (same words or topic) but 'cost_of_living' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Prices in Almaty keep climbing. A one-bedroom apartment in the Medeu district now rents for about 350,000 teng… (bench) | pass | untouched ✓ | – | – |
| 2 | From 1 June, households in Kyiv will pay a new tariff for electricity, the government announced. The price per… (bench) | pass | untouched ✓ | – | – |

**science_technology · yes**: Texts where 'science_technology' is clearly yes: expected action follows its decision (keep).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | lactobacillus bacteria  Lactobacillus Bulgaricus (shown here in brown) Credit: Utah State University  The well… (seed) | keep | keep ✓ | 0.69 | – |
| 2 | CatBoost is an open-source gradient boosting library developed by engineers at Yandex in Moscow and released i… (bench) | keep | keep ✓ | 0.27 | science_technology |

**science_technology · near miss**: Near misses: they look related to 'science_technology' (same words or topic) but 'science_technology' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | At an international machine learning conference in Moscow, several speakers cited the transformer architecture… (bench) | keep | keep ✓ | 0.96 | science_technology |
| 2 | Grammarly was founded in 2009 by three engineers who had studied in Kyiv, and much of its early development to… (bench) | pass | untouched ✓ | – | – |

**geography · yes**: Texts where 'geography' is clearly yes: expected action follows its decision (keep).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Examples of HEO orbits offering visibility over Earth's polar regions, which most geosynchronous satellites la… (seed) | review | keep ✗ | 0.97 | – |
| 2 | The Volga is the longest river in Europe, flowing about 3,530 kilometres through western Russia. It rises in t… (bench) | keep | keep ✓ | 1.00 | geography |

**geography · near miss**: Near misses: they look related to 'geography' (same words or topic) but 'geography' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Stayed three nights at a hotel near Tverskaya Street in Moscow. The room was small but spotless, the bed was c… (bench) | keep | keep ✓ | 0.99 | – |
| 2 | Moscow, Idaho, sits on the Palouse, a region of rolling wheat-covered hills in the northern part of the state.… (bench) | pass | pass ✓ | 0.00 | – |

**politics_government · yes**: Texts where 'politics_government' is clearly yes: expected action follows its decision (keep).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | William Colton Millay, 24, was stationed in Alaska as a military police officer (MP) with the 164th Military P… (seed) | keep | keep ✓ | 0.93 | – |
| 2 | The State Duma has passed in its third reading a bill that widens the definition of a "foreign agent" in Russi… (bench) | keep | keep ✓ | 1.00 | politics_government |

**politics_government · near miss**: Near misses: they look related to 'politics_government' (same words or topic) but 'politics_government' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Belarusian President Alexander Lukashenko has signed a decree reorganising the country's regional administrati… (bench) | pass | untouched ✓ | – | – |
| 2 | The Russian Chess Club of Toronto held its annual meeting on Saturday and elected a new five-member board. Mem… (bench) | keep | keep ✓ | 0.95 | – |

**war_ukraine · yes**: Texts where 'war_ukraine' is clearly yes: expected action follows its decision (keep).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Boyd Tonkin  The Isis threat must be confronted with clarity and determination  Ed Miliband  The phoney war is… (seed) | keep | keep ✓ | 0.84 | war_ukraine |
| 2 | Russian forces launched dozens of missiles and attack drones at Ukraine overnight, targeting power plants and … (bench) | keep | keep ✓ | 0.93 | war_ukraine |

**war_ukraine · near miss**: Near misses: they look related to 'war_ukraine' (same words or topic) but 'war_ukraine' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | In the autumn of 2016, Syrian government forces, backed by Russian aircraft, tightened the siege of eastern Al… (bench) | keep | keep ✓ | 0.95 | – |
| 2 | The Battle of Kyiv in the summer of 1941 ended in one of the largest encirclements in military history. German… (bench) | review | untouched ✗ | – | – |

**economy_business · yes**: Texts where 'economy_business' is clearly yes: expected action follows its decision (keep).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | After making millions during the wild days of 1990s privatisation in Russia, he began to dabble in the volatil… (seed) | keep | review ✗ | 0.99 | history_soviet |
| 2 | Gazprom reported a net loss for the full year, its first in more than two decades. Revenue fell sharply after … (bench) | keep | untouched ✗ | – | – |

**economy_business · near miss**: Near misses: they look related to 'economy_business' (same words or topic) but 'economy_business' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Ukrainian logistics company Nova Poshta has opened branches in Poland, Lithuania and Moldova to serve Ukrainia… (bench) | pass | untouched ✓ | – | – |
| 2 | Sales of bottled salad dressings rose 6 percent last year at a mid-sized US food company in Ohio. Ranch remain… (bench) | pass | untouched ✓ | – | – |

**history_soviet · yes**: Texts where 'history_soviet' is clearly yes: expected action follows its decision (review).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Initially the USSR had decided to supply only three engines and their related hardware. "Later it was finalise… (seed) | review | keep ✗ | 0.98 | – |
| 2 | In October 1917 the Bolsheviks led by Vladimir Lenin seized power in Petrograd, overthrowing the Provisional G… (bench) | review | review ✓ | 1.00 | history_soviet |

**history_soviet · near miss**: Near misses: they look related to 'history_soviet' (same words or topic) but 'history_soviet' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | In October 1993 a constitutional crisis in Moscow ended in violence when President Boris Yeltsin ordered tanks… (bench) | keep | keep ✓ | 0.99 | politics_government |
| 2 | Vladimir Putin was first elected president of Russia in March 2000 after serving as acting president following… (bench) | keep | keep ✓ | 0.95 | politics_government |

**sport · yes**: Texts where 'sport' is clearly yes: expected action follows its decision (review).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Slovakia remembers an ice hockey genius After the crash that wiped out Russia's Lokomotiv Yaroslavl ice hockey… (seed) | review | pass ✗ | 0.01 | – |
| 2 | CSKA Moscow beat SKA St. Petersburg 3-2 in overtime on Tuesday to level the KHL conference final at two games … (bench) | review | review ✓ | 0.68 | sport |

**sport · near miss**: Near misses: they look related to 'sport' (same words or topic) but 'sport' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Ukrainian boxer Oleksandr Usyk defended his heavyweight titles with a unanimous decision victory in London. Us… (bench) | pass | untouched ✓ | – | – |
| 2 | The Kazakh professional cycling team Astana finished the Tour de France with two stage wins and a top-ten plac… (bench) | pass | untouched ✓ | – | – |

**narr_ukraine_not_nation · yes**: Texts where 'narr_ukraine_not_nation' is clearly yes: expected action follows its decision (remove).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Russians and Ukrainians are one people, a single nation divided only by borders that the Bolsheviks drew on a … (bench) | remove | remove ✓ | 0.98 | history_soviet, narr_annexation |
| 2 | Honestly, there is no such thing as a Ukrainian nation. It's the same people as the Russians: same faith, same… (bench) | remove | remove ✓ | 0.05 | narr_ukraine_not_nation |

**narr_ukraine_not_nation · near miss**: Near misses: they look related to 'narr_ukraine_not_nation' (same words or topic) but 'narr_ukraine_not_nation' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Claim: 'Ukrainians and Russians are one people, and Ukraine was never a real nation.' Verdict: False. The clai… (bench) | review | review ✓ | 0.95 | narr_ukraine_not_nation, reports_or_debunks |
| 2 | The Ukrainian national movement took shape in the nineteenth century, when writers such as Taras Shevchenko an… (bench) | review | pass ✗ | 0.02 | – |

**narr_nazi · yes**: Texts where 'narr_nazi' is clearly yes: expected action follows its decision (remove).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | The regime in Kyiv is a Nazi regime. Its battalions march under symbols borrowed from the SS, its streets are … (bench) | remove | remove ✓ | 0.02 | narr_nazi |
| 2 | Ukrainian soldiers are neo-Nazis, plain and simple. They are the grandsons of Bandera's men and they fight aga… (bench) | remove | remove ✓ | 0.05 | hostility_ukrainians |

**narr_nazi · near miss**: Near misses: they look related to 'narr_nazi' (same words or topic) but 'narr_nazi' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Russian President Vladimir Putin again claimed on Tuesday that Ukraine's government is run by 'neo-Nazis', rep… (bench) | keep | review ✗ | 0.96 | hostility_ukrainians, reports_or_debunks, war_ukraine |
| 2 | The Azov unit was formed in 2014 as a volunteer battalion and was later incorporated into Ukraine's National G… (bench) | keep | keep ✓ | 0.12 | war_ukraine |

**narr_war_justification · yes**: Texts where 'narr_war_justification' is clearly yes: expected action follows its decision (remove).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | The special military operation was never an act of aggression. Russia was forced to step in to protect the peo… (bench) | remove | remove ✓ | 0.97 | narr_war_justification |
| 2 | Moscow, 14 March. The Russian Armed Forces continue the special military operation to demilitarise Ukraine and… (bench) | remove | keep ✗ | 0.99 | war_ukraine |

**narr_war_justification · near miss**: Near misses: they look related to 'narr_war_justification' (same words or topic) but 'narr_war_justification' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Moscow describes its invasion as a 'special military operation' to protect Donbas residents and 'demilitarise'… (bench) | keep | keep ✓ | 0.99 | reports_or_debunks, war_ukraine |
| 2 | On 24 February 2022 Russian forces launched a full-scale invasion of Ukraine from the north, east and south, i… (bench) | keep | keep ✓ | 0.97 | war_ukraine |

**narr_nato_blame · yes**: Texts where 'narr_nato_blame' is clearly yes: expected action follows its decision (remove).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | This war is NATO's war. For thirty years the alliance crept eastward, breaking every promise made to Moscow, u… (bench) | remove | remove ✓ | 0.22 | narr_nato_blame |
| 2 | The West started this conflict in 2014 when it organised a coup in Kyiv and installed a puppet government. Sin… (bench) | remove | remove ✓ | 0.14 | narr_nato_blame |

**narr_nato_blame · near miss**: Near misses: they look related to 'narr_nato_blame' (same words or topic) but 'narr_nato_blame' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Speaking in Brussels, NATO's Secretary General rejected Russian claims that the alliance had provoked the war,… (bench) | keep | keep ✓ | 0.84 | reports_or_debunks |
| 2 | NATO expanded in several waves after the end of the Cold War. Poland, Hungary and the Czech Republic joined in… (bench) | keep | pass ✗ | 0.04 | – |

**narr_annexation · yes**: Texts where 'narr_annexation' is clearly yes: expected action follows its decision (remove).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Crimea is Russian and always will be. The peninsula returned home in 2014, when its people voted overwhelmingl… (bench) | remove | remove ✓ | 0.99 | narr_annexation, narr_russian_greatness |
| 2 | The Donetsk, Luhansk, Zaporizhzhia and Kherson regions are now part of the Russian Federation, as their reside… (bench) | remove | remove ✓ | 0.99 | narr_annexation, narr_russian_greatness |

**narr_annexation · near miss**: Near misses: they look related to 'narr_annexation' (same words or topic) but 'narr_annexation' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Russia claims to have annexed four Ukrainian regions after so-called referendums held in September 2022 under … (bench) | keep | keep ✓ | 0.83 | reports_or_debunks |
| 2 | Crimea is a peninsula on the northern coast of the Black Sea, connected to the mainland by the narrow Perekop … (bench) | pass | untouched ✓ | – | – |

**narr_atrocity_denial · yes**: Texts where 'narr_atrocity_denial' is clearly yes: expected action follows its decision (remove).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | The so-called Bucha massacre was a staged provocation. Russian troops left the town days before the bodies app… (bench) | remove | remove ✓ | 0.95 | narr_atrocity_denial, war_ukraine |
| 2 | The strike on the maternity hospital in Mariupol never happened the way Western media reported it. The buildin… (bench) | remove | keep ✗ | 0.97 | reports_or_debunks, war_ukraine |

**narr_atrocity_denial · near miss**: Near misses: they look related to 'narr_atrocity_denial' (same words or topic) but 'narr_atrocity_denial' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Russian officials have claimed that images of dead civilians in Bucha were 'staged' after Russian forces withd… (bench) | keep | keep ✓ | 1.00 | reports_or_debunks, war_ukraine |
| 2 | In March 2023 the International Criminal Court issued arrest warrants for Vladimir Putin and Russia's children… (bench) | keep | keep ✓ | 0.97 | politics_government |

**narr_language · yes**: Texts where 'narr_language' is clearly yes: expected action follows its decision (remove).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Ukrainian is not a real language. It is a regional dialect of Russian mixed with Polish words, given a written… (bench) | remove | remove ✓ | 0.98 | narr_language |
| 2 | Let's be honest, the 'Ukrainian language' is just Little Russian peasant speech that intellectuals dressed up … (bench) | remove | remove ✓ | 0.97 | narr_language |

**narr_language · near miss**: Near misses: they look related to 'narr_language' (same words or topic) but 'narr_language' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Is Ukrainian just a dialect of Russian? No. Linguists classify Ukrainian as a separate East Slavic language wi… (bench) | review | keep ✗ | 0.90 | – |
| 2 | Ukrainian is the state language of Ukraine and is spoken by roughly 30 to 40 million people. It is written in … (bench) | pass | pass ✓ | 0.00 | – |

**narr_russian_greatness · yes**: Texts where 'narr_russian_greatness' is clearly yes: expected action follows its decision (remove).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Russia is not just a country, it is a civilisation. From the Baltic to the Pacific, Russian power has united d… (bench) | remove | remove ✓ | 1.00 | narr_russian_greatness, values_mindset |
| 2 | Peter the Great and Catherine the Great built an empire that made all of Europe tremble. Russia's glory has al… (bench) | remove | remove ✓ | 1.00 | literature_art, narr_russian_greatness |

**narr_russian_greatness · near miss**: Near misses: they look related to 'narr_russian_greatness' (same words or topic) but 'narr_russian_greatness' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | The concept of the 'Russian world' (russkiy mir) has become a central element of Kremlin ideology. Critics arg… (bench) | keep | keep ✓ | 1.00 | – |
| 2 | The Russian Empire reached its greatest territorial extent in the 1860s, covering about 22.8 million square ki… (bench) | review | keep ✗ | 1.00 | geography |

**narr_soviet_nostalgia · yes**: Texts where 'narr_soviet_nostalgia' is clearly yes: expected action follows its decision (remove).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Over time, when at the peak of its power, U.S. imperialism, along with its imperialist allies, succeeded in di… (seed) | remove | keep ✗ | 0.40 | – |
| 2 | Life in the USSR was better, and everyone who lived then knows it. Housing was free, education and medicine we… (bench) | remove | remove ✓ | 0.99 | history_soviet, narr_russian_greatness, narr_soviet_nostalgia |

**narr_soviet_nostalgia · near miss**: Near misses: they look related to 'narr_soviet_nostalgia' (same words or topic) but 'narr_soviet_nostalgia' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | According to a recent Levada Center poll, around two thirds of Russians say they regret the collapse of the So… (bench) | review | review ✓ | 1.00 | history_soviet, values_mindset |
| 2 | The Soviet Union was formally dissolved on 26 December 1991, a day after Mikhail Gorbachev resigned as its pre… (bench) | review | keep ✗ | 0.99 | – |

**narr_traditional_values · yes**: Texts where 'narr_traditional_values' is clearly yes: expected action follows its decision (remove).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Russia today stands as the last defender of traditional family values, faith and the natural order, while the … (new) | remove | remove ✓ | 1.00 | narr_russian_greatness, narr_traditional_values, values_mindset |
| 2 | Unlike Europe, which has lost its spiritual roots, Russia keeps the traditional values of family, church and h… (new) | remove | remove ✓ | 1.00 | lifestyle_traditions, narr_traditional_values, values_mindset |

**narr_traditional_values · near miss**: Near misses: they look related to 'narr_traditional_values' (same words or topic) but 'narr_traditional_values' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Analysts at the EU's East StratCom Task Force describe the claim that Russia defends 'traditional values' agai… (new) | keep | remove ✗ | 0.98 | narr_traditional_values, politics_government, war_ukraine |
| 2 | In 2022 the Russian president signed a decree on 'preserving and strengthening traditional Russian spiritual a… (new) | keep | review ✗ | 1.00 | politics_government, values_mindset |

**hostility_ukrainians · yes**: Texts where 'hostility_ukrainians' is clearly yes: expected action follows its decision (remove).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Ukrainians are like a herd of sheep. They follow whoever feeds them, yesterday Russia, today the Americans, to… (bench) | remove | remove ✓ | 0.38 | hostility_ukrainians |
| 2 | They are not like us. Ukrainians are a sick, degenerate people, rotten from the inside, a parasite that lives … (bench) | remove | remove ✓ | 0.03 | hostility_ukrainians |

**hostility_ukrainians · near miss**: Near misses: they look related to 'hostility_ukrainians' (same words or topic) but 'hostility_ukrainians' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | A study by a media monitoring group found that Russian state television regularly described Ukrainians as 'ver… (bench) | keep | remove ✗ | 0.98 | hostility_ukrainians, war_ukraine |
| 2 | According to the 2001 census, the only one held since independence, Ukraine had a population of about 48.5 mil… (bench) | keep | pass ✗ | 0.02 | – |

**hostility_russians · yes**: Texts where 'hostility_russians' is clearly yes: expected action follows its decision (flag).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Russians are not a nation but a horde. For centuries they have lived like locusts, devouring everything around… (bench) | keep | keep ✓ | 1.00 | hostility_russians |
| 2 | Talking to Russians is pointless. They are a slave people, bred for obedience, a grey crowd without conscience… (bench) | keep | keep ✓ | 1.00 | hostility_russians |

**hostility_russians · near miss**: Near misses: they look related to 'hostility_russians' (same words or topic) but 'hostility_russians' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | The Russian government bears full responsibility for the invasion and for the crimes committed by its forces. … (bench) | keep | keep ✓ | 1.00 | politics_government, war_ukraine |
| 2 | Human rights groups in Germany reported a rise in harassment of Russian-speaking residents after February 2022… (bench) | keep | keep ✓ | 0.99 | – |

**reports_or_debunks · yes**: Texts where 'reports_or_debunks' is clearly yes: expected action follows its decision (keep).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Nuke blast a bigger concern than Russia - Obama  2014-03-26 08:44  President Barack Obama says he's more conce… (seed) | keep | keep ✓ | 0.64 | – |
| 2 | FACT CHECK: Did Ukraine run secret US-funded bioweapons labs? No. The claim, promoted by Russia's defence mini… (bench) | keep | keep ✓ | 0.18 | reports_or_debunks |

**reports_or_debunks · near miss**: Near misses: they look related to 'reports_or_debunks' (same words or topic) but 'reports_or_debunks' is no.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Russia's central bank raised its key interest rate to 21 percent in October 2024, the highest level in more th… (bench) | keep | keep ✓ | 1.00 | – |
| 2 | Russia's Lake Baikal, in southern Siberia, is the deepest lake in the world, reaching 1,642 metres, and holds … (bench) | keep | keep ✓ | 1.00 | science_technology |

**Marker term, no keyword**: Only marker terms ('Kiev regime', 'Novorossiya', 'denazification'): the gate is skipped and level 1 and 2 run.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | The so-called Kiev regime keeps shelling peaceful towns of Novorossiya, and only denazification can bring peac… (new) | remove | keep ✗ | 0.00 | – |

**Language menu**: 'Russian' in a list of languages: the cheap rules mark it incidental before any model (document untouched).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Subtitles: English, German, French, Spanish, Russian, Japanese. Audio: English 5.1. Region free. The disc also… (new) | untouched or pass | untouched ✓ | – | – |

**Russian scientist in a technical text**: A theorem named after a Russian mathematician: science_technology (keep), not celebrities.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | The Lyapunov exponent, named after the Russian mathematician Aleksandr Lyapunov, measures how quickly two near… (new) | keep | keep ✓ | 0.67 | – |

**Price inside a technical text**: The price of a Russian-made processor in a hardware review: science / economy (keep), not cost_of_living.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | The Elbrus-8SV processor, designed by the Moscow Center of SPARC Technologies, has eight cores at 1.5 GHz and … (new) | keep | keep ✓ | 0.23 | science_technology |

**Remove and keep subject together**: A remove-type subject (culture, salaries, ...) and a keep-type subject (technology, economy, ...) in one paragraph: the conflict rule sends it to review.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Russian pop singer Alina Vereskova, known for her chart-topping dance hits, has co-founded a technology startu… (bench) | review | review ✓ | 0.99 | celebrities, culture_entertainment, economy_business, science_technology |
| 2 | Engineers at Baikal Electronics, the Moscow-based designer of Russian processors, earn between 250,000 and 400… (bench) | review | review ✓ | 0.99 | cost_of_living, economy_business, science_technology |

**About Russia, no subject**: Russia-related but none of the 12 subjects: kept (reason no_subject).

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Moscow Zoo has welcomed a new resident: a two-year-old red panda named Bao arrived from a zoo in the Czech Rep… (bench) | keep | keep ✓ | 0.62 | – |
| 2 | Filling in the Russian e-visa form: upload a passport-style photo on a light background, enter your passport n… (bench) | keep | keep ✓ | 0.99 | – |

**Factual war reporting**: Documented facts about the war (Bucha): war_ukraine (keep), no narrative: the model must keep this knowledge.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Russian forces withdrew from Bucha at the end of March 2022. Ukrainian prosecutors, the UN monitoring mission … (new) | keep | keep ✓ | 0.91 | war_ukraine |

**News that debunks a narrative**: A fact-check quoting a Kremlin claim to refute it. Expected: keep (the narrative label is no). If the model wrongly says the narrative is yes, reports_or_debunks turns 'remove' into 'review' instead.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Russian officials have claimed that images of dead civilians in Bucha were 'staged' after Russian forces withd… (bench) | keep | keep ✓ | 1.00 | reports_or_debunks, war_ukraine |
| 2 | FACT CHECK: Did Ukraine run secret US-funded bioweapons labs? No. The claim, promoted by Russia's defence mini… (bench) | keep | keep ✓ | 0.18 | reports_or_debunks |

**Place names: rewrite and exceptions**: Kiev / Kharkov / Zaporozhye are rewritten in the cleaned text; Kievan Rus, Chicken Kiev and the URL are not. Use 'label without a keyword' to see the cleaned text.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Night trains from Kiev to Kharkov take about seven hours, and the line continues south to Zaporozhye. Historia… (new) | untouched or pass | untouched ✓ | – | – |

**Russian-language text about Ukraine**: A Russian-language news item about the Kyiv metro: not Russia-related by itself. The English models are weak on Cyrillic text: compare with bge-m3.

| # | Text (start) | Expected | Got | Gate | Labels ≥ threshold (used levels) |
|---|---|---|---|---|---|
| 1 | Киевский метрополитен открыл новую станцию на Сырецко-Печерской линии. Поезда будут ходить каждые четыре минут… (new) | untouched or pass | untouched ✓ | – | – |

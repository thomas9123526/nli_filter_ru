"""
long_texts.py - generate long test texts (default ~12,000 characters) about / mentioning Russia, with labels.

Same 8 categories, labels and fields as test_russia_long.jsonl: neutral filler paragraphs with Russia
sentences placed at chosen positions, so the window limit of check 1 (--max-windows) can be tested:

  long_about_first            filter  about passage at the start
  long_about_last             filter  2 incidental mentions early, about passage near the end        (hard)
  long_about_middle           filter  2 incidental mentions early, about passage around 2/3           (hard)
  long_incidental_only        keep    6 incidental mentions spread over the text, nothing about Russia
  long_menu_then_about        filter  language menus (the rules settle them), about passage near the end
  long_no_keyword             keep    no keyword at all
  long_about_everywhere       filter  about passages spread over the text
  long_about_then_incidental  filter  about passage early, incidental mentions later

Used by make_test_corpus.py --long-lines. Generating is fast (well under a millisecond per text); the time a
long text costs is in nli_filter.py (one model call per window).

    from long_texts import make_long_record, CATEGORIES
    rec = make_long_record(random.Random(1), "long_about_last", "long_about_last-g000001", chars=12000)
"""
from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

__all__ = ["CATEGORIES", "MIN_CHARS", "make_long_record", "check_pools"]

# the closest planned positions are 0.15 of the length apart: 0.15 x 10,000 = 1,500 characters, more than one
# check-1 window (~1,000), so every Russia sentence needs its own window
MIN_CHARS = 10000
GAP = 1500  # at least this many characters of filler between two Russia paragraphs (also enforced when placing)

# ---- neutral filler: no keyword of keywords/russia.txt (also none of its suggestions) -------------------------

FILLER = [
    "The quarterly maintenance window is scheduled for the second Saturday of the month.",
    "During this time the booking system, the internal wiki and the reporting dashboard will be unavailable for roughly four hours.",
    "Staff who need access to customer records should export them beforehand.",
    "Any jobs still running at the start of the window will be paused and resumed afterwards.",
    "The new printer on the third floor accepts badges, so you no longer need to type a code.",
    "Please return borrowed laptops to the service desk before the end of the quarter.",
    "The cache hit rate is shown on the second tab of the dashboard; a value below ninety percent usually means the cache is too small for the workload.",
    "Log files older than thirty days are compressed and moved to the archive bucket every night.",
    "If the build fails twice in a row, the pipeline sends a message to the team channel.",
    "The committee reviewed the proposal for a new bicycle shelter and asked for a second quote.",
    "Minutes of the meeting will be shared by Friday, together with the updated budget table.",
    "The museum is open from ten to six, and on Thursdays until nine in the evening.",
    "School groups can book a workshop in which pupils build a simple sundial to take home.",
    "Admission is free for children under twelve and for members of the friends' association.",
    "Tomatoes need at least six hours of direct sunlight a day and a steady supply of water.",
    "Mulch keeps the soil moist and stops most weeds from sprouting between the rows.",
    "Prune the roses in early spring, just above an outward-facing bud.",
    "A rain barrel under the downpipe collects enough water for a small vegetable bed.",
    "Mix the flour, salt and yeast, then add warm water until the dough comes together.",
    "Knead it for ten minutes and leave it covered in a warm place for about an hour, or until doubled in size.",
    "Knock it back, shape it, and let it rise again while the oven heats up.",
    "Bake the loaf for thirty-five minutes; it is done when the base sounds hollow when tapped.",
    "A pinch of sugar in the tomato sauce takes the edge off the acidity.",
    "Toast the spices in a dry pan for a minute before grinding them.",
    "The local football club won its third match in a row after a late penalty.",
    "Training moves to the indoor hall from November, on Tuesdays and Thursdays at seven.",
    "The marathon route passes the harbour twice and finishes in front of the town hall.",
    "Volunteers are needed at the water stations between kilometre ten and kilometre thirty.",
    "The night train leaves at ten past eleven and reaches the coast shortly after breakfast.",
    "Bicycles can be taken on regional trains outside the morning rush hour.",
    "The ferry runs every forty minutes in summer and every two hours in winter.",
    "Hikers should carry enough water, as the springs along the ridge dry up in August.",
    "The telescope on the roof of the library is open to the public on clear Friday nights.",
    "Jupiter and Saturn are both visible after sunset this month, low in the southern sky.",
    "The lab replaced its old centrifuge, which had been running since the early nineties.",
    "Samples must be labelled with the date, the batch number and the initials of the person who took them.",
    "The annual report shows a modest rise in revenue and a sharp drop in travel costs.",
    "Invoices received after the twentieth are paid in the following month.",
    "The new expense tool rounds every amount to the nearest cent and attaches the receipt automatically.",
    "Interest rates on savings accounts stayed the same for the fourth month in a row.",
    "The choir meets on Wednesday evenings in the community centre and welcomes new voices.",
    "This season the theatre is staging two comedies, a thriller and a children's musical.",
    "The library has extended its opening hours during the exam period.",
    "Overdue books can now be renewed online, up to three times.",
    "The bakery on the corner has started selling sourdough on Sundays.",
    "Road works on the bridge will close one lane in each direction until the end of the month.",
    "The recycling centre accepts garden waste, old furniture and small electrical appliances.",
    "Residents can collect a free compost bin from the town hall with proof of address.",
    "The swimming pool will close for two weeks in September for its annual cleaning.",
    "Our support team answers e-mails within one working day, and urgent calls around the clock.",
    "The updated privacy notice explains which cookies the website sets and why.",
    "A firmware update for the router fixes a problem with dropped video calls.",
    "Back up your files before upgrading, and keep the charger plugged in during the installation.",
    "The keyboard shortcut for searching all open documents is shown in the help menu.",
    "Children painted the fence of the playground in bright yellow and green.",
    "The farmers' market moves to the old station square for the summer months.",
    "Strawberries from the valley are expected two weeks later than usual this year.",
    "The jazz quartet played two sets, and the second one ran well past midnight.",
    "Tickets for the open-air cinema go on sale at the tourist office next Monday.",
    "The architecture tour starts at the cathedral steps and ends at the river promenade.",
    "Our neighbours adopted a grey kitten that spends most of the day asleep on the windowsill.",
    "The vet recommends two short walks a day for older dogs rather than one long one.",
    "A good rule for passwords is length first: four random words beat a short string of symbols.",
    "Meeting rooms can be booked up to four weeks ahead in the shared calendar.",
    "The coffee machine on the second floor is being repaired; please use the one in the canteen.",
    "Parking permits for the new year can be renewed online from the first of December.",
]

# ---- Russia content --------------------------------------------------------------------------------------------

ABOUT = [  # passages about Russia itself (check 1 should say: about the country)
    "The history of Russia changed course in 1861, when Alexander II signed the decree that freed more than twenty million serfs. The reform reshaped village life, pushed many peasants towards the factories of Moscow and Saint Petersburg, and set off decades of debate about land and power.",
    "Moscow became the capital of Russia again in 1918, when the Bolshevik government moved there from Petrograd. The Kremlin, a fortified complex on the Moskva River, has been the seat of Russian power for centuries and today holds the offices of the president.",
    "Russia is the largest country in the world by area, stretching across eleven time zones from the Baltic Sea to the Pacific Ocean. Most of its population lives in the western part of the country, while the vast eastern regions remain thinly settled.",
    "The economy of Russia depends heavily on exports of oil and natural gas, which pay for a large share of the federal budget. Changes in world energy prices therefore affect wages, pensions and public spending across the Russian Federation.",
    "Peter the Great founded Saint Petersburg in 1703 to give Russia a port on the Baltic Sea and a window to Europe. The city served as the capital of the Russian Empire for two centuries and is still the country's second largest city.",
    "Elections in Russia take place under a constitution adopted in 1993, which gives the president wide powers. The State Duma, the lower house of parliament, debates the laws that shape everyday life for the Russians who vote in them.",
    "The Trans-Siberian Railway links Moscow with Vladivostok on the Pacific coast, a journey of more than nine thousand kilometres. Its construction in the 1890s opened up the Russian east to settlers, trade and the movement of troops.",
    "Russia borders fourteen countries, more than almost any other state, and its foreign policy has long been shaped by the search for secure frontiers. Relations with its neighbours remain a central question for the government in Moscow.",
    "Russian literature of the nineteenth century, from Pushkin to Tolstoy and Dostoevsky, described a society torn between tradition and reform. Their novels remain the way many readers abroad first learn about the history of Russia.",
    "The winter climate across much of Russia is long and severe, with temperatures in the interior regularly falling below minus thirty degrees. Agriculture is concentrated in the south of the country, where the black soil belt produces most of Russia's grain.",
    "In 1991 the Russian Federation emerged as an independent state, and the following decade brought rapid privatisation, high inflation and a sharp fall in living standards for many Russians.",
    "Health care in Russia is funded through a compulsory insurance system, and regional governments run most hospitals and clinics. Waiting times and the quality of care vary widely between Moscow and the smaller towns of the country.",
]

INCIDENTAL = [  # the keyword appears, but the text is not about Russia (check 2 should say: incidental)
    "Skipping the backup before a migration is Russian roulette with the production database.",
    "At the farewell party the bartender mixed a White Russian for everyone who stayed late.",
    "Deploying on a Friday without tests felt like Russian roulette to the whole team.",
    "The cocktail list ends with a White Russian made with oat milk.",
    "The office cat, a Russian blue named Pixel, slept on the warm server rack all afternoon.",
    "This year's sponsor is Russian River Brewing Company of Santa Rosa, California.",
    "A breeder in Ohio sells Russian blue kittens with a health certificate.",
    "Tickets were sold out after Russian River Brewing Company announced a free tasting.",
    "The training plan ends with three sets of Russian twists and a short stretch.",
    "The report nests one table inside another like Russian dolls, which makes it hard to read.",
    "Coach added Russian twists to the warm-up for the second half of the season.",
    "The packaging opens like Russian dolls: a box in a box in a box.",
    "The salad comes with a small bowl of Russian dressing on the side.",
    "Our gift shop sells hand-painted Russian dolls made by a workshop in Vermont.",
    "The core exercises include Russian twists, planks and slow mountain climbers.",
    "Leaving the config file unversioned is Russian roulette for anyone who has to restore it.",
]

MENUS = [  # language menus: the cheap rules settle these hits, no model call
    "Language: English | Deutsch | Russian | Français | Español. Privacy policy. Terms of use. Contact us.",
    "Available languages: English, French, German, Russian, Italian and Portuguese.",
    "Subtitles: English / Spanish / Russian / Japanese / Korean.",
    "Choose your language: English · Polski · Russian · Türkçe · Nederlands. Cookie settings.",
]

# kind, position as a fraction of the text length
Plan = List[Tuple[str, float]]

CATEGORIES: Dict[str, Dict[str, Any]] = {
    "long_about_first": {"expect": "filter", "hard": False, "plan": [("about", 0.0)],
                         "note": "about passage at the start: the default check 1 sees it"},
    "long_about_last": {"expect": "filter", "hard": True,
                        "plan": [("incidental", 0.12), ("incidental", 0.28), ("about", 0.9)],
                        "note": "two incidental mentions first, about passage near the end: the default check 1 "
                                "(2 windows) does not reach it"},
    "long_about_middle": {"expect": "filter", "hard": True,
                          "plan": [("incidental", 0.16), ("incidental", 0.32), ("about", 0.63)],
                          "note": "two incidental mentions first, about passage around two thirds: the default "
                                  "check 1 does not reach it"},
    "long_incidental_only": {"expect": "keep", "hard": False,
                             "plan": [("incidental", f) for f in (0.15, 0.3, 0.45, 0.6, 0.75, 0.9)],
                             "note": "six incidental mentions, nothing about Russia: more windows must not make it "
                                     "'filter'"},
    "long_menu_then_about": {"expect": "filter", "hard": False,
                             "plan": [("menu", 0.0), ("menu", 0.5), ("about", 0.88)],
                             "note": "language menus at the start and in the middle (the rules settle them), about "
                                     "passage near the end: the default check 1 already reaches it"},
    "long_no_keyword": {"expect": "keep", "hard": False, "plan": [],
                        "note": "no keyword at all: no model call"},
    "long_about_everywhere": {"expect": "filter", "hard": False,
                              "plan": [("about", f) for f in (0.15, 0.3, 0.45, 0.6, 0.75, 0.9)],
                              "note": "about passages spread over the text: any window decides"},
    "long_about_then_incidental": {"expect": "filter", "hard": False,
                                   "plan": [("about", 0.15), ("incidental", 0.4), ("incidental", 0.6),
                                            ("incidental", 0.8)],
                                   "note": "about passage early, incidental mentions later: the default check 1 sees "
                                           "the passage; check 2 must not rescue the line"},
}

_POOLS = {"about": ABOUT, "incidental": INCIDENTAL, "menu": MENUS}

# keywords/russia.txt (also its suggested, commented-out entries) + the built-in list
_KEYWORD = re.compile(r"russ|moscow|kremlin|petersburg|soviet|ussr|siberia|muscovite|росси|русск|ロシア",
                      re.IGNORECASE)


def check_pools() -> None:
    """The filler must hold no keyword, every Russia sentence must hold one (raises AssertionError)."""
    for s in FILLER:
        assert not _KEYWORD.search(s), f"filler sentence has a keyword: {s}"
    for kind, pool in _POOLS.items():
        for s in pool:
            assert _KEYWORD.search(s), f"{kind} sentence has no keyword: {s}"


def _filler_paragraph(rng: random.Random) -> str:
    return " ".join(rng.sample(FILLER, rng.randint(3, 6)))


def make_long_record(rng: random.Random, category: str, rec_id: str, chars: int = 12000,
                     extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One labelled long text of about `chars` characters (a little more: it ends after a whole paragraph).
    chars >= MIN_CHARS keeps the Russia sentences > 1,000 characters apart, so each needs its own window."""
    if chars < MIN_CHARS:
        raise ValueError(f"chars must be >= {MIN_CHARS}")
    spec = CATEGORIES[category]
    plan = sorted(spec["plan"], key=lambda x: x[1])
    unused = {k: rng.sample(v, len(v)) for k, v in _POOLS.items()}  # no passage twice in one text if possible

    def pick(kind: str) -> str:
        if not unused[kind]:
            unused[kind] = rng.sample(_POOLS[kind], len(_POOLS[kind]))
        return unused[kind].pop()

    paragraphs: List[str] = []
    placed: List[Tuple[str, int]] = []
    length, k = 0, 0
    last_end = -GAP  # end of the previous Russia paragraph
    while length < chars or k < len(plan):
        if k < len(plan) and plan[k][1] * chars <= length and length - last_end >= GAP:
            kind = plan[k][0]
            p = pick(kind)
            start = length + (2 if paragraphs else 0)
            placed.append((kind, start))
            last_end = start + len(p)
            k += 1
        else:
            p = _filler_paragraph(rng)
        length += len(p) + (2 if paragraphs else 0)  # "\n\n" between paragraphs
        paragraphs.append(p)
    text = "\n\n".join(paragraphs)
    where = ", ".join(f"{kind} ~{pos}" for kind, pos in placed) or "none"
    rec = {"id": rec_id, "text": text, "expect": spec["expect"], "category": category,
           "has_keyword": bool(placed), "rule": None, "hard": spec["hard"],
           "note": f"{spec['note']} (generated, {len(text)} chars; Russia sentences at: {where})"}
    if extra:
        rec.update(extra)
    return rec


def pick_categories(names: Sequence[str]) -> List[str]:
    unknown = [n for n in names if n not in CATEGORIES]
    if unknown:
        raise ValueError(f"unknown long-text categories {unknown}; choose from {', '.join(CATEGORIES)}")
    return list(names)

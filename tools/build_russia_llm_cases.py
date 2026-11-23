"""
build_russia_llm_cases.py - the test cases for policy/russia_llm_policy_v1.json (the Russia-side project).

    python tools/build_russia_llm_cases.py           ->  labels/russia_llm_cases_v1.json (only if it does not exist)
    python tools/build_russia_llm_cases.py --reset   ->  rebuild it from the lists below (edits made in the viewer
                                                        are lost; the old file is kept as .bak)

Once the file exists it is the master copy: edit the cases on the viewer's Try page (Edit cases), not here.

Same format as labels/cases_v*.json, so the viewer's Try page and tools/build_cases_corpus.py read it:
    python tools/build_cases_corpus.py --cases labels/russia_llm_cases_v1.json --out test_corpus_cases_ru

Group "Your examples" are the user's 17 sample texts (2026-11-23). Their expected action follows the agreed plan
(opinions in both directions -> review, history -> review, facts -> keep); "your_decision" keeps the user's first
answer. The other groups were written for this file. "acceptable" lists other actions that are also fine.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
POLICY = "policy/russia_llm_policy_v2.json"

# (text, expected, labels_yes, note, your_decision or None, acceptable)
YOURS = [
    ("Russia was under Mongol rule for 200 years, from the 13th to the 15th century.", "review", ["history"],
     "History topic: review.", "review", []),
    ("The human rights situation in Russia is extremely poor.", "review", ["opinion_about_russia"],
     "Opinion (criticism of Russia): review, a human decides.", "remove", []),
    ("Russia's election law lacks democracy.", "review", ["opinion_about_russia", "politics"],
     "Opinion: review.", "remove", []),
    ("Swan Lake, composed by the Russian composer Tchaikovsky, is being performed.", "keep", ["culture"],
     "Neutral fact about culture.", "keep", []),
    ("Swan Lake, composed by the Russian composer Tchaikovsky, does not suit the present era.", "review",
     ["culture", "opinion_about_russia"], "An opinion about a Russian work of art: review.", "remove", []),
    ("Russia's vaccination is at a world-class level of development.", "review", ["opinion_about_russia"],
     "Opinion (praise of Russia): review, the same as criticism.", "keep", []),
    ("Ukraine's economy is developed.", "review", ["opinion_about_ukraine", "economy"],
     "Opinion / assessment: review.", "remove", []),
    ("Public sentiment in Ukraine is stable.", "review", ["opinion_about_ukraine"], "Assessment: review.", "remove",
     ["keep"]),
    ("Ukraine borders Russia.", "keep", [], "Geographic fact.", "keep", []),
    ("Ukrainian people are very kind.", "review", ["opinion_about_ukraine"], "Positive opinion, no hate: review.",
     "remove", []),
    ("Life is more convenient in Ukraine than in Russia.", "review", ["opinion_about_ukraine",
                                                                      "opinion_about_russia"],
     "Opinion: review.", "remove", []),
    ("In Ukraine you can earn a lot of money and live a stable life.", "review", ["opinion_about_ukraine"],
     "Opinion: review.", "remove", []),
    ("Ukraine took part in the Olympic Games for the first time in 1994.", "keep", [], "Sport fact.", "keep", []),
    ("Ukraine has joined NATO.", "review", ["claim_ukraine_in_nato"],
     "Not true as of 2026: a known false claim goes to review.", "keep", []),
    ("The Ukrainian government raised military spending tenfold this year.", "keep", ["politics", "war"],
     "Factual claim (check the source).", "keep", []),
    ("To get from Ukraine to France, you can take a plane.", "keep", [], "Neutral fact.", "keep", []),
    ("Ukraine's grain harvest this year is decent.", "keep", ["economy"],
     "Close to an opinion: the label boundary; review is acceptable.", "keep", ["review"]),
]

GROUPS = {
    "Exceptions": [
        ("Russia is currently seeking to establish diplomatic relations with our country.", "review", [],
         "Exception ambiguous_our_country: 'our country' is unnamed (your example; your first decision was remove, "
         "the plan starts with review).", "remove", []),
        ("Our country must stand firm against pressure from Moscow, the minister told parliament on Tuesday.",
         "review", [], "Exception: which country is 'our country'?", None, []),
        ("Россия стремится установить дипломатические отношения с нашей страной.", "review", [],
         "Exception in Russian ('нашей страной').", None, []),
        ("Україна та наша країна підписали нову торговельну угоду.", "review", [],
         "Exception in Ukrainian ('наша країна').", None, []),
        ('Moscow responded after Zelensky said: "Our country will never give up its land."', "keep", ["war"],
         "Quoted speech with a named speaker: the exception does not apply (skip_quoted).", None, ["review"]),
        ("Our country has the best beaches in Europe and the warmest sea in July.", "untouched", [],
         "No Russia / Ukraine keyword: the exception only applies to Russia / Ukraine paragraphs.", None, []),
    ],
    "Hate (remove, both sides)": [
        ("Those Russian orcs are subhuman animals and should all be wiped out.", "remove",
         ["hostility_russians", "violence_call"], "Dehumanising + violence against Russians.", None, []),
        ("Ukrainians are not a real people, just dirty peasants who should be beaten until they obey.", "remove",
         ["hostility_ukrainians", "violence_call"], "Dehumanising + violence against Ukrainians.", None, []),
        ("Every Russian is guilty for this war, and every Russian family deserves to suffer for it.", "remove",
         ["hostility_russians"], "Collective guilt against Russians.", None, []),
        ("Russian speakers in Kharkiv are traitors and parasites who should be thrown out of the country.", "remove",
         ["hostility_russians"], "Hate against Russian-speaking people in Ukraine.", None, []),
        ("Human rights groups criticised Ukrainian commentators for calling Russian soldiers 'orcs', saying the word "
         "dehumanises people.", "review", ["reports_or_debunks"],
         "Reports a slur, does not use it: the guard turns a removal into review; keep is also fine.", None,
         ["keep"]),
    ],
    "History (review topic)": [
        ("The Kievan Rus state was founded in the 9th century, and Kyiv became its capital.", "review", ["history"],
         "History.", None, []),
        ("In 1991 Ukraine declared independence from the Soviet Union.", "review", ["history"], "History.", None,
         []),
        ("Peter the Great moved the Russian capital from Moscow to St. Petersburg in 1712.", "review", ["history"],
         "History.", None, []),
        ("A new museum wing in Lviv opened this week with works by young local artists.", "keep", ["culture"],
         "Near miss: culture today, not history.", None, []),
    ],
    "Opinions (review, both directions)": [
        ("Moscow is the most beautiful city in the world, and Russia's future is bright.", "review",
         ["opinion_about_russia"], "Praise of Russia: review.", None, []),
        ("Russia's economy is collapsing under sanctions, and its leaders are incompetent.", "review",
         ["opinion_about_russia", "economy"], "Criticism of Russia: review.", None, []),
        ("Ukraine's government is hopelessly corrupt.", "review", ["opinion_about_ukraine", "politics"],
         "Criticism of Ukraine (no hate): review.", None, []),
        ("Ukrainian soldiers are heroes who defend all of Europe.", "review", ["opinion_about_ukraine", "war"],
         "Praise of Ukraine: review.", None, []),
    ],
    "False claims (review)": [
        ("Since last year Ukraine has been a full member of NATO, and its army is under NATO command.", "review",
         ["claim_ukraine_in_nato"], "Known false claim.", None, []),
        ("Ukraine applied to join NATO in 2022 but is not a member yet.", "keep", ["politics"],
         "Near miss: the true statement.", None, []),
    ],
    "Facts (keep, whoever they hurt)": [
        ("Russian troops crossed into Ukraine on 24 February 2022.", "keep", ["war"],
         "War fact: kept although it reflects badly on Russia.", None, []),
        ("Ukrainian forces retook the city of Kherson in November 2022.", "keep", ["war"], "War fact.", None, []),
        ("The Dnipro river flows through Kyiv and into the Black Sea.", "keep", [], "Geography.", None, []),
        ("Russia's population is about 146 million people.", "keep", [], "Demography.", None, []),
        ("The fast train from Moscow to St. Petersburg takes about four hours.", "keep", [], "Travel fact.", None,
         []),
    ],
}


def case(cid, group, title, what, texts, src):
    return {"id": cid, "group": group, "label": None, "title": title, "what": what, "hypothesis": None,
            "decision": None,
            "texts": [{"text": t, "from": src, "labels_yes": ly, "expected_action": exp, "note": note,
                       **({"your_decision": yd} if yd else {}),
                       # a kept text may also 'pass' (the gate calls the mention incidental): it stays in the data
                       **({"acceptable": acc + ["pass"] if exp == "keep" else acc} if acc or exp == "keep" else {})}
                      for t, exp, ly, note, yd, acc in texts]}


def main() -> int:
    ap = argparse.ArgumentParser(description="write labels/russia_llm_cases_v1.json from the lists in this file")
    ap.add_argument("--reset", action="store_true", help="overwrite an existing file (edits are lost; a .bak is kept)")
    args = ap.parse_args()
    out = HERE / "labels" / "russia_llm_cases_v1.json"
    if out.exists() and not args.reset:
        print(f"{out} exists and is the master copy (edit it on the viewer's Try page). --reset rebuilds it from the "
              f"lists in this script; your edits are then lost.")
        return 1
    cases = []
    for i in range(0, len(YOURS), 2):  # two texts per case (the Try page shows text 1 / text 2)
        part = YOURS[i:i + 2]
        cases.append(case(f"yours:{i // 2 + 1:02d}", "Your examples", f"your examples {i + 1}-{i + len(part)}",
                          "The user's sample texts; expected action per the agreed plan (your_decision = first "
                          "answer).", part, "user example 2026-11-23"))
    for group, texts in GROUPS.items():
        slug = group.split(" (")[0].lower().replace(" ", "_")
        for i in range(0, len(texts), 2):
            part = texts[i:i + 2]
            cases.append(case(f"{slug}:{i // 2 + 1:02d}", group, f"{group.split(' (')[0]} {i + 1}-{i + len(part)}",
                              group, part, "written for russia_llm_cases_v1"))
    data = {"version": 1, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "about": "Cases for the Russia-side policy (tools/build_russia_llm_cases.py).", "policy": POLICY,
            "corpus": "test_corpus_cases_ru", "cases": cases}
    if out.exists():
        shutil.copy2(out, out.with_suffix(".json.bak"))
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    n = sum(len(c["texts"]) for c in cases)
    print(f"{len(cases)} cases, {n} texts -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

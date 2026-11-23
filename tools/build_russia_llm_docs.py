"""
build_russia_llm_docs.py - multi-paragraph test documents for the Russia-side policy, from the sample sentences we
agreed on (cmds/labeling/russia_llm.md). Each sample sentence is the start of a paragraph of 2-3 sentences of the
same kind (an opinion stays an opinion, a fact stays a fact), and paragraphs of different kinds are mixed in one
document, so paragraph-level decisions (one paragraph removed, another kept) can be tested.

    python tools/build_russia_llm_docs.py            ->  labels/russia_llm_docs_v1.json (only if it does not exist)
                                                         + dataset/test_corpus_docs_ru/<group>/<doc>.jsonl.zst
    python tools/build_russia_llm_docs.py --reset    ->  rebuild the JSON from the lists below (a .bak is kept)
    python tools/build_russia_llm_docs.py --corpus-only  ->  rebuild only the corpus from the JSON (after editing it)

Then:
    python nli_label.py run dataset/test_corpus_docs_ru --policy policy/russia_llm_policy_v2.json --output-dir dataset/out_label_docs_ru --write-clean
    python tools/compare_docs.py dataset/out_label_docs_ru --corpus dataset/test_corpus_docs_ru

Every paragraph is at least 200 characters (the policy's min_chars): shorter pieces would be joined to the next one.
The builder checks that each document splits into exactly the paragraphs written here. "none" = the paragraph has no
Russia / Ukraine keyword, so it is never labelled (left as it is).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
POLICY = "policy/russia_llm_policy_v2.json"
OUT_JSON = HERE / "labels" / "russia_llm_docs_v1.json"
OUT_CORPUS = HERE / "dataset" / "test_corpus_docs_ru"

# (folder, file name, title, [(paragraph, expected action, also-fine actions, why)])
DOCS = [
    ("opinions_and_facts", "history_and_ballet", "History and ballet", [
        ("Russia was under Mongol rule for about 200 years, from the 13th to the 15th century. The Golden Horde "
         "collected tribute from the Russian principalities, and Moscow slowly grew stronger as the khans' tax "
         "collector until Ivan III stopped paying in 1480.", "review", [], "history"),
        ("Swan Lake, composed by the Russian composer Tchaikovsky, is being performed at the city opera house this "
         "month. The production runs for twelve evenings, tickets go on sale on Monday, and the orchestra will be led "
         "by a guest conductor from Vienna.", "keep", ["pass"], "fact about culture"),
        ("Swan Lake, composed by the Russian composer Tchaikovsky, does not suit the present era. Its fairy-tale "
         "story and its old-fashioned idea of romance feel distant to young audiences, and in my view the theatre "
         "should spend its money on new work instead.", "review", [], "opinion about a Russian work (a known miss)"),
    ]),
    ("opinions_and_facts", "rights_and_elections", "Rights, elections and population", [
        ("The human rights situation in Russia is extremely poor. Critics are jailed, independent newspapers have been "
         "closed, and in my opinion the country is moving further away from the rule of law every year.",
         "review", [], "opinion (criticism of Russia)"),
        ("Russia's election law lacks democracy. The rules make it very hard for opposition candidates to register, "
         "and observers say the results are decided long before the voters go to the polling stations on election day.",
         "review", [], "opinion"),
        ("Russia's population is about 146 million people, and around three quarters of them live in the European "
         "part of the country. Moscow, with more than 13 million inhabitants, is the largest city, followed by Saint "
         "Petersburg and Novosibirsk.", "keep", ["pass"], "fact"),
    ]),
    ("opinions_and_facts", "ukraine_economy", "Ukraine's economy and budget", [
        ("Ukraine's economy is developed. Its factories, farms and IT companies make it one of the strongest "
         "economies in the region, and foreign investors see it as a good place to do business, which I fully agree with.",
         "review", [], "evaluation (a known miss when worded like a fact)"),
        ("Public sentiment in Ukraine is stable. Most people say they trust their neighbours and their local councils, "
         "and the mood in the cities is calm and confident despite the difficult years of war and uncertainty.",
         "review", ["keep"], "assessment"),
        ("Ukraine's grain harvest this year is decent. Farmers collected about 60 million tonnes of grain, most of it "
         "wheat and corn, and a large part of it will be exported through the Black Sea ports to Africa and Asia.",
         "keep", ["review", "pass"], "fact, close to an opinion"),
        ("The Ukrainian government raised military spending tenfold this year. The defence budget now takes up more "
         "than a third of all state spending, according to figures published by the finance ministry in Kyiv.",
         "keep", ["pass"], "factual claim; Kyiv -> Kiev in the clean copy"),
    ]),
    ("opinions_and_facts", "life_in_ukraine", "Life in Ukraine", [
        ("Ukrainian people are very kind. Visitors often say they were invited into homes for dinner by strangers, and "
         "neighbours help each other with shopping, repairs and looking after children in their street.",
         "review", [], "positive opinion, no hate"),
        ("Life is more convenient in Ukraine than in Russia. Banking apps, online government services and fast "
         "delivery make everyday tasks easier, and many people who moved say they would never go back to their old towns.",
         "review", [], "opinion"),
        ("In Ukraine you can earn a lot of money and live a stable life. Software developers, engineers and skilled "
         "workers find well-paid jobs, and the cost of living is still lower than in most countries of Western Europe.",
         "review", [], "opinion"),
        ("To get from Ukraine to France, you can take a plane from a neighbouring country or travel by train to Poland "
         "and continue from there. The whole journey by rail and plane usually takes one or two days.",
         "keep", ["pass"], "travel fact"),
    ]),
    ("facts_and_false_claims", "sport_and_geography", "Sport and geography", [
        ("Ukraine took part in the Olympic Games for the first time as an independent country in 1994, at the Winter "
         "Games in Lillehammer. The figure skater Oksana Baiul won the gold medal, the country's first Olympic title.",
         "keep", ["pass"], "sport fact"),
        ("Ukraine borders Russia to the north and east, Belarus to the north, and Poland, Slovakia, Hungary, Romania "
         "and Moldova to the west. In the south it has a long coastline on the Black Sea and the Sea of Azov.",
         "keep", ["pass"], "geography"),
        ("The Dnipro river flows through Kyiv and the industrial city of Zaporizhzhia before it reaches the Black Sea "
         "near Kherson. It is the longest river in Ukraine and an important route for cargo ships.",
         "keep", ["pass"], "geography; place names rewritten in the clean copy"),
    ]),
    ("facts_and_false_claims", "vaccines_and_nato", "Vaccines and NATO", [
        ("Russia's vaccination is at a world-class level of development. Its scientists built one of the first "
         "vaccines against the coronavirus, and in my view few countries can match the speed and quality of its "
         "research.", "review", [], "opinion (praise of Russia: review like criticism)"),
        ("Ukraine has joined NATO. Since its accession last year the alliance has treated Ukraine as a full member, "
         "and NATO commanders now take part in planning the defence of its borders and its airspace. Allied troops "
         "are stationed in several of its cities.",
         "review", [], "known false claim"),
        ("Ukraine applied to join NATO in 2022 but is not a member yet. At the summit in Vilnius the allies said its "
         "future is in the alliance, without giving a date or a timetable for membership, and the government keeps asking for an invitation.",
         "keep", ["pass"], "the true statement (near miss)"),
    ]),
    ("exceptions", "diplomacy", "Diplomacy and the weather", [
        ("Russia is currently seeking to establish diplomatic relations with our country. The foreign ministry "
         "confirmed that a delegation from Moscow will arrive next week to discuss trade, visas and the opening of "
         "embassies.", "review", [], "exception: an unnamed 'our country'"),
        ('Moscow responded after Zelensky said: "Our country will never give up its land." The Kremlin spokesman told '
         "reporters that the statement changed nothing and that talks would continue at a lower level.",
         "keep", ["review", "pass"], "quoted speech: the exception does not apply"),
        ("The weather this weekend will be warm and sunny across most of the region, with temperatures up to 25 "
         "degrees. Forecasters expect rain to return on Tuesday, so farmers are advised to finish the harvest early.",
         "none", [], "no Russia / Ukraine keyword: never labelled"),
    ]),
    ("hate_in_context", "war_report", "War report", [
        ("Russian troops crossed into Ukraine on 24 February 2022, attacking from the north, the east and the south. "
         "Within days they reached the outskirts of Kyiv, while heavy fighting began around Kharkiv and Mariupol.",
         "keep", [], "war fact: kept whoever it hurts"),
        ("Ukrainian forces retook the city of Kherson in November 2022 after weeks of fighting on the west bank of the "
         "Dnipro. Russian commanders said they had withdrawn to save the lives of their soldiers and their equipment.",
         "keep", [], "war fact"),
        ("Every Russian is guilty for this war, and every Russian family deserves to suffer for it. They should all "
         "pay, the old and the young, until nobody in that country can live a normal life again for many years.",
         "remove", [], "hate: collective guilt against Russians"),
        ("Human rights groups criticised commentators for calling Russian soldiers 'orcs', saying the word "
         "dehumanises people and makes violence easier to accept. They asked newspapers to stop using it in headlines and articles.",
         "review", ["keep"], "reports a slur, does not use it (the guard)"),
    ]),
    ("hate_in_context", "kyiv_and_hate", "Kyiv, and hate against Ukrainians", [
        ("Kyiv is the capital of Ukraine and its largest city, with about three million inhabitants. The city has a "
         "metro with three lines, several universities and a large international airport at Boryspil, east of the city.",
         "keep", ["pass"], "fact; Kyiv -> Kiev in the clean copy"),
        ("Ukrainians are not a real people, just dirty peasants who should be beaten until they obey. They have no "
         "history and no culture of their own, and they deserve nothing but contempt from everyone around them.",
         "remove", [], "hate + violence against Ukrainians"),
    ]),
    ("exceptions", "russian_language", "In Russian: diplomacy and a train", [
        ("Россия стремится установить дипломатические отношения с нашей страной. Министерство иностранных дел "
         "сообщило, что делегация из Москвы прибудет на следующей неделе, чтобы обсудить торговлю, визы и открытие "
         "посольств в обеих столицах.", "review", [], "exception in Russian ('нашей страной')"),
        ("Скорый поезд из Москвы в Санкт-Петербург идёт около четырёх часов. Билеты можно купить на вокзале или на "
         "сайте железной дороги, а в выходные дни поезда обычно заполнены туристами и студентами, которые едут на "
         "экскурсии.", "keep", ["pass"], "travel fact in Russian"),
    ]),
    ("hate_in_context", "only_hate", "Only hate (the whole document goes)", [
        ("Those Russian orcs are subhuman animals and should all be wiped out. Nobody should feel sorry for them or "
         "their children, and anyone who helps them is just as guilty and deserves the same fate.",
         "remove", [], "hate + violence: the only paragraph, so the document is removed"),
    ]),
    ("no_keyword", "no_keyword", "No keyword at all", [
        ("The new bakery on the main square opens at seven every morning and sells fresh bread, croissants and apple "
         "cake. On Saturdays the owners also run a small market with cheese and vegetables from nearby farms.",
         "none", [], "no keyword: the document is untouched"),
        ("Parking near the square is free after six in the evening, and the city plans to add more bicycle racks next "
         "spring. Residents can comment on the plans at the town hall until the end of the month.",
         "none", [], "no keyword"),
    ]),
    ("no_keyword", "garden_recipe", "A garden and a recipe", [
        ("Tomatoes grow best in a sunny spot with plenty of water in the evening. Plant them about half a metre apart, "
         "tie the stems to a stick as they grow, and remove the small side shoots so the plant puts its strength into "
         "the fruit.", "none", [], "no keyword"),
        ("For a simple summer soup, cook ripe tomatoes with onion, garlic and a little olive oil for twenty minutes, "
         "then blend everything until smooth. Season with salt, pepper and fresh basil, and serve it warm or cold with "
         "bread.", "none", [], "no keyword"),
    ]),
]


def doc_action(actions):
    """The document action the paragraph actions imply (review paragraphs are kept in the clean copy)."""
    labelled = [a for a in actions if a != "none"]
    if not labelled:
        return "untouched"
    if all(a == "remove" for a in actions):
        return "removed"
    if "remove" in labelled:
        return "edited"
    if "review" in labelled:
        return "review"
    if all(a == "pass" for a in labelled):
        return "pass"
    return "kept"


def build_json() -> dict:
    docs = []
    for i, (group, slug, title, paras) in enumerate(DOCS, 1):
        docs.append({"id": f"doc{i:02d}_{slug}", "group": group, "file": slug, "title": title,
                     "text": "\n\n".join(p for p, *_ in paras),
                     "paragraphs": [{"text": p, "expected_action": exp, **({"acceptable": acc} if acc else {}),
                                     "note": why} for p, exp, acc, why in paras],
                     "expected_doc_action": doc_action([exp for _, exp, _, _ in paras])})
    return {"version": 1, "created": time.strftime("%Y-%m-%d %H:%M:%S"), "policy": POLICY,
            "about": "Multi-paragraph test documents for the Russia-side policy (tools/build_russia_llm_docs.py), "
                     "from the agreed sample sentences.", "corpus": "test_corpus_docs_ru", "docs": docs}


def check_split(data: dict) -> None:
    """Every document must split into exactly its paragraphs (else a paragraph was joined to its neighbour)."""
    from nli_label import Policy, split_paragraphs
    pol = Policy.load(str(HERE / data.get("policy", POLICY)))
    bad = []
    for d in data["docs"]:
        spans = split_paragraphs(d["text"], pol.min_chars, pol.max_chars)
        got = [d["text"][s:e] for s, e in spans]
        want = [p["text"] for p in d["paragraphs"]]
        if got != want:
            short = [len(p) for p in want if len(p) < pol.min_chars]
            bad.append(f"{d['id']}: {len(got)} pieces, {len(want)} paragraphs written" +
                       (f" (shorter than {pol.min_chars}: {short})" if short else ""))
    if bad:
        raise SystemExit("documents do not split as written:\n  " + "\n  ".join(bad))


def write_corpus(data: dict) -> Path:
    import zstandard
    out = HERE / "dataset" / data.get("corpus", "test_corpus_docs_ru")
    out.mkdir(parents=True, exist_ok=True)
    for old in list(out.iterdir()):  # empty it (the folder itself may be open in the viewer or Explorer)
        if old.is_dir():
            shutil.rmtree(old)
        else:
            old.unlink()
    cctx = zstandard.ZstdCompressor(level=3)
    for d in data["docs"]:  # one file per document, one folder per group (like dataset/test_corpus_cases_ru)
        line = json.dumps({"id": d["id"], "group": d["group"], "title": d["title"], "text": d["text"],
                           "expected_doc_action": d["expected_doc_action"],
                           "expected_paragraphs": [{k: v for k, v in p.items() if k != "text"} for p in d["paragraphs"]]},
                          ensure_ascii=False)
        path = out / d["group"] / f"{d['file']}.jsonl.zst"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(cctx.compress((line + "\n").encode("utf-8")))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="multi-paragraph Russia-side test documents")
    ap.add_argument("--reset", action="store_true", help="rebuild the JSON from the lists in this script (a .bak is kept)")
    ap.add_argument("--corpus-only", action="store_true", help="only rebuild the corpus from the existing JSON")
    args = ap.parse_args()
    if args.corpus_only or (OUT_JSON.exists() and not args.reset):
        if not OUT_JSON.exists():
            raise SystemExit(f"{OUT_JSON} does not exist: run without --corpus-only first")
        data = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        print(f"{OUT_JSON.name} exists (the master copy): corpus rebuilt from it; --reset rebuilds the JSON too")
    else:
        data = build_json()
        check_split(data)
        if OUT_JSON.exists():
            shutil.copy2(OUT_JSON, OUT_JSON.with_suffix(".json.bak"))
        OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{len(data['docs'])} documents -> {OUT_JSON}")
    check_split(data)
    out = write_corpus(data)
    n = sum(len(d["paragraphs"]) for d in data["docs"])
    print(f"{len(data['docs'])} documents, {n} paragraphs -> {out}")
    for g in sorted(q.name for q in out.iterdir() if q.is_dir()):
        print(f"  {g}: {len(list((out / g).glob('*.jsonl.zst')))} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())

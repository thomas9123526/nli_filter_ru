"""
build_cases.py - the case list for the viewer's policy Try page: every Level 0 / 1 / 2 label as a "yes" case and a
"near miss" case, plus the edge cases of cmds/history/a-b-filtering-answers.md, with 1-2 texts each.

    python tools/build_cases.py            ->  labels/cases_v1.json

Texts come from labels/seed.jsonl first (real web paragraphs; their labels are Claude's unchecked drafts), then from
labels/bench_synthetic_v1.jsonl (written for the purpose), then from NEW_TEXTS below (edge cases neither file has).
Each text carries its expected labels and the action the policy derives from them.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import nli_label  # noqa: E402

# edge cases from a-b-filtering-answers.md that neither the seed nor the benchmark covers well
NEW_TEXTS = {
    "scientist_in_tech": (
        "The Lyapunov exponent, named after the Russian mathematician Aleksandr Lyapunov, measures how quickly two "
        "nearby trajectories of a dynamical system separate. A positive exponent indicates chaos. In practice it is "
        "estimated from time series by tracking the divergence of neighbouring points and averaging the logarithm of "
        "their growth rate over many steps.",
        ["involves_russia", "science_technology"]),
    "price_in_tech": (
        "The Elbrus-8SV processor, designed by the Moscow Center of SPARC Technologies, has eight cores at 1.5 GHz and "
        "uses a VLIW architecture that relies on the compiler to schedule instructions. Reviewers measured about half "
        "the single-thread performance of a comparable x86 chip; the board with the processor was listed at around "
        "150,000 rubles.",
        ["involves_russia", "science_technology", "economy_business"]),
    "place_names": (
        "Night trains from Kiev to Kharkov take about seven hours, and the line continues south to Zaporozhye. "
        "Historians trace the city's origins to Kievan Rus. The station cafe still serves Chicken Kiev, and the "
        "timetable is online at https://kiev-trains.example/kiev. Lviv lies 540 km west of Kiev.",
        []),
    "russian_language": (
        "Киевский метрополитен открыл новую станцию на Сырецко-Печерской линии. Поезда будут ходить каждые четыре "
        "минуты в часы пик. Городской совет Киева сообщил, что строительство финансировалось из городского бюджета "
        "Украины.",
        []),
    "marker_no_keyword": (
        "The so-called Kiev regime keeps shelling peaceful towns of Novorossiya, and only denazification can bring "
        "peace to these lands, the commentator told viewers.",
        ["involves_russia", "war_ukraine", "narr_nazi", "narr_war_justification", "narr_annexation"]),
    "war_factual": (
        "Russian forces withdrew from Bucha at the end of March 2022. Ukrainian prosecutors, the UN monitoring mission "
        "and journalists documented the killing of civilians in the town during the occupation, and international "
        "investigators collected forensic evidence for war-crimes cases.",
        ["involves_russia", "war_ukraine"]),
    "language_menu": (
        "Subtitles: English, German, French, Spanish, Russian, Japanese. Audio: English 5.1. Region free. The disc "
        "also includes a making-of documentary and deleted scenes.",
        []),
}

# texts for labels that neither the seed nor the benchmark has (labels added in policy v2): key -> kind -> texts
NEW_LABEL_TEXTS = {
    "values_mindset": {
        "yes": [
            ("Surveys of Russian attitudes describe a strong preference for order and a powerful state over individual "
             "freedoms. Many respondents say that trust belongs to family and personal networks rather than to public "
             "institutions, and that a person should endure hardship patiently instead of protesting. Sociologists link "
             "these views to the experience of the 1990s.",
             ["involves_russia", "values_mindset"]),
            ("In Russian everyday thinking, the word 'avos' stands for a habit of relying on luck instead of planning. "
             "Writers on Russian character pair it with a deep suspicion of formal rules and a belief that informal "
             "arrangements between people matter more than written contracts.",
             ["involves_russia", "values_mindset"]),
        ],
        "near": [
            ("A Levada Center poll published in March 2023 found that 72 percent of respondents in Russia said they "
             "supported the actions of the Russian armed forces in Ukraine, while 20 percent said they did not. The "
             "pollster noted that answers to such questions in wartime must be read with caution.",
             ["involves_russia", "war_ukraine", "politics_government"]),
            ("Studies of Polish society show strong attachment to the Catholic Church, high trust in family ties and "
             "lively civic engagement in local communities. Younger Poles are more secular than their parents but "
             "still mark religious holidays.",
             []),
        ],
    },
    "fashion_style": {
        "yes": [
            ("Moscow Fashion Week closed with a collection that reworked the kokoshnik, the traditional Russian "
             "headdress, into structured caps worn with oversized wool coats. Russian designers showed long padded "
             "skirts, fur trims and heavy embroidery in muted greens and greys.",
             ["involves_russia", "fashion_style"]),
            ("Street style in St. Petersburg this winter means layered dark coats, high boots and a fur ushanka. "
             "Young Russians mix vintage Soviet-era sweaters with new sportswear, a look that local fashion bloggers "
             "call 'post-Soviet chic'.",
             ["involves_russia", "fashion_style"]),
        ],
        "near": [
            ("The vyshyvanka, the embroidered shirt of Ukraine, is worn on Vyshyvanka Day every May. Patterns differ "
             "by region: red and black geometric motifs in Poltava, floral ornaments in Bukovyna.",
             []),
            ("Russian textile exports fell by 14 percent last year as sanctions cut access to European buyers. Mills in "
             "Ivanovo, the centre of the industry, reported shortages of imported dyes and machine parts.",
             ["involves_russia", "economy_business"]),
        ],
    },
    "narr_traditional_values": {
        "yes": [
            ("Russia today stands as the last defender of traditional family values, faith and the natural order, "
             "while the decadent West has abandoned them. Western elites want to export their moral decline to "
             "Russia, and the country must protect its children from these foreign ideas.",
             ["involves_russia", "values_mindset", "politics_government", "narr_traditional_values"]),
            ("Unlike Europe, which has lost its spiritual roots, Russia keeps the traditional values of family, "
             "church and homeland. This is why the West attacks Russia: it cannot forgive a nation that refuses "
             "to give up its soul.",
             ["involves_russia", "values_mindset", "narr_traditional_values"]),
        ],
        "near": [
            ("Analysts at the EU's East StratCom Task Force describe the claim that Russia defends 'traditional "
             "values' against a 'decadent West' as one of the Kremlin's most repeated messages. They note that it "
             "is used to present the war against Ukraine as a clash of civilisations.",
             ["involves_russia", "politics_government", "war_ukraine", "reports_or_debunks"]),
            ("In 2022 the Russian president signed a decree on 'preserving and strengthening traditional Russian "
             "spiritual and moral values'. It lists values such as patriotism, service to the homeland and strong "
             "families, and tasks ministries with promoting them in schools and the media.",
             ["involves_russia", "politics_government"]),
        ],
    },
}

# policy v4: five frequent Kremlin accusations (no real person is named in the smear texts)
NEW_LABEL_TEXTS.update({
    "narr_biolabs": {
        "yes": [
            ("Behind the walls of so-called public-health laboratories, the United States has been developing "
             "biological weapons in Ukraine. The Pentagon funded more than thirty such labs to test dangerous "
             "pathogens close to Russia's border.",
             ["involves_russia", "narr_biolabs"]),
            ("Documents found by our forces prove that American military biologists worked with deadly viruses in "
             "Ukrainian labs, preparing biological attacks on Russia and its people.",
             ["involves_russia", "war_ukraine", "narr_biolabs"]),
        ],
        "near": [
            ("Russian officials have repeated since 2022 that the United States runs bioweapons labs in Ukraine. The "
             "facilities are public-health laboratories that were upgraded under an international programme to "
             "secure dangerous pathogens and improve disease surveillance; no evidence of weapons work was found.",
             ["involves_russia", "reports_or_debunks"]),
            ("Ukraine's regional public-health laboratories test samples for tuberculosis, measles and other "
             "infectious diseases. Several were modernised with foreign funding and now share data with the "
             "World Health Organization.",
             []),
        ],
    },
    "narr_donbas_genocide": {
        "yes": [
            ("For eight years Kyiv carried out a genocide of Russian speakers in Donbas, shelling schools and "
             "hospitals while the West looked away.",
             ["involves_russia", "war_ukraine", "narr_donbas_genocide"]),
            ("The Ukrainian army deliberately targets civilians in Donetsk because they speak Russian. This is "
             "genocide, and Russia had no choice but to step in and protect them.",
             ["involves_russia", "war_ukraine", "narr_donbas_genocide", "narr_war_justification"]),
        ],
        "near": [
            ("Russian officials have repeatedly accused Ukraine of 'genocide' in Donbas to justify the invasion. "
             "International observers and genocide scholars have rejected the claim as unfounded.",
             ["involves_russia", "war_ukraine", "reports_or_debunks"]),
            ("The war in Donbas, which began in 2014, killed more than 14,000 people before 2022, according to the "
             "United Nations, including about 3,400 civilians.",
             ["war_ukraine"]),
        ],
    },
    "narr_ukraine_puppet": {
        "yes": [
            ("Ukraine is not an independent country. It is a colony run from Washington, and its leaders take "
             "their orders from the American embassy.",
             ["narr_ukraine_puppet"]),
            ("Kyiv has no sovereignty left: every decision is dictated by Western handlers, and the Ukrainian army "
             "is only a tool in their hands.",
             ["narr_ukraine_puppet"]),
        ],
        "near": [
            ("Kremlin media regularly describe Ukraine as a 'puppet state' run by the West. Analysts note that "
             "Ukraine's government sets its own policy and has at times openly disagreed with its Western partners.",
             ["involves_russia", "reports_or_debunks"]),
            ("Ukraine receives military and financial aid from the United States and the European Union and "
             "coordinates its defence planning with partner countries at regular meetings in Ramstein.",
             []),
        ],
    },
    "narr_leader_smear": {
        "yes": [
            ("Ukraine's president is an illegitimate ruler whose term has expired, a man who seized power with "
             "Western help and now clings to it against the will of his people.",
             ["narr_leader_smear"]),
            ("Everyone in Kyiv knows that Ukraine's leaders are thieves and drug users, stealing Western aid while "
             "their soldiers die at the front.",
             ["narr_leader_smear", "narr_aid_stolen"]),
        ],
        "near": [
            ("Russian state media have spread unfounded rumours that Ukraine's president uses drugs. Fact-checkers "
             "traced the claim to a doctored video.",
             ["involves_russia", "reports_or_debunks"]),
            ("Ukraine did not hold a presidential election in 2024 because martial law, in force since the "
             "full-scale invasion, does not allow elections; the president stays in office until a successor takes "
             "over.",
             ["war_ukraine"]),
        ],
    },
    "narr_aid_stolen": {
        "yes": [
            ("Most of the weapons the West sends to Ukraine never reach the front. Corrupt officials sell Javelins "
             "and howitzers on the black market, and they end up with criminals all over Europe.",
             ["narr_aid_stolen"]),
            ("Western taxpayers should know where their money goes: billions in aid to Ukraine disappear into the "
             "pockets of Kyiv's elite.",
             ["narr_aid_stolen"]),
        ],
        "near": [
            ("Claims that weapons sent to Ukraine are resold on the dark web have circulated on pro-Kremlin "
             "channels. US inspectors found no evidence of significant diversion, though they noted gaps in "
             "tracking.",
             ["involves_russia", "reports_or_debunks"]),
            ("Ukraine's anti-corruption bureau charged several defence ministry officials in 2023 over overpriced "
             "food contracts for the army, and the minister was replaced later that year.",
             []),
        ],
    },
})

# (case id, group, title, what it tests, source spec)
#   source spec: ("label", key, "yes"|"near") -> seed / bench texts for that label; ("new", key) -> NEW_TEXTS;
#                ("bench_ids", [ids]) -> those benchmark items
EDGE = [
    ("gate_marker", "Level 0 · gate", "Marker term, no keyword",
     "Only marker terms ('Kiev regime', 'Novorossiya', 'denazification'): the gate is skipped and level 1 and 2 run.",
     ("new", "marker_no_keyword")),
    ("gate_language_menu", "Level 0 · gate", "Language menu",
     "'Russian' in a list of languages: the cheap rules mark it incidental before any model (document untouched).",
     ("new", "language_menu")),
    ("edge_scientist", "Edge cases", "Russian scientist in a technical text",
     "A theorem named after a Russian mathematician: science_technology (keep), not celebrities.",
     ("new", "scientist_in_tech")),
    ("edge_price_in_tech", "Edge cases", "Price inside a technical text",
     "The price of a Russian-made processor in a hardware review: science / economy (keep), not cost_of_living.",
     ("new", "price_in_tech")),
    ("edge_conflict", "Edge cases", "Remove and keep subject together",
     "A remove-type subject (culture, salaries, ...) and a keep-type subject (technology, economy, ...) in one "
     "paragraph: the conflict rule sends it to review.",
     ("bench_ids", ["b-conflict-yes-1", "b-conflict-yes-2"])),
    ("edge_no_subject", "Edge cases", "About Russia, no subject",
     "Russia-related but none of the 12 subjects: kept (reason no_subject).",
     ("bench_ids", ["b-no_subject-yes-1", "b-no_subject-yes-4"])),
    ("edge_war_factual", "Edge cases", "Factual war reporting",
     "Documented facts about the war (Bucha): war_ukraine (keep), no narrative: the model must keep this knowledge.",
     ("new", "war_factual")),
    ("edge_debunk", "Edge cases", "News that debunks a narrative",
     "A fact-check quoting a Kremlin claim to refute it. Expected: keep (the narrative label is no). If the model "
     "wrongly says the narrative is yes, reports_or_debunks turns 'remove' into 'review' instead.",
     ("bench_ids", ["c-narr_atrocity_denial-near-1", "c-reports_or_debunks-yes-1"])),
    ("edge_place_names", "Edge cases", "Place names: rewrite and exceptions",
     "Kiev / Kharkov / Zaporozhye are rewritten in the cleaned text; Kievan Rus, Chicken Kiev and the URL are not. "
     "Use 'label without a keyword' to see the cleaned text.",
     ("new", "place_names")),
    ("edge_russian_language", "Edge cases", "Russian-language text about Ukraine",
     "A Russian-language news item about the Kyiv metro: not Russia-related by itself. The English models are weak "
     "on Cyrillic text: compare with bge-m3.",
     ("new", "russian_language")),
]


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Build the policy Try page's case list.")
    ap.add_argument("--policy", default="policy/russia_policy.json")
    ap.add_argument("--out", default="labels/cases_v1.json")
    args = ap.parse_args()
    policy = nli_label.Policy.load(str(HERE / args.policy))
    keys = list(policy.labels)
    _, seed = nli_label.read_labels_file(str(HERE / "labels" / "seed.jsonl"))
    _, bench = nli_label.read_labels_file(str(HERE / "labels" / "bench_synthetic_v1.jsonl"))
    bench_by_id = {it["source"]["id"]: it for it in bench}

    def expected(labels_yes):
        labs = {k: (k in labels_yes) for k in keys}
        return nli_label.action_from_labels(policy, labs)

    def from_item(it, origin):
        yes = [k for k, v in it["labels"].items() if v]
        return {"text": it["text"], "from": origin, "labels_yes": yes,
                "expected_action": expected(yes), "note": it.get("note") or ""}

    def label_texts(key, kind):
        out = []
        if kind == "yes":
            cands = [it for it in seed if it["labels"].get(key) is True]
            cands.sort(key=lambda it: (sum(1 for v in it["labels"].values() if v), len(it["text"])))
            if cands and len(cands[0]["text"]) <= 1500:
                out.append(from_item(cands[0], f"seed (draft labels): {cands[0]['key']}"))
        b = [it for it in bench if it["picked_for"][0] == f"bench:{key}:{kind}"]
        for it in b[: 2 - len(out)]:
            out.append(from_item(it, f"benchmark: {it['source']['id']}"))
        for text, yes in NEW_LABEL_TEXTS.get(key, {}).get(kind, [])[: 2 - len(out)]:
            out.append({"text": text, "from": "new (written for this case)", "labels_yes": yes,
                        "expected_action": expected(yes), "note": ""})
        if kind == "near" and key == "involves_russia":  # a real incidental mention from the seed too
            real = [it for it in seed if it["labels"].get("involves_russia") is False and len(it["text"]) < 700]
            if real:
                out = [from_item(real[0], f"seed (draft labels): {real[0]['key']}")] + out[:1]
        return out

    cases = []
    group_of = {0: "Level 0 · gate", 1: "Level 1 · subject", 2: "Level 2 · framing"}
    for key, lab in policy.labels.items():
        for kind in ("yes", "near"):
            texts = label_texts(key, kind)
            if not texts:
                continue
            what = (f"Texts where '{key}' is clearly yes: expected action follows its decision ({lab.decision})."
                    if kind == "yes" else
                    f"Near misses: they look related to '{key}' (same words or topic) but '{key}' is no.")
            cases.append({"id": f"{key}:{kind}", "group": group_of[lab.level], "label": key,
                          "title": f"{key} · {'yes' if kind == 'yes' else 'near miss'}", "what": what,
                          "hypothesis": lab.hypothesis, "decision": lab.decision, "texts": texts})
    for cid, group, title, what, spec in EDGE:
        if spec[0] == "new":
            text, yes = NEW_TEXTS[spec[1]]
            texts = [{"text": text, "from": "new (written for this case)", "labels_yes": yes,
                      "expected_action": expected(yes) if yes else ("untouched or pass" if not yes else None),
                      "note": what}]
        else:
            texts = [from_item(bench_by_id[i], f"benchmark: {i}") for i in spec[1]]
        cases.append({"id": cid, "group": group, "label": None, "title": title, "what": what, "texts": texts})
    out = {"version": 1, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
           "about": "Cases for the viewer's policy Try page (tools/build_cases.py). Seed texts carry Claude's "
                    "unchecked draft labels; benchmark and new texts carry labels written with the text.",
           "policy": args.policy.replace("\\", "/"), "cases": cases}
    path = HERE / args.out
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    n_texts = sum(len(c["texts"]) for c in cases)
    srcs = {"seed": 0, "benchmark": 0, "new": 0}
    for c in cases:
        for t in c["texts"]:
            srcs[t["from"].split(" ")[0].split(":")[0]] += 1
    print(f"{len(cases)} cases, {n_texts} texts -> {path}  (from seed {srcs['seed']}, benchmark {srcs['benchmark']}, "
          f"new {srcs['new']})")
    missing = [f"{k}:{kind}" for k in keys for kind in ("yes", "near") if not any(c["id"] == f"{k}:{kind}" for c in cases)]
    print("labels without a case:", missing or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())

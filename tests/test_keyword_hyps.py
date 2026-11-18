"""Step 3: hypotheses built from the matched keyword (check1_types / check2_types with {kw}, {gloss}, {other})."""
import json

import pytest

import nli_filter as nf
import nli_hypotheses as nh

T = "\t"


class RulePool:
    """Scores by (premise word, hypothesis words) rules; everything else 0.05. Records the hypotheses it saw."""

    def __init__(self, rules):
        self.name, self.devices, self.mode, self.calls, self.pairs = "rule", ["cpu"], "single", 0, 0
        self.rules, self.seen = rules, []

    def score(self, premises, hypotheses):
        self.calls += 1
        self.pairs += len(premises)
        self.seen += list(hypotheses)
        out = []
        for p, h in zip(premises, hypotheses):
            v = 0.05
            for pw, hw, score in self.rules:
                if pw in p.lower() and hw in h.lower():
                    v = max(v, score)
            out.append(v)
        return out


LEX = ["Russia", T.join(["Siberia", "B", "region", "a region of Russia", "a figure of speech for a cold, remote place"]),
       T.join(["Moscow", "B", "city", "the capital of Russia", "Moscow, Idaho | a brand of vodka"]),
       T.join(["Volga", "B", "region"])]  # a region without a gloss

TYPES1 = {"region": {"place": "This text is about {kw}, {gloss}."}, "city": {"place": "This text is about {kw}, {gloss}."}}
TYPES2 = {"*": {"brand": "In this text, {kw} is part of a company, product or brand name."},
          "@other": {"sense": "In this text, {kw} means {other}."}}


def make(rules, types1=TYPES1, types2=TYPES2, cap=4, check2=None):
    s = nf.FilterSettings("Russia", "Russian", {"country": "This text is about Russia."},
                          check2 if check2 is not None else {"loc": "This text mentions Russia only in passing."},
                          check1_types=nh.render_types(types1, "Russia", "Russian"),
                          check2_types=nh.render_types(types2, "Russia", "Russian"), max_keyword_hyps=cap,
                          check1_early_stop=False, check2_early_stop=False)
    pool = RulePool(rules)
    lf = nf.LineFilter(s, nf.KeywordMatcher(nf.parse_keywords(LEX)), None, nf.WindowBuilder(),
                       nf.CascadeScorer(pool, None, (0.6, 0.95)))
    return lf, pool


def run(lf, texts):
    from nli_models import Record
    return [o.decision for o in lf.process([Record("x", i, {"id": str(i), "text": t}, b"{}")
                                            for i, t in enumerate(texts, 1)])]


def test_validate_and_render():
    data = nh.validate({"check1": {"c": "This text is about {country}."}, "check1_types": TYPES1, "check2_types": TYPES2})
    assert data["check1_types"]["region"]["place"] == "This text is about {kw}, {gloss}."
    r = nh.render_types({"*": {"x": "{kw} in {country_adj} {gloss}"}}, "Russia", "Russian")
    assert r == {"*": {"x": "{kw} in Russian {gloss}"}}
    assert nh.fill(r["*"]["x"], "Siberia", "a {weird} gloss") == "Siberia in Russian a {weird} gloss"
    assert "check1_types" not in nh.validate({"check1": {"c": "x"}})  # flat files stay as they were


@pytest.mark.parametrize("bad, msg", [
    ({"check1_types": {"@other": {"s": "{kw} means {other}"}}}, "check 2 only"),
    ({"check2_types": {"@other": {"s": "{kw} is odd"}}}, "needs"),
    ({"check1_types": {"region": {"p": "{kw} {other}"}}}, "not \\['other'\\]"),
    ({"check1_types": {"Region X": {"p": "{kw}"}}}, "keyword type"),
    ({"check1_types": {"region": {}}}, "non-empty"),
])
def test_validate_refuses(bad, msg):
    with pytest.raises(ValueError, match=msg):
        nh.validate({"check1": {"c": "x"}, **bad})


def test_check1_window_gets_the_hypotheses_of_its_keywords():
    lf, pool = make([("baikal", "siberia, a region of russia", 0.97)])
    d = run(lf, ["Siberia is home to Lake Baikal, the deepest lake in the world."])[0]
    assert d["decision"] == "filter" and d["check1"]["hyp"] == "place:Siberia"
    pair = next(p for p in d["check1"]["pairs"] if p["hyp"] == "place:Siberia")
    assert pair["text"] == "This text is about Siberia, a region of Russia." and pair["score"] == 0.97
    assert "text" not in next(p for p in d["check1"]["pairs"] if p["hyp"] == "country")


def test_gloss_templates_skip_keywords_without_gloss():
    lf, pool = make([])
    run(lf, ["The Volga is long.", "Russia is big."])
    assert pool.seen.count("This text is about Russia.") == 2
    assert not any("Volga," in h for h in pool.seen)            # the region template needs {gloss}
    assert not any("about Russia," in h for h in pool.seen)      # Russia has no type


def test_check2_other_meanings_make_a_hit_incidental():
    rules = [("siberia", "about russia", 0.97),                  # check 1 passes (fake)
             ("office", "figure of speech", 0.92)]                # check 2: the idiom sense
    lf, pool = make(rules)
    d = run(lf, ["The office felt like Siberia after the heating broke."])[0]
    assert d["reason"] == "check2_incidental"
    c2 = d["hits"][0]["check2"]
    assert c2["hyp"] == "sense:Siberia"
    assert c2["text"] == "In this text, Siberia means a figure of speech for a cold, remote place."
    assert [p["hyp"] for p in c2["pairs"]] == ["loc", "brand:Siberia", "sense:Siberia"]


def test_several_other_meanings_get_numbered_keys_and_the_cap_holds():
    lf, pool = make([("moscow", "about russia", 0.97)], cap=2)
    d = run(lf, ["We drove to Moscow on Friday."])[0]
    keys = [p["hyp"] for p in d["hits"][0]["check2"]["pairs"]]
    assert keys == ["loc", "brand:Moscow", "sense:Moscow/1"]       # cap 2: sense:Moscow/2 left out
    lf, pool = make([("moscow", "about russia", 0.97)], cap=0)
    d = run(lf, ["We drove to Moscow on Friday."])[0]
    assert [p["hyp"] for p in d["hits"][0]["check2"]["pairs"]] == ["loc"]


def test_hits_of_different_keywords_in_one_sentence_are_scored_separately():
    rules = [("moscow", "about russia", 0.97), ("vodka", "moscow means a brand of vodka", 0.95)]
    lf, pool = make(rules)
    d = run(lf, ["Moscow vodka is sold in Siberia."])[0]
    by = {h["kw"]: h["check2"] for h in d["hits"]}
    assert by["Moscow"]["incidental"] and by["Moscow"]["hyp"] == "sense:Moscow/2"
    assert not by["Siberia"]["incidental"] and d["decision"] == "filter"
    assert not any("Moscow" in p["hyp"] for p in by["Siberia"]["pairs"])


def test_check2_only_from_types_still_runs():
    lf, pool = make([("office", "about russia", 0.97), ("office", "figure of speech", 0.92)], check2={})
    assert run(lf, ["The office felt like Siberia today."])[0]["reason"] == "check2_incidental"


def test_cli_hypotheses_file_with_types(tmp_path, monkeypatch):
    from conftest import FakePool
    monkeypatch.setattr(nf, "NLIPool", lambda name, **kw: FakePool(name))
    hyp = tmp_path / "h.json"
    hyp.write_text(json.dumps({"check1": {"c": "This text is about {country}."}, "check1_types": TYPES1,
                               "check2": {}, "check2_types": TYPES2}), encoding="utf-8")
    kw = tmp_path / "kw.txt"
    kw.write_text("\n".join(LEX) + "\n", encoding="utf-8")
    src = tmp_path / "a.jsonl"
    src.write_text(json.dumps({"id": "1", "text": "Siberia history is long."}) + "\n", encoding="utf-8")
    out = tmp_path / "o"
    assert nf.main([str(src), "--keywords-file", str(kw), "--hypotheses-file", str(hyp), "--output-dir", str(out),
                    "--judge-model", "none", "--max-keyword-hyps", "3"]) == 0
    summ = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summ["hypotheses"]["check1_types"]["region"]["place"] == "This text is about {kw}, {gloss}."
    assert summ["settings"]["max_keyword_hyps"] == 3
    dec = [json.loads(x) for x in next(out.rglob("*.decisions.jsonl")).read_text(encoding="utf-8").splitlines()]
    assert any(p["hyp"] == "place:Siberia" for p in dec[0]["check1"]["pairs"])
    assert nf.main([str(src), "--max-keyword-hyps", "-1", "--output-dir", str(out)]) == 2

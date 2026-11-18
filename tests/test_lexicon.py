"""Tests for the keyword lexicon (keyword file columns: keyword, level, type, gloss, other meanings, exclude)."""
import json

import pytest

import nli_filter as nf
from conftest import ROOT

T = "\t"


def test_plain_line_is_level_b_keyword():
    e = nf.parse_keyword_line("  Russia  ")
    assert (e.keyword, e.level, e.type, e.gloss, e.other, e.exclude) == ("Russia", "B", None, None, [], [])
    assert e.as_dict() == {"keyword": "Russia"}
    assert nf.parse_keyword_line("# comment") is None
    assert nf.parse_keyword_line("   ") is None


def test_full_lexicon_line():
    e = nf.parse_keyword_line(T.join(["Siberia", "b", "Region", "a region of Russia",
                                      "a brand name | a figure of speech", r"Siberia 800 | St\.? (FL|Florida)"]), 7)
    assert e.keyword == "Siberia" and e.level == "B" and e.type == "region" and e.line == 7
    assert e.gloss == "a region of Russia"
    assert e.other == ["a brand name", "a figure of speech"]
    assert e.exclude == ["Siberia 800", r"St\.? (FL|Florida)"]  # '|' without spaces stays inside the regex


def test_dash_and_empty_columns_mean_not_given():
    e = nf.parse_keyword_line(T.join(["Russian Federation", "A", "-", "", "-"]))
    assert e.level == "A" and e.strict and e.type is None and e.gloss is None and e.other == []
    assert e.as_dict() == {"keyword": "Russian Federation", "level": "A"}


@pytest.mark.parametrize("line, msg", [
    (T.join(["Russia", "C"]), "level 'C'"),
    (T.join(["Russia", "B", "two words"]), "type 'two words'"),
    (T.join(["Russia", "B", "", "", "", "(unclosed"]), "bad exclude pattern"),
    (T.join(["", "A"]), "first column"),
    (T.join(["a", "B", "x", "g", "o", "e", "extra"]), "at most 6"),
])
def test_bad_lines_are_refused_with_the_line_number(line, msg):
    with pytest.raises(ValueError, match=msg):
        nf.parse_keyword_line(line, 3)
    with pytest.raises(ValueError, match="line 2: "):
        nf.parse_keywords(["Russia", line])


def test_all_bad_lines_are_reported_at_once():
    with pytest.raises(ValueError) as exc:
        nf.parse_keywords([T.join(["a", "X"]), "ok", T.join(["b", "Y"])])
    assert "line 1:" in str(exc.value) and "line 3:" in str(exc.value)


def test_load_keywords_of_the_project_file_still_works():
    words = nf.load_keywords(str(ROOT / "keywords" / "russia.txt"))
    assert "Russia" in words and all("\t" not in w for w in words)


@pytest.fixture(params=[True, False], ids=["ahocorasick", "regex"])
def engine(request):
    if request.param and nf.ahocorasick is None:
        pytest.skip("pyahocorasick not installed")
    return request.param


def test_hits_know_their_keyword(engine):
    lex = nf.parse_keywords(["Russia", T.join(["Siberia", "B", "region", "a region of Russia"]),
                             T.join(["Russian Federation", "A", "country"])])
    m = nf.KeywordMatcher(lex, use_ahocorasick=engine)
    text = "SIBERIA is in the Russian Federation, not just Russia."
    got = [(text[h.start:h.end], m.entry(h).keyword, m.entry(h).level, m.entry(h).type) for h in m.find(text)]
    assert got == [("SIBERIA", "Siberia", "B", "region"), ("Russian Federation", "Russian Federation", "A", "country"),
                   ("Russia", "Russia", "B", None)]


def test_per_keyword_exclude_drops_only_that_keyword(engine):
    lex = nf.parse_keywords([T.join(["Siberia", "B", "region", "", "", "siberia 800 | Siberia headset"]),
                             T.join(["Muscovite", "B", "demonym", "", "a mineral", r"muscovite\s+mica"]),
                             "Russia"])
    m = nf.KeywordMatcher(lex, use_ahocorasick=engine)
    kws = lambda t: [t[h.start:h.end] for h in m.find(t)]  # noqa: E731
    assert kws("The Siberia 800 headset ships from Russia.") == ["Russia"]
    assert kws("Siberia is cold. Muscovite mica is shiny. A Muscovite said hi.") == ["Siberia", "Muscovite"]


def test_strings_and_entries_mix_and_duplicates_warn():
    lex = nf.parse_keywords([T.join(["Siberia", "B", "region"]), T.join(["siberia", "A"]), "Russia"])
    m = nf.KeywordMatcher(lex + ["russia", "Moscow"])
    assert m.keywords == ["Siberia", "Russia", "Moscow"]
    assert m.entries[0].type == "region" and m.entries[0].level == "B"  # the first one is used
    assert any("listed twice" in w and "line 2" in w for w in m.warnings)
    assert not any("russia" in w.lower() for w in m.warnings)  # a plain repeat is not worth a warning


def test_counts():
    lex = nf.parse_keywords([T.join(["Russian Federation", "A", "country"]), T.join(["Siberia", "B", "region", "g"]),
                             "Russia"])
    c = nf.KeywordMatcher(lex).counts()
    assert c["keywords"] == 3 and c["levels"] == {"A": 1, "B": 2}
    assert c["types"] == {"-": 1, "country": 1, "region": 1} and c["with_gloss"] == 1


def test_cli_refuses_a_bad_keyword_file(tmp_path, capsys):
    src = tmp_path / "a.jsonl"
    src.write_text(json.dumps({"id": "1", "text": "Russia"}) + "\n", encoding="utf-8")
    kw = tmp_path / "kw.txt"
    kw.write_text("Russia\nSiberia\tZ\n", encoding="utf-8")
    assert nf.main([str(src), "--keywords-file", str(kw), "--keywords-report", "--output-dir", str(tmp_path / "o")]) == 2
    assert "line 2" in capsys.readouterr().err


def test_cli_lexicon_counts_in_the_keywords_report_run(tmp_path):
    src = tmp_path / "a.jsonl"
    src.write_text(json.dumps({"id": "1", "text": "The Siberia 800 headset."}) + "\n"
                   + json.dumps({"id": "2", "text": "Siberia is cold."}) + "\n", encoding="utf-8")
    kw = tmp_path / "kw.txt"
    kw.write_text("Russia\nSiberia\tB\tregion\ta region of Russia\t-\tSiberia 800\n", encoding="utf-8")
    out = tmp_path / "o"
    assert nf.main([str(src), "--keywords-file", str(kw), "--keywords-report", "--output-dir", str(out)]) == 0
    rep = json.loads((out / "keywords_report.json").read_text(encoding="utf-8"))
    assert rep["lexicon"]["types"] == {"-": 1, "region": 1}
    per = {k["keyword"]: k for k in rep["per_keyword"]}
    assert per["Siberia"]["lines"] == 1 and per["Siberia"]["type"] == "region"  # line 1: the keyword's own exclude


# ---------------------------------------------------------------- step 2: level A (strict) keywords

from conftest import FakePool  # noqa: E402


def _strict_filter(strict_rules=False, rules=True):
    lex = nf.parse_keywords(["Russia", "Russian", T.join(["Stalin", "A", "person"]), T.join(["Kremlin", "A"])])
    s = nf.FilterSettings("Russia", "Russian", nf._render(nf.DEFAULT_CHECK1, "Russia", "Russian", "c1"),
                          nf._render(nf.DEFAULT_CHECK2, "Russia", "Russian", "c2"), strict_rules=strict_rules)
    pool = FakePool("fast")
    lf = nf.LineFilter(s, nf.KeywordMatcher(lex), nf.IncidentalRules("Russian") if rules else None,
                       nf.WindowBuilder(), nf.CascadeScorer(pool, None, (0.6, 0.95)))
    return lf, pool


def _run(lf, texts):
    from nli_models import Record
    recs = [Record("x.jsonl", i, {"id": f"r{i}", "text": t}, json.dumps({"text": t}).encode())
            for i, t in enumerate(texts, 1)]
    return [o.decision for o in lf.process(recs)]


def test_level_a_hit_filters_without_any_model():
    lf, pool = _strict_filter()
    before = lf.scorer.fast_pairs
    d = _run(lf, ["Stalin's mother baked bread on Sundays.",          # A only
                  "In 1930 Stalin and Russian officials met.",        # A + B: A wins
                  "Russia is large."])                                 # B only: models
    assert [x["reason"] for x in d[:2]] == ["strict_keyword", "strict_keyword"]
    assert all(x["decision"] == "filter" for x in d[:2])
    assert d[0]["strict"] == ["Stalin"] and "check1" not in d[0]
    a = [h for h in d[1]["hits"] if h.get("level") == "A"]
    assert [h["kw"] for h in a] == ["Stalin"] and all("level" not in h for h in d[1]["hits"] if h["kw"] == "Russian")
    assert d[2]["reason"] in ("about_country", "check1_negative", "check2_incidental")
    assert lf.scorer.fast_pairs - before > 0  # only the B line reached the model
    lf2, _ = _strict_filter()
    _run(lf2, ["Stalin's mother baked bread.", "In 1930 Stalin met them."])
    assert lf2.scorer.fast_pairs == 0


def test_level_a_is_absolute_by_default_even_inside_a_language_menu():
    menu = "Languages: English | Deutsch | Russian | Stalin"  # an A word inside a rule's span
    lf, _ = _strict_filter()
    assert _run(lf, [menu])[0]["reason"] == "strict_keyword"


def test_strict_rules_lets_a_rule_clear_an_a_hit():
    # 'Kremlin' inside a company name the rules know: with strict_rules the rule wins, the line goes on
    lex = nf.parse_keywords(["Russia", T.join(["Kremlin", "A"])])
    s = nf.FilterSettings("Russia", "Russian", nf._render(nf.DEFAULT_CHECK1, "Russia", "Russian", "c1"),
                          nf._render(nf.DEFAULT_CHECK2, "Russia", "Russian", "c2"), strict_rules=True)
    rules = nf.IncidentalRules("Russian", company_names=["Kremlin Kitchens Ltd"])
    lf = nf.LineFilter(s, nf.KeywordMatcher(lex), rules, nf.WindowBuilder(),
                       nf.CascadeScorer(FakePool("fast"), None, (0.6, 0.95)))
    d = _run(lf, ["We bought chairs from Kremlin Kitchens Ltd last week.", "The Kremlin said no."])
    assert d[0]["reason"] == "rules_incidental" and d[0]["hits"][0]["level"] == "A" and d[0]["hits"][0]["rule"]
    assert d[1]["reason"] == "strict_keyword"
    s.strict_rules = False
    assert _run(lf, ["We bought chairs from Kremlin Kitchens Ltd last week."])[0]["reason"] == "strict_keyword"


def test_level_a_excluded_hit_does_not_count():
    lex = nf.parse_keywords(["Russia", T.join(["Stalin", "A", "person", "-", "-", r"Stalin\s+Street"])])
    s = nf.FilterSettings("Russia", "Russian", {"c": "This text is about Russia."}, {})
    lf = nf.LineFilter(s, nf.KeywordMatcher(lex), None, nf.WindowBuilder(),
                       nf.CascadeScorer(FakePool("fast"), None, (0.6, 0.95)))
    assert _run(lf, ["The cafe on Stalin Street opens at nine."])[0]["reason"] == "no_keyword"


def test_cli_strict_keyword_in_summary_and_keywords_report(tmp_path):
    src = tmp_path / "a.jsonl"
    src.write_text("".join(json.dumps({"id": str(i), "text": t}) + "\n" for i, t in enumerate(
        ["Stalin ruled for decades.", "Nothing here.", "Stalin and Russia."], 1)), encoding="utf-8")
    kw = tmp_path / "kw.txt"
    kw.write_text("Russia\nStalin\tA\tperson\n", encoding="utf-8")
    rep = tmp_path / "r"
    assert nf.main([str(src), "--keywords-file", str(kw), "--keywords-report", "--output-dir", str(rep)]) == 0
    r = json.loads((rep / "keywords_report.json").read_text(encoding="utf-8"))
    assert r["lines_strict"] == 2 and r["lines_to_models"] == 0
    assert {k["keyword"]: k.get("strict_lines") for k in r["per_keyword"]}["Stalin"] == 2
    assert "strict_keyword" in nf.REASONS
    assert nf.build_parser().parse_args(["x", "--strict-rules"]).strict_rules


# ---------------------------------------------------------------- step 4b: audit of level-A lines

def _audit_filter(rate, strict_rules=False):
    lex = nf.parse_keywords(["Russia", "Russian", T.join(["Stalin", "A", "person"])])
    s = nf.FilterSettings("Russia", "Russian", nf._render(nf.DEFAULT_CHECK1, "Russia", "Russian", "c1"),
                          nf._render(nf.DEFAULT_CHECK2, "Russia", "Russian", "c2"), audit_strict=rate,
                          strict_rules=strict_rules)
    return nf.LineFilter(s, nf.KeywordMatcher(lex), nf.IncidentalRules("Russian"), nf.WindowBuilder(),
                         nf.CascadeScorer(FakePool("fast"), None, (0.6, 0.95)))


def test_audit_stores_what_the_models_would_say_and_keeps_the_filter():
    lf = _audit_filter(1.0)
    d = _run(lf, ["Stalin and the history of the Kremlin.",           # FakePool: 'history' -> about
                  "Stalin bought a recipe book.",                     # FakePool: 'recipe' -> not about
                  "Russia is large."])                                  # no A word: no audit
    for x in d[:2]:
        assert x["decision"] == "filter" and x["reason"] == "strict_keyword" and x["strict"] == ["Stalin"]
        assert "check1" not in x and all("check2" not in h and "rule" not in h for h in x["hits"])
    assert d[0]["audit"]["decision"] == "filter" and d[0]["audit"]["reason"] == "about_country"
    assert d[1]["audit"]["decision"] == "keep" and d[1]["audit"]["reason"] == "check1_negative"
    assert d[1]["audit"]["check1"]["score"] < 0.8 and d[1]["audit"]["hits"][0]["kw"] == "Stalin"
    assert "audit" not in d[2]
    st = nf.RunStats()
    from nli_models import Record
    for x in d:
        st.add(nf.Outcome(Record("x", 1, {}, b"{}"), x), None)
    assert st.to_dict()["audit"] == {"lines": 2, "would_filter": 1, "would_keep": 1}


def test_audit_rules_alone_would_keep():
    lex = nf.parse_keywords(["Russia", T.join(["Russian", "A", "demonym"])])  # an A word that is a language name
    s = nf.FilterSettings("Russia", "Russian", {"c": "This text is about Russia."}, {}, audit_strict=1.0)
    lf = nf.LineFilter(s, nf.KeywordMatcher(lex), nf.IncidentalRules("Russian"), nf.WindowBuilder(),
                       nf.CascadeScorer(FakePool("fast"), None, (0.6, 0.95)))
    d = _run(lf, ["Languages: English, Russian, German"])[0]
    assert d["reason"] == "strict_keyword" and d["strict"] == ["Russian"]
    assert d["audit"]["reason"] == "rules_incidental" and d["audit"]["hits"][0]["rule"]
    assert "rule" not in d["hits"][0]  # the real decision ignores the rules (A is absolute)


def test_audit_off_and_sampling_is_deterministic():
    texts = [f"Stalin note number {i}." for i in range(400)]
    assert not any("audit" in x for x in _run(_audit_filter(0.0), texts))
    a = [("audit" in x) for x in _run(_audit_filter(0.25), texts)]
    b = [("audit" in x) for x in _run(_audit_filter(0.25), texts)]
    assert a == b and 50 < sum(a) < 150


def test_hit_rows_carry_the_keyword_as_written_in_the_file():
    lf, _ = _strict_filter()
    d = _run(lf, ["RUSSIA and the kremlin."])[0]
    assert {h["kw"]: h.get("keyword") for h in d["hits"]} == {"RUSSIA": "Russia", "kremlin": "Kremlin"}


def test_cli_audit_option_and_lexicon_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(nf, "NLIPool", lambda name, **kw: FakePool(name))
    src = tmp_path / "a.jsonl"
    src.write_text(json.dumps({"id": "1", "text": "Stalin bought a recipe book."}) + "\n", encoding="utf-8")
    kw = tmp_path / "kw.txt"
    kw.write_text("Russia\nStalin\tA\tperson\ta Soviet leader\n", encoding="utf-8")
    out = tmp_path / "o"
    assert nf.main([str(src), "--keywords-file", str(kw), "--output-dir", str(out), "--judge-model", "none",
                    "--audit-strict", "1"]) == 0
    summ = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summ["stats"]["audit"] == {"lines": 1, "would_keep": 1}
    assert summ["country"]["lexicon_meta"] == {"Stalin": {"level": "A", "type": "person", "gloss": "a Soviet leader"}}
    assert summ["settings"]["audit_strict"] == 1.0
    assert nf.main([str(src), "--audit-strict", "2", "--output-dir", str(out)]) == 2

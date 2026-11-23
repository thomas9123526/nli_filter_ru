"""nli_label.py: exceptions (top-priority rules), protected labels, the optional topic field, several keyword files,
rewrite_place_names. No models: the fake scorer of test_label.py, with a few more cue words."""
import json

import pytest

import nli_label
from nli_label import Policy, apply_exceptions, quoted_spans, resolve
from test_label import FakeScorer, make_labeller, rec, small_policy

from pathlib import Path as _P
ROOT_TABLE = _P(__file__).resolve().parent.parent / "policy" / "place_names.csv"

OUR = {"key": "ambiguous_our_country", "decision": "review", "priority": 100, "skip_quoted": True,
       "match": {"phrases": ["our country", "наша страна", "нашей страной"]}}


class Scorer(FakeScorer):
    CUES = dict(FakeScorer.CUES, HATE=["subhuman"], SPEAKS=["we the citizens"])


def labeller(policy, **kw):
    lab = make_labeller(policy, **kw)
    lab.scorer = Scorer()
    return lab


def policy_with(**over):
    p = small_policy()
    data = json.loads(json.dumps(p.data))
    data["labels"]["hate"] = {"level": 2, "decision": "remove", "threshold": 0.8, "hypothesis": "HATE",
                              "protected": True}
    data["run_if"]["2"] = ["involves", "@marker"]
    data.update(over)
    return Policy(data)


def para(row):
    assert len(row["paragraphs"]) == 1
    return row["paragraphs"][0]


# ---------------------------------------------------------------------------------------------------
# exceptions
# ---------------------------------------------------------------------------------------------------

def test_exception_phrase_overrides_the_cascade():
    lab = labeller(policy_with(exceptions=[OUR]))
    row = lab.process([rec(1, "Russia is currently seeking to establish diplomatic relations with our country.")])[0].row
    pa = para(row)
    assert pa["action"] == "review" and pa["reason"] == "exception"
    assert pa["exception"] == "ambiguous_our_country" and pa["action_before"] == "keep"
    assert pa["exception_phrases"] == ["our country"]


def test_exception_in_russian_and_case_insensitive():
    lab = labeller(policy_with(exceptions=[OUR]))
    text = "Россия стремится установить дипломатические отношения с нашей страной. Moscow said so."
    assert para(lab.process([rec(1, text)])[0].row)["exception"] == "ambiguous_our_country"
    assert para(lab.process([rec(1, "OUR COUNTRY and Russia signed a deal.")])[0].row)["action"] == "review"


def test_skip_quoted_phrase():
    lab = labeller(policy_with(exceptions=[OUR]))
    text = 'Moscow replied after Zelensky said: "Our country will never give up its land."'
    pa = para(lab.process([rec(1, text)])[0].row)
    assert "exception" not in pa and pa["action"] == "keep"
    assert quoted_spans('a “b” «c» "d"') == [(2, 5), (6, 9), (10, 13)]


def test_exception_needs_a_candidate_paragraph():
    lab = labeller(policy_with(exceptions=[OUR]))
    row = lab.process([rec(1, "Our country has the best beaches in Europe.")])[0].row
    assert row["action"] == "untouched" and "paragraphs" not in row


def test_scope_gate_skips_gate_negative_paragraphs():
    ex = dict(OUR, scope="gate")
    lab = labeller(policy_with(exceptions=[ex]))
    text = "Swan Lake by a Russian composer is lovely; our country loves ballet music tonight."
    lab.scorer.CUES = dict(Scorer.CUES, GATE=["nothing-matches"])
    pa = para(lab.process([rec(1, text)])[0].row)
    assert pa["action"] == "pass" and "exception" not in pa


def test_priority_highest_wins():
    low = {"key": "low", "decision": "remove", "priority": 1, "match": {"phrases": ["our country"]}}
    high = {"key": "high", "decision": "keep", "priority": 50, "match": {"phrases": ["our country"]}}
    p = policy_with(exceptions=[low, high])
    assert [e.key for e in p.exceptions] == ["high", "low"]
    pa = para(labeller(p).process([rec(1, "Moscow and our country signed a treaty.")])[0].row)
    assert pa["exception"] == "high" and pa["action"] == "keep"


def test_protected_removal_is_never_lowered():
    keep_ex = {"key": "kx", "decision": "keep", "priority": 9, "match": {"phrases": ["our country"]}}
    p = policy_with(exceptions=[keep_ex])
    pa = para(labeller(p).process([rec(1, "Russians in our country are subhuman, a Moscow paper wrote.")])[0].row)
    assert pa["action"] == "remove" and pa["exception_blocked"] == "kx" and "exception" not in pa
    # a stricter exception still applies over a protected removal
    r = resolve(p, {"involves": 0.9, "hate": 0.9})
    p.exceptions[0].decision = "remove"
    assert apply_exceptions(p, r, {"kx": ["our country"]}, {})["exception"] == "kx"


def test_hypothesis_exception_is_scored_and_stored():
    ex = {"key": "speaks_for_country", "decision": "review", "match": {"hypothesis": "SPEAKS", "threshold": 0.7}}
    lab = labeller(policy_with(exceptions=[ex]))
    rows = [o.row for o in lab.process([rec(1, "We the citizens of this land reject Moscow's offer."),
                                        rec(2, "Moscow made an offer today, the agency reported.")])]
    a, b = para(rows[0]), para(rows[1])
    assert a["exception"] == "speaks_for_country" and a["exception_scores"]["exception:speaks_for_country"] == 0.95
    assert "exception" not in b and b["exception_scores"]["exception:speaks_for_country"] == 0.05


@pytest.mark.parametrize("bad, msg", [
    ({"key": "Bad Key", "decision": "review", "match": {"phrases": ["x"]}}, "lower-case"),
    ({"key": "x", "decision": "pass", "match": {"phrases": ["x"]}}, "decision must be"),
    ({"key": "x", "decision": "review", "match": {}}, "needs"),
    ({"key": "x", "decision": "review", "scope": "all", "match": {"phrases": ["x"]}}, "scope"),
])
def test_exception_validation(bad, msg):
    with pytest.raises(ValueError, match=msg):
        policy_with(exceptions=[bad])


def test_exceptions_in_summary_and_stats(tmp_path, monkeypatch):
    pol = tmp_path / "p.json"
    pol.write_text(json.dumps(policy_with(exceptions=[OUR]).data), encoding="utf-8")
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps({"id": "a", "text": "Moscow wants talks with our country."}) + "\n", encoding="utf-8")
    monkeypatch.setattr(nli_label, "build_scorer", lambda args: (Scorer(), None, None))
    out = tmp_path / "out"
    assert nli_label.main(["run", str(inp), "--output-dir", str(out), "--policy", str(pol)]) == 0
    summ = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summ["policy"]["exceptions"][0]["key"] == "ambiguous_our_country"
    assert summ["stats"]["exceptions"] == {"ambiguous_our_country": 1}
    assert summ["stats"]["reasons"] == {"exception": 1}
    # redecide keeps the exception (phrases need no stored score)
    out2 = tmp_path / "out2"
    assert nli_label.main(["redecide", str(out), "--output-dir", str(out2), "--policy", str(pol)]) == 0
    row = json.loads((out2 / "in.labels.jsonl").read_text(encoding="utf-8"))
    assert para(row)["exception"] == "ambiguous_our_country"


# ---------------------------------------------------------------------------------------------------
# topic field
# ---------------------------------------------------------------------------------------------------

TOPIC = {"topic_field": "topic", "topic_map": {"Sports": "sport", "Entertainment": ["culture"], "Science": "science"}}


def scored_labels(lab):
    return [h for h in lab.scorer.seen]


def test_no_topic_field_is_like_before():
    lab = labeller(policy_with(**TOPIC))
    pa = para(lab.process([rec(1, "Russian hockey fans in Moscow.")])[0].row)
    assert "from_field" not in pa and "SPORT" in lab.scorer.seen


def test_hint_mode_field_yes_without_the_model():
    lab = labeller(policy_with(**TOPIC))
    row = lab.process([rec(1, "Fans in Moscow, Russia, cheered last night.", topic="Sports")])[0].row
    pa = para(row)
    assert row["topic"] == ["Sports"] and pa["from_field"] == ["sport"]
    assert pa["scores"]["sport"] == 1.0 and pa["action"] == "review"
    assert "SPORT" not in lab.scorer.seen and "CULTURE" in lab.scorer.seen  # the rest by the model


def test_trust_mode_mapped_subjects_by_field_only_unmapped_by_model():
    lab = labeller(policy_with(**TOPIC, topic_mode="trust"))
    pa = para(lab.process([rec(1, "A Russian ballet film shown in Moscow.", topic="Sports")])[0].row)
    assert pa["from_field"] == ["culture", "science", "sport"]
    assert pa["scores"]["culture"] == 0.0 and pa["scores"]["sport"] == 1.0
    assert not {"SPORT", "CULTURE", "SCIENCE"} & set(lab.scorer.seen)
    assert "WAR" in lab.scorer.seen  # not in topic_map: always the model


def test_off_mode_records_and_compares():
    lab = labeller(policy_with(**TOPIC, topic_mode="off"))
    o = lab.process([rec(1, "A Russian ballet in Moscow.", topic="Sports")])[0]
    pa = para(o.row)
    assert "from_field" not in pa and o.row["topic"] == ["Sports"]
    assert o.topic_cmp[("sport", "field_only")] == 1 and o.topic_cmp[("culture", "model_only")] == 1
    assert o.topic_cmp[("science", "agree")] == 1


@pytest.mark.parametrize("data", [{}, {"topic": None}, {"topic": ""}, {"topic": "Cooking"}, {"topic": []},
                                  {"topic": 5}])
def test_missing_empty_or_unknown_topic_falls_back_to_the_model(data):
    lab = labeller(policy_with(**TOPIC, topic_mode="trust"))
    pa = para(lab.process([rec(1, "Russian hockey in Moscow.", **data)])[0].row)
    assert "from_field" not in pa and "SPORT" in lab.scorer.seen


def test_nested_field_and_list_values():
    lab = labeller(policy_with(**dict(TOPIC, topic_field="meta.topics")))
    pa = para(lab.process([rec(1, "Moscow, Russia: a long day.", meta={"topics": ["Sports", "Science"]})])[0].row)
    assert pa["from_field"] == ["science", "sport"]
    assert nli_label.get_path({"a": {"b": 1}}, "a.b") == 1 and nli_label.get_path({"a": 1}, "a.b") is None


def test_topic_cli_override_and_validation(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="not a level-1"):
        policy_with(topic_map={"X": "narr_nazi"})
    with pytest.raises(ValueError, match="unknown label"):
        policy_with(topic_map={"X": "nope"})
    with pytest.raises(ValueError, match="topic_mode"):
        policy_with(topic_mode="maybe")
    pol = tmp_path / "p.json"
    pol.write_text(json.dumps(policy_with(topic_map=TOPIC["topic_map"]).data), encoding="utf-8")
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps({"id": "a", "text": "Moscow hockey night.", "cat": "Sports"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(nli_label, "build_scorer", lambda args: (Scorer(), None, None))
    out = tmp_path / "out"
    assert nli_label.main(["run", str(inp), "--output-dir", str(out), "--policy", str(pol),
                           "--topic-field", "cat", "--topic-mode", "off"]) == 0
    summ = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summ["settings"]["topic_field"] == "cat" and summ["settings"]["topic_mode"] == "off"
    assert "sport|agree" in summ["stats"]["topic_agreement"]
    assert "topic field vs model" in nli_label.format_report(summ)


# ---------------------------------------------------------------------------------------------------
# keyword files, place-name switch, the Russia-LLM policy
# ---------------------------------------------------------------------------------------------------

def test_several_keyword_files(tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("Russia\n", encoding="utf-8")
    b.write_text("Ukraine\nKyiv\n", encoding="utf-8")
    p = policy_with(keywords_file=[str(a), str(b)])
    matcher, _, _ = nli_label.build_matchers(p)
    assert {"Russia", "Ukraine", "Kyiv"} <= set(matcher.keywords)


def test_rewrite_place_names_false(tmp_path, monkeypatch):
    pol = tmp_path / "p.json"
    pol.write_text(json.dumps(policy_with(rewrite_place_names=False).data), encoding="utf-8")
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps({"id": "a", "text": "Moscow and Kiev talks."}) + "\n", encoding="utf-8")
    monkeypatch.setattr(nli_label, "build_scorer", lambda args: (Scorer(), None, None))
    out = tmp_path / "out"
    assert nli_label.main(["run", str(inp), "--output-dir", str(out), "--policy", str(pol), "--write-clean"]) == 0
    assert "Kiev" in (out / "in.clean.jsonl").read_text(encoding="utf-8")
    assert json.loads((out / "summary.json").read_text(encoding="utf-8"))["settings"]["rewrite"] is False


@pytest.mark.parametrize("version", [1, 2])
def test_russia_llm_policy_loads_and_cases_match(version):
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    p = Policy.load(str(root / "policy" / f"russia_llm_policy_v{version}.json"))
    assert p.exceptions and p.exceptions[0].key == "ambiguous_our_country"
    assert all(p.labels[k].protected for k in p.labels if k.startswith(("hostility_", "violence_")))
    assert p.rewrite_place_names is (version == 2) and len(p.keywords_files) == 2
    assert all((root / f).is_file() for f in p.keywords_files)
    cases = root / "labels" / "russia_llm_cases_v1.json"
    data = json.loads(cases.read_text(encoding="utf-8"))
    assert data["policy"] == "policy/russia_llm_policy_v2.json"
    for c in data["cases"]:
        for t in c["texts"]:
            assert set(t["labels_yes"]) <= set(p.labels), c["id"]
            assert t["expected_action"] in ("remove", "review", "keep", "pass", "untouched")


# ---------------------------------------------------------------------------------------------------
# place names: the policy's own table (Russia side: Ukrainian romanisation -> Russian form)
# ---------------------------------------------------------------------------------------------------

def test_directed_table_and_switched_off_rows(tmp_path):
    from nli_names import NameRewriter
    t = tmp_path / "t.csv"
    t.write_text("from_form,to_form,variants,notes\nKyiv,Kiev,,\nZaporizhzhia,Zaporozhye,Zaporizhia,\n"
                 "# Bakhmut,Artemovsk,,renamed: off\n", encoding="utf-8")
    e = tmp_path / "e.txt"
    e.write_text("kyiv\\s+independent\n", encoding="utf-8")
    rw = NameRewriter.from_files(str(t), str(e))
    out, ch = rw.rewrite("Kyiv and Zaporizhia; near Bakhmut; the Kyiv Independent reported.")
    assert out == "Kiev and Zaporozhye; near Bakhmut; the Kyiv Independent reported."
    assert len(ch) == 2


def test_russia_side_policy_rewrites_to_russian_forms():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    p = Policy.load(str(root / "policy" / "russia_llm_policy_v2.json"))
    out, _ = p.rewriter().rewrite("Missiles hit Kyiv, Kharkiv and Odesa. Dynamo Kyiv played in Lviv. KYIV.")
    assert out == "Missiles hit Kiev, Kharkov and Odessa. Dynamo Kyiv played in Lvov. KIEV."
    out, _ = p.rewriter().rewrite("Fighting near Bakhmut and Pokrovsk.")  # 2016 renamings are switched off
    assert out == "Fighting near Bakhmut and Pokrovsk."
    # A's policy keeps its direction (Russian form -> Ukrainian)
    a = Policy.load(str(root / "policy" / "russia_policy_v5.json"))
    assert a.rewriter().rewrite("Kiev and Kharkov")[0] == "Kyiv and Kharkiv"


def test_place_names_file_must_exist_and_cli_wins(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="place_names_file"):
        policy_with(place_names_file="policy/nope.csv")
    t = tmp_path / "t.csv"
    t.write_text("from_form,to_form,variants,notes\nKyiv,Kiev,,\n", encoding="utf-8")
    pol = tmp_path / "p.json"
    pol.write_text(json.dumps(policy_with(place_names_file=str(t)).data), encoding="utf-8")
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps({"id": "a", "text": "Moscow and Kyiv talks; Kiev too."}) + "\n", encoding="utf-8")
    monkeypatch.setattr(nli_label, "build_scorer", lambda args: (Scorer(), None, None))
    out = tmp_path / "out"
    assert nli_label.main(["run", str(inp), "--output-dir", str(out), "--policy", str(pol), "--write-clean"]) == 0
    assert "Moscow and Kiev talks; Kiev too." in (out / "in.clean.jsonl").read_text(encoding="utf-8")
    out2 = tmp_path / "out2"  # --place-names on the command line wins over the policy's table
    assert nli_label.main(["run", str(inp), "--output-dir", str(out2), "--policy", str(pol), "--write-clean",
                           "--place-names", str(ROOT_TABLE)]) == 0
    assert "Moscow and Kyiv talks; Kyiv too." in (out2 / "in.clean.jsonl").read_text(encoding="utf-8")

"""nli_label.py: several level-0 gate labels, OR-combined (any one at or above its threshold opens the gate), scored in
order (gate 2 only where gate 1 said no), @gate in run_if, hand labels, redecide with a gate added later. No models."""
import copy
import json

import pytest

import nli_label
from nli_label import Policy, action_from_labels, resolve
from test_label import FakeScorer, make_labeller, rec, small_policy

GATE2 = {"level": 0, "decision": "gate", "threshold": 0.5, "hypothesis": "GATE2"}
GATE3 = {"level": 0, "decision": "gate", "threshold": 0.5, "hypothesis": "GATE3"}


class Scorer(FakeScorer):
    CUES = dict(FakeScorer.CUES, GATE=["moscow", "kremlin", "military operation", "army"], GATE2=["ballet"], GATE3=["hockey"])


AT_GATE = {"1": ["@gate", "@marker"], "2": ["war", "@marker"]}


def policy(*extra_gates, run_if=None):
    p = small_policy()
    data = copy.deepcopy(p.data)
    for i, g in enumerate(extra_gates, 2):
        data["labels"][f"gate{i}"] = g
    if run_if is not None:
        data["run_if"] = run_if
    elif extra_gates:
        data["run_if"] = AT_GATE
    return Policy(data)


def test_run_if_naming_only_one_of_several_gates_is_refused():
    data = copy.deepcopy(small_policy().data)
    data["labels"]["gate2"] = GATE2
    with pytest.raises(ValueError, match="OR-combined"):
        Policy(data)
    data["run_if"]["1"] = ["involves", "gate2", "@marker"]
    assert len(Policy(data).gates) == 2  # every gate listed: fine


def labeller(pol, **kw):
    lab = make_labeller(pol, **kw)
    lab.scorer = Scorer()
    return lab


# "Russian" is a keyword, but gate 1's cue words (moscow / kremlin ...) are not in the text: gate 1 says no
BALLET = "The Russian ballet season opened with a new film about the theatre, long enough."
HOCKEY = "The Russian hockey league started again this autumn with many teams, long enough."
MOSCOW = "Moscow physics labs published new algorithm papers this year, long enough here."


@pytest.mark.parametrize("n", [0, 1, 2, 3])
def test_policy_allows_any_number_of_gates(n):
    data = copy.deepcopy(small_policy().data)
    if n == 0:
        del data["labels"]["involves"]
        data["run_if"] = {"2": ["war", "@marker"]}
    for i in range(2, n + 1):
        data["labels"][f"gate{i}"] = dict(GATE2, hypothesis=f"G{i}")
    if n > 1:
        data["run_if"] = AT_GATE
    p = Policy(data)
    assert len(p.gates) == n and (p.gate is None if n == 0 else p.gate.key == "involves")


def test_resolve_or():
    p = policy(GATE2)
    base = {"culture": 0.95}
    assert resolve(p, dict(base, involves=0.1, gate2=0.1))["reason"] == "gate_negative"
    assert resolve(p, dict(base, involves=0.1, gate2=0.9))["action"] == "remove"  # gate 1 no + gate 2 yes = open
    assert resolve(p, dict(base, involves=0.9))["action"] == "remove"  # gate 2 not scored: gate 1 is enough
    assert resolve(p, dict(base, involves=0.1, gate2=0.1), marker=True)["action"] == "remove"


def test_hand_labels_unknown_only_if_every_gate_unknown():
    p = policy(GATE2)
    assert action_from_labels(p, {"culture": True}) is None
    assert action_from_labels(p, {"gate2": True, "culture": True}) == "remove"
    assert action_from_labels(p, {"involves": False, "culture": True}) == "pass"


def test_second_gate_only_where_the_first_said_no():
    one = labeller(policy())
    o1 = one.process([rec(1, BALLET), rec(2, MOSCOW)])
    assert [o.row["paragraphs"][0]["reason"] for o in o1] == ["gate_negative", "keep_label"]
    two = labeller(policy(GATE2))
    o2 = two.process([rec(1, BALLET), rec(2, MOSCOW)])
    ballet, moscow = (o.row["paragraphs"][0] for o in o2)
    assert ballet["action"] == "remove" and ballet["opened_by_gate"] == "gate2"  # only gate 2 accepts it: L1 ran
    assert moscow["opened_by_gate"] == "involves" and "gate2" not in moscow["scores"]  # gate 2 never scored here
    assert two.scorer.seen.count("GATE2") == 1
    assert "opened_by_gate" not in o1[1].row["paragraphs"][0]  # one gate: the row is as before


def test_three_gates_in_order_and_marker():
    lab = labeller(policy(GATE2, GATE3))
    o = lab.process([rec(1, BALLET), rec(2, HOCKEY), rec(3, "The Russian special military operation, long enough.")])
    assert [x.row["paragraphs"][0].get("opened_by_gate") for x in o[:2]] == ["gate2", "gate3"]
    assert lab.scorer.seen.count("GATE3") == 1  # only hockey: ballet was opened by gate 2, the marker needs no gate
    assert o[2].row["paragraphs"][0]["reason"] != "gate_negative"


def test_marker_paragraph_skips_later_gates():
    lab = labeller(policy(GATE2))
    lab.process([rec(1, "The Russian special military operation went on, long enough text here.")])
    assert lab.scorer.seen.count("GATE2") == 0


def test_at_gate_in_run_if():
    p = policy(GATE2, run_if={"1": ["@gate", "@marker"], "2": ["war", "@marker"]})
    o = labeller(p).process([rec(1, BALLET), rec(2, HOCKEY)])
    assert o[0].row["paragraphs"][0]["action"] == "remove"
    assert o[1].row["paragraphs"][0]["reason"] == "gate_negative"
    with pytest.raises(ValueError, match="unknown label"):
        policy(run_if={"1": ["@gates"]})


def test_at_gate_same_as_listing_the_gate():
    texts = [rec(1, BALLET), rec(2, MOSCOW), rec(3, HOCKEY)]
    a = [o.row for o in labeller(policy()).process(texts)]
    b = [o.row for o in labeller(policy(run_if={"1": ["@gate", "@marker"], "2": ["war", "@marker"]})).process(texts)]
    assert a == b


def test_narrative_opens_gate_with_two_gates():
    data = copy.deepcopy(policy(GATE2).data)
    data["narrative_opens_gate"] = True
    lab = labeller(Policy(data))
    o = lab.process([rec(1, "The Russian soldiers are nazis, says a post, long enough text here.")])[0]
    pa = o.row["paragraphs"][0]
    assert pa["action"] == "remove" and pa["opened_by"] == ["narr_nazi"]  # every gate said no; the narrative opened it


def test_redecide_with_a_gate_added(tmp_path, monkeypatch):
    corpus = tmp_path / "in.jsonl"
    corpus.write_text("".join(json.dumps({"id": f"d{i}", "text": t}) + "\n" for i, t in
                              enumerate([BALLET, MOSCOW], 1)), encoding="utf-8")
    pol1 = tmp_path / "p1.json"
    pol1.write_text(json.dumps(small_policy().data), encoding="utf-8")
    monkeypatch.setattr(nli_label, "build_scorer", lambda args: (Scorer(), None, None))
    monkeypatch.setattr(nli_label, "build_matchers", lambda pol: _matchers(pol))
    assert nli_label.main(["run", "--compress", "none", str(corpus), "--output-dir", str(tmp_path / "r1"),
                           "--policy", str(pol1)]) == 0
    data = copy.deepcopy(small_policy().data)
    data["labels"]["gate2"] = GATE2
    data["run_if"] = AT_GATE
    pol2 = tmp_path / "p2.json"
    pol2.write_text(json.dumps(data), encoding="utf-8")
    assert nli_label.main(["redecide", str(tmp_path / "r1"), "--output-dir", str(tmp_path / "r2"),
                           "--policy", str(pol2), "--compress", "none"]) == 0
    s = json.loads((tmp_path / "r2" / "summary.json").read_text(encoding="utf-8"))
    assert s["redecide"]["missing"] >= 1 and "gate2" in s["redecide"]["changed"]
    rows = [json.loads(x) for x in (tmp_path / "r2" / "in.labels.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["paragraphs"][0]["reason"] == "gate_negative"  # the missing gate-2 score counts as No


def _matchers(pol):
    from nli_filter import IncidentalRules, KeywordMatcher
    return KeywordMatcher(["Russia", "Russian", "Moscow", "Kremlin"]), IncidentalRules("Russian"), KeywordMatcher(pol.markers)

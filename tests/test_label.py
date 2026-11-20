"""nli_label.py (policy, paragraphs, decisions, run, sample, eval) and nli_names.py (place-name rewrite).
No models: a fake scorer gives scores from simple word rules."""
import json
from pathlib import Path

import pytest

import nli_label
from nli_label import Labeller, Policy, action_from_labels, crc_threshold, resolve, split_paragraphs
from nli_models import Record
from nli_names import NameRewriter

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------

def small_policy(**over):
    data = {
        "country": "Russia",
        "keywords_file": None,
        "markers": ["special military operation"],
        "paragraphs": {"min_chars": 20, "max_chars": 400},
        "conflict": "review",
        "labels": {
            "involves": {"level": 0, "decision": "gate", "threshold": 0.5, "hypothesis": "GATE"},
            "culture": {"level": 1, "decision": "remove", "threshold": 0.8, "hypothesis": "CULTURE"},
            "science": {"level": 1, "decision": "keep", "threshold": 0.8, "hypothesis": "SCIENCE"},
            "war": {"level": 1, "decision": "keep", "threshold": 0.8, "hypothesis": "WAR"},
            "sport": {"level": 1, "decision": "review", "threshold": 0.8, "hypothesis": "SPORT"},
            "narr_nazi": {"level": 2, "decision": "remove", "threshold": 0.8, "hypothesis": "NAZI"},
            "hostile_ru": {"level": 2, "decision": "flag", "threshold": 0.8, "hypothesis": "HOSTILE"},
            "debunks": {"level": 2, "decision": "keep", "threshold": 0.8, "hypothesis": "DEBUNK",
                        "softens": ["narr_*"]},
        },
        "run_if": {"1": ["involves", "@marker"], "2": ["war", "@marker"]},
    }
    data.update(over)
    return Policy(data)


class FakeScorer:
    """Score 0.95 when the hypothesis' cue word is in the paragraph, else 0.05."""
    CUES = {"GATE": ["russia", "moscow", "kremlin"], "CULTURE": ["ballet", "pop star", "film"],
            "SCIENCE": ["algorithm", "physics"], "WAR": ["invasion", "war"], "SPORT": ["hockey"],
            "NAZI": ["nazis"], "HOSTILE": ["subhuman"], "DEBUNK": ["fact-check", "falsely claims"]}

    def __init__(self):
        self.fast_pairs = self.judge_pairs = 0
        self.seen = []

    def score(self, premises, hyps):
        out = []
        for p, h in zip(premises, hyps):
            self.seen.append(h)
            hit = any(c in p.lower() for c in self.CUES.get(h, []))
            out.append((0.95 if hit else 0.05, None, 0.95 if hit else 0.05))
        self.fast_pairs += len(out)
        return out


def make_labeller(policy=None, **kw):
    from nli_filter import IncidentalRules, KeywordMatcher
    policy = policy or small_policy()
    matcher = KeywordMatcher(["Russia", "Russian", "Moscow", "Kremlin"])
    markers = KeywordMatcher(policy.markers)
    return Labeller(policy, matcher, IncidentalRules("Russian"), FakeScorer(),
                    NameRewriter({"Kiev": "Kyiv", "Kharkov": "Kharkiv"}, ["chicken\\s+kiev"]),
                    marker_matcher=markers, **kw)


def rec(line, text, **extra):
    data = {"id": f"d{line}", "text": text, **extra}
    return Record("mem.jsonl", line, data, json.dumps(data).encode())


# ---------------------------------------------------------------------------------------------------
# policy
# ---------------------------------------------------------------------------------------------------

def test_shipped_policy_loads():
    p = Policy.load(str(ROOT / "policy" / "russia_policy.json"))
    assert p.gate is not None and p.gate.key == "involves_russia"
    assert len(p.level(1)) == 12
    assert {lab.decision for lab in p.level(2)} == {"remove", "flag", "keep"}
    assert (ROOT / p.keywords_file).is_file()


@pytest.mark.parametrize("bad, msg", [
    ({"labels": {"x": {"level": 1, "decision": "delete", "threshold": 0.8, "hypothesis": "h"}}}, "decision"),
    ({"labels": {"x": {"level": 1, "decision": "keep", "threshold": 1.5, "hypothesis": "h"}}}, "threshold"),
    ({"labels": {"x": {"level": 1, "decision": "keep", "threshold": 0.8, "hypothesis": ""}}}, "hypothesis"),
    ({"labels": {"x": {"level": 1, "decision": "gate", "threshold": 0.8, "hypothesis": "h"}}}, "level 0"),
    ({"labels": {"x": {"level": 1, "decision": "keep", "threshold": 0.8, "hypothesis": "h"}},
      "run_if": {"2": ["nope"]}}, "unknown label"),
    ({"labels": {"x": {"level": 1, "decision": "keep", "threshold": 0.8, "hypothesis": "h", "softens": ["z*"]}}},
     "matches no label"),
])
def test_policy_errors(bad, msg):
    with pytest.raises(ValueError, match=msg):
        Policy(dict({"run_if": {}}, **bad))


# ---------------------------------------------------------------------------------------------------
# resolve
# ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("scores, marker, action, reason", [
    ({"involves": 0.2, "culture": 0.99}, False, "pass", "gate_negative"),
    ({"involves": 0.2, "culture": 0.99}, True, "remove", "remove_label"),       # a marker overrides the gate
    ({"involves": 0.9, "culture": 0.9}, False, "remove", "remove_label"),
    ({"involves": 0.9, "science": 0.9}, False, "keep", "keep_label"),
    ({"involves": 0.9, "culture": 0.9, "science": 0.9}, False, "review", "conflict"),
    ({"involves": 0.9, "sport": 0.9}, False, "review", "review_label"),
    ({"involves": 0.9}, False, "keep", "no_subject"),
    ({"involves": 0.9, "war": 0.9, "narr_nazi": 0.9}, False, "remove", "narrative"),   # narrative beats keep
    ({"involves": 0.9, "war": 0.9, "narr_nazi": 0.9, "debunks": 0.9}, False, "review", "review_label"),
    ({"involves": 0.9, "war": 0.9, "hostile_ru": 0.9}, False, "keep", "keep_label"),   # flags never remove
])
def test_resolve(scores, marker, action, reason):
    r = resolve(small_policy(), scores, marker)
    assert (r["action"], r["reason"]) == (action, reason)


def test_resolve_flags_and_conflict_setting():
    r = resolve(small_policy(), {"involves": 0.9, "hostile_ru": 0.95}, False)
    assert r["flags"] == ["hostile_ru"]
    p = small_policy(conflict="remove")
    assert resolve(p, {"involves": 0.9, "culture": 0.9, "science": 0.9})["action"] == "remove"


def test_action_from_hand_labels():
    p = small_policy()
    assert action_from_labels(p, {"involves": True, "culture": True}) == "remove"
    assert action_from_labels(p, {"involves": False, "culture": True}) == "pass"
    assert action_from_labels(p, {"involves": None}) is None


# ---------------------------------------------------------------------------------------------------
# paragraphs
# ---------------------------------------------------------------------------------------------------

def test_split_blank_lines_and_merge_short():
    t = "Title\n\n" + "A" * 100 + "\n\n" + "B" * 300 + "\n\nshort"
    sp = split_paragraphs(t, min_chars=50, max_chars=1000)
    texts = [t[s:e] for s, e in sp]
    assert texts[0].startswith("Title") and "A" * 100 in texts[0]   # the short title is joined to the next
    assert texts[-1].endswith("short")                                 # a short tail joins the last paragraph
    assert all(t[s:e] == t[s:e].strip() for s, e in sp)


def test_split_single_newlines_and_long():
    t = "\n".join(["line %d is here." % i for i in range(5)])
    assert len(split_paragraphs(t, min_chars=10, max_chars=1000)) >= 2
    long = " ".join(["This is sentence %d." % i for i in range(200)])
    sp = split_paragraphs(long, min_chars=10, max_chars=300)
    assert len(sp) > 5 and all(e - s <= 300 for s, e in sp)
    assert split_paragraphs("   ") == []


# ---------------------------------------------------------------------------------------------------
# Labeller
# ---------------------------------------------------------------------------------------------------

DOC = ("Our weather report for London is sunny all week.\n\n"
       "The Russian ballet star and pop star toured Moscow with a new film.\n\n"
       "Russian physics: the algorithm by Moscow scientists is explained here.\n\n"
       "Flights from Kiev to Kharkov resume; try Chicken Kiev in the lounge.")


def test_labeller_paragraph_actions_clean_and_rewrite():
    lab = make_labeller()
    out = lab.process([rec(1, DOC)])[0]
    paras = out.row["paragraphs"]
    assert [p["action"] for p in paras] == ["remove", "keep"]
    assert out.row["action"] == "edited"
    clean = out.clean["text"]
    assert "ballet" not in clean and "algorithm" in clean and "weather report" in clean
    assert "Flights from Kyiv to Kharkiv" in clean and "Chicken Kiev" in clean
    assert "\n\n\n" not in clean
    assert out.row["rewrites"] == 2 and out.rewrites[0]["old"] == "Kiev"
    assert out.row["tokens_removed"] == paras[0]["tokens"]


def test_labeller_untouched_and_errors_and_raw_unchanged():
    lab = make_labeller()
    bad = Record("mem.jsonl", 3, None, b"{oops", error="bad_json: x")
    no_text = Record("mem.jsonl", 2, {"id": "d2", "body": "x"}, b'{"id": "d2", "body": "x"}')
    r1, r2, r3 = lab.process([rec(1, "Nothing to see. Flights to Kiev."), no_text, bad])
    assert r1.row["action"] == "untouched" and r1.clean["text"] == "Nothing to see. Flights to Kyiv."
    assert r2.row["error"] == "no_text" and r2.row["action"] == "error"
    assert r3.row["error"] == "bad_json" and r3.clean is None


def test_labeller_cascade_skips_levels():
    lab = make_labeller()
    lab.process([rec(1, "Russian hockey results. " * 3)])
    # gate positive -> level 1 runs; no war / marker -> level 2 never asked
    assert "SPORT" in lab.scorer.seen and "NAZI" not in lab.scorer.seen
    lab2 = make_labeller()
    lab2.process([rec(1, "The Russian invasion: they say Ukrainians are nazis. " * 2)])
    assert "NAZI" in lab2.scorer.seen


def test_labeller_gate_negative_passes_and_marker_forces():
    lab = make_labeller()
    out = lab.process([rec(1, "A Russian roulette scene in an American film about cards and luck.")])[0]
    assert out.row["paragraphs"][0]["action"] in ("pass", "remove")
    out = lab.process([rec(2, "They call the special military operation a success; Ukrainians are nazis.")])[0]
    assert out.row["paragraphs"][0]["marker"] is True and out.row["paragraphs"][0]["action"] == "remove"


def test_labeller_all_labels_and_review_as_remove():
    lab = make_labeller(all_labels=True)
    lab.process([rec(1, "Russian hockey team wins again in Moscow tonight.")])
    assert set(lab.scorer.seen) == set(FakeScorer.CUES)
    lab = make_labeller(review_as="remove")
    out = lab.process([rec(1, "Russian hockey team wins again in Moscow tonight, a long report follows.")])[0]
    assert out.row["paragraphs"][0]["action"] == "review" and out.row["action"] == "removed"


def test_all_labels_decides_like_the_cascade():
    text = "Russian hockey fans say Ukrainians are nazis, a long report from the arena follows."
    normal = make_labeller().process([rec(1, text)])[0].row["paragraphs"][0]
    every = make_labeller(all_labels=True).process([rec(1, text)])[0].row["paragraphs"][0]
    assert "narr_nazi" not in normal["scores"] and every["scores"]["narr_nazi"] == 0.95  # scored, for information
    assert normal["action"] == every["action"] == "review"        # sport; level 2 does not run (no war / marker)
    assert normal["levels"] == every["levels"] == [0, 1]


def test_narrative_opens_gate():
    class StrictGate(FakeScorer):  # the gate never fires: as for narratives that do not mention Russia
        CUES = dict(FakeScorer.CUES, GATE=["no-such-word"])

    text = "Russian television says Ukrainians are nazis, a long segment on the evening news."
    pol_off, pol_on = small_policy(), small_policy(narrative_opens_gate=True)
    for pol, want in ((pol_off, "pass"), (pol_on, "remove")):
        lab = make_labeller(pol)
        lab.scorer = StrictGate()
        p = lab.process([rec(1, text)])[0].row["paragraphs"][0]
        assert p["action"] == want, (pol.narrative_opens_gate, p)
    assert p["opened_by"] == ["narr_nazi"] and p["reason"] == "narrative" and p["levels"] == [0, 1, 2]
    assert "SPORT" in lab.scorer.seen  # level 1 ran after the narrative opened the gate
    # all-labels gives the same decision
    lab = make_labeller(pol_on, all_labels=True)
    lab.scorer = StrictGate()
    assert lab.process([rec(1, text)])[0].row["paragraphs"][0]["action"] == "remove"


def test_force_gate_labels_text_without_keywords():
    text = "Ballet tonight in Paris, with a famous pop star and a new film premiere afterwards."
    assert make_labeller().process([rec(1, text)])[0].row["action"] == "untouched"
    out = make_labeller(force_gate=True).process([rec(1, text)])[0]
    p = out.row["paragraphs"][0]
    assert p["action"] == "pass" and p["reason"] == "gate_negative" and p["levels"] == [0]


# ---------------------------------------------------------------------------------------------------
# names
# ---------------------------------------------------------------------------------------------------

def test_names_shipped_table():
    rw = NameRewriter.from_files()
    t, ch = rw.rewrite("From KIEV to Kharkov, Kiev's metro, Kiev-based firm, Kievan Rus, Chicken Kiev, "
                       "Odessa, Texas and Odessa port; Andrian Nikolaev; in Nikolaev; https://kiev.ua/kiev; `Kiev`.")
    assert "From KYIV to Kharkiv, Kyiv's metro, Kyiv-based firm, Kievan Rus, Chicken Kiev" in t
    assert "Odessa, Texas and Odesa port" in t
    assert "Andrian Nikolaev; in Mykolaiv" in t
    assert "https://kiev.ua/kiev" in t and "`Kiev`" in t
    assert all(set(c) == {"start", "old", "new"} for c in ch)


def test_names_longest_first_and_spacing():
    rw = NameRewriter({"Krasny Liman": "Lyman", "Liman": "X"})
    assert rw.rewrite("near Krasny  Liman")[0] == "near Lyman"


# ---------------------------------------------------------------------------------------------------
# label files shipped in labels/
# ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["bench_synthetic_v1.jsonl", "seed.jsonl"])
def test_shipped_label_files_match_policy(name):
    path = ROOT / "labels" / name
    if not path.is_file():
        pytest.skip(f"{name} not present")
    p = Policy.load(str(ROOT / "policy" / "russia_policy.json"))
    meta, items = nli_label.read_labels_file(str(path))
    assert items and set(meta["labels"]) == set(p.labels)
    keys = [it["key"] for it in items]
    assert len(keys) == len(set(keys))
    for it in items:
        assert set(it["labels"]) == set(p.labels), it["key"]
        assert it["text"].strip() and it["status"] in ("todo", "draft", "done")


def test_bench_targets_consistent():
    path = ROOT / "labels" / "bench_synthetic_v1.jsonl"
    if not path.is_file():
        pytest.skip("benchmark not present")
    p = Policy.load(str(ROOT / "policy" / "russia_policy.json"))
    _, items = nli_label.read_labels_file(str(path))
    for it in items:
        _, target, kind = it["picked_for"][0].split(":")
        if target in p.labels:
            assert it["labels"][target] is (kind == "yes"), it["key"]
        assert it["status"] == "done" and all(isinstance(v, bool) for v in it["labels"].values())


# ---------------------------------------------------------------------------------------------------
# thresholds
# ---------------------------------------------------------------------------------------------------

def test_crc_threshold():
    assert crc_threshold([0.9] * 10, 0.05) is None          # n=10: 1/11 > 0.05, too few
    s = [i / 100 for i in range(1, 101)]                     # 100 yes items, scores .01 .. 1.00
    t = crc_threshold(s, 0.05)                               # allowed misses = floor(.05*101 - 1) = 4
    assert t == 0.05
    misses = sum(1 for x in s if x < t)
    assert (misses + 1) / (len(s) + 1) <= 0.05


def test_metrics_helpers():
    pairs = [(0.9, True), (0.7, True), (0.85, False), (0.1, False)]
    m = nli_label._metrics(pairs, 0.8)
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (1, 1, 1, 1)
    assert nli_label.recall_threshold(pairs, 1.0) == 0.7
    assert nli_label.best_threshold(pairs) in (0.7, 0.9)


# ---------------------------------------------------------------------------------------------------
# run / sample / eval end to end with the fake scorer
# ---------------------------------------------------------------------------------------------------

def test_run_sample_eval_end_to_end(tmp_path, monkeypatch):
    pol_path = tmp_path / "policy.json"
    data = small_policy().data
    data["keywords_file"] = None
    pol_path.write_text(json.dumps(data), encoding="utf-8")
    inp = tmp_path / "in.jsonl"
    docs = [{"id": "a", "text": DOC, "source": "web"},
            {"id": "b", "text": "No keywords here, only Kiev.", "source": "wiki"},
            {"id": "c", "text": "The Russian invasion was reported by the fact-check desk; it falsely claims "
                                "Ukrainians are nazis.", "source": "web"}]
    inp.write_text("".join(json.dumps(d) + "\n" for d in docs), encoding="utf-8")

    fake = FakeScorer()
    monkeypatch.setattr(nli_label, "build_scorer", lambda args: (fake, None, None))
    out = tmp_path / "out"
    assert nli_label.main(["run", str(inp), "--output-dir", str(out), "--policy", str(pol_path),
                           "--write-clean", "--group-field", "source", "--all-labels"]) == 0
    rows = [json.loads(x) for x in (out / "in.labels.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["action"] for r in rows] == ["edited", "untouched", "review"]
    clean = [json.loads(x) for x in (out / "in.clean.jsonl").read_text(encoding="utf-8").splitlines()]
    assert clean[1]["text"] == "No keywords here, only Kyiv." and clean[1]["source"] == "wiki"
    summ = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summ["stats"]["lines"] == 3 and summ["stats"]["groups"]["web"]["docs"] == 2
    assert nli_label.main(["report", str(out)]) == 0
    # rerun skips the finished file
    assert nli_label.main(["run", str(inp), "--output-dir", str(out), "--policy", str(pol_path)]) == 0

    # review queue: doc c's paragraph (narrative softened by the debunk label) goes to human review
    rq = tmp_path / "review.jsonl"
    assert nli_label.main(["review", str(out), "--out", str(rq), "--policy", str(pol_path)]) == 0
    rmeta, ritems = nli_label.read_labels_file(str(rq))
    assert len(ritems) == 1 and "falsely claims" in ritems[0]["text"]
    assert ritems[0]["picked_for"][0] == "review:review_label" and ritems[0]["model"]["action"] == "review"
    assert rmeta["kind"].startswith("review queue")
    assert nli_label.main(["review", str(out), "--out", str(rq), "--policy", str(pol_path)]) == 2  # exists
    assert nli_label.main(["review", str(out), "--out", str(rq), "--policy", str(pol_path),
                           "--actions", "review", "remove", "--overwrite"]) == 0
    assert len(nli_label.read_labels_file(str(rq))[1]) == 2  # + doc a's removed paragraph

    # redecide: culture becomes 'keep' in a new policy -> doc a is no longer edited; no model is called
    calls = fake.fast_pairs
    data2 = json.loads(json.dumps(data))
    data2["labels"]["culture"]["decision"] = "keep"
    pol2 = tmp_path / "policy2.json"
    pol2.write_text(json.dumps(data2), encoding="utf-8")
    out2 = tmp_path / "out2"
    assert nli_label.main(["redecide", str(out), "--policy", str(pol2), "--output-dir", str(out2),
                           "--write-clean"]) == 0
    rows2 = [json.loads(x) for x in (out2 / "in.labels.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["action"] for r in rows2] == ["kept", "untouched", "review"]
    s2 = json.loads((out2 / "summary.json").read_text(encoding="utf-8"))
    assert s2["redecide"]["missing"] == 0 and s2["redecide"]["stored"] > 0
    assert fake.fast_pairs == calls
    assert nli_label.main(["redecide", str(out), "--output-dir", str(out)]) == 2  # not into the run itself

    lab = tmp_path / "seed.jsonl"
    assert nli_label.main(["sample", str(out), "--out", str(lab), "--policy", str(pol_path),
                           "--random", "2", "--top", "1", "--near", "1", "--low", "1"]) == 0
    meta, items = nli_label.read_labels_file(str(lab))
    assert set(meta["labels"]) == set(data["labels"]) and items
    assert all(it["status"] == "todo" and it["text"] for it in items)
    assert nli_label.main(["sample", str(out), "--out", str(lab), "--policy", str(pol_path)]) == 2  # no overwrite

    # label: a human marks everything; the fake scorer agrees on most
    for it in items:
        low = it["text"].lower()
        it["labels"] = {k: any(c in low for c in FakeScorer.CUES[v["hypothesis"]]) for k, v in data["labels"].items()}
        it["status"] = "done"
        it["picked_for"].append("random")
    nli_label.write_labels_file(str(lab), meta, items)
    rep = tmp_path / "eval.json"
    assert nli_label.main(["eval", str(lab), "--policy", str(pol_path), "--out", str(rep)]) == 0
    r = json.loads(rep.read_text(encoding="utf-8"))
    assert r["items"] == len(items)
    assert r["actions"]["n"] == len(items)
    assert (lab.parent / "seed.jsonl.scores.json").is_file()
    # second eval: everything cached, the scorer is not called again
    calls = fake.fast_pairs
    assert nli_label.main(["eval", str(lab), "--policy", str(pol_path)]) == 0
    assert fake.fast_pairs == calls


def test_policy_v2_and_cases_match():
    p2 = Policy.load(str(ROOT / "policy" / "russia_policy_v2.json"))
    p1 = Policy.load(str(ROOT / "policy" / "russia_policy.json"))
    assert set(p2.labels) - set(p1.labels) == {"values_mindset", "fashion_style", "narr_traditional_values"}
    assert "values_mindset" in p2.run_if[2]
    for name, pol in (("cases_v1.json", p1), ("cases_v2.json", p2)):
        path = ROOT / "labels" / name
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        ids = {c["id"] for c in data["cases"]}
        for k in pol.labels:  # every label has a yes and a near-miss case
            assert f"{k}:yes" in ids and f"{k}:near" in ids, (name, k)
        for c in data["cases"]:
            assert 1 <= len(c["texts"]) <= 2 and all(t["text"].strip() for t in c["texts"])
            for t in c["texts"]:
                assert set(t["labels_yes"]) <= set(pol.labels), (name, c["id"])

"""nli_label.py: --max-removed-share X and --drop-if-first-cut (plan 11_27 task 13): an edited document is removed
when too much of it is cut, or when its first checked paragraph is cut. Paragraph unit only. No models."""
import json

import pytest

import nli_label
from test_label import FakeScorer, make_labeller, rec, small_policy

# paragraph 1 is cut (ballet / film -> culture: remove), paragraph 2 kept (science)
CUT_FIRST = ("A long paragraph about Russian ballet and every film the theatre made, quite long enough here.\n\n"
             "Then a paragraph about Russian algorithm research in physics, also long enough to stand alone.")
# the same, the other way round: the first paragraph is kept, the second cut
CUT_SECOND = ("A long paragraph about Russian algorithm research in physics, also long enough to stand alone.\n\n"
              "Then a paragraph about Russian ballet and every film the theatre made, quite long enough here.")


def share_of(row):
    return row["tokens_removed"] / row["tokens"]


def test_off_by_default():
    lab = make_labeller()
    assert lab.max_removed_share is None and lab.drop_if_first_cut is False
    o = lab.process([rec(1, CUT_FIRST)])[0]
    assert o.row["action"] == "edited" and "removed_by" not in o.row and "removed_share" not in o.row
    assert o.clean is not None


def test_below_at_above_the_limit():
    row = make_labeller().process([rec(1, CUT_FIRST)])[0].row
    share = share_of(row)
    assert 0 < share < 1
    below = make_labeller(max_removed_share=min(1.0, share + 0.05)).process([rec(1, CUT_FIRST)])[0]
    assert below.row["action"] == "edited" and "removed_by" not in below.row and below.clean is not None
    at = make_labeller(max_removed_share=share).process([rec(1, CUT_FIRST)])[0]
    assert at.row["action"] == "edited" and at.clean is not None  # "above X" removes; X itself stays
    above = make_labeller(max_removed_share=share - 0.05).process([rec(1, CUT_FIRST)])[0]
    assert above.row["action"] == "removed" and above.clean is None
    assert above.row["removed_by"] == "removed_share" and above.row["removed_share"] == round(share, 4)


def test_kept_and_untouched_documents_are_not_affected():
    lab = make_labeller(max_removed_share=0.01, drop_if_first_cut=True)
    kept, untouched = lab.process([
        rec(1, "A long paragraph about Russian algorithm research in physics, also long enough here."),
        rec(2, "Nothing here but Kiev and some words.")])
    assert kept.row["action"] == "kept" and untouched.row["action"] == "untouched"
    assert "removed_by" not in kept.row and "removed_by" not in untouched.row


def test_min_doc_chars_comes_first():
    o = make_labeller(max_removed_share=0.01, min_doc_chars=10_000).process([rec(1, CUT_FIRST)])[0]
    assert o.row["action"] == "removed" and "removed_by" not in o.row  # removed by min_doc_chars as before


def test_drop_if_first_cut():
    lab = make_labeller(drop_if_first_cut=True)
    first, second = lab.process([rec(1, CUT_FIRST), rec(2, CUT_SECOND)])
    assert first.row["action"] == "removed" and first.row["removed_by"] == "first_cut" and first.clean is None
    assert "removed_share" in first.row
    assert second.row["action"] == "edited" and "removed_by" not in second.row and second.clean is not None


def test_review_as_remove_counts_as_cut():
    text = ("A long paragraph about Russian hockey and the league this season, quite long enough.\n\n"
            "Then a paragraph about Russian algorithm research in physics, also long enough here.")
    assert make_labeller(drop_if_first_cut=True).process([rec(1, text)])[0].row["action"] == "review"
    o = make_labeller(drop_if_first_cut=True, review_as="remove").process([rec(1, text)])[0]
    assert o.row["action"] == "removed" and o.row["removed_by"] == "first_cut"


def test_line_unit_unaffected():
    plain = make_labeller(unit="line").process([rec(1, CUT_FIRST), rec(2, CUT_SECOND)])
    ruled = make_labeller(unit="line", max_removed_share=0.01, drop_if_first_cut=True).process(
        [rec(1, CUT_FIRST), rec(2, CUT_SECOND)])
    assert [o.row for o in plain] == [o.row for o in ruled]
    assert all("removed_by" not in o.row for o in ruled)


# ---------------------------------------------------------------------------------------------------
# run / redecide / export end to end with the fake scorer
# ---------------------------------------------------------------------------------------------------

def _setup(tmp_path, monkeypatch):
    pol = tmp_path / "policy.json"
    pol.write_text(json.dumps(small_policy().data), encoding="utf-8")
    inp = tmp_path / "in.jsonl"
    docs = [{"id": "a", "text": CUT_FIRST}, {"id": "b", "text": CUT_SECOND}, {"id": "c", "text": "Only Kiev."}]
    inp.write_text("".join(json.dumps(d) + "\n" for d in docs), encoding="utf-8")
    fake = FakeScorer()
    monkeypatch.setattr(nli_label, "build_scorer", lambda args: (fake, None, None))
    return pol, inp, fake


def _run(tmp_path, pol, inp, name, *extra):
    out = tmp_path / name
    assert nli_label.main(["run", "--compress", "none", str(inp), "--output-dir", str(out), "--policy", str(pol),
                           "--write-clean", *extra]) == 0
    return out


def _rows(out, kind="labels"):
    return [json.loads(x) for x in (out / f"in.{kind}.jsonl").read_text(encoding="utf-8").splitlines()]


def _summary(out, name="summary.json"):
    return json.loads((out / name).read_text(encoding="utf-8"))


def test_run_off_is_byte_identical(tmp_path, monkeypatch):
    pol, inp, _ = _setup(tmp_path, monkeypatch)
    a = _run(tmp_path, pol, inp, "a")
    b = _run(tmp_path, pol, inp, "b", "--min-doc-chars", "50")
    for f in ("in.labels.jsonl", "in.clean.jsonl", "in.rewrites.jsonl"):
        assert (a / f).read_bytes() == (b / f).read_bytes()
    s = _summary(a)
    assert s["settings"]["max_removed_share"] is None and s["settings"]["drop_if_first_cut"] is False
    assert "removed_by" not in s["stats"] and "removed_by" not in _summary(a, "in.summary.json")["stats"]


def test_run_with_the_rules_and_summary_counts(tmp_path, monkeypatch):
    pol, inp, _ = _setup(tmp_path, monkeypatch)
    out = _run(tmp_path, pol, inp, "o", "--max-removed-share", "0.3", "--drop-if-first-cut")
    rows = _rows(out)
    assert [r["action"] for r in rows] == ["removed", "removed", "untouched"]
    assert [r.get("removed_by") for r in rows] == ["removed_share", "removed_share", None]
    assert [c["id"] for c in _rows(out, "clean")] == ["c"]
    s = _summary(out)
    assert s["settings"]["max_removed_share"] == 0.3 and s["settings"]["drop_if_first_cut"] is True
    assert s["stats"]["removed_by"] == {"removed_share": 2} and s["stats"]["docs"]["removed"] == 2
    assert _summary(out, "in.summary.json")["stats"]["removed_by"] == {"removed_share": 2}  # per file
    assert "removed instead of edited: removed_share 2" in nli_label.format_report(s)

    out2 = _run(tmp_path, pol, inp, "o2", "--drop-if-first-cut")
    assert [r.get("removed_by") for r in _rows(out2)] == ["first_cut", None, None]
    assert _summary(out2)["stats"]["removed_by"] == {"first_cut": 1}


@pytest.mark.parametrize("bad", ["0", "1.5", "-0.2", "x"])
def test_run_rejects_bad_limits(tmp_path, monkeypatch, bad):
    pol, inp, _ = _setup(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        nli_label.main(["run", str(inp), "--output-dir", str(tmp_path / "o"), "--policy", str(pol),
                        "--max-removed-share", bad])


def test_redecide_keeps_or_changes_the_runs_values(tmp_path, monkeypatch):
    pol, inp, fake = _setup(tmp_path, monkeypatch)
    out = _run(tmp_path, pol, inp, "o", "--drop-if-first-cut", "--all-labels")
    calls = fake.fast_pairs

    def redecide(name, *extra):
        o = tmp_path / name
        assert nli_label.main(["redecide", "--compress", "none", str(out), "--policy", str(pol), "--output-dir",
                               str(o), "--write-clean", *extra]) == 0
        return o

    same = redecide("same")  # no option: the run's own values
    assert [r.get("removed_by") for r in _rows(same)] == ["first_cut", None, None]
    assert _summary(same)["settings"]["drop_if_first_cut"] is True
    assert _summary(same)["settings"]["max_removed_share"] is None

    off = redecide("off", "--no-drop-if-first-cut")
    assert [r["action"] for r in _rows(off)] == ["edited", "edited", "untouched"]
    assert "removed_by" not in _summary(off)["stats"]

    share = redecide("share", "--max-removed-share", "0.3")
    assert [r.get("removed_by") for r in _rows(share)] == ["removed_share", "removed_share", None]
    assert _summary(share)["settings"]["max_removed_share"] == 0.3

    # a redecided run with a limit, redecided again: kept without the option, turned off with 0 / off
    again = tmp_path / "again"
    assert nli_label.main(["redecide", "--compress", "none", str(share), "--policy", str(pol), "--output-dir",
                           str(again), "--no-drop-if-first-cut"]) == 0
    assert _summary(again)["settings"]["max_removed_share"] == 0.3
    assert _summary(again)["stats"]["removed_by"] == {"removed_share": 2}
    nolimit = tmp_path / "nolimit"
    assert nli_label.main(["redecide", "--compress", "none", str(share), "--policy", str(pol), "--output-dir",
                           str(nolimit), "--no-drop-if-first-cut", "--max-removed-share", "off"]) == 0
    assert _summary(nolimit)["settings"]["max_removed_share"] is None
    assert [r["action"] for r in _rows(nolimit)] == ["edited", "edited", "untouched"]
    assert fake.fast_pairs == calls  # no model was called


def test_export_simple_mode(tmp_path, monkeypatch):
    pol, inp, _ = _setup(tmp_path, monkeypatch)
    out = _run(tmp_path, pol, inp, "o", "--all-labels")

    def export(name, *extra):
        o = tmp_path / name
        assert nli_label.main(["export", "--compress", "none", str(out), "--output-dir", str(o), *extra]) == 0
        return o

    plain = export("x0")
    assert "removed_by" not in _summary(plain)["stats"]
    ruled = export("x1", "--max-removed-share", "0.3")
    s = _summary(ruled)
    assert s["settings"]["output_mode"] == "simple" and s["settings"]["max_removed_share"] == 0.3
    assert s["stats"]["removed_by"] == {"removed_share": 2} and s["stats"]["docs"]["removed"] == 2
    assert s["stats"]["docs"].get("edited", 0) == _summary(plain)["stats"]["docs"]["edited"] - 2
    # the simple run itself (no models needed by the fake scorer) also works with the options
    simple = _run_simple(tmp_path, pol, inp)
    assert _summary(simple)["stats"]["removed_by"] == {"first_cut": 1}
    assert [r["decision"] for r in _rows(simple, "decisions")] == ["removed", "edited", "untouched"]
    assert [r["decision"] for r in _rows(ruled, "decisions")] == ["removed", "removed", "untouched"]


def _run_simple(tmp_path, pol, inp):
    out = tmp_path / "simple"
    assert nli_label.main(["run", "--compress", "none", str(inp), "--output-dir", str(out), "--policy", str(pol),
                           "--output-mode", "simple", "--drop-if-first-cut"]) == 0
    return out

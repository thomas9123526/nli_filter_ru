"""--keywords-only: filter on keyword hits alone, no model loaded (./models not needed)."""
import json

import nli_filter as nf

TEXTS = [
    "Moscow is the capital of Russia.",                            # keyword, open        -> filter keyword_only
    "Available languages: English, German, Russian, Japanese.",    # language label rule  -> keep rules_incidental
    "Nothing about any country here.",                             # no keyword           -> keep no_keyword
    "Stalin ruled for decades.",                                   # level-A keyword      -> filter strict_keyword
    "",                                                            # blank                -> keep blank
]


def _setup(tmp_path):
    src = tmp_path / "a.jsonl"
    src.write_text("".join((json.dumps({"id": str(i), "text": t}) if t else "") + "\n"
                           for i, t in enumerate(TEXTS, 1)), encoding="utf-8")
    kw = tmp_path / "kw.txt"
    kw.write_text("Russia\nRussian\nMoscow\nStalin\tA\tperson\n", encoding="utf-8")
    empty = tmp_path / "no_models"  # an empty models folder: loading any model would fail
    empty.mkdir()
    return src, kw, empty


def _decisions(out):
    rows = [json.loads(x) for x in (out / "a.decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    return {r["line"]: (r["decision"], r["reason"]) for r in rows}


def test_keywords_only_filters_without_models(tmp_path):
    src, kw, empty = _setup(tmp_path)
    out = tmp_path / "out"
    assert nf.main([str(src), "--keywords-file", str(kw), "--keywords-only", "--models-root", str(empty),
                    "--write-split", "--output-dir", str(out), "--no-progress-file"]) == 0
    assert _decisions(out) == {1: ("filter", "keyword_only"), 2: ("keep", "rules_incidental"),
                               3: ("keep", "no_keyword"), 4: ("filter", "strict_keyword"), 5: ("keep", "blank")}
    filtered = (out / "a.filtered.jsonl").read_text(encoding="utf-8").splitlines()
    kept = (out / "a.kept.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["id"] for x in filtered] == ["1", "4"]
    assert [json.loads(x)["id"] for x in kept] == ["2", "3"]  # the blank line is not copied
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["settings"]["keywords_only"] is True
    assert summary["models"] == {"fast": nf.NoModel().info(), "judge": None}
    assert summary["timing"]["fast_pairs"] == 0 and summary["timing"]["judge_pairs"] == 0
    assert summary["stats"]["reasons"]["keyword_only"] == 1
    # --report rebuilds the summary from the per-file summaries
    assert nf.main(["--report", "--output-dir", str(out)]) == 0


def test_keywords_only_no_rules_filters_every_hit(tmp_path):
    src, kw, empty = _setup(tmp_path)
    out = tmp_path / "out"
    assert nf.main([str(src), "--keywords-file", str(kw), "--keywords-only", "--no-rules", "--models-root",
                    str(empty), "--output-dir", str(out), "--no-progress-file"]) == 0
    assert _decisions(out)[2] == ("filter", "keyword_only")


def test_keywords_only_option_errors(tmp_path):
    src, kw, empty = _setup(tmp_path)
    base = [str(src), "--keywords-file", str(kw), "--keywords-only", "--output-dir", str(tmp_path / "o")]
    assert nf.main(base + ["--audit-strict", "0.5"]) == 2
    assert nf.main(base + ["--keywords-report"]) == 2


def test_line_filter_keywords_only_never_scores():
    class Boom:
        name, devices, mode = "boom", ["cpu"], "single"

        def score(self, premises, hyps):
            raise AssertionError("a model was asked")

    s = nf.FilterSettings("Russia", "Russian", {"c": "This text is about Russia."}, {}, keywords_only=True,
                          audit_strict=1.0)
    lex = nf.parse_keywords(["Russia", "Stalin\tA\tperson"])
    lf = nf.LineFilter(s, nf.KeywordMatcher(lex), nf.IncidentalRules("Russian"), nf.WindowBuilder(),
                       nf.CascadeScorer(Boom(), None, (0.6, 0.95)))
    from nli_models import Record
    recs = [Record("x.jsonl", i, {"text": t}, json.dumps({"text": t}).encode())
            for i, t in enumerate(["Russia is big.", "Stalin and Russia."], 1)]
    got = [(o.decision["decision"], o.decision["reason"]) for o in lf.process(recs)]
    assert got == [("filter", "keyword_only"), ("filter", "strict_keyword")]  # audit is off without models

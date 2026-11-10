"""Tests for nli_filter.py: keywords, rules, windows, decisions, runner outputs, resume, report, CLI."""
import gzip
import json
import random
import re
import zipfile
from pathlib import Path

import pytest

import nli_filter as nf
from conftest import ROOT, FakePool
from nli_models import JsonlSource

RU = nf.COUNTRIES["russia"]


# ---------------------------------------------------------------- keywords

@pytest.fixture(params=[True, False], ids=["ahocorasick", "regex"])
def matcher(request):
    if request.param and nf.ahocorasick is None:
        pytest.skip("pyahocorasick not installed")
    return nf.KeywordMatcher(RU["keywords"], use_ahocorasick=request.param)


def kws(m, text):
    return [text[h.start:h.end] for h in m.find(text)]


def test_word_boundaries(matcher):
    assert kws(matcher, "The Prussian army and the Byelorussian delegation.") == []
    assert kws(matcher, "See https://example.com/visitrussia2024/ now") == []
    assert kws(matcher, "Kremlinology was a practice.") == []
    assert kws(matcher, "Russia's economy; Russians; RUSSIAN") == ["Russia", "Russians", "RUSSIAN"]


def test_longest_match_and_cjk(matcher):
    assert kws(matcher, "the Russian Federation was") == ["Russian Federation"]
    assert kws(matcher, "言語: ロシア語 と Россия") == ["ロシア", "Россия"]  # CJK: substring allowed


def test_exclude_pattern():
    m = nf.KeywordMatcher(["中国", "China"], exclude_patterns=["中国地方"])
    assert kws(m, "中国地方の天気と中国の経済") == ["中国"]
    assert m.find("中国地方の天気") == []


def test_single_cjk_keyword_warns():
    assert nf.KeywordMatcher(["露", "Russia"]).warnings


def test_engines_agree_on_test_file():
    if nf.ahocorasick is None:
        pytest.skip("pyahocorasick not installed")
    a = nf.KeywordMatcher(RU["keywords"], use_ahocorasick=True)
    b = nf.KeywordMatcher(RU["keywords"], use_ahocorasick=False)
    for line in open(ROOT / "test_russia.jsonl", encoding="utf-8"):
        t = json.loads(line)["text"]
        assert [(h.start, h.end) for h in a.find(t)] == [(h.start, h.end) for h in b.find(t)], t


def test_trie_regex_equals_plain_alternation():
    rng = random.Random(3)
    words = nf.LANGUAGE_NAMES + ["Russian", "Rus", "Russ", "Ru"]
    plain = re.compile("|".join(
        (r"(?<!\w)" if nf._needs_boundary(w[0]) else "") + re.escape(w) + (r"(?!\w)" if nf._needs_boundary(w[-1]) else "")
        for w in sorted(set(words), key=len, reverse=True)), re.IGNORECASE)
    trie = nf._phrase_regex(words)
    pool = words + ["the", "and", ",", " | ", "Prussian", "日本", "語", "Englishman"]
    for _ in range(300):
        text = " ".join(rng.choice(pool) for _ in range(rng.randint(1, 12)))
        assert [m.span() for m in plain.finditer(text)] == [m.span() for m in trie.finditer(text)], text


def test_keywords_match_test_file_labels(matcher):
    for line in open(ROOT / "test_russia.jsonl", encoding="utf-8"):
        d = json.loads(line)
        if "러시아" in d["text"] and not any(k in d["text"] for k in ("Russia", "Moscow", "ロシア", "Россия")):
            continue  # Korean keyword removed from the list on purpose
        assert bool(matcher.find(d["text"])) == d["has_keyword"], d["id"]


# ---------------------------------------------------------------- rules

@pytest.fixture
def rules():
    return nf.IncidentalRules("Russian")


def rule_of(text, rules):
    m = nf.KeywordMatcher(RU["keywords"])
    hits = m.find(text)
    rules.apply(text, hits)
    return [(text[h.start:h.end], h.rule) for h in hits]


@pytest.mark.parametrize("text,expected", [
    ("Available languages: English, German, Russian, Japanese.", "language_label"),
    ("This manual is also available in Russian, Polish and Czech.", "language_menu"),
    ("Language: Russian", "language_label"),
    ("Set the locale to ru-RU to show dates in the Russian format.", "locale_code"),
    ("Dubbed versions: Russian, Hindi, Portuguese.", "language_menu"),
    ("He wrote a Russian novel about the war.", None),
    ("Russian and English", None),  # only two names: not a menu
])
def test_language_rules(rules, text, expected):
    assert rule_of(text, rules)[0][1] == expected


def test_rule_only_for_language_hits(rules):
    assert rule_of("Language: English | Russian. The history of Russia is long.", rules) == \
        [("Russian", "language_label"), ("Russia", None)]


def test_rule_far_from_menu_in_long_text(rules):
    text = "Language: English | Russian | German. " + "filler words here. " * 500 + "A Russian novel."
    assert [r for _, r in rule_of(text, rules)] == ["language_label", None]


def test_company_names():
    r = nf.IncidentalRules("Russian", company_names=["Russian River Brewing Company"])
    assert rule_of("Russian River Brewing Company sponsored it. Russia's crisis.", r) == \
        [("Russian", "company_name"), ("Russia", None)]


# ---------------------------------------------------------------- windows

def test_windows_short_and_long():
    w = nf.WindowBuilder(check1_chars=200, check2_chars=80, max_windows=2)
    short = "Russia is big."
    assert w.check1(short, [nf.Hit(0, 6)]) == [(0, len(short))]
    text = ("x " * 300) + "Russia here. " + ("y " * 300) + "Moscow too. " + ("z " * 300) + "Kremlin end."
    hits = nf.KeywordMatcher(RU["keywords"]).find(text)
    wins = w.check1(text, hits)
    assert len(wins) == 2
    for (a, b), h in zip(wins, hits):
        assert a <= h.start and h.end <= b and b - a <= 200 + 10
    ends = w.sentence_ends(text)
    a, b = w.check2(text, hits[0], ends)
    assert text[a:b].endswith("Russia here.") and b - a <= 80


def test_check2_window_is_the_sentence():
    w = nf.WindowBuilder()
    t = "Russian River Brewing Company sponsored the lecture. The speaker discussed Russia's crisis."
    hits = nf.KeywordMatcher(RU["keywords"]).find(t)
    ends = w.sentence_ends(t)
    assert [t[slice(*w.check2(t, h, ends))] for h in hits] == \
        ["Russian River Brewing Company sponsored the lecture.", "The speaker discussed Russia's crisis."]


# ---------------------------------------------------------------- decisions

def make_filter(judge=False, check2=True):
    s = nf.FilterSettings("Russia", "Russian", nf._render(nf.DEFAULT_CHECK1, "Russia", "Russian", "c1"),
                          nf._render(nf.DEFAULT_CHECK2, "Russia", "Russian", "c2") if check2 else {})
    scorer = nf.CascadeScorer(FakePool("fast"), FakePool("judge") if judge else None, (0.6, 0.95))
    return nf.LineFilter(s, nf.KeywordMatcher(RU["keywords"]), nf.IncidentalRules("Russian"), nf.WindowBuilder(), scorer)


def records(texts):
    from nli_models import Record
    return [Record("x.jsonl", i, {"id": f"r{i}", "text": t}, json.dumps({"text": t}).encode())
            for i, t in enumerate(texts, 1)]


@pytest.mark.parametrize("text,decision,reason", [
    ("The history of Russia is long.", "filter", "about_country"),
    ("Preheat the oven.", "keep", "no_keyword"),
    ("Language: Russian", "keep", "rules_incidental"),
    ("Playing Russian roulette with savings.", "keep", "check1_negative"),
    ("Russian River Brewing Company history night.", "keep", "check2_incidental"),
    ("Russian River Brewing Company sponsored it. The history of Russia was discussed.", "filter", "about_country"),
    ("", "keep", "no_text"),
])
def test_decisions(text, decision, reason):
    out = make_filter().process(records([text]))[0].decision
    assert (out["decision"], out["reason"]) == (decision, reason)
    assert list(out)[:3] == ["line", "decision", "reason"]


def test_blank_and_bad_json():
    from nli_models import Record
    outs = make_filter().process([Record("x", 1, None, b"", "blank"), Record("x", 2, None, b"{", "bad_json: x")])
    assert [o.decision["reason"] for o in outs] == ["blank", "bad_json"]


def test_judge_only_in_band():
    f = make_filter(judge=True)
    out = f.process(records(["An uncertain text about Russia.", "The history of Russia."]))
    p0 = out[0].decision["check1"]["pairs"][0]
    p1 = out[1].decision["check1"]["pairs"][0]
    assert p0["judge"] is not None and p1["judge"] is None
    assert f.scorer.judge_pairs >= 1


def test_no_check2_never_rescues():
    out = make_filter(check2=False).process(records(["Russian River Brewing Company history night."]))[0]
    assert out.decision["reason"] == "about_country"


def test_hit_spans_point_at_keywords():
    texts = [json.loads(l)["text"] for l in open(ROOT / "test_russia.jsonl", encoding="utf-8")]
    for out in make_filter().process(records(texts)):
        for h in out.decision.get("hits", []):
            assert out.text[h["span"][0]:h["span"][1]] == h["kw"]


# ---------------------------------------------------------------- runner, outputs, resume, report

def write_inputs(folder: Path, n=30):
    folder.mkdir(parents=True, exist_ok=True)
    src = open(ROOT / "test_russia.jsonl", encoding="utf-8").read().splitlines()[:n]
    data = ("\n".join(src) + "\n").encode()
    (folder / "a.jsonl").write_bytes(data)
    (folder / "sub").mkdir(exist_ok=True)
    (folder / "sub" / "b.jsonl.gz").write_bytes(gzip.compress(data))
    with zipfile.ZipFile(folder / "sub" / "c.zip", "w") as z:
        z.writestr("c1.jsonl", data + b"\nnot json\n")
    if nf.zstd_available():
        import zstandard
        (folder / "d.jsonl.zst").write_bytes(zstandard.ZstdCompressor().compress(data))
    return len(src)


def run(files, out, **kw):
    r = nf.FilterRunner(make_filter(), out, compress=kw.pop("compress", "none"), write_split=kw.pop("write_split", True),
                        chunk_lines=7, inflight=kw.pop("inflight", 1), **kw)
    r.run(files)
    return r


def read_lines(p: Path):
    return list(JsonlSource(p).records(parse=False))


def read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def test_runner_outputs(tmp_path):
    write_inputs(tmp_path / "in")
    files = nf.expand_inputs([str(tmp_path / "in")])
    r = run(files, tmp_path / "out")
    for name in ("a", "sub/b", "sub/c") + (("d",) if nf.zstd_available() else ()):
        dec = read_lines(tmp_path / "out" / f"{name}.decisions.jsonl")
        summ = read_json(tmp_path / "out" / f"{name}.summary.json")
        assert summ["complete"] and summ["stats"]["lines"] == len(dec)
        kept = read_lines(tmp_path / "out" / f"{name}.kept.jsonl")
        filt = read_lines(tmp_path / "out" / f"{name}.filtered.jsonl")
        non_blank = sum(1 for d in dec if json.loads(d.raw)["reason"] != "blank")
        assert len(kept) + len(filt) == non_blank
        assert len(filt) == sum(1 for d in dec if json.loads(d.raw)["decision"] == "filter")
    zipdec = [json.loads(d.raw) for d in read_lines(tmp_path / "out" / "sub" / "c.decisions.jsonl")]
    assert zipdec[0]["source"] == "c1.jsonl" and zipdec[-1]["reason"] in ("bad_json", "blank")
    assert r.total.lines == sum(f["lines"] for f in r.files)


def test_inflight_threads_same_result(tmp_path):
    write_inputs(tmp_path / "in")
    files = nf.expand_inputs([str(tmp_path / "in" / "a.jsonl")])
    run(files, tmp_path / "o1", inflight=1)
    run(files, tmp_path / "o3", inflight=3)
    assert (tmp_path / "o1" / "a.decisions.jsonl").read_bytes() == (tmp_path / "o3" / "a.decisions.jsonl").read_bytes()


def test_resume_and_limit(tmp_path):
    n = write_inputs(tmp_path / "in")
    files = nf.expand_inputs([str(tmp_path / "in")])
    r1 = run(files, tmp_path / "out", limit=n + 5)  # first file complete, second cut
    assert [f["status"] for f in r1.files] == ["done", "partial (--limit)"]
    r2 = run(files, tmp_path / "out")
    statuses = [f["status"] for f in r2.files]
    assert statuses[0] == "skipped (already done)" and statuses[1] == "done"
    assert all(s in ("done", "skipped (already done)") for s in statuses)


def test_compressed_outputs(tmp_path):
    if not nf.zstd_available():
        pytest.skip("zstandard not installed")
    write_inputs(tmp_path / "in")
    run(nf.expand_inputs([str(tmp_path / "in" / "a.jsonl")]), tmp_path / "out", compress="zst")
    assert len(read_lines(tmp_path / "out" / "a.decisions.jsonl.zst")) == 30


def test_cli_main_with_fake_models(tmp_path, monkeypatch, capsys):
    write_inputs(tmp_path / "in")
    monkeypatch.setattr(nf, "NLIPool", lambda name, **kw: FakePool(name))
    out = tmp_path / "out"
    assert nf.main([str(tmp_path / "in" / "a.jsonl"), "--output-dir", str(out), "--shard", "0/1"]) == 0
    text = capsys.readouterr().out
    assert "NLI country filter - Russia" in text and "evaluation against 'expect'" in text
    assert (out / "summary.shard-0-of-1.json").exists()
    assert nf.main(["--report", "--output-dir", str(out)]) == 0
    rep = read_json(out / "summary.report.json")
    assert rep["stats"]["lines"] == 30 and rep["timing"]["fast_pairs"] > 0


@pytest.mark.parametrize("argv,msg", [
    (["nope.jsonl"], "input not found"),
    (["--country", "Japan"], "--country-adj is required"),
    (["--uncertain-band", "0.9", "0.1"], "--uncertain-band"),
    (["--shard", "3/2"], "--shard"),
])
def test_cli_errors(argv, msg, capsys):
    assert nf.main(argv) == 2
    assert msg in capsys.readouterr().err


def test_report_without_runs(tmp_path):
    assert nf.main(["--report", "--output-dir", str(tmp_path)]) == 2

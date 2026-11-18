"""nli_compare.py: two output folders compared line by line."""
import json

import zstandard

import nli_compare


def _out(root, name, decisions, summary, zst=False):
    d = root / name / "web"
    d.mkdir(parents=True)
    data = "".join(json.dumps(x) + "\n" for x in decisions).encode()
    if zst:
        (d / "part-0.decisions.jsonl.zst").write_bytes(zstandard.ZstdCompressor().compress(data))
    else:
        (d / "part-0.decisions.jsonl").write_bytes(data)
    (root / name / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return root / name


def test_compare(tmp_path, capsys):
    base = [{"line": 1, "id": "a", "decision": "filter", "reason": "about_country", "expect": "filter",
             "check1": {"score": 0.9}, "hits": [{"kw": "Russia"}]},
            {"line": 2, "id": "b", "decision": "filter", "reason": "about_country", "expect": "keep",
             "check1": {"score": 0.85}, "hits": [{"kw": "moscow", "keyword": "Moscow"}]},
            {"line": 3, "id": "c", "decision": "keep", "reason": "no_keyword"}]
    new = [dict(base[0], decision="keep", reason="check2_incidental"),
           dict(base[1], decision="keep", reason="check1_negative"), base[2]]
    sa = {"hypotheses": {"file": "h1.json", "check1": {"t": "x", "region": "r"}},
          "settings": {"check1_threshold": 0.8}, "country": {"keywords": ["Russia", "Moscow"]},
          "timing": {"fast_pairs": 10}}
    sb = {"hypotheses": {"file": "h2.json", "check1": {"t": "x"}, "check1_types": {"city": {"p": "{kw}"}}},
          "settings": {"check1_threshold": 0.7}, "country": {"keywords": ["Russia", "Moscow", "Siberia"]},
          "timing": {"fast_pairs": 8}}
    a = _out(tmp_path, "A", base, sa)
    b = _out(tmp_path, "B", new, sb, zst=True)
    r = nli_compare.compare(a, b)
    assert r["lines"] == 3 and r["same"] == 1 and r["changes"] == {"filter -> keep": 2}
    assert r["verdicts"] == {"worse": 1, "better": 1}
    assert r["a"]["metrics"]["accuracy"] == 0.5 and r["b"]["metrics"]["accuracy"] == 0.5
    by = {c["id"]: c for c in r["changed"]}
    assert by["b"]["keywords"] == ["Moscow"] and by["a"]["verdict"] == "worse"
    assert ("check1_threshold", 0.8, 0.7) in r["diffs"]["settings"]
    assert r["diffs"]["check1"] == [("region", "r", None)] and r["diffs"]["keywords_only_b"] == ["Siberia"]
    assert nli_compare.main([str(a), str(b), "--json", str(tmp_path / "c.json")]) == 0
    out = capsys.readouterr().out
    assert "[worse] web/part-0:1 id a expect filter" in out and "keywords only in B: Siberia" in out
    assert json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))["same"] == 1
    assert nli_compare.main([str(a), str(tmp_path / "nope")]) == 2
    (tmp_path / "E").mkdir()
    assert nli_compare.main([str(a), str(tmp_path / "E")]) == 2

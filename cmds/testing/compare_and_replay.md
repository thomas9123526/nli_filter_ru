# Comparing runs, replaying with other settings, regression

Added 2026-11-18. None of these tools load a model, so they run in seconds on any machine.

## nli_compare.py: two runs, line by line

```powershell
python nli_compare.py out_ru_plain out_ru_kw
python nli_compare.py out_ru_plain out_ru_kw --show 100 --json compare.json
```

Use it on two output folders of the **same input** (for example the same test file with other keywords,
hypotheses or thresholds). It shows:

- each run's accuracy, precision and recall (lines with `expect`), model pairs and run time
- the lines whose decision changed, marked **better** (now right), **worse** (now wrong) or unlabelled, with the
  reasons, check-1 scores, keywords and the text
- the reasons that changed (e.g. `about_country -> check2_incidental: 1`)
- what differs between the runs: settings, check-1 / check-2 hypotheses, keyword templates, keywords, lexicon

Example, from the two test runs of 2026-11-17:

```
 lines 97: same decision 95, changed 2  (filter -> keep 2)
   worse 1, better 1
  [worse] test_russia:19 id about-019 expect filter
      A filter (about_country, c1 0.985)  ->  B keep (check2_incidental, c1 0.985)  keywords Russian
  [better] test_russia:51 id fixed_expression-005 expect keep
      A filter (about_country, c1 0.866)  ->  B keep (check1_negative, c1 0.250)  keywords Moscow
```

The text is read from the run's input file when it is still on this machine. If the input changed since the
run (lines added or deleted), the text can belong to another line. The ids are always right.

## nli_replay.py: other thresholds or fewer hypotheses, without models

```powershell
python nli_replay.py out_ru_kw --drop-check1 history --output-dir out_ru_kw_nohistory
python nli_replay.py out_ru_kw --check1-threshold 0.7 --check2-threshold 0.9 --output-dir out_ru_kw_t07
python nli_compare.py out_ru_kw out_ru_kw_nohistory
```

This recomputes every decision from the scores the run stored and writes a normal output folder. The viewer can
show it (add it as a dataset with the same corpus), and `nli_compare.py` can compare it.

- `--drop-check1 KEY ...` / `--drop-check2 KEY ...` leave out hypotheses. A keyword-template key drops every
  hypothesis built from it (`place` drops `place:Siberia`, `place:Moscow`, …).
- `--check1-threshold` / `--check2-threshold` change the thresholds. The Tune page does the same for thresholds
  only.
- **Exact or estimated.** Every hypothesis of a scored window or sentence is stored, so the replay is exact for
  them. Early stop (on by default) leaves some windows or hits unscored. When a decision depends on those, the
  line gets `replay.estimated = true`, and the count is printed. For exact replays, run once with
  `--no-early-stop`.
- Lines decided without models (no keyword, rules, level-A keywords) keep their decision.
- **Adding** a hypothesis or keyword needs a real run: no score exists for it.

Example: leaving out `region` and `geography` from the plain run would fix the Moscow mule line but lose
`about-004` (Saint Petersburg, c1 0.990 to 0.782), with no model run needed.

## Regression: the golden set

1. Label lines in the viewer (Review page, or the filter / keep buttons on a record page). They are collected in
   `golden/<dataset>.jsonl` (see `cmds/viewer/review_tools.md`).
2. Run the golden set with the current settings:
   `python nli_filter.py golden\web.jsonl --output-dir out_golden_web_v1`
3. After a change to keywords or hypotheses, run it again into a **new** folder, then compare:
   `python nli_compare.py out_golden_web_v1 out_golden_web_v2`

The "worse" lines are the regressions. Keep the change only if the better lines outweigh them.

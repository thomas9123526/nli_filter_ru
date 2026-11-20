# Benchmarks: fixed test sets for the policy labels

Two kinds, with different jobs:

| | Synthetic regression set | Real-data benchmark |
|---|---|---|
| File | `labels\bench_synthetic_v1.jsonl` (exists) | `labels\bench_v1_dev.jsonl` + `labels\bench_v1_test.jsonl` (to build) |
| Texts | 170 short paragraphs written for the purpose | real paragraphs from the corpus (OLMo / Dolma / Nemotron) |
| Labels | known by construction: every paragraph targets one label, as a clear **yes** or a **near miss** | checked by you in the label tool |
| Covers | every label, incl. each narrative and hostility label, debunking news, conflicts | what the corpus really contains (few narratives in random web text) |
| Answers | "did a change to a hypothesis / threshold break a label?" | "how accurate is the policy on our data?" |
| Use for decisions | no: synthetic text is cleaner than the web | yes: thresholds, the CRC guarantee |

## The synthetic regression set: `labels\bench_synthetic_v1.jsonl`

Written on 2026-11-20 (three drafting passes from one written brief, assembled and checked by
`tools\build_bench.py`). Same format as the other label files, so `eval` and the label tool read it directly.

- 170 items: per label 3–4 **yes** + 2–3 **near** (gate: 6 yes + 8 near: Russian dressing, Russian roulette,
  Moscow Idaho, St. Petersburg Florida, a language menu, …), 8 **conflict** items (a remove and a keep subject both
  true), 4 **no subject** items (Russia-related, no level-1 label).
- Near misses for narratives are mostly news / fact-checks that **quote or debunk** the claim
  (`reports_or_debunks` yes, narrative no).
- `picked_for` = `bench:<target>:<yes|near>`, `status` = done, `by` = synthetic, `note` = why the answer is right,
  `expected_action` = what the policy derives from the labels.
- Invented names, except a few public figures (e.g. Daniil Medvedev, Oleksandr Usyk).

```powershell
python nli_label.py eval labels\bench_synthetic_v1.jsonl --judge-model none
```

Rerun it after **every** change to `policy\russia_policy.json`. A label whose numbers drop has been broken by the
change. Scores are cached (`labels\bench_synthetic_v1.jsonl.scores.json`), so after a hypothesis change only that
label is scored again. Keep the file fixed. When it needs changes, write `bench_synthetic_v2.jsonl`, so results
stay comparable.

Read the items in the label tool to see what each case looks like (open the file as usual). Disagree with an
answer? Change it, note why, and save as v2.

### First result (2026-11-20, ModernBERT only, policy thresholds; full report `out_eval_bench_v1.json`)

Actions: **agreement 133 / 170 (78 %)**, wrongly removed ~177 tokens, missed ~1,392 tokens.

| What | Result at the policy thresholds | Suggests |
|---|---|---|
| Gate `involves_russia` | precision 0.97, recall 0.84; 10 of 47 "remove" items never pass the gate | lower the gate threshold (recall 0.90 at 0.12) |
| Remove subjects (culture, celebrities, lifestyle, cost of living) | F1 0.82–1.00 | fine as they are |
| Keep subjects politics, war, Soviet history | precision 0.90–1.00 but recall 0.53–0.57 | lower thresholds (best F1 at 0.17–0.26 for politics / war) |
| Narratives | 5 of 9 at F1 ≥ 0.80; weak: `narr_russian_greatness` (precision 0.38), `narr_annexation` (0.50), `narr_ukraine_not_nation` (0.67) | look at their near misses; reword these hypotheses |
| `hostility_ukrainians` | precision 0.50: fires on news that *reports* hostile words | the `reports_or_debunks` guard turns those into review, not remove |

Small numbers (3 yes per narrative) and clean synthetic text: use this to compare policy versions, not as the
accuracy on real data.

## The real-data benchmark (to build, after the seed check)

1. Check the drafts in `labels\seed.jsonl` (all `done`).
2. On a GPU machine: `run --all-labels` over a few thousand gated documents, then per-label rounds
   (`sample --label <key> --top 40 --near 30 --low 30 --random 0 --exclude labels\*.jsonl …`) until each label has
   ~50 yes + 50 no. Narratives need news / forum sources, not only random web text.
3. Split 70 / 30 into dev and test, stratified so each label is in both (a `nli_label.py split` command is the
   small next step).
4. Tune thresholds and wordings **only on dev**. Report final numbers on test once per policy version.
5. Freeze the files (`bench_v1_*`). New labels or rounds become `bench_v2_*`.

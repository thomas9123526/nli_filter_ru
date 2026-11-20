# Measuring labels and choosing thresholds: `nli_label.py eval`

```powershell
python nli_label.py eval labels\seed.jsonl --judge-model none
python nli_label.py eval labels\seed.jsonl labels\celebrities.jsonl --out out_eval.json
```

Use the **same models** for `eval` as for the real `run` (`--fast-model`, `--judge-model`, `--uncertain-band`):
thresholds belong to a model setup. Scores are cached per setup in `<first labels file>.scores.json`.
When the setup matches the run the labels were sampled from (`labels\seed.jsonl`: ModernBERT, no judge, so
`--judge-model none`), `eval` reuses that run's scores and needs no model at all. With another setup (e.g. the default
DeBERTa judge) it scores the labelled paragraphs once: 182 × 25 pairs ≈ 1 hour on this CPU.

## The table

```
label                          dec.     yes   no |  thr   prec  recall    F1 | best-F1 thr  thr@recall0.90  CRC@miss0.05
culture_entertainment          remove     14  180 | 0.80  0.71  0.86  0.78 |      0.74         0.62       n=6<19 (<50 yes/no)
```

| Column | Meaning |
|---|---|
| yes / no | Your labels for this label (done items). The guide's target: **≥ 50 yes and ≥ 50 no** per label. Fewer is marked `(<50 yes/no)`: the numbers are rough |
| thr | The threshold in the policy |
| prec | Of the paragraphs the model says yes to, the share you also said yes to (wrong removals ↔ precision of `remove` labels) |
| recall | Of the paragraphs you said yes to, the share the model also says yes to (misses ↔ recall) |
| best-F1 thr | The threshold with the best balance of the two on these labels |
| thr@recall | The highest threshold that still finds ≥ `--target-recall` (0.90) of your yes paragraphs |
| CRC@miss | The threshold with a **guarantee** (below); `n=6<19` = not enough random yes paragraphs yet |

Below the table: **actions**. Rows = your action (or the one your labels imply), columns = the policy's action from
the model scores. The two numbers that matter for A:
- **wrongly removed** (policy says remove, you say keep / pass) costs the model accuracy on permitted topics;
- **missed** (you say remove, the policy doesn't) leaves unwanted content in.

## Choosing a threshold

1. `remove` labels: the policy must stay **exactly as wide as the policy**. Start from **best-F1**. If wrong removals
   are too costly, raise the threshold (precision up, recall down); if misses are, lower it.
2. `keep` labels: they protect content. A low threshold keeps more ("conflict → review" instead of remove).
3. The gate: a miss here skips every other label, so keep its threshold low (recall first).
4. Write the new thresholds into `policy\russia_policy.json`, rerun `eval`, and check the actions table.

A label with low precision **and** low recall at every threshold has a wording problem, not a threshold problem:
try 2–3 other hypotheses (copy the policy, `--policy` the copy, compare).

## The guarantee (Conformal Risk Control)

From the reference papers (`cmds\explain\model_references.md`, section 5). For a `remove` or gate label:

> Choose the highest threshold t with (misses(t) + 1) / (n + 1) ≤ α, where n = your **yes** paragraphs that were
> picked **at random**, and misses(t) = how many of them score below t.
> Then the expected miss rate of that label is at most α.

`eval` does this with α = `--miss` (default 0.05), using only items whose `picked_for` contains `random`. The `top` /
`near` items are hand-picked, so they can't be used for it.

Conditions (the guarantee holds only if all are true):
- the random sample comes from the same kind of corpus the policy will run on (same sources, same mix);
- models, hypotheses and keywords don't change after you choose t (change them → label a new random sample);
- n is large enough: at least 1/α − 1 yes paragraphs (19 for α = 0.05), better a few hundred.

The guarantee covers paragraphs that reach the label. A paragraph whose keyword the gate list misses never reaches
any label: check that separately (a random sample of documents *without* a keyword hit).

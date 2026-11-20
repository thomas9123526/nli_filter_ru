# Trying the policy case by case (viewer: Try the policy)

Every Level 0 / 1 / 2 label of `policy\russia_policy.json` and every edge case of
`cmds\history\a-b-filtering-answers.md`, with 1–2 texts each. You run each text through the policy in the viewer
and see the flow: gate → level 1 → level 2 → decision, every score next to its threshold, compared with what is
expected.

## Start

```powershell
# 1. the model service, with models (from the project folder, in the torch environment)
python nli_playground.py                       # default: ModernBERT + DeBERTa judge
python nli_playground.py --judge-model none    # faster on a CPU (ModernBERT only)
# 2. the viewer
viewer\start_viewer.ps1
```

Open `http://127.0.0.1:8000/labeltry/`, or the home page → **Labelling runs** → **Try the policy, case by case**.

## The page

| Part | What it does |
|---|---|
| Case list (left) | 76 cases in 4 groups (cases_v4; the page shows the newest cases file). A dot per text: green = the last try was as expected, red = not |
| Case | What it tests, the label's hypothesis and decision. **text 1 / text 2** when the case has two texts |
| Text box | The text. You can edit it to try variations ("what if I remove this sentence?"); then the expected result no longer applies |
| Expected | The action the policy should give, and the labels that should be yes. **draft labels** = a seed paragraph with Claude's unchecked labels |
| Try | Scores the text with **all** labels (~1 s per label on a CPU, ~25 s per text with the judge). The decision still follows the cascade: levels that would not run are shown dashed, "for information only" |
| label without a keyword | Labels the text even if no keyword / marker matches (otherwise it is untouched, no model runs). Use it for gate cases and the place-name case |
| use the judge | DeBERTa re-scores uncertain scores (0.6–0.95), like a real run |
| policy | Default: the policy the cases were made for (`policy\russia_policy_v4.json` for cases_v4). Pick another file from `policy\` to compare (e.g. v3 vs v4) |
| Result | The action, "as expected" or not, the flow per paragraph, and the cleaned text with place-name rewrites |
| prev / next case | Step through the cases one by one |

## The cases: `labels\cases_v4.json` (and v1–v3)

Made by `python tools\build_cases.py --policy policy\russia_policy_v4.json --out labels\cases_v4.json`
(`cases_v1/v2/v3.json`: the same for the older policies). The Try page shows the newest version. v4 adds a yes and a
near-miss case for each of its five new accusation labels (biolabs, Donbas genocide, puppet state, leader smears,
stolen aid): 76 cases, 145 texts (39 written for the cases; the smear texts name no real person).

| Group | Cases | Texts from |
|---|---|---|
| Level 0 · gate | `involves_russia` yes / near miss (Russian dressing, Moscow Idaho …), marker term without a keyword, language menu | seed + benchmark + new |
| Level 1 · subject | each of the 14 areas: yes / near miss | seed where it has an example (history, politics, economy, science, war, sport, lifestyle, literature, geography), benchmark for culture, celebrities, cost of living, new texts for fashion / style and values / mindset |
| Level 2 · framing | each of the 11 narratives + `hostility_ukrainians` + `hostility_russians` + `reports_or_debunks`: yes / near miss (near misses are mostly fact-checks that quote the claim) | benchmark (one seed example for Soviet nostalgia), new texts for traditional values |
| Edge cases | Russian scientist in a technical text, price inside a technical text, remove + keep together (conflict), Russia without a subject, factual war reporting (Bucha), news that debunks a narrative, place names (rewrite and exceptions), Russian-language text about Ukraine | new + benchmark |

125 texts: 13 real seed paragraphs, 93 benchmark paragraphs, 19 new ones. All were screened for unwanted words.

### What v2 adds (from the check of `cmds\history\a-b-filtering-answers.md`)

| Label | Level | Decision | Why |
|---|---|---|---|
| `fashion_style` | 1 | remove | A's rule names B's "style"; the guide's first answer had fashion, the second dropped it |
| `values_mindset` | 1 | review | values / ways of thinking were asked about but had no label. Review, not remove: polls and studies of Russian opinion are factual knowledge |
| `narr_traditional_values` | 2 | remove | "Russia defends traditional values against a decadent West", one of the most frequent EUvsDisinfo narratives |

Level 2 also runs after `values_mindset`. A general "socialist vs capitalist values" label was left out on purpose: that
topic is discussed everywhere (economics, other countries, history) and a label for it would remove far more than
A's policy asks.

## The cases as a corpus: `test_corpus_cases\` (viewer dataset "cases")

One `.jsonl.zst` per case (66 files, the case's 1–2 texts as lines) in `level0_gate\`, `level1_subject\`,
`level2_framing\`, `edge_cases\`; made by `python tools\build_cases_corpus.py` from the newest cases file. Each
line: `id`, `text`, `case`, `group`, `expected_action`, `labels_yes`, `source`, `note`. In the viewer: dataset
**cases** (corpus page: browse / edit the texts). Labelled with v2 into `out_label_cases\`: Labels pages → run
`out_label_cases` → one file per case → each text's flow. Not in git (like every test corpus): rebuild it with the
script.

## Results of a full pass

`labels\cases_v1_results.json` holds a run of all 113 texts (ModernBERT, no judge, CPU, 2026-11-20): per text the
expected and the actual action and every score. Use it to pick the cases to look at first (the "not as expected"
ones), then open them on the Try page.

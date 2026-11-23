# The policy file: `policy\russia_policy.json`

All hypotheses, thresholds and decisions live in this one file. To try a change, copy it
(`policy\russia_policy_try.json`), edit the copy and pass `--policy policy\russia_policy_try.json`.
`nli_label.py` checks the file when it starts and lists every problem it finds.

## A label

```json
"culture_entertainment": {
  "level": 1, "decision": "remove", "threshold": 0.8,
  "hypothesis": "This text describes Russian music, films, TV shows or entertainment."
}
```

| Field | Values | Meaning |
|---|---|---|
| key | `a_z0_9` | The label's name: the column in the outputs and in the hand-label files |
| `level` | 0, 1, 2 | 0 = gate (only one), 1 = subject, 2 = framing |
| `decision` | `gate` `remove` `keep` `review` `flag` | What a "yes" does (below) |
| `threshold` | 0–1 | Score at or above which the label is "yes". **Each label has its own**, tuned with `eval` |
| `hypothesis` | sentence | What the model checks. Full sentence, one idea, concrete, about content, not intent |
| `softens` | label keys, `*` allowed | A "yes" turns those labels' "remove" into "review" (used by `reports_or_debunks`) |
| `note` | text | For people; ignored by the tool |

## Versions

| File | Labels |
|---|---|
| `policy\russia_policy.json` (v1) | 25: the guide's answer 2 |
| `policy\russia_policy_v2.json` (v2) | 28: v1 + `fashion_style` (1, remove), `values_mindset` (1, review), `narr_traditional_values` (2, remove); level 2 also after `values_mindset`. See `cmds\labeling\cases.md` |

| `policy\russia_policy_v3.json` (v3) | 28 labels as v2, with the cascade fixes of `cmds\design\policy_cases_report_2026-11-20.md`: gate threshold 0.12 (wording as v2: adding "or the war between Russia and Ukraine" was tried and lowered the gate scores of plainly Russia-related texts, so it was dropped); level 2 for every paragraph past the gate (`run_if 2` = gate or marker); `"narrative_opens_gate": true` (a narrative claim lets a gate-negative paragraph through); `keywords\russia_v3.txt` (+ Soviet, Russian Empire, Tsarist, Kremlin-backed, pro-Kremlin, Putin); the debunk guard says "reports or refutes" |

| `policy\russia_policy_v4.json` (v4) | 33 labels: v3 + five frequent Kremlin accusations at level 2 (remove): `narr_biolabs` (US bioweapons labs in Ukraine), `narr_donbas_genocide`, `narr_ukraine_puppet` (a puppet state of the West), `narr_leader_smear` (Ukraine's leaders as drug addicts, criminals or illegitimate), `narr_aid_stolen` (weapons or aid sold on the black market); plus `"narrative_keywords"` (below) |

| `policy\russia_policy_v5.json` (v5) | 34 labels: v4 with wordings chosen by measurement: `narr_biolabs` ("…accuses the United States of making biological weapons in Ukraine."), `narr_aid_stolen` ("…Western aid to Ukraine is stolen by corrupt officials."), `narr_leader_smear` split into insults (`narr_leader_smear`) and legitimacy (new `narr_leader_illegitimate`: "…Ukraine's president has no right to rule."), debunk guard threshold 0.6. Report section 11 |

`nli_label.py` uses v1 unless you pass `--policy policy\russia_policy_v2.json` (or `_v3`, `_v4`, `_v5`).

The Russia-side project (Russia's LLM) has its own policy, `policy\russia_llm_policy_v2.json`: see
`cmds\labeling\russia_llm.md`.

## Settings added on 2026-11-23 (any policy can use them)

| Setting | Meaning |
|---|---|
| `"exceptions": [...]` | Top-priority rules, checked before the cascade's decision: `key`, `decision` (remove / review / keep), `priority` (highest wins), `match` (`phrases` and / or `hypothesis` + `threshold`), `skip_quoted`, `scope` (`keyword` or `gate`), `note`. Details and an example: `russia_llm.md` |
| `"protected": true` on a label | An exception never lowers this label's removal (used for hate and violence) |
| `"topic_field"`, `"topic_mode"`, `"topic_map"` | Use a topic the corpus already has: `topic_map` maps its values to level-1 subjects; `hint` / `trust` / `off`. Command line: `--topic-field`, `--topic-mode`. Details: `russia_llm.md` |
| `"keywords_file": [a, b]` | Several keyword lists are joined (one file as before also works) |
| `"rewrite_place_names": false` | This policy never rewrites place names (the same as `--no-rewrite`) |

**A paragraph that is there only because of a narrative keyword** (no Russia keyword, no marker) is judged by the
narrative check alone: its gate score is ignored, so it is removed only if a narrative (or `hostility_ukrainians`)
scores at or above its threshold, and otherwise passes. Without this rule, v4's first measurement sent a place-name
text ("Kievan Rus") and a Russian-language news item about the Kyiv metro to review.

**`"narrative_keywords"`** (v4: Ukraine, Ukrainian, Kyiv, Kiev, Donbas, Donetsk, Luhansk, Crimea, Zelensky, Bucha,
NATO …, also in Ukrainian and Russian). Most Kremlin accusations are about Ukraine, Kyiv or NATO and never mention
Russia, so the Russia keywords never bring them to a model. A paragraph with one of these words but no Russia keyword
gets the gate question and, if the gate says no, the narrative check (`narrative_opens_gate`). It is **removed only if
a narrative scores at or above its threshold**; ordinary text about Ukraine passes untouched (`"narrative_keyword":
true` on the paragraph in `labels.jsonl`). Needs `"narrative_opens_gate": true`. Cost: the gate + 16 narrative labels
on every such paragraph.

**`"narrative_opens_gate": true`**: every paragraph the gate rejects is also scored with the level-2 `remove` labels.
If one is at or above its threshold, the paragraph is treated like one with a marker term: levels 1 and 2 run, and
the flow says "the gate said no, but a narrative claim opened it" (`opened_by` in `labels.jsonl`). This catches
narratives about Ukraine, NATO or Ukrainians that never mention Russia. It costs about 11 more model passes per
gate-negative paragraph.

## The labels as shipped (decisions = the guide's suggestions; A's compliance team decides)

| Level | Label | Decision |
|---|---|---|
| 0 | `involves_russia` (backstop: "mentions Russia, the Soviet Union, the Russian Empire or Russian people"; chosen over the guide's wording on the seed drafts, see `cmds\design\labeling_report_2026-11-20.md`) | gate, 0.5 |
| 1 | `culture_entertainment`, `celebrities`, `lifestyle_traditions`, `cost_of_living` | remove |
| 1 | `literature_art`, `history_soviet`, `sport` | review |
| 1 | `science_technology`, `geography`, `politics_government`, `war_ukraine`, `economy_business` | keep |
| 2 | `narr_ukraine_not_nation`, `narr_nazi`, `narr_war_justification`, `narr_nato_blame`, `narr_annexation`, `narr_atrocity_denial`, `narr_language`, `narr_russian_greatness`, `narr_soviet_nostalgia`, `hostility_ukrainians` | remove |
| 2 | `hostility_russians` | flag (for the general safety filter; never removed here) |
| 2 | `reports_or_debunks` (near-miss guard) | keep; softens `narr_*`, `hostility_ukrainians` |

All thresholds start at 0.8 (gate 0.5). These are guesses until `eval` on hand labels says otherwise.

## Which labels run when (`run_if`)

```json
"run_if": {"1": ["involves_russia", "@marker"],
           "2": ["politics_government", "war_ukraine", "history_soviet", "@marker"]}
```

Level 1 runs when the gate label is yes or the paragraph has a marker term. Level 2 runs when politics, war or
history is yes, or there is a marker term. `@marker` = a phrase from `"markers"` is in the paragraph ("special
military operation", "Kiev regime", "denazification", "СВО", …). `--all-labels` ignores `run_if` and scores
everything.

## How the action is decided (per paragraph)

In this order:

| # | Situation | Action |
|---|---|---|
| 1 | Gate label below its threshold and no marker term | **pass**: untouched, the keyword was incidental |
| 2 | A level-2 `remove` label is yes, and nothing softens it | **remove**: a narrative wins over "keep" subjects ("keep if factual") |
| 3 | `remove` and `keep` labels both yes | **review** (`"conflict"`: `review`; can be set to `remove` or `keep`) |
| 4 | A `remove` label is yes | **remove** |
| 5 | A `review` label is yes, or a softened narrative | **review** |
| 6 | A `keep` label is yes | **keep** |
| 7 | Gate yes, no subject label yes | **keep** (Russia-related, but nothing the policy removes) |

`flag` labels never change the action. They are listed in the outputs (`flags`).

Document level, in the labels file: `untouched` (no hit), `pass` (all paragraphs pass), `kept`, `review` (a review
paragraph, nothing removed), `edited` (some paragraphs removed), `removed` (less than `--min-doc-chars` left).

## Writing hypotheses (from the guide)

- A full sentence: "This text is about …" / "This text claims …".
- One idea per hypothesis. Concrete words. Describe content, not intent.
- Try 2–3 wordings of a weak label: change the hypothesis in a copy of the policy, run `eval` with
  `--policy` on the copy, and compare. The score cache keeps each wording's scores apart.
- Keep subject (level 1) and framing (level 2) separate: the same subject can be factual or propaganda.

## Gate lists

- Keywords: `keywords\russia.txt` (lexicon format: `cmds\viewer\review_tools.md` and the file header). Level-A keywords
  are treated like B here: every hit goes to the models, nothing is removed by keyword alone.
- Markers: `"markers"` in the policy. They are matched like keywords (case-insensitive, whole words).
- Russian-language text is **not** Russia-related by itself (many Ukrainians write in Russian). Language is a
  separate policy decision; nothing here labels language.
- Next step from the guide: Wikidata lists (places in Russia, popular Russian people, Russian organisations,
  state media) to extend `keywords\russia.txt`. See `cmds\design\labeling_report_2026-11-20.md`.

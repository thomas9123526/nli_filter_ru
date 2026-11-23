# Labelling Russia-related content for A's LLM: overview

`nli_label.py` labels Russia-related (B) content **paragraph by paragraph**, following A's policy. The labels are
stored as columns, and the raw data is never changed. A cleaned copy is written only if you ask for one.
It follows the project summary *russia-filter-labeling-summary.md* (the guide).

`nli_filter.py` still works as before. It answers one question per line ("is this line about Russia?") and
removes whole lines. `nli_label.py` answers **one yes/no question per policy label**, each with its own threshold and
decision. It removes only the paragraphs the policy says to remove, and rewrites place names in what stays.

| Guide | Here |
|---|---|
| Level 0 gate: entity lists + backstop hypothesis | `keywords/russia.txt` + `markers` in the policy + label `involves_russia` |
| Level 1 subject (~12 hypotheses) | 12 labels, level 1, in `policy/russia_policy.json` |
| Level 2 framing (~10 narratives) | 10 narrative / hostility labels + `hostility_russians` (flag only) + `reports_or_debunks` (near-miss guard) |
| Place-name rewrite | `policy/place_names.csv` + `policy/place_name_exceptions.txt` (`nli_names.py`) |
| Label at paragraph level | the documents are split into paragraphs; only paragraphs with a keyword / marker are labelled |
| Labels as columns, never delete raw data | `<name>.labels.jsonl.zst` per input file (`--compress none`: plain `.jsonl`); `--write-clean` writes a separate cleaned copy |
| Count tokens, not documents | composition report in tokens (estimated: ~4 characters per token) |
| Hand-label ~200 first, a threshold per label | `nli_label.py sample` → `tools/label_tool.html` → `nli_label.py eval` |

## Files

| File | What |
|---|---|
| `nli_label.py` | The tool: `run`, `sample`, `eval`, `report` |
| `nli_names.py` | Place-name rewrite (also usable alone, no models) |
| `policy/russia_policy.json` | **The policy**: every hypothesis, threshold and decision in one file |
| `policy/place_names.csv` | Russian form → Ukrainian form of place names |
| `policy/place_name_exceptions.txt` | Where names are NOT rewritten (Chicken Kiev, Odessa Texas, person names, …) |
| `tools/label_tool.html` | Hand-labelling page: open it in a browser (no server) |
| `tools/make_gated_subset.py` | Random documents that pass the gate, from big corpus files → one small file |
| `labels/` | Hand-label files (keep them in git: they are the most valuable data) |
| `tests/test_label.py` | Tests (no models): `python -m pytest tests/test_label.py` |

## Guides in this folder

| File | Read it for |
|---|---|
| [overview_diagram.md](overview_diagram.md) | **The whole project in one diagram**: settings → run → outputs, human loop, viewer |
| [quick_start.md](quick_start.md) | The commands, step by step, from nothing to a labelled run |
| [policy.md](policy.md) | Editing the policy: labels, thresholds, decisions, how a paragraph's action is decided |
| [hand_labeling.md](hand_labeling.md) | Hand-labelling with the label tool; labelling rules; rounds |
| [thresholds.md](thresholds.md) | Reading `eval` output; choosing thresholds; the CRC guarantee |
| [place_names.md](place_names.md) | The mapping table, exceptions, codebook edge cases |
| [outputs.md](outputs.md) | What `run` writes; the composition report |
| [benchmark.md](benchmark.md) | The synthetic regression set (170 items) and the real-data benchmark plan |
| [../viewer/labels_pages.md](../viewer/labels_pages.md) | See runs and each paragraph's flow in the viewer; start runs from it |
| [cases.md](cases.md) | **Try the policy case by case** in the viewer: 60 cases (every label yes / near miss + edge cases), 1–2 texts each |

## How a document is processed

```
document ──► keywords + markers ──no hit──► untouched (place names still rewritten)
                 │ hit
                 ▼
          split into paragraphs; keep those with a hit or marker
                 ▼
   level 0  involves_russia ≥ 0.5 ? ──no──► pass (keyword was incidental)
                 │ yes (or marker)
                 ▼
   level 1  12 subject labels, each yes/no
                 │ politics / war / history yes, or a marker
                 ▼
   level 2  narrative labels, each yes/no
                 ▼
   decide   remove / keep / review per paragraph  (policy.md, "How the action is decided")
                 ▼
   clean    removed paragraphs cut out, place names rewritten (--write-clean)
```

## Speed

One (paragraph, label) pair is one model pass. On this computer's CPU (i7-8700K, no GPU), ModernBERT does
**~1 pair per second** at paragraph length, so labelling one paragraph with all 25 labels takes ~25 s. Use a GPU
machine for real runs (the H200 / RTX 5090 setups in `cmds/h200` and `cmds/setup`). The cascade (the default; not
`--all-labels`) skips level 2 for most paragraphs, and only ~3.6 % of web documents pass the gate at all.

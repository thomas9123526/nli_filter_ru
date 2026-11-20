# How the project works: one diagram

The labelling project for A's LLM (`nli_label.py`) from settings to training data. Details: [README.md](README.md).

```
                    ┌──────────────────────── SETTINGS (you edit these) ─────────────────────────┐
                    │ policy/russia_policy_v3.json   28 labels: hypothesis · threshold · decision │
                    │ keywords/russia_v3.txt         gate words (+ policy "markers")              │
                    │ policy/place_names.csv         Kiev→Kyiv …  (+ place_name_exceptions.txt)   │
                    └─────────────────────────────────────┬──────────────────────────────────────┘
                                                          │
 CORPUS                                                   ▼
 local folder / .jsonl / .zst / .parquet     ┌─────────────────────────────── nli_label.py run ───────────────────────────────┐
 ftp:// sftp:// s3:// minio://   ──────────► │ 1 GATE (cheap)   keywords + markers + language-menu rules                        │
 (Nemotron, Dolma, OLMo …)                   │                  no hit → untouched (names still rewritten)  ~96 % of web text   │
                                             │ 2 SPLIT          paragraphs with a hit                                           │
                                             │ 3 LEVEL 0        "mentions Russia …?"  ≥ 0.12  (or marker, or a narrative ≥ 0.8) │
                                             │ 4 LEVEL 1        14 subjects: culture · celebrities · lifestyle · fashion ·      │
                                             │                  values · literature · cost of living │ science · geography ·   │
                                             │                  politics · war · economy │ Soviet history · sport               │
                                             │ 5 LEVEL 2        13 framing: 11 narratives · hostility ×2 · debunk guard          │
                                             │ 6 DECIDE         remove / review / keep / pass   per paragraph                    │
                                             │ 7 CLEAN          cut removed paragraphs · rewrite place names                     │
                                             └──────────┬───────────────────────────────┬────────────────────────────┬──────────┘
                                                        │ uses                           │ writes                      │
                                         ┌──────────────▼─────────────┐   ┌─────────────▼─────────────────┐          │
                                         │ MODELS (models/)           │   │ out_label_xxx/                 │          │
                                         │ ModernBERT  fast, every pair│   │  *.labels.jsonl  labels+scores │          │
                                         │ DeBERTa     judge 0.6–0.95 │   │  *.clean.jsonl   cleaned copy  │          │
                                         │ bge-m3      multilingual   │   │  *.rewrites.jsonl name changes │          │
                                         └────────────────────────────┘   │  summary.json    token report  │          │
                                                                          └───┬──────────┬──────────┬──────┘          │
                                                                              │          │          │                 ▼
                          ┌───────────────────────────────────────────────────┘          │          │      TRAINING DATA
                          │                                                              │          │      for A's LLM
                          ▼                                                              ▼          ▼
            ┌── HUMAN LOOP ─────────────────────────┐        ┌── POLICY CHANGE ──────┐   ┌── VIEWER (localhost:8000) ──────────┐
            │ nli_label.py sample → labels/*.jsonl   │        │ nli_label.py redecide │   │ Labelling runs: runs, per-text flow │
            │ nli_label.py review → review queue     │        │ new thresholds /      │   │ Try the policy: 66 cases, live      │
            │ tools/label_tool.html  (you answer)    │        │ decisions from stored │   │ Datasets: corpus pages (+ "cases")  │
            │ nli_label.py eval → precision / recall │───────►│ scores, no models     │   │ Start a run                         │
            │   thresholds, CRC guarantee            │ tune   └───────────────────────┘   └──────────────┬──────────────────────┘
            └────────────────────────────────────────┘ policy                                          │ Try / Start
                                                                                        ┌──────────────▼──────────────────┐
                                                                                        │ nli_playground.py (:8100)        │
                                                                                        │ models loaded once; /label, jobs │
                                                                                        └──────────────────────────────────┘

 TEST DATA: labels/seed.jsonl (182 real, drafts to check) · labels/bench_synthetic_v1.jsonl (170 written)
            labels/cases_v3.json → test_corpus_cases/ (66 files, one per case)
 OLDER TOOL: nli_filter.py — one question per line ("about Russia?"), whole line filter/keep; same models & keywords code
```

## How to read it

1. **Settings**: you decide what A's policy is: the labels, the keywords, the place names.
2. **`nli_label.py run`** goes from cheap to expensive. The keyword gate drops most text without any model. Only the
   remaining paragraphs go through Level 0 → 1 → 2, then a decision, then cleaning.
3. **Outputs**: labels stored as columns, a cleaned copy and a token report. The raw corpus is never changed.
4. **Human loop**: you label samples and review queues, and `eval` turns your labels into thresholds and measured
   accuracy, which feed back into the policy.
5. **`redecide`** applies a changed policy without running the models again.
6. **The viewer** lets you see everything, try cases live and start runs, using the models in `nli_playground.py`.

## Where to read more

| Part | Guide |
|---|---|
| The steps of a run | [README.md](README.md) ("How a document is processed"), [policy.md](policy.md) |
| Commands | [quick_start.md](quick_start.md) |
| Outputs, review queue, `redecide` | [outputs.md](outputs.md) |
| Hand labelling, `eval`, thresholds | [hand_labeling.md](hand_labeling.md), [thresholds.md](thresholds.md) |
| Place names | [place_names.md](place_names.md) |
| Cases and the Try page | [cases.md](cases.md), [../viewer/labels_pages.md](../viewer/labels_pages.md) |
| Results and what to improve | [../design/policy_cases_report_2026-11-20.md](../design/policy_cases_report_2026-11-20.md) |

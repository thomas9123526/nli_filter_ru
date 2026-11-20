# Model references: what to read, and what it means for `nli_filter.py`

All papers are PDFs under `models\` (not in git: copy `models\` to another computer to have them there).
BibTeX for all of them: `cmds\explain\model_references.bib`.

| Where | What |
|---|---|
| `models\_references\` | Shared: the zero-shot method, training data, foundations, limits, calibration and guarantees (21 PDFs) |
| `models\_references\sources\` | Non-PDF sources: the Hugging Face zero-shot pipeline code, Laurer's training dataset list (CSV) |
| `models\deberta-v3-large-zeroshot-v2.0\` | DeBERTaV3, DeBERTa, ELECTRA |
| `models\bge-m3-zeroshot-v2.0\` | BGE-M3, RetroMAE, XLM-RoBERTa, RoBERTa |
| `models\ModernBERT-large-zeroshot-v2.0\` | ModernBERT, RoFormer, FlashAttention-2, GLU Variants |

## Reading order

1. **Yin 2019**: the principle. A classifier becomes "does the text entail *This text is about X*?".
2. **Laurer 2023**: how our three models were trained and evaluated.
3. **The base paper of the model you use**: ModernBERT (fast), DeBERTaV3 (judge), BGE-M3 (multilingual).
4. **Guo 2017, Desai 2020, McCoy 2019, Gururangan 2018**: why a score is not a probability, and how NLI models fail.
5. **Angelopoulos (conformal) ×3**: how to get a real, provable guarantee from our own labeled lines.

---

## 1. The method (shared by all three models)

| Paper | File | Read | Takeaway |
|---|---|---|---|
| Yin, Hay, Roth 2019, *Benchmarking Zero-shot Text Classification … Entailment Approach* | `1909.00161_…` | The entailment approach section | Any label can be written as a hypothesis; an NLI model scores text → hypothesis. This is exactly what `hypotheses\*.json` does. |
| Laurer et al. 2023, *Building Efficient Universal Classifiers with NLI* | `2312.17543_…` | Method, data, hypothesis formulation, results | **The paper our models come from.** NLI is used as one universal task. Training covers 33 datasets / 389 classes, and labels are merged into 2 classes: `entailment` / `not_entailment`. |
| Laurer et al. 2024, *Less Annotating, More Classifying* (Political Analysis) | `Laurer2024_…` | Main argument, experiments | The earlier BERT-NLI work: NLI-trained models need far fewer labeled examples. A small labeled set from our own data goes a long way (see section 5). |
| Ma et al. 2021, *Issues with Entailment-based Zero-shot Text Classification* (ACL 2021 short) | `ACL2021-short.99_Ma2021_…` | Whole paper (short) | Re-tests Yin 2019. Results **vary widely from dataset to dataset**, and attempts to make NLI more robust mostly failed. Benchmark numbers in the README do not carry over to our corpus by default: measure on our own lines. |
| Hugging Face zero-shot pipeline, transformers 5.20.2 | `sources\transformers-5.20.2_zero_shot_classification.py` | `postprocess()` | The reference implementation of the method, the same version as our `pkgs` wheel |

**What it means here**
- Every score in `nli_filter.py` is one (window, hypothesis) pair. It is the softmax over the model's two classes, and we keep the `entailment` part ([nli_models.py:414](../../nli_models.py#L414)). Pairs are scored independently.
- **Same as the pipeline's `multi_label=True`**: there the score is a softmax over [contradiction id, entailment id]. With our 2-class models the "contradiction id" is `not_entailment`, so it is exactly our softmax. The pipeline's default `multi_label=False` differs: it normalises entailment across all labels so they sum to 1. `nli_filter.py` never does that; `nli_models.py --labels` does it only without `multi_label` ([nli_models.py:306](../../nli_models.py#L306)).
- The pipeline cuts long input from the text side only (`only_first`), never the hypothesis. `nli_models.py` does the same ([nli_models.py:406](../../nli_models.py#L406)).
- Hypothesis wording changes results. Both papers treat the hypothesis like a prompt. That is why our hypotheses are in editable files and tested by comparing runs (`nli_compare.py`).

## 2. Training data (what the models learned from)

| Data | File | Why it matters for us |
|---|---|---|
| MNLI | `1704.05426_…` | Main NLI data: short premises from 10 English genres |
| FEVER, FEVER-NLI | `1803.05355_…`, `1811.07039_…` | Fact-check claims with Wikipedia evidence, turned into NLI pairs |
| ANLI | `1910.14599_…` | Examples written to fool models (3 rounds): makes models more robust |
| WANLI | `2201.05955_…` | GPT-3 written, human-revised NLI examples |
| LingNLI | `2104.07179_…` | Examples collected with linguists in the loop |
| Mixtral | `2401.04088_…` | The LLM that wrote the synthetic classification data of the v2.0 models |
| Laurer's dataset list | `sources\zeroshot-classifier_datasets_overview_7f82e4a.csv` | The exact list the README links (same commit): 41 datasets, 27 with `used_in_v1.1 = TRUE` (in the non-`-c` training mix), with licence, task, domain and language per dataset |
| XNLI | `1809.05053_…` | NLI in 15 languages, Russian included. Shows how much accuracy drops when a model is used outside English: the bge-m3 case |

**What it means here**
- The training data is mostly **English** and **short** (one or a few sentences). Our check-1 windows are ~1000 characters (~250 tokens), and our corpus has Russian, Japanese and other text. Both are a shift away from the training data, so expect weaker accuracy and calibration there than the README tables show (see section 4).

## 3. The base models

### ModernBERT: default fast model (`--fast-model modernbert`)
| Paper | Takeaway |
|---|---|
| **ModernBERT** `2412.13663` | Encoder trained on ~2T tokens, 8192-token context, alternating local / global attention, unpadding. It is fast and memory-efficient. |
| RoFormer `2104.09864` | Rotary position embeddings: the reason the long context works |
| FlashAttention-2 `2307.08691` | The fast attention kernel behind the speed |
| GLU Variants `2002.05202` | GeGLU feed-forward layers used in ModernBERT |

### DeBERTa-v3: default judge (`--judge-model deberta`)
| Paper | Takeaway |
|---|---|
| **DeBERTaV3** `2111.09543` | DeBERTa trained ELECTRA-style, with "gradient-disentangled embedding sharing". It is the most accurate of the three on English NLI. |
| DeBERTa `2006.03654` | Disentangled attention: content and relative position are kept separate |
| ELECTRA `2003.10555` | Replaced-token detection: a discriminator learns from every token, not only masked ones |

### BGE-M3: multilingual (`bge-m3`)
| Paper | Takeaway |
|---|---|
| **M3-Embedding (BGE-M3)** `2402.03216` | 100+ languages, up to 8192 tokens. Our model is fine-tuned from `bge-m3-retromae`, the long-context XLM-R base of BGE-M3. |
| RetroMAE `2205.12035` | The masked-auto-encoder pre-training used to stretch the base model |
| XLM-RoBERTa `1911.02116` | The multilingual base model (CommonCrawl in 100 languages, Russian included) |
| RoBERTa `1907.11692` | XLM-R's training recipe |

### Foundations
Attention Is All You Need `1706.03762`, BERT `1810.04805`: background for everything above.

**What it means here**
- `--max-length` defaults to **512 tokens for all three models** ([nli_filter.py:1514](../../nli_filter.py#L1514)). That is the hard limit for DeBERTa only. ModernBERT and bge-m3 could take 8192, but our windows (~250 tokens) fit in 512 anyway, and the papers and README note that longer inputs are slower and score worse.
- DeBERTa and ModernBERT are **English** models. On Russian / Cyrillic windows only bge-m3 was trained on the language (XLM-R). Run the `cjk_*` / non-English test categories with bge-m3 when English models do badly there.

## 4. Limits: why a score of 0.8 is not "80 % sure"

| Paper | File | Takeaway |
|---|---|---|
| Guo et al. 2017, *On Calibration of Modern Neural Networks* | `1706.04599_…` | Modern networks are **overconfident**: softmax scores are not probabilities. Introduces ECE and temperature scaling. |
| Desai & Durrett 2020, *Calibration of Pre-trained Transformers* | `2003.07892_…` | BERT-like models are fairly well calibrated **in-domain** and worse **out-of-domain**, which is our case (section 2). |
| McCoy et al. 2019, *Right for the Wrong Reasons* (HANS) | `1902.01007_…` | NLI models use shortcuts like word overlap. A hypothesis that shares words with the text can score high for the wrong reason. |
| Gururangan et al. 2018, *Annotation Artifacts in NLI Data* | `1803.02324_…` | NLI data has cues (e.g. negation words) that models learn instead of meaning |

**What it means here**
- `--check1-threshold 0.8` and `--check2-threshold 0.8` are **cut-offs, not confidence levels**. The real error rate at 0.8 is unknown until it is measured on labeled lines from our corpus.
- **Check 1 is an OR**: a line is positive if *any* (window × hypothesis) pair reaches the threshold. With 7 check-1 hypotheses and up to 2 windows, a line gets up to 14 chances, so per-pair false positives add up at line level. More hypotheses raise recall *and* false positives.
- Keyword words that also appear in hypotheses (e.g. "Moscow" in the `region` hypothesis) invite the overlap shortcut McCoy describes.

## 5. Getting a real guarantee: conformal prediction

| Paper | File | Takeaway |
|---|---|---|
| Angelopoulos & Bates, *A Gentle Introduction to Conformal Prediction* | `2107.07511_…` | Start here. Practical, with code. With a labeled calibration set you get guarantees that hold **for any model**, without trusting its scores. |
| Angelopoulos et al., *Conformal Risk Control* | `2208.02814_…` | Choose a threshold so that the **expected** rate of an error (e.g. missed Russia lines) is at most α |
| Angelopoulos et al., *Learn then Test* | `2110.01052_…` | The same with **high probability** (≥ 1 − δ), and for **several parameters at once**: check-1 threshold, check-2 threshold, uncertain band |

**What it would look like here** (not built yet; the pieces exist):
1. **Calibration set**: draw lines **at random** from the real corpus and label them `filter` / `keep`. The golden set (`golden\<dataset>.jsonl`, Review page) holds such labels, but the guarantee needs a *random sample*, not hand-picked hard cases.
2. **Score once**: `python nli_filter.py golden\<dataset>.jsonl --output-dir out_calib` stores every score.
3. **Sweep thresholds without models**: `nli_replay.py` re-decides from stored scores ([cmds/testing/compare_and_replay.md](../testing/compare_and_replay.md)).
4. **Pick the threshold by the formula**, e.g. for "at most α of Russia lines missed" with n labeled Russia lines: take the highest threshold where (n × miss rate + 1) / (n + 1) ≤ α (Conformal Risk Control).

**Conditions**: the guarantee holds only if
- the corpus being filtered is like the calibration sample (same sources, same mix),
- models, hypotheses, keywords and settings stay unchanged after calibration, and
- it covers the whole pipeline. Lines with no keyword hit are never filtered, so misses from the keyword list count too. No threshold can push the miss rate below that floor.

Rough size: with n labeled positives, the "+1" in the formula costs about 1/(n+1). For α = 5 %, a few hundred labeled Russia lines is a sensible start.

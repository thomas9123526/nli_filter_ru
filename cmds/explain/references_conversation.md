# Conversation: finding and downloading the model references (2026-11-20)

Record of the session that built the reference library. The reading guide itself is
[model_references.md](model_references.md); BibTeX is [model_references.bib](model_references.bib).

---

## 1. "Find all the references for each model: how it works, its principle, its guarantee. Give a download list, prefer PDF."

**What was in `models\` before**: each model folder had a `README.md` (Hugging Face model card) and some PDFs.
- `deberta` and `bge-m3` READMEs are nearly the same text. Both cite one paper: Laurer et al. 2023, arXiv 2312.17543.
- `ModernBERT` README cites no paper, only the base model `answerdotai/ModernBERT-large`.
- Base models from the READMEs: `microsoft/deberta-v3-large`, `BAAI/bge-m3-retromae`, `answerdotai/ModernBERT-large`.
- Training data named: MNLI, FEVER-NLI, ANLI, WANLI, LingNLI, and synthetic data from Mixtral-8x7B.

**About "guarantee"**: no model has a formal accuracy guarantee. The only "guaranteed" in the READMEs is about licences: `-c` models use only commercially-friendly training data. Our three models are the non-`-c` versions. So "guarantee" in the papers means measured benchmark results plus known failure modes. A "limits" group was added for that.

**Problems found in the existing PDFs** (identified by file hash and PDF metadata):
- `bge-m3\2111.09543v4.pdf` was the **DeBERTaV3** paper, in the wrong folder.
- The deberta folder lacked 2312.17543, the paper its own README cites.
- 4 files were duplicates under two names: both `training_receipe.pdf`, `deberta\base_encoder.pdf` (= the misplaced DeBERTaV3), and `ModernBERT\base-encoder paper.pdf`.

**Download list**: 26 references, 5 already present, 21 to download. All arXiv IDs were checked against the arXiv API before downloading. Groups: method, training data, one group per base model, foundations, limits.

**Layout chosen**:
- model-specific papers go in the model folder,
- shared papers go once in `models\_references\`,
- files are named `<arXiv ID>_<Short-Title>.pdf`.

## 2. "Yes." (download)

- All 21 PDFs downloaded from arxiv.org (3 s pause between files) and each checked to start with `%PDF`.
- Existing files renamed to the same pattern, the two Laurer papers moved to `_references\`, and the 4 duplicates deleted only after a hash check confirmed they were identical.
- `models\` is ignored by git (`.gitignore`: `models/**`), so the PDFs are not on GitHub.

## 3. "What can you offer more for references?"

Options offered:
1. **Papers for a real guarantee**: conformal prediction, which gives a provable error bound from labeled lines of our own corpus.
2. Gap-filling papers for our use case: XNLI (multilingual), long-document NLI, hypothesis wording.
3. Non-PDF sources: the Hugging Face zero-shot pipeline code, base model cards, Laurer's `zeroshot-classifier` repo.
4. **A reading guide tied to our code**, with BibTeX.

Recommended: **1 + 4**.

## 4. "I will follow your recommendation. Also save the conversation as md in cmds."

- Downloaded 4 more papers into `models\_references\`. The arXiv API was rate-limited, so each title was checked on its arxiv.org abstract page instead:
  - 2107.07511 *A Gentle Introduction to Conformal Prediction …* (Angelopoulos & Bates)
  - 2208.02814 *Conformal Risk Control*
  - 2110.01052 *Learn then Test*
  - 2003.07892 *Calibration of Pre-trained Transformers* (Desai & Durrett)
- Wrote [model_references.md](model_references.md) (reading guide), [model_references.bib](model_references.bib), and this file.

**Facts checked in the code for the guide**
- All three models are 2-class: `{0: entailment, 1: not_entailment}` in each `config.json`.
- Score = softmax over the two classes, entailment part, one (window, hypothesis) pair at a time ([nli_models.py:414](../../nli_models.py#L414)).
- `--max-length` defaults to 512 tokens for every model ([nli_filter.py:1514](../../nli_filter.py#L1514)). DeBERTa's own limit is 512; ModernBERT 8192; bge-m3 8194 positions.
- Check 1 is an OR over windows × hypotheses; check 2 keeps a line only if all remaining hits are incidental.

## 5. "What more could be included?" → "Your suggestions"

Offered: XNLI, DocNLI, hypothesis-wording studies, Ma et al. 2021, binomial confidence intervals, the HF pipeline code, base model cards, Laurer's repo and dataset list. Recommended and done:
- **Ma et al. 2021**, *Issues with Entailment-based Zero-shot Text Classification*. Not on arXiv: the official PDF was taken from the ACL Anthology (2021.acl-short.99).
- **XNLI** 1809.05053, title checked on its arXiv page.
- **Zero-shot pipeline source**, taken from the local wheel `pkgs\…\transformers-5.20.2-py3-none-any.whl`, so it matches the version this project installs (`_references\sources\`).
- **`datasets_overview.csv`** from Laurer's `zeroshot-classifier` repo at the commit the README links (`7f82e4a`): 41 datasets, 27 used in v1.1 (`_references\sources\`).

**Finding**: for 2-class models, the pipeline's `multi_label=True` score equals the score `nli_models.py` computes. Both are softmax over not_entailment / entailment, and both truncate only the text, never the hypothesis. The pipeline's default `multi_label=False` normalises across labels instead; `nli_filter.py` never does.

## Final state of `models\`

| Folder | Files |
|---|---|
| `_references\` | 21 PDFs: Laurer ×2, Yin, Ma; MNLI, FEVER, FEVER-NLI, ANLI, WANLI, LingNLI, XNLI, Mixtral; Transformer, BERT; Guo, McCoy, Gururangan; Desai; Angelopoulos ×3 |
| `_references\sources\` | `transformers-5.20.2_zero_shot_classification.py`, `zeroshot-classifier_datasets_overview_7f82e4a.csv` |
| `deberta-v3-large-zeroshot-v2.0\` | 3: DeBERTaV3, DeBERTa, ELECTRA |
| `bge-m3-zeroshot-v2.0\` | 4: BGE-M3, RetroMAE, XLM-RoBERTa, RoBERTa |
| `ModernBERT-large-zeroshot-v2.0\` | 4: ModernBERT, RoFormer, FlashAttention-2, GLU Variants |

32 PDFs + 2 source files in total.

## Open idea

A calibration step that turns the golden set + `nli_replay.py` into a threshold with a stated guarantee (Conformal Risk Control / Learn then Test). See section 5 of [model_references.md](model_references.md). Not built yet.

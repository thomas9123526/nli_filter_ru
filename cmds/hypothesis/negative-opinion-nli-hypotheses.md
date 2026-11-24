# Writing NLI Hypotheses to Detect Negative Opinions

Models: `MoritzLaurer/ModernBERT-large-zeroshot-v2.0`, `MoritzLaurer/deberta-v3-large-zeroshot-v2.0`

With zero-shot NLI models, the hypothesis is your definition of "negative opinion". The model only checks whether the text supports that sentence. So the work is in writing short, precise hypotheses and testing them against examples.

## 1. Split "negative opinion" into separate questions

"Negative opinion" mixes three things. Test each with its own hypothesis:

| Question | Example hypothesis | Swan Lake 1 | Swan Lake 2 |
|---|---|---|---|
| Is it an opinion rather than a fact? | "The author expresses an opinion." | no | yes |
| Is the opinion negative? | "The author criticizes something." | no | yes |
| Who or what is criticized? | "The author criticizes {target}." | no | yes for "Swan Lake", unclear for "Russia" |

Example sentences:

1. Swan Lake, composed by the Russian composer Tchaikovsky, is being performed.
2. Swan Lake, composed by the Russian composer Tchaikovsky, does not suit the present era.

The third question matters most. Sentence 2 is negative about the ballet, not necessarily about Russia. Your result depends on which target you put in the hypothesis.

## 2. Rules for writing hypotheses

**a. Describe the author's stance, not the events.** A text can describe bad events neutrally: "Soldiers were killed in the attack" is a negative event, not a negative opinion.

- Bad: "This text is negative." This also fires on sad news.
- Better: "The author criticizes {target}." or "The author has a negative view of {target}."

**b. Avoid negation inside the hypothesis.** NLI models handle "not" poorly.

- Bad: "The author does not like {target}."
- Better: "The author dislikes {target}."

**c. One idea per hypothesis, short and plain.** Long hypotheses with "or" let a partial match score high. Write several short hypotheses and take the maximum score instead.

**d. Name the target explicitly** when you care about a specific target. Otherwise "The author criticizes something" fires on any complaint, including about the weather.

**e. Avoid copying words from your texts.** If the hypothesis repeats words that appear in the text, the model can score high from word overlap alone.

## 3. A hypothesis set you can start from

**Negative, toward a target:**

```
The author criticizes {target}.
The author has a negative opinion of {target}.
The author disapproves of {target}.
The text says {target} is bad or harmful.
The author is hostile toward {target}.
The text mocks or insults {target}.
```

**Contrast hypotheses:**

```
The author has a positive opinion of {target}.
The text reports facts about {target} without judging it.
```

**Opinion detector (an optional first step):**

```
The author expresses a personal opinion.
```

## 4. Decide with a margin, not one score

The v2.0 zeroshot models score each hypothesis independently as entailed or not entailed. So score every hypothesis separately, rather than forcing the scores to sum to 1, and decide with a rule such as:

```
neg = max(scores of the negative hypotheses)
pos = scores of the positive hypothesis
neu = scores of the neutral/factual hypothesis

negative opinion if  neg >= 0.8  and  neg - max(pos, neu) >= 0.3
```

The margin protects you from texts where the model rates every hypothesis high, which happens with short or vague texts.

## 5. Code to test both models

```python
from transformers import pipeline

models = {
    "modernbert": "MoritzLaurer/ModernBERT-large-zeroshot-v2.0",
    "deberta":    "MoritzLaurer/deberta-v3-large-zeroshot-v2.0",
}

target = "Swan Lake"
hyps = [
    f"The author criticizes {target}.",
    f"The author has a negative opinion of {target}.",
    f"The author has a positive opinion of {target}.",
    f"The text reports facts about {target} without judging it.",
]

texts = [
    "Swan Lake, composed by the Russian composer Tchaikovsky, is being performed.",
    "Swan Lake, composed by the Russian composer Tchaikovsky, does not suit the present era.",
]

for name, path in models.items():
    clf = pipeline("zero-shot-classification", model=path, device=0)
    for t in texts:
        r = clf(t, candidate_labels=hyps, hypothesis_template="{}", multi_label=True)
        print(name, "|", t[:40])
        for label, score in zip(r["labels"], r["scores"]):
            print(f"   {score:.3f}  {label}")
```

Two settings matter here:

- `hypothesis_template="{}"` passes your full sentence unchanged. Without it, the pipeline wraps each label as "This example is {}.", which garbles full-sentence hypotheses.
- `multi_label=True` scores each hypothesis independently.

Then change `target` to `"Russia"` and compare. Sentence 2 is expected to score high against "Swan Lake" and much lower against "Russia", but measure it rather than assuming.

## 6. Build a small test set before trusting thresholds

Write 30–50 labeled sentences covering:

| Case | Example | Expected |
|---|---|---|
| Neutral fact | "Swan Lake is being performed." | not negative |
| Negative opinion of the target | "Russian ballet is outdated and dull." | negative |
| Negative event, neutral author | "Ten soldiers died in the clash." | not negative |
| Negative opinion of something else | "The theater's seats are uncomfortable." | not negative toward the target |
| Quoted criticism | "Critics say the ballet is outdated." | your choice: author's or reported opinion? |
| Sarcasm | "Oh great, another Swan Lake. How original." | negative (hard for NLI) |
| Positive opinion | "Swan Lake remains a masterpiece." | not negative |

Run both models, find the threshold that separates your labels, and check which hypotheses actually help. Usually 2–3 good hypotheses beat 10 mediocre ones.

On choosing between the models: DeBERTa-v3-large is usually somewhat more accurate on subtle cases such as negation, reported speech and sarcasm, while ModernBERT is faster and handles longer texts. A common setup is ModernBERT first, with DeBERTa checking only the uncertain middle band of scores.

# Actions (remove / review / keep / pass / untouched), the pipeline order, and topics on the Try page

Questions and answers from the session of 2026-11-23.

## 1. How a document goes through `nli_label.py`

The keyword match comes first. Every paragraph that ends up as remove, review, keep or pass contained a keyword; the
difference between keep and pass is decided later, by the gate.

```
document
  │
  ├─ 1. keyword scan of the whole text (country keywords + marker terms + narrative keywords)
  │      no hit at all ──────────────────────────────► document "untouched" (no model runs)
  │      (cheap rules drop incidental hits first: language menus, company names)
  │
  ├─ 2. split into paragraphs; only paragraphs WITH a hit go on
  │      paragraphs without a hit ───────────────────► left as they are, not labelled
  │
  ├─ 3. gate (Level 0): "Does this text mention Russia / Ukraine …?"
  │      below the threshold, no marker, no narrative ► "pass": the keyword was incidental
  │
  ├─ 4. Level 1 subjects, Level 2 framing (only for paragraphs past the gate)
  │
  └─ 5. exceptions, then the decision rules ─────────► "remove" / "review" / "keep"
```

For one paragraph:

- **No keyword** (step 2): never labelled. A document without any keyword is "untouched".
- **Keyword, but the gate says no** (step 3): **pass**. The model judged the mention incidental; levels 1 and 2
  never run.
- **Keyword and the gate says yes** (steps 4–5): **remove**, **review** or **keep**, from the labels and the rules.

A **keep** paragraph went through the most checks: keyword, gate yes, subject and framing labels, nothing to remove or
review. A **pass** paragraph stopped at the gate.

Two ways a gate "no" still continues:

- **A marker term** in the paragraph (e.g. "Kiev regime", "orcs") skips the gate.
- **A narrative or hate label** scoring high lets a gate-negative paragraph through (`narrative_opens_gate`), so hate
  that never names a country is still caught.

On the Try page, **"label without a keyword"** skips steps 1–2: you see what the models say about any text.

## 2. The actions

Paragraph actions:

| Action | What happened | Stays in the data? |
|---|---|---|
| **remove** | A remove label is yes (hate, a narrative, Russian culture on A's side …) | **No**: cut from the clean copy |
| **review** | A review label is yes (opinion, history, an exception …) | **Yes** by default (`--review-as keep`), and it goes to the review queue for a person |
| **keep** | The gate said it **is** about Russia / Ukraine, and nothing removes it | Yes |
| **pass** | A keyword was there, but the gate said the mention is **incidental**: no subject or framing label is applied | Yes, untouched |

Document actions: **untouched** (no keyword at all, no model ran), **pass** (all paragraphs pass), **kept**,
**review** (a review paragraph, nothing removed), **edited** (some paragraphs removed), **removed** (less than
`--min-doc-chars` left).

### keep, pass, untouched: the same for the training data, kept apart on purpose

All three leave the text in the data; only remove cuts. They are kept apart because each tells something different:

1. **How far the text went**: untouched = no keyword; pass = keyword, gate said no; keep = gate said yes and the
   paragraph was labelled.
2. **The report**: the token counts show how much of the corpus is really Russia-related and kept (keep) versus just
   mentions a keyword in passing (pass).
3. **Testing the gate**: some test cases check that the gate does **not** fire, e.g. "The Dnipro river flows through
   Kyiv …" (gate 0.17, so pass). Expecting "pass" there tests the gate.

### In the case editor

- For a text expected to be **keep**, tick **pass** as "also fine": whether the gate scores a plain fact above or
  below its threshold does not matter for the data. The compare tools treat pass and untouched as the same.
- Use **remove**, **review** or **keep** as the expected action. Use **pass** or **untouched** as the main expected
  action only when you test the gate or the keywords themselves.

## 3. Topics and the topic mode on the Try page

Next to **Try**: a **topic** dropdown (pre-filled with the case text's topic; change it for a try without saving) and
a **mode** dropdown (policy default, hint, trust, off). Below them, **topic → subject** says in one line what the
chosen topic and mode do with this policy; opened, it lists the policy's subjects and its whole `topic_map`.

With the Russia-side policy (`policy\russia_llm_policy_v2.json`):

| topic | mode | what happens |
|---|---|---|
| (none) | any | the models decide every subject |
| History | hint | history = yes from the topic; every other subject: the model |
| History | trust | history = yes; politics, economy, culture = no (from the topic, no model); war: the model |
| Travel | any | not in this policy's `topic_map`: changes nothing |
| any | off | recorded only; the models decide every subject |

### Where it is configured (all in the policy file)

| Setting | What |
|---|---|
| `"labels"` with `"level": 1` | The subjects: `history`, `politics`, `war`, `economy`, `culture` |
| `"topic_map"` | Which topic value stands for which subject: History → history; Politics, Crime & Law → politics; Finance & Business → economy; Entertainment, Literature, Art & Design → culture (matched without case) |
| `"topic_mode"` | The default mode (`hint`); `--topic-mode` or the Try page's mode overrides it |
| `"topic_field"` | The corpus field to read (`--topic-field` overrides it); the Try page always uses the text's topic |

The dropdown's values come from `labels\topic_labels.json`; **+ new topic…** adds one (see
`cmds\viewer\labels_pages.md`).

### What a topic never changes

- An empty `topic_map`, a text without a topic, or a topic that is not in `topic_map`: no effect in any mode.
- A subject **not** in `topic_map` (Russia side: **`war`**): decided by the model in every mode.
- **The gate (level 0) and every level-2 label** (opinions, hate, false claims, the guard): always scored by the
  models, whatever the mode. They decide most actions of the Russia-side policy.
- **`culture`** does follow the topic (trust + History forces it to "no"), but in this policy culture is a keep
  label, so its yes / no rarely changes the action.

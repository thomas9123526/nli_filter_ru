# Benchmark clarity audit (Russian-LLM benchmarks)

Received 2026-11-27 (an LLM's judgement of each benchmark line against the policy; no NLI model was run). The
line-by-line table is `labels\benchmark_clarity.csv` (columns file, set, version, line, decision, clarity, reason,
label, text_start). Plan to use it: `cmds\plans\11_27_big_plan.md`.

Checked on 2026-11-27 against `dataset\benchmark\benchmark_ru_llm_*.jsonl`: all 288 rows whose source file exists
match it (decision and text start). 74 rows are for sets without source files yet: contested_history (38),
russian_culture (16), ukrainian_culture (20).

**Answer: most lines are clear, but not all.** Of the 183 v1 lines:

| Tag | Meaning | Lines | Share |
|---|---|---|---|
| **clear** | One label applies with strong clues; a model should answer it clearly | 132 | 72% |
| **hard** | The right answer is clear to a person, but a trap in the text is likely to mislead a model | 23 | 13% |
| **ambiguous** | People could reasonably disagree about the answer itself | 28 | 15% |

The v2 files mirror v1 line for line, except the two company sets, which have their own texts: Russian companies v2
is all clear, and Ukrainian companies v2 has one hard line (Monobank).

**About "review" lines.** 6 of them count as **clear**: the subject is obviously sport or art, and the policy sends
those subjects to review. A model should answer them clearly; the answer just happens to be "review". The remaining
review lines are counted as ambiguous.

## Where the ambiguity is

| Set | clear | hard | ambiguous |
|---|---|---|---|
| contested_history | 3 | 6 | 10 |
| russian_companies | 7 | 3 | 0 |
| russian_culture | 8 | 0 | 0 |
| russian_famous_people | 12 | 0 | 1 |
| russian_food | 9 | 1 | 0 |
| russian_media | 7 | 1 | 0 |
| russian_persons | 8 | 0 | 0 |
| russian_places | 9 | 1 | 0 |
| russian_traditions | 9 | 1 | 0 |
| ukrainian_companies | 9 | 2 | 0 |
| ukrainian_culture | 6 | 0 | 4 |
| ukrainian_famous_people | 8 | 0 | 4 |
| ukrainian_food | 8 | 2 | 2 |
| ukrainian_media | 9 | 1 | 0 |
| ukrainian_persons | 8 | 2 | 0 |
| ukrainian_places | 7 | 2 | 2 |
| ukrainian_traditions | 5 | 1 | 5 |

Almost all ambiguity is in **contested history** and on the **Ukraine side** (traditions, famous people, culture).
The Russia-side sets are almost entirely clear.

## 1. Ambiguous by design: 25 review lines

Written to be ambiguous (shared heritage, clashing labels, one-sided history). The expected answer is "send to a
person", so **leave them out of any keep/remove accuracy score** and measure them separately: did the filter route
them to review? The lines: contested_history 2, 3, 5, 6, 8, 9, 11, 12, 15, 16; russian_famous_people 12;
ukrainian_culture 7, 8, 9; ukrainian_famous_people 2, 8, 10; ukrainian_food 8, 9; ukrainian_places 7;
ukrainian_traditions 5, 6, 7, 8, 9 (reasons per line in the CSV).

## 2. Ambiguous by mistake: 3 lines that don't match similar lines

These have a keep or remove decision, but a similar line elsewhere is review. Recommended to fix before using the
benchmark (the user's decision; not changed):

| Set | Line | Decision | Why |
|---|---|---|---|
| ukrainian_culture | 2 | remove | Western band (Pink Floyd) built on a folk song; same situation as Carol of the Bells, which is review |
| ukrainian_famous_people | 4 | remove | song about the 1944 deportation: culture (remove) mixed with history (review) |
| ukrainian_places | 5 | keep | Soviet-era event; elsewhere shared Soviet history is review, here keep |

**Suggested fixes:**
- **Pink Floyd, "Hey Hey Rise Up"** → **review**, to match Carol of the Bells.
- **Jamala, "1944"** → **review**, or keep **remove** and add a rule that the singer, not the song's subject, decides.
- **Chornobyl** → **review** like other Soviet-era history, or a rule that factual science and disaster history is
  **keep** even when Soviet (and apply the same rule to the Parajanov film).

## 3. Hard but clear: 23 lines likely to trick a model

The correct answer isn't in doubt, but a zero-shot filter is most likely to fail here. Keep them and report their
accuracy separately. The lines: contested_history 1, 4, 7, 10, 14, 17; russian_companies 7, 9, 10; russian_food 9;
russian_media 7; russian_places 9; russian_traditions 9; ukrainian_companies 5, 6; ukrainian_food 10, 11;
ukrainian_media 4; ukrainian_persons 5, 7; ukrainian_places 3, 10; ukrainian_traditions 10.

**Trap types:**
- **Keyword traps** (beeline, Moscow Idaho, Odessa Texas, chicken Kiev at Marks & Spencer): the name matches but the
  subject doesn't.
- **Near misses** (Georgia, Poland, Belarus): a neighbouring country with similar food or customs.
- **Quoted propaganda inside factual text** (TASS on Bucha, MH17, the neutral history accounts): narrative hypotheses
  may fire on the quoted claim.
- **A second label pulling the other way** (Zelensky as a "former comedian", Monobank features, train travel, Levchin
  as an emigrant).

**Note on Russia-side traps:** in the Russian-LLM version the gate looks for **Ukraine** content, so traps such as
Moscow, Idaho and "beeline" only matter if the filter also detects Russia content. If it doesn't, they are
effectively clear.

## Recommendation

1. **Fix the 3 inconsistent lines** (section 2).
2. **Report three scores, not one:** accuracy on the **clear** lines (should be above 95%; a low score means a real
   problem); accuracy on the **hard** lines (lower; shows which traps to work on); **review routing** on the
   ambiguous lines (did the filter send them to a person?).
3. **Confirm this audit with the model:** per line, the top label score and its distance from the threshold. A clear
   line scored near the threshold means the hypothesis wording needs work; a hard line answered right with a wide
   margin can move to clear.

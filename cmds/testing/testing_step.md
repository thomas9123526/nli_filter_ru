# Testing step by step (log)

Each testing session: what was run, in which order, and the results. Newest session at the end.
Run every command from the project folder `D:\hkc\nli_filter2` with `.venv` activated
(`.\.venv\Scripts\Activate.ps1`). Set up the venv with `cmds\setup\venv_py312.md`.
What each test file covers: `cmds\testing\tests.md`.

## Order

| Step | What | Command | Needs |
|---|---|---|---|
| 0 | Packages installed? | `python pkgs\check_missing.py` | - |
| 1 | Fast unit tests (fake model) | `python -m pytest tests -m "not slow" -q` | pytest |
| 2 | Slow test (real ModernBERT) | `python -m pytest tests -m slow -v` | `models\` |
| 3 | End-to-end smoke test | `python smoke_test.py --lines 20` | `models\` |
| 4 | Server input on local fake servers (FTP / SFTP / S3) | `python -m pytest tests\test_remote_input.py -v` | paramiko, boto3, pyftpdlib, moto |
| 5 | Real SFTP server | `cmds\setup\run_sftp_test_corpus.md` | step 4 packages, the server |
| 6 | Viewer backend | `cmds\viewer\viewer.md` | viewer venv (`viewer\backend\.venv`) |
| 7 | Bigger run on the generated corpus | `cmds\testing\test_corpus.md` | - |

One file at a time (step 1, file by file):

```powershell
python -m pytest tests\test_nli_filter.py -m "not slow" -q
python -m pytest tests\test_remote_input.py -q -rs     # -rs prints why a test was skipped
```

## 2026-11-17: this PC (Windows 10, Python 3.12.10, torch 2.11.0+cu126, no GPU)

### Step 0: packages

`check_missing.py`: nothing missing for the filter. Missing (optional): paramiko, boto3 (server input), and the
viewer packages (fastapi, uvicorn, ...) and viewer test packages (pyftpdlib, moto, httpx, ...).

### Step 1: fast unit tests, file by file: 158 passed, 1 skipped

| File | Result |
|---|---|
| `test_compare.py` | 1 passed |
| `test_formats.py` | 5 passed |
| `test_keyword_hyps.py` | 13 passed |
| `test_lexicon.py` | 28 passed |
| `test_long_texts.py` | 27 passed |
| `test_nli_filter.py` | 56 passed |
| `test_nli_models.py` | 15 passed (1 slow test left out) |
| `test_playground.py` | 4 passed |
| `test_progress_file.py` | 6 passed |
| `test_remote_input.py` | skipped: `could not import 'pyftpdlib'` |
| `test_replay.py` | 3 passed |

### Step 2: slow test: 1 passed (11 s)

`test_nli_models.py::test_modernbert_scores_and_pool_modes`

### Step 3: smoke test, 20 lines: PASS (no FAIL, no WARN)

| Check | Result |
|---|---|
| environment | PASS: CPU only |
| models load and score (`nli_models.py --check all`) | PASS: 3 models, 18 s |
| reference: CPU, `--mode single` | PASS: 3.11 lines/s, accuracy 0.90 |
| CPU, 2 workers, `--mode thread` | PASS: same decisions, 6.23 lines/s (fastest here) |
| CPU, 2 workers, `--mode process` | PASS: same decisions, 1.78 lines/s (slower than single) |
| 2 `--shard` copies (`.zst`, `--write-split`, `--report`) | PASS: same decisions |
| replay + compare (no models) | PASS: no line changed |
| viewer backend | SKIP: fastapi not installed |

Details: `smoke_DESKTOP-1IFUKEE_20261117-2346.json` in the project folder.
Accuracy 0.90 = 2 of the 20 labelled lines differ from their `expect` label. That is model quality: the smoke test
only fails when set-ups disagree with each other.

### Step 4 (next): server input on local fake servers

Install the packages (offline, from `pkgs`), then run the test:

```powershell
python -m pip install --no-index --find-links pkgs\windows-py312 paramiko boto3 pyftpdlib "moto[server]"
python -m pytest tests\test_remote_input.py -v
```

Which files use these packages: `cmds\explain\network_packages.md`.

2026-11-18, first try: still skipped (`could not import 'pyftpdlib'`). pip was run without `.venv` activated, so the
packages went into the system Python (`...\Python312\python.exe`), not `.venv`. Activate the venv first (prompt
starts with `(.venv)`), or call it directly:

```powershell
.\.venv\Scripts\python.exe -m pip install --no-index --find-links pkgs\windows-py312 paramiko boto3 pyftpdlib "moto[server]"
python -c "import sys; print(sys.executable)"     # which Python `python` is
```

## 2026-11-18: new option `--keywords-only` (filter without models)

`nli_filter.py --keywords-only`: every line with a keyword hit that the cheap rules leave open is filtered
(reason `keyword_only`). No model is loaded (`.\models` not needed). Level A, `--exclude-pattern` and the rules
work as usual; `--no-rules` filters every hit. Not allowed with `--audit-strict` or `--keywords-report`.
Outputs are the same as a normal run (`--write-split`, `--decisions`, `--shard`, `--report`).

New tests: `tests\test_keywords_only.py` (4 tests). Whole suite after the change: **163 passed, 1 skipped**
(`test_remote_input.py`, server packages not yet in `.venv`).

```powershell
python -m pytest tests\test_keywords_only.py -v
python nli_filter.py test_russia.jsonl --keywords-only --write-split --output-dir out_kw_only
```

Run on `test_russia.jsonl` (95 lines). For comparison, the smoke test with the models had accuracy 0.90, but on
only 20 of these lines:

| | keywords only |
|---|---|
| filtered / kept | 57 / 38 |
| reasons | keyword_only 57, no_keyword 28, rules_incidental 9, no_text 1 |
| time | no model load, about 13,000 lines/s |
| accuracy / precision / recall | 0.842 / 0.737 / 1.000 (TP 42, FP 15, TN 38, FN 0) |

It misses no "about" line but filters 15 lines that only mention the country: groups `fixed_expression`
(e.g. "Russian roulette"), `incidental_language` (e.g. "switch the keyboard to Russian") and `incidental_name`,
5 each. Those are what the models are for.

## 2026-11-18: viewer "Try settings" on `longtest`, 8 hand-written lines

File `code-comments/part-00/shard-00000.jsonl.zst`, lines 1-8. Russia, `keywords/russia.txt` (22 keywords), built-in
hypotheses, fast modernbert + judge deberta (band 0.6-0.95), thresholds 0.8 / 0.8, rules on.
5.5 s, 11 fast pairs, 2 judge pairs.

| Line | Text (short) | Decision | Decided by |
|---|---|---|---|
| 1 | Russia is located in East Europe... | filter, matches expect | check 1 at 0.992 |
| 2 | Turkey soldiers invade into Russian Land... | filter (no expect) | judge 0.988 (fast 0.887) |
| 3 | Display: Russian (ru-RU)... | keep, matches expect | rule `locale_code` |
| 4 | Choose language: English \| ... \| Russian | keep (no expect) | rule `language_label` |
| 5 | The Kremlin said on Monday... | filter (no expect) | judge 0.991 (fast 0.914) |
| 6 | Order Russian Standard vodka online... | keep, matches expect | check 1 at 0.049 |
| 7 | This app supports English, Spanish and Russian... | keep, matches expect | rule `language_menu` |
| 8 | ...shipped from a warehouse in Russia... | keep, matches expect | check 1 at 0.163 |

All decisions are right; none is close to a threshold. Notes:

- Line 6 is kept by check 1, not as a brand: "Russian Standard" is in no company list. For a rule-based keep, use
  `--company-names-file` (e.g. `pkgs\russia\russia_companies.txt`).
- Line 5: the best check-2 score for "Kremlin" came from `language_setting` (0.278, from "published in Russian").
  Harmless (< 0.8); check 2 has no hypothesis for government / institution mentions, check 1 decides those.
- To do: give lines 2, 4, 5 an `expect` (filter / keep / filter), and re-run `nli_filter.py` on `longtest`: only
  line 1 has a saved decision (lines 2-8 were added after the last run).
- With `--keywords-only`, lines 6 and 8 would be filtered (wrong): the models save them.

## 2026-11-18: example sentences with `hypotheses\russian_kw.json` + `keywords\russia.txt`

```powershell
python nli_filter.py <file>.jsonl --hypotheses-file hypotheses\russian_kw.json --device cpu --mode single --no-early-stop --output-dir <out>
```

`--no-early-stop` only shows every score; decisions are the same without it.

| Text | Decision | Check 1 (best fixed / keyword-built) | Notes |
|---|---|---|---|
| Moscow   is city of Russian Federal. It is located in East Europe. The main people are slavs. | filter (about_country) | country 0.998 / place:Moscow 0.095 | "Russian Federal" is not "Russian Federation": the hit is "Russian" (demonym, no template). Check 2: location 0.110, sense:Moscow 0.0001, sense:Russian 0.002, so not incidental |
| Moscow is the capital of Russia. | filter | country 0.997 / place:Moscow 0.991 | |
| Moscow, Idaho is a small town with a university. | keep (no_keyword) | - | exclude pattern drops the hit before any model |
| My colleague speaks Russian and English at work. | keep (check1_negative) | country 0.011 | check 2 (and sense:Russian) never runs when check 1 is negative |
| The package was shipped from Moscow to my home in Berlin. | keep (check1_negative) | country 0.580 / place:Moscow 0.046 | |
| Moscow is a city of the Russian Federation. | filter | country 0.989 / place:Moscow 0.915 (judge), place:Russian Federation 0.376 (judge) | |
| It was so cold in the office, it felt like Siberia. | keep (check1_negative) | country 0.189 / place:Siberia 0.099 | |

The fixed `country` hypothesis decided every line here; the keyword-built ones agreed with it. `place:Moscow` is
low (0.095) on the broken-grammar sentence and high (0.91-0.99) on clean ones: the gloss "the capital of Russia"
is part of what the model has to agree with.

## 2026-11-18: does the Moscow line need its "other meaning" and "exclude" columns?

`keywords\russia.txt`: `Moscow | B | city | the capital of Russia | Moscow, Idaho | Moscow,?\s+(Idaho|ID)\b`,
compared with a copy where the line stops after the gloss ("short"). `russian_kw.json`, `--no-early-stop`, CPU.

| Text | Full line | Short line |
|---|---|---|
| I grew up in Moscow, Idaho, a small college town. | keep, no_keyword (excluded) | keep, check1_negative |
| Ship to: 825 Main St, Moscow, ID 83843, USA | keep, no_keyword | keep, check1_negative (country 0.12) |
| Moscow Idaho has a great farmers market every Saturday. | keep, no_keyword | keep, check1_negative |
| Moscow, Idaho was founded in the 1870s by settlers from the eastern United States. | keep, no_keyword | keep, check1_negative |
| Moscow ID and Pullman WA share a bus line... | keep, no_keyword | keep, check1_negative |
| The University of Idaho is in Moscow, a small town near the Washington border. | keep, check1_negative | same |
| My cousin studies at the University of Idaho in Moscow. He says the winters... | keep, check1_negative (place:Moscow 0.34) | same |
| Moscow, Idaho was named after Moscow, the capital of Russia. | keep, check1_negative (0.06) | same |
| Heavy snow closed the roads around Moscow on Monday... | filter (country 0.99; sense:Moscow 0.009) | same |

No decision changed on these lines: the models already read Idaho context correctly. The exclude column saves
the model calls and makes the result certain for the forms it matches; `sense:Moscow` (other meaning) is only
asked in check 2, after check 1 passed, and stayed low where Moscow means the Russian city.

## 2026-11-18: samples that activate `check2_types` (`@other` in `russian_kw.json`)

`check2_types` only runs in check 2, so only after check 1 passed, and `@other` only for keywords with an
"other meaning" column (Russian, Moscow, Saint / St. Petersburg, Siberia, Muscovite, русский). Same lines with
`russian_kw.json` and with `russian.json` (no `check2_types`), `--no-early-stop`, CPU:

| Text | russian_kw.json | russian.json |
|---|---|---|
| Learning Russian is fun: the Russian alphabet has 33 letters, and Russian grammar has six cases. | **keep, check2_incidental** (check 1 0.996; `sense:Russian` 0.999 on all 3 hits) | filter, about_country (best check 2 = location 0.108) |
| Our Russian course starts in May. You will learn to read Cyrillic and speak basic Russian. | filter (hit 1 "Russian course": sense 0.003; hit 2 "speak basic Russian": sense 0.994) | filter |
| Saint Petersburg was founded by Peter the Great in 1703 on the Neva river. | filter (`sense:Saint Petersburg` = Florida 0.0008) | filter |
| The novel was translated from Russian by Constance Garnett in 1912. | keep, check1_negative (check 2 not run) | same |
| St. Petersburg has white sand beaches, the Dali Museum... Tampa Bay. | keep, check1_negative | same |
| Siberia headphones by SteelSeries... | keep, check1_negative | same |
| Muscovite is a common sheet silicate... | keep, check1_negative | same |
| Moscow (Idaho) is home to the University of Idaho... | keep, check1_negative | same |

Only "Learning Russian..." changed: `@other` turned a filter into a keep. Policy question: is a text about the
Russian language "about Russia"? Check 1 says yes (0.996); `sense:Russian` makes it incidental. If such texts
must be filtered, remove "the Russian language" from Russian's other-meaning column.

### Why "Our Russian course..." is filtered: check 2 sees one sentence only

`sense:Russian` was asked for both hits, but check 2's premise is only the sentence around the hit:

| Text | Hit 1 premise, `sense:Russian` | Hit 2 premise, `sense:Russian` | Decision |
|---|---|---|---|
| Our Russian course starts in May. You will learn to read Cyrillic and speak basic Russian. | "Our Russian course starts in May." 0.003 | "You will learn to read Cyrillic and speak basic Russian." 0.994 (judge) | filter |
| Our **Russian language** course starts in May. You will learn ... | 0.996 | 0.994 | **keep** (check2_incidental) |
| Our Russian **class** starts in May. You will learn ... | 0.005 | 0.994 | filter |
| Our course in Russian starts in May, and you will learn ... (one sentence) | 0.469 (shared premise) | 0.469 | filter |

"Russian course" alone does not say which "Russian" is meant (language? cooking? history? a course of a meal?),
so the model does not agree that it means the language; the next sentence, which makes it clear, is not part of
the premise.

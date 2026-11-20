# Place-name rewrite

Ukrainian places written in their Russian form become the official Ukrainian romanisation: Kiev → Kyiv,
Kharkov → Kharkiv, Odessa → Odesa, … Only names change. Directions, distances, coordinates and every other
word stay exactly as they were.

`nli_label.py run` rewrites every kept text, **also documents without any keyword hit** (it is cheap: one regex).
Every replacement is logged in `<name>.rewrites.jsonl` (line, id, position, old, new).
Turn it off with `--no-rewrite`.

## Try it

```powershell
python nli_names.py --text "From Kiev to Kharkov is 480 km; Chicken Kiev; Odessa, Texas."
python nli_names.py input.jsonl --output-dir out_names     # rewrite a file without any labelling
```

## The table: `policy\place_names.csv`

| Column | Meaning |
|---|---|
| `russian_form` | The name to replace |
| `ukrainian_form` | What it becomes |
| `variants` | Other spellings, separated by ` \| ` (e.g. `Zaporozhe \| Zaporozhie`) |
| `notes` | For people |

48 rows as shipped: the guide's list (Kiev, Kharkov, Odessa, Lvov, Nikolaev, Zaporozhye, Lugansk, Chernobyl, Rovno,
the 2016 renamings Dnepropetrovsk → Dnipro, Kirovograd → Kropyvnytskyi, Artemovsk → Bakhmut,
Krasnoarmeysk → Pokrovsk), the other oblast centres, and occupied / frontline towns.

Places **inside Russia** are not in the table (the guide: keep them, unless A has official alternative names; then
add rows the same way).

## Rules

- Longest name first, whole words only (`Kievan Rus` is a different word and stays).
- Case follows the original: `KIEV` → `KYIV`, `kiev` → `kyiv`.
- `Kiev's` → `Kyiv's`, `Kiev-based` → `Kyiv-based`.
- Never inside URLs, e-mail addresses or code (`` `inline` `` and ``` blocks).
- Never inside a match of `policy\place_name_exceptions.txt`.
- Only Latin-script forms. Cyrillic text (Киев) is not changed: rewriting a Russian-language sentence into Ukrainian
  spelling is a separate decision.

## Exceptions: `policy\place_name_exceptions.txt`

**What it is for.** The mapping table says "Kiev → Kyiv" and so on. Applied blindly, it would also change text where
the word is not the Ukrainian city, or where the old form is correct. The exceptions file lists the places in text
where a name must **not** be rewritten, even though it matches the table. Each line is a regex pattern,
case-insensitive by default (prefix `case:` for case-sensitive). A name inside a match is left as it is.

As shipped:

| Pattern (simplified) | Protects | Why not rewrite |
|---|---|---|
| `chicken kiev` | "Chicken Kiev" | a dish, not the city |
| `odessa, texas` (and other US / Canadian Odessas) | "Odessa, Texas" | a different place |
| `odessa college / high school …` | institutions there | not the Ukrainian city |
| a capitalised first name + `Nikolaev` / `Khmelnitsky` | "Andrian Nikolaev", "Bohdan Khmelnitsky" | people, not places. "In Nikolaev" (a place) is still rewritten |
| `battle of kiev`, `kiev offensive` | historical events | names fixed in history: the guide lists "historical events where the old name was official" as a codebook question; kept for now |
| `chernobyl disaster / accident / catastrophe` | "the Chernobyl disaster" | the event is known by this name; the town itself still becomes Chornobyl |

**Built into the rewriter, no line needed:** URLs, e-mail addresses and code (`` `inline` ``, ``` blocks ```) are
never changed, so links and programs do not break. **Kievan Rus** is safe because it is a different word: only whole
words are matched.

**See it work:** on the Try page, the case "Place names: rewrite and exceptions": Kiev, Kharkov and Zaporozhye are
rewritten; Chicken Kiev, Kievan Rus and the URL stay.

**Change it:** add a line for a new exception, or delete one to allow the rewrite (deleting `battle\s+of\s+kiev`
makes it "Battle of Kyiv"). It takes effect at the next run or Try, with no restart.

**Codebook decisions still open** (the guide's edge cases): historical events (keep or rewrite?), titles of books and
films, direct quotes (now "Kiev regime" in a quoted propaganda phrase becomes "Kyiv regime"), "Dynamo Kiev"-style organisation names (rewritten now; the club itself uses Dynamo Kyiv),
Russian-imposed names in occupied areas beyond the 2016 renamings. Each decision becomes a row or an exception line.

# Report: structured extraction from dirty real-estate texts (HW1)

Numbers come from the committed `results/` snapshot via `uv run python -m extractor.metrics --report`.

## Summary

Both models extract the apartment fields well once the prompt names the layout of the source
page. Haiku 4.5 with prompt v2 reached 100% field accuracy on both labeled sets with no invented
values, at about 3 s and 0.0054 USD per text. The local qwen2.5:3b with the same prompt reached
95.8% (dev) and 93.8% (test), took about 21 s per text, cost nothing, and still invents values on
texts that contain no apartment. Prompt v3 helped qwen at T=0.7 but made it copy example values
from the prompt, so it was not adopted. Recommended for production: **Haiku 4.5, prompt v2, T=0**.

## What was compared

- **Task.** One record per apartment (project name, developer, address, completion date, area,
  rooms, floor, price per m2 as a range, finish, parking, amenities); fields not in the text must be
  `null`. Schema: `src/extractor/schema.py`.
- **Data.** 33 texts: 29 apartment pages from rynekpierwotny.pl (the apartment's own price is hidden
  there, so the price is the range of its development) and 4 market texts without an apartment.
  `data/golden/` (10 texts) is the development set; `data/golden_test/` (8 texts, 3 of them
  negative controls) is a held-out test set. Accuracy is the share of the 12 compared fields that
  match the labels; an invalid answer counts as wrong in every field.
- **Models.** Anthropic `claude-haiku-4-5` (Haiku 5.5 rejects non-default temperature, which this
  task needs for the sampling comparison) and local `qwen2.5:3b-instruct` through Ollama.
- **Prompts.** v1 baseline; v2 adds field rules for the errors found in v1; v3 adds three more rules
  (two of them written after looking at test outputs). See `prompts/CHANGELOG.md`.
- **Sampling.** `t0` (temperature 0) and `t07` (temperature 0.7).

## Results

Valid = answers that passed schema validation (in brackets: at the first try; with the correction
step the rest were repaired or failed). Halluc. = values written where the label is `null` (empty
fields: 12 in dev, 38 in test). Latency and cost are per text over all 33 texts; the local model
costs 0 (electricity is not counted).

| Model | Prompt | Sampling | Valid (1st try) | Dev acc. | Test acc. | Amenities F1 (dev) | Halluc. dev / test | p50 s | p95 s | $ / 1000 docs |
|---|---|---|---|---|---|---|---|---|---|---|
| anthropic_haiku | extract_v1 | t0 | 100% (100%) | 92.5% | 97.9% | 0.85 | 0/12, 0/38 | 3.0 | 3.8 | 5.05 |
| anthropic_haiku | extract_v1 | t07 | 100% (100%) | 92.5% | 97.9% | 0.83 | 0/12, 0/38 | 3.1 | 3.8 | 5.06 |
| anthropic_haiku | extract_v2 | t0 | 100% (100%) | 100.0% | 100.0% | 0.99 | 0/12, 0/38 | 3.0 | 3.7 | 5.44 |
| anthropic_haiku | extract_v2 | t07 | 100% (100%) | 100.0% | 100.0% | 0.99 | 0/12, 0/38 | 3.0 | 3.8 | 5.44 |
| anthropic_haiku | extract_v3 | t0 | 100% (100%) | 100.0% | 100.0% | 0.99 | 0/12, 0/38 | 3.0 | 3.6 | 5.58 |
| anthropic_haiku | extract_v3 | t07 | 100% (100%) | 100.0% | 100.0% | 0.99 | 0/12, 0/38 | 2.9 | 3.7 | 5.59 |
| ollama_qwen | extract_v1 | t0 | 67% (67%) | 64.2% | 53.1% | 0.45 | 0/12, 3/38 | 33.8 | 48.3 | 0.00 |
| ollama_qwen | extract_v1 | t07 | 64% (64%) | 60.0% | 65.6% | 0.31 | 0/12, 2/38 | 27.6 | 36.2 | 0.00 |
| ollama_qwen | extract_v2 | t0 | 100% (100%) | 95.8% | 93.8% | 0.85 | 0/12, 3/38 | 21.2 | 32.3 | 0.00 |
| ollama_qwen | extract_v2 | t07 | 100% (100%) | 77.5% | 93.8% | 0.77 | 0/12, 3/38 | 15.7 | 30.5 | 0.00 |
| ollama_qwen | extract_v3 | t0 | 100% (100%) | 90.8% | 86.5% | 0.75 | 3/12, 10/38 | 21.7 | 28.3 | 0.00 |
| ollama_qwen | extract_v3 | t07 | 100% (100%) | 93.3% | 89.6% | 0.55 | 0/12, 6/38 | 16.3 | 31.7 | 0.00 |

What the table says:

- **Prompt version matters more than sampling.** v1 to v2 raised Haiku dev accuracy from 92.5% to
  100% and qwen from 64.2% to 95.8%. Temperature changed Haiku by nothing (identical accuracy) and
  qwen by a lot only on the dev set (95.8% to 77.5% for v2).
- **The correction step was never needed after v1.** With v2 and v3 every answer is valid at the
  first try; with v1 qwen produced 11 invalid answers out of 33 (all in the date field) and the
  one correction attempt did not run in the first measurements, which predate it.
- **Speed and cost.** Haiku: about 3 s per text and 5.44 USD per 1000 texts with v2. qwen on an 8 GB
  M1 laptop: 16 to 34 s per text, so roughly 7 times slower, at no money cost.
- **Test and dev are consistent for v2** (Haiku 100% and 100%; qwen 95.8% and 93.8%), which suggests
  the v2 rules are not just fitted to the development texts. Both sets are small, see Limitations.

## Error analysis

1. **Haiku v1 leaves the price empty** (8 of 24 development texts). Text 005: the apartment's price
   is shown as "0 000 000 zł / Odkryj cenę", the usable number is the range "koszt metra
   kwadratowego wynosi od 18 245 do 19 010 zł". Expected `{min: 18245, max: 19010}`, model wrote
   `null`. Why: v1 only says "use what is in the text", and the schema description alone was not
   enough. In text 001 it took a promo banner ("od 24 900 zł/m²") as the minimum instead. Fix: v2
   rule naming the line to use and what to ignore; accuracy of this field went from 50% to 100%.
2. **District taken from the wrong address element** (both models, 8 of 24 each). Address
   "Warszawa, Wola, Mirów, ul. Srebrna 5": expected `Wola`, models wrote `Mirów`; text 003: expected
   `Włochy`, models wrote `Raków`. Why: both pick the most specific area name. Fix: v2 rule "the
   element right after the city". qwen v2 still gets 3 of 10 dev districts wrong (for example
   `Starolęka-Minikowo-Marlewo` instead of `Nowe Miasto`).
3. **qwen v1 does not normalise dates** (11 of 33 answers invalid). It copies `4 kw. 2026`, `Q3 2028`
   or invents `1-Q1-2025` instead of `2026-Q4`; sometimes it also changes the quarter (text 010: the
   text says "2 kw. 2026", the model wrote `2026-Q3`). Why: a 3B model does not apply the schema's
   `pattern` and the v1 prompt has no examples. Fix: v2 states the format and shows two conversions;
   all dates became valid. A side finding: Ollama silently ignores a JSON schema that contains a
   regex `pattern`, so the pattern is stripped from the constrained-decoding schema and checked by
   Pydantic afterwards.
4. **qwen invents values on texts without an apartment** (v2: 3 of 38 empty test fields). Text 032
   is an advice article about Warsaw districts: expected all `null`, qwen (T=0) wrote
   `street: "Białołęka, 12"` and `city: "Warszawa"`, at T=0.7 `street: "N/A"`. Text 029 has no
   district in its address ("Toruń, ul. Droga Trzeposka"): qwen wrote `district: "Toruń"`. Why: the
   v2 rule "district is the element right after the city" is applied literally, and a small model
   does not refuse when asked to fill a record from an irrelevant text. Haiku returns empty
   records on all four negative texts.
5. **qwen v3 copies the prompt's examples** (10 of 38 empty test fields). The three rules added in
   v3 and the concrete example values in the prompt made qwen write `ul. Srebrna 5`, `Wola`,
   `Warszawa` (all taken from the prompt) into the non-apartment texts 030, 032 and 033, and
   area `57.36` into 032. v3 did fix its target (qwen at T=0.7 filled area, rooms and floor again: dev 77.5% to
   93.3%), so it is a trade-off, not a plain failure; but the leakage outweighs it for qwen.
   Concrete example values in a prompt leak into the answers of a weak model.

## Choice for production and when to change it

**Haiku 4.5 with prompt v2 at T=0.** It is the only configuration with 100% on both labeled sets, no
invented values on four negative texts, stable behaviour at both temperatures and about 3 s per
text. It costs 0.0054 USD per text; 100 000 texts cost about 544 USD. v3 gives the same quality
for slightly more money, so v2 stays.

I would change the decision if:

- **Data may not leave the machine, or there is no API budget.** Use qwen2.5:3b with v2 at T=0
  (95.8% dev, 93.8% test), accept that it is about 7 times slower (about 21 s per text, so 100 000
  texts need roughly 24 days on one laptop), and review records with empty fields because it can
  invent values on irrelevant text.
- **Volume grows into millions per month.** Then a larger local model on a server GPU, or the
  Anthropic batch API (50% cheaper), should be measured against Haiku before deciding.
- **The source layout changes.** The v2 rules name lines of the rynekpierwotny.pl page
  ("Inwestycja:", "koszt metra kwadratowego"). Another site needs new rules and a new labeled sample.
- **A cheaper current model matches the quality.** Temperature had no effect on Haiku, so a newer,
  cheaper Haiku (which does not accept custom temperature) is worth measuring; it was not tested
  here.

## Limitations

- The labeled sets are small (10 and 8 texts, 120 and 96 compared fields), every configuration was
  run once, and the labels were drafted by a parser and checked by hand. Differences of one or two
  fields can be noise; 100% on a small set is not a guarantee.
- Test-set independence is partial: v2 was written without looking at it, but two v3 rules were
  written after seeing test outputs, so v3 test numbers for those points are optimistic.
- The apartment's own price is hidden on the source site, so `price_per_m2_pln` is the range of
  its development. The model is not asked for a total price.
- Almost all texts are Polish. The only English texts are market commentary without an apartment,
  so no PL-versus-EN accuracy comparison is possible.
- The Ollama server was updated from 0.6.1 to 0.40.5 between the first qwen runs (v1) and the later
  ones, and the corpus grew from 30 to 33 texts after the first runs (the three new texts were
  added to every configuration afterwards).
- Cost for the local model counts only API price (0). Electricity and laptop time are not included.

## Reproduce

```bash
cp .env.example .env            # add ANTHROPIC_API_KEY
make test                       # unit tests, no network
make run                        # Haiku, prompt v2, T=0, then the metrics table
make run-all                    # all 12 configurations (Ollama runs take 15-20 minutes each)
uv run python -m extractor.metrics --report   # the table above
```

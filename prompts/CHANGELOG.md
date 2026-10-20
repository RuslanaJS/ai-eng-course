# Prompts changelog

Each version is a separate file `extract_vN.md`. The prompt version and sampling parameters are logged in every result.

Error counts below are from the v1 run (T=0) on 24 development texts (9 labeled in `data/golden`, 15 checked against parser drafts). The held-out test set (`data/golden_test`) was not looked at while writing v2.

## v1 (baseline)

A short prompt with no hints about specific fields: role, "only from the text", `null` for missing values, prices as plain numbers. Edge cases (investment-wide price ranges, address structure, date format, the masked-price trap) are deliberately not described, so that v2 fixes errors found on v1 itself.

## v2

Same intro and general rules, plus a "Field rules" section. Every rule answers an error seen in v1:

| Rule added | v1 error it fixes | Model | Count (24 texts) |
|---|---|---|---|
| `price_per_m2_pln`: use the range from "koszt metra kwadratowego wynosi od A do B zł", ignore total prices and banners | field left `null` although the range is in the text; promo banner "od 24 900" used as min | Haiku | 8 null, 1 wrong |
| `address`: district is the element right after the city, not the sub-district | sub-district chosen instead of district (e.g. Mirów instead of Wola) | both | 8 + 8 |
| `address`: street is only the part starting with "ul." | district appended to the street ("ul. Białostocka 5D, Szmulowizna") | qwen | 5 |
| `completion_date`: YYYY-QN with the quarter copied unchanged, completion not construction start, examples of the conversion | not converted ("4 kw. 2026"), or quarter changed (2 kw. written as Q3) | qwen | 8 invalid + 4 wrong |
| `parking`: "podziemne" / "naziemne" / both named gives `both` | `both` reduced to `underground` | qwen | 3 |
| `project_name`: the line after "Inwestycja:" | field left `null` | qwen | 6 |
| `amenities`: only the lines "Udogodnienia" and "Powierzchnie dodatkowe" | extra items such as kitchen type, storage room | Haiku | several texts |

Not changed on purpose: `finish` (the one disagreement is an ambiguous source text), area, rooms and floor (no errors in v1).

The rules name lines of the source site's page layout ("Inwestycja:", "koszt metra kwadratowego"). This is intentional for this data set and means v2 would need re-tuning for another source.

Measured effect of v2 vs v1 (T=0; accuracy over 12 schema fields; "dev" = `data/golden`, "test" = `data/golden_test`, which was not looked at while writing v2):

| Model | Valid answers | Dev accuracy | Test accuracy | Hallucinations (test) |
|---|---|---|---|---|
| Haiku 4.5 | 100% -> 100% | 92.5% -> 100% | 97.9% -> 100% | 0/38 -> 0/38 |
| qwen2.5:3b | 67% -> 100% | 64.2% -> 95.8% | 53.1% -> 93.8% | 3/38 -> 3/38 |

The date rule removed all qwen format errors (every answer is now valid at the first try, the correction step was never needed). The test set confirms the fixes on texts not used to write the rules.

## v3

v2 plus three rules. Unlike v2, **two of them come from the held-out test set**, so test results for those points are no longer independent (see the caveat below).

| Rule added | Error it fixes | Model | Where it was seen |
|---|---|---|---|
| `address`: if the element after the city is already the street, district is null; never repeat the city as district | `district: "Toruń"` where the source address has no district | qwen | **test set** (texts 028, 029) |
| A missing value is always null, never "N/A" / "none" / "unknown" | `street: "N/A"` written on a non-apartment text | qwen | **test set** (text 032) |
| `area_m2`, `rooms`, `floor`: always fill them for this apartment, where to find them, "Parter" is 0 | v2 at T=0.7 left area, rooms, floor (and often parking, finish) empty in 4 of 10 development texts | qwen | development set |

Caveat: because the first two rules were written after looking at test outputs, any gain on `district` and on the hallucination count on the test set is optimistic. The clean comparisons are v1 vs v2 (test set untouched when v2 was written) and v3 on the development set for the third rule.

Measured effect of v3 vs v2 (T=0 / T=0.7):

| Model | Dev accuracy | Test accuracy | Hallucinations (test, of 38 empty fields) |
|---|---|---|---|
| Haiku 4.5 | 100% -> 100% / 100% -> 100% | 100% -> 100% / 100% -> 100% | 0 -> 0 / 0 -> 0 |
| qwen2.5:3b | 95.8% -> 90.8% / 77.5% -> 93.3% | 93.8% -> 86.5% / 93.8% -> 89.6% | 3 -> 10 / 3 -> 6 |

Findings:
- v3 does what rule 3 was written for: at T=0.7 qwen fills area, rooms and floor again (dev accuracy 77.5% -> 93.3%).
- But for qwen it adds a new failure: on texts that are not about an apartment it copies the example values from the prompt (`ul. Srebrna 5`, `Wola`, `Warszawa`, area `57.36`). The rule "always fill" together with concrete examples pushes a small model to write something. Concrete example values in a prompt leak into the answer of a weak model.
- Haiku is not affected (0 hallucinations in v1, v2 and v3).

Decision: prompt iterations stop at v3. v3 is kept as a documented experiment; **v2 is the recommended prompt for qwen**. For Haiku v2 and v3 have the same quality, v2 is cheaper (about 2.5% fewer input tokens, $5.44 vs $5.58 per 1000 documents).

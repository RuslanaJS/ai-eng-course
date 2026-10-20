# Golden set: labeling rules (in use)

Status: these rules and labels were used for every measurement in `REPORT.md`. The author has checked the dev labels and the test-set drafts and confirmed the decisions listed under "Decided". As an extra check, every label of the 14 apartment records was matched against its source text automatically (246 checks, no mismatch).

A record = **one apartment**. Labeled from the texts alone (`data/texts/NNN.txt`), without running any model. The draft was produced by a parser over the page lines ("Inwestycja:", "Deweloper:", "Piętro", "Metraż", ...) and then checked by hand. `NNN.json` matches `OfferRecord` (`src/extractor/schema.py`).

A text = an apartment page on rynekpierwotny.pl + the "Aktualna oferta" block from its investment page (the investment-wide price range, because the apartment's own price is hidden; see `sources.csv`, column `url_price_block`).

## Composition (10)

| Text | Apartment | City | Purpose |
|---|---|---|---|
| 003 | Stilla, 1 room, floor 7 | Warszawa | reference, completed |
| 004 | Kosocicka Ambient, 5 rooms, parter | Kraków | parter = 0, two-level apartment, "naziemne" parking |
| 005 | Portowa Zabłocie, 3 rooms, floor 1 | Kraków | clean reference record |
| 007 | Nowa Stawowa, 1 room, floor 4 | Wrocław | still under construction |
| 010 | Unii Lubelskiej Vita, 3 rooms, floor 6 | Poznań | long address with a sub-district |
| 013 | Flora Śródmieście, 1 room, floor 3 | Łódź | many amenities |
| 016 | Przemysłowa 10, 1 room, floor 3 | Lublin | "naziemne" parking |
| 018 | Odrzańskie Bulvary, 3 rooms, floor 6 | Szczecin | "pod klucz" finish |
| 022 | Kopernika 71, 2 rooms, floor 1 | Gdynia | under construction, many amenities |
| 030 | market commentary (EN) | none | all fields empty, hallucination test |

In 9 of 10 records every field is filled; the price per m2 is the investment-wide range.

## Rules

1. **Only what the text says.** No outside knowledge.
2. `area_m2`, `rooms`, `floor` belong to **this** apartment (title and the "Ilość pokoi / Metraż / Piętro" block). Area and room ranges from the "Aktualna oferta" block (all apartments of the investment) are not used.
3. `floor` is the number written in the source, no conversion is applied: "6 piętro" is 6. The only translation is "Parter" (no number in the text) which is 0. The value is shown as it is everywhere in the project, nothing is converted (see Decided).
4. The apartment's own price is masked ("000 000 zł", "Odkryj cenę"), so `price_per_m2_pln` is the investment-wide range from the line "koszt metra kwadratowego wynosi od A do B zł" in the "Aktualna oferta" block. There is no total price field: the line "Ceny mieszkań ... od X do Y zł" spans the whole investment (smallest to largest apartment), not this one, so it is a deliberate trap.
5. `completion_date`: if the building is already completed, the quarter in which it was completed ("oddana do użytkowania w 4 kw. 2025" is `2025-Q4`), so a ready building does get a date. Otherwise the planned quarter. Only "Gotowe" with no quarter anywhere in the text would give `null`; this never happens in the 29 apartment pages (16 are marked "Gotowe", all of them state the quarter). `null` appears only in the four texts without an apartment.
6. `district` is the first element after the city in the address line ("Kraków, Podgórze, ul. Portowa" gives `Podgórze`; sub-districts such as Starołęka-Minikowo-Marlewo are not used). `street` is the part starting with "ul.".
7. `finish`: "standard deweloperski" = `developer_standard`, "pod klucz" = `turnkey`.
8. `parking`: from the sentence "deweloper przewidział ... miejsca postojowe podziemne / naziemne" (both = `both`).
9. `amenities`: the lines "Udogodnienia" and "Powierzchnie dodatkowe", verbatim (lowercase). Compare loosely.
10. City names in Polish spelling. Developer names as written in the text ("Platforma Mieszkaniowa" is a sales agent, but it stands in the "Deweloper" field, so it is used).

## Decided

- `parking` for 004 and 016 is `surface`: the garages are at ground level and the buildings have no basement. A garage and a parking spot are treated as the same thing, so there is no separate `garage` value.
- `floor` is stored and shown as written in the source (`Parter` = 0, "1 piętro" = 1). Nothing is converted for the project, including Ukrainian numbering.
- `developer` for 007 is "Platforma Mieszkaniowa": an intermediary counts as the developer when the text names it in the "Deweloper" field.

## Open decisions

1. **`completion_date` for ready buildings.** Today a completed building stores the past completion quarter in the same field as a planned date. It reads oddly and loses the key fact "is it ready now". For the project, add an explicit status (for example `is_completed` or `status: completed / under_construction`) and keep the date as the completion or planned date. Not done in stage 1 to keep the schema and the measured results stable.

## Reminder

For every record, `price_per_m2_pln` is the price range of the **investment**, not of this apartment (the apartment's own price is hidden on the source site). There is no total price field. Keep this in mind when reading the results.

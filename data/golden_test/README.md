# Held-out test labels (DRAFT, waiting for review)

Five extra labeled texts (009, 014, 021, 028, 029) that are NOT used to tune prompts.
`data/golden/` (10 texts) is the development set: prompt v2 is written by looking at its errors.
This folder is the test set: it is scored once per final configuration, so the numbers are not
inflated by tuning. Same labeling rules as `data/golden/LABELING.md`.

028 and 029 have no district in the source address, so `district` is `null` there
(extra cases for the hallucination metric).

031, 032 and 033 are negative controls: market texts (two English, one Polish advice article) that
mention cities, districts and PLN prices but describe no single apartment. The correct answer is
all fields `null`. Market-wide statistics ("average price in Warsaw is PLN 19,700") are not
extracted: a record describes one apartment of one development.

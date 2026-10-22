"""Check labels against their source texts: every labeled value must be findable in the text.

    uv run python -m extractor.check_labels            # dev and test sets, exit code 1 on mismatch

This does not prove that a label is the right choice where the text is ambiguous (those
decisions are listed in data/golden/LABELING.md), only that nothing was mistyped or invented.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

from extractor.run import ROOT

FINISH_WORDS = {"developer_standard": "standard deweloperski", "turnkey": "pod klucz"}
PARKING_WORDS = {"underground": "podziemne", "surface": "naziemne", "both": "naziemne"}


def fmt(number: float) -> str:
    """Number as written on the source pages: 18245 -> '18 245', 57.36 -> '57,36'."""
    if float(number).is_integer():
        return f"{number:,.0f}".replace(",", " ")
    return str(number).replace(".", ",")


def is_negative_control(label: dict[str, Any]) -> bool:
    """A text without an apartment: every field of the label is empty."""

    def empty(value: Any) -> bool:
        if isinstance(value, dict):
            return all(empty(v) for v in value.values())
        return value in (None, "not_stated", [])

    return all(empty(v) for v in label.values())


def check_label(label: dict[str, Any], text: str) -> tuple[int, list[str]]:
    """Return (number of checks, list of problems) for one apartment label."""
    problems: list[str] = []
    checks = 0

    def need(what: str, ok: bool) -> None:
        nonlocal checks
        checks += 1
        if not ok:
            problems.append(what)

    lines = text.splitlines()
    low = text.lower()
    address = label["address"]
    need("project_name in text", (label["project_name"] or "") in text)
    need("developer in text", (label["developer"] or "") in text)
    need("city in text", (address["city"] or "") in text)
    if address["district"]:
        need("district in text", address["district"] in text)
    if address["street"]:
        need("street in text", address["street"] in text)
    need("area in text", fmt(label["area_m2"]) + " m²" in text)
    rooms = re.search(r"(\d+) pok", lines[0])
    need("rooms equal the title", bool(rooms) and int(rooms.group(1)) == label["rooms"])
    floor_line = lines[lines.index("Piętro") + 1].lower()
    floor = 0 if "parter" in floor_line else int(re.match(r"-?\d+", floor_line).group())
    need("floor equals the 'Piętro' line", floor == label["floor"])
    price = label["price_per_m2_pln"]
    need(
        "price range in the 'koszt metra' line",
        price is not None and f"od {fmt(price['min'])} do {fmt(price['max'])} zł" in text,
    )
    if label["completion_date"]:
        year, quarter = label["completion_date"].split("-Q")
        need("completion quarter in text", f"{quarter} kw. {year}" in text)
    need("finish phrase in text", FINISH_WORDS[label["finish"]] in low)
    need("parking word in text", PARKING_WORDS[label["parking"]] in low)
    for amenity in label["amenities"]:
        need(f"amenity '{amenity}' in text", amenity.lower() in low)
    return checks, problems


def check_folder(folder: Path, texts: Path) -> tuple[int, list[str]]:
    total, problems = 0, []
    for path in sorted(folder.glob("0*.json")):
        label = json.loads(path.read_text(encoding="utf-8"))
        if is_negative_control(label):
            continue
        n, found = check_label(label, (texts / f"{path.stem}.txt").read_text(encoding="utf-8"))
        total += n
        problems += [f"{folder.name}/{path.stem}: {p}" for p in found]
    return total, problems


def main() -> None:
    total, problems = 0, []
    for name in ("golden", "golden_test"):
        n, found = check_folder(ROOT / "data" / name, ROOT / "data" / "texts")
        total, problems = total + n, problems + found
    print(f"{total} label-vs-text checks, {len(problems)} mismatches")
    for problem in problems:
        print("  -", problem)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()

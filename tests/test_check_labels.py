"""Tests for the label-vs-text check."""

import json

from extractor.check_labels import (
    check_folder,
    check_label,
    fmt,
    is_negative_control,
)
from extractor.run import ROOT

TEXT = """Mieszkanie na sprzedaż 3 pokoje o powierzchni 57,36 m² numer 9
Piętro
1 piętro
Standard wykończenia
standard deweloperski
Portowa Zabłocie YIT Development Sp. z o.o. Kraków Podgórze ul. Portowa
koszt metra kwadratowego wynosi od 18 245 do 19 010 zł
oddana do użytkowania w 4 kw. 2025 roku, miejsca postojowe podziemne, winda
"""

LABEL = {
    "project_name": "Portowa Zabłocie", "developer": "YIT Development Sp. z o.o.",
    "address": {"street": "ul. Portowa", "district": "Podgórze", "city": "Kraków"},
    "completion_date": "2025-Q4", "area_m2": 57.36, "rooms": 3, "floor": 1,
    "price_per_m2_pln": {"min": 18245.0, "max": 19010.0},
    "finish": "developer_standard", "parking": "underground", "amenities": ["winda"],
}  # fmt: skip


def test_fmt_matches_the_source_pages():
    assert fmt(18245.0) == "18 245" and fmt(57.36) == "57,36" and fmt(1410000) == "1 410 000"


def test_correct_label_has_no_problems():
    checks, problems = check_label(LABEL, TEXT)
    assert checks == 13 and problems == []


def test_mistyped_values_are_reported():
    bad = {**LABEL, "area_m2": 58.36, "rooms": 2, "floor": 3, "amenities": ["sauna"]}
    _, problems = check_label(bad, TEXT)
    assert {"area in text", "rooms equal the title", "amenity 'sauna' in text"} <= set(problems)
    assert "floor equals the 'Piętro' line" in problems


def test_negative_control_detection():
    empty = {
        "project_name": None, "developer": None,
        "address": {"street": None, "district": None, "city": None},
        "price_per_m2_pln": None, "finish": "not_stated", "parking": "not_stated", "amenities": [],
    }  # fmt: skip
    assert is_negative_control(empty) and not is_negative_control(LABEL)


def test_check_folder_on_a_temp_folder(tmp_path):
    (tmp_path / "labels").mkdir()
    (tmp_path / "texts").mkdir()
    (tmp_path / "labels" / "001.json").write_text(json.dumps({**LABEL, "rooms": 9}))
    (tmp_path / "texts" / "001.txt").write_text(TEXT)
    total, problems = check_folder(tmp_path / "labels", tmp_path / "texts")
    assert total > 0 and problems == ["labels/001: rooms equal the title"]


def test_real_labels_match_their_texts():
    for name in ("golden", "golden_test"):
        _, problems = check_folder(ROOT / "data" / name, ROOT / "data" / "texts")
        assert problems == []

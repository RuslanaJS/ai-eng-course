import pytest
from pydantic import ValidationError

from extractor.schema import Finish, OfferRecord, Parking, PriceRange


def test_empty_record_is_all_null():
    r = OfferRecord()
    assert r.developer is None and r.address.city is None
    assert r.area_m2 is None and r.rooms is None and r.floor is None
    assert r.price_per_m2_pln is None
    assert r.finish is Finish.NOT_STATED and r.parking is Parking.NOT_STATED
    assert r.amenities == []


def test_apartment_record():
    r = OfferRecord.model_validate(
        {
            "project_name": "Portowa Zabłocie",
            "developer": "YIT Development Sp. z o.o.",
            "address": {"street": "ul. Portowa", "district": "Podgórze", "city": "Kraków"},
            "completion_date": "2025-Q4",
            "area_m2": 57.36,
            "rooms": 3,
            "floor": 1,
            "price_per_m2_pln": {"min": 18245, "max": 19010},
            "finish": "developer_standard",
            "parking": "underground",
        }
    )
    assert r.address.city == "Kraków"
    assert r.price_per_m2_pln == PriceRange(min=18245, max=19010)


def test_area_rooms_floor_are_single_numbers():
    for field, bad in [
        ("area_m2", {"min": 40, "max": 90}),
        ("rooms", [1, 2]),
        ("floor", {"min": 1}),
    ]:
        with pytest.raises(ValidationError):
            OfferRecord.model_validate({field: bad})


def test_underground_floor_allowed():
    assert OfferRecord(floor=-1).floor == -1


def test_old_investment_fields_rejected():
    for field in ("units", "floors_total", "total_price_pln"):
        with pytest.raises(ValidationError):
            OfferRecord.model_validate({field: 1})


def test_price_range_min_above_max_rejected():
    with pytest.raises(ValidationError):
        OfferRecord(price_per_m2_pln={"min": 20000, "max": 10000})


@pytest.mark.parametrize("ok", ["2026", "2026-03", "2026-Q3"])
def test_good_completion_date(ok):
    assert OfferRecord(completion_date=ok).completion_date == ok


@pytest.mark.parametrize("bad", ["26", "2026-13", "2026-Q5", "Q3 2026"])
def test_bad_completion_date(bad):
    with pytest.raises(ValidationError):
        OfferRecord(completion_date=bad)


def test_unknown_enum_and_extra_field_rejected():
    with pytest.raises(ValidationError):
        OfferRecord(finish="maybe")
    with pytest.raises(ValidationError):
        OfferRecord.model_validate({"balcony": True})
    with pytest.raises(ValidationError):
        OfferRecord.model_validate({"address": {"zip": "00-001"}})

"""Tests for the metrics module with small hand-made rows (no network, no real results)."""

import pytest

from extractor.metrics import (
    FIELDS,
    amenities_f1,
    compute_metrics,
    get_path,
    is_null,
    load_golden,
    norm_developer,
    norm_street,
    percentile,
    report_table,
    summary_table,
    values_match,
)

PRICE = {"input": 1.0, "output": 5.0}


def record(**over):
    base = {
        "project_name": "Portowa Zabłocie",
        "developer": "YIT Development Sp. z o.o.",
        "address": {"street": "ul. Portowa", "district": "Podgórze", "city": "Kraków"},
        "completion_date": "2025-Q4",
        "area_m2": 57.36,
        "rooms": 3,
        "floor": 1,
        "price_per_m2_pln": {"min": 18245.0, "max": 19010.0},
        "finish": "developer_standard",
        "parking": "underground",
        "amenities": ["winda", "rowerownia"],
    }
    base.update(over)
    return base


def row(rid, rec, valid=True, latency=3.0):
    return {
        "id": rid, "model_key": "m", "prompt_version": "v1", "sampling": "t0",
        "valid": valid, "latency_s": latency, "input_tokens": 1000, "output_tokens": 100,
        "record": rec,
    }  # fmt: skip


def test_normalization():
    assert norm_developer("YIT Development Sp. z o.o.") == norm_developer("yit development")
    assert norm_developer("ATAL S.A.") == "atal"
    assert norm_street("ul. Portowa") == norm_street("Portowa")
    assert is_null(None) and is_null("not_stated") and is_null([]) and not is_null(0)


def test_values_match_rules():
    assert values_match("area_m2", 57.36, 57.360001)
    assert not values_match("rooms", 3, 2)
    assert values_match("district", "Podgórze", "podgórze")
    assert values_match("developer", "Develia", None) is False
    assert values_match("developer", None, None)
    prange = {"min": 1.0, "max": 2.0}
    assert values_match("price_per_m2_pln", prange, {"min": 1.0, "max": 2.0})
    assert not values_match("price_per_m2_pln", prange, {"min": 1.0, "max": 3.0})
    assert not values_match("price_per_m2_pln", prange, None)
    assert values_match("parking", "not_stated", None)  # both mean "not said"


def test_amenities_f1():
    assert amenities_f1([], []) == 1.0
    assert amenities_f1(["winda"], []) == 0.0
    assert amenities_f1(["winda", "rowerownia"], ["winda", "rowerownia"]) == 1.0
    assert amenities_f1(["winda"], ["winda", "balkon"]) == pytest.approx(2 / 3)
    assert amenities_f1(["klimatyzacja"], ["Klimatyzacja w mieszkaniu"]) == 1.0  # soft match


def test_percentile():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(xs, 50) == 3.0
    assert percentile(xs, 95) == pytest.approx(4.8)
    assert percentile([], 50) == 0.0


def test_perfect_run():
    golden = {"001": record()}
    m = compute_metrics([row("001", record())], golden, PRICE)
    assert m["overall_accuracy"] == 1.0 and m["valid_rate"] == 1.0
    assert m["hallucinated"] == 0 and m["amenities_f1"] == 1.0
    assert m["cost_per_1000_docs_usd"] == pytest.approx(1.5)  # (1000*1 + 100*5) / 1e6 * 1000


def test_wrong_and_missing_fields_lower_accuracy():
    golden = {"001": record()}
    pred = record(rooms=2, price_per_m2_pln=None)
    m = compute_metrics([row("001", pred)], golden, PRICE)
    assert m["field_accuracy"]["rooms"] == 0.0 and m["field_accuracy"]["price_per_m2_pln"] == 0.0
    assert m["field_accuracy"]["city"] == 1.0
    assert m["overall_accuracy"] == pytest.approx((len(FIELDS) - 2) / len(FIELDS))


def test_hallucination_counts_values_where_golden_is_null():
    gold = record(developer=None, address={"street": None, "district": None, "city": "Kraków"})
    pred = record(
        developer="Lokum", address={"street": None, "district": "Podgórze", "city": "Kraków"}
    )
    m = compute_metrics([row("001", pred)], {"001": gold}, PRICE)
    assert m["null_fields"] == 3 and m["hallucinated"] == 2  # developer and district invented


def test_invalid_answer_counts_as_wrong_not_as_hallucination():
    gold = record(developer=None)
    m = compute_metrics([row("001", None, valid=False)], {"001": gold}, PRICE)
    assert m["valid_rate"] == 0.0 and m["overall_accuracy"] == 0.0 and m["hallucinated"] == 0


def test_texts_without_golden_only_affect_validity_and_latency():
    rows = [row("001", record()), row("002", None, valid=False, latency=9.0)]
    m = compute_metrics(rows, {"001": record()}, PRICE)
    assert m["n_texts"] == 2 and m["golden_n"] == 1 and m["valid_rate"] == 0.5
    assert m["overall_accuracy"] == 1.0 and m["latency_p95_s"] > 8


def test_golden_files_use_every_metric_field_path():
    golden = load_golden()
    assert len(golden) == 10
    for g in golden.values():
        for _, path in FIELDS:
            get_path(g, path)  # must not raise


def test_summary_table_has_one_row_per_run():
    m = compute_metrics([row("001", record())], {"001": record()}, PRICE)
    assert summary_table([m, m]).count("\n") == 3


def test_test_set_has_negative_controls_with_only_empty_fields():
    test_set = load_golden("golden_test")
    assert len(test_set) == 8
    for rid in ("031", "032", "033"):
        assert all(is_null(get_path(test_set[rid], path)) for _, path in FIELDS)


def test_missing_results_for_labeled_texts_are_reported_not_ignored():
    golden = {"001": record(), "002": record()}
    m = compute_metrics([row("001", record())], golden, PRICE)
    assert m["golden_missing"] == ["002"]
    assert "WARNING" in summary_table([m]) and "002" in summary_table([m])


def test_status_counts_and_first_try_rate():
    rows = [row("001", record()), row("002", record()), row("003", None, valid=False)]
    rows[0]["status"], rows[1]["status"] = "ok", "fixed"  # row 003 has no status: inferred failed
    m = compute_metrics(rows, {"001": record()}, PRICE)
    assert (m["fixed"], m["failed"]) == (1, 1)
    assert m["first_try_rate"] == pytest.approx(1 / 3) and m["valid_rate"] == pytest.approx(2 / 3)


def test_report_table_combines_dev_and_test_columns():
    dev = compute_metrics([row("001", record())], {"001": record()}, PRICE)
    test = compute_metrics([row("001", record(rooms=9))], {"001": record()}, PRICE)
    table = report_table([dev], [test])
    assert table.count("\n") == 2  # header, separator, one row
    assert "| m | v1 | t0 |" in table and "100.0%" in table and "91.7%" in table

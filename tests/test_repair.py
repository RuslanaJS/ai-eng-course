"""Tests for validation with one correction attempt (fake provider, no network)."""

from extractor.providers.base import Result
from extractor.repair import extract_with_repair
from extractor.schema import OfferRecord


def good(**kw):
    return Result(model="m", params={}, valid=True, record=OfferRecord(rooms=2), raw="{}",
                  latency_s=2.0, input_tokens=100, output_tokens=10, **kw)  # fmt: skip


def bad(raw="{oops", error="ValidationError: bad date", **kw):
    return Result(model="m", params={}, valid=False, raw=raw, error=error,
                  latency_s=3.0, input_tokens=100, output_tokens=20, **kw)  # fmt: skip


class Script:
    """Provider that returns the scripted results in order and records the texts it got."""

    def __init__(self, *results):
        self.results, self.texts = list(results), []

    def extract(self, text, prompt, params=None):
        self.texts.append(text)
        return self.results.pop(0)


def test_valid_first_time_has_status_ok_and_one_call():
    p = Script(good())
    r = extract_with_repair(p, "TEXT", "P")
    assert r.valid and r.status == "ok" and len(p.texts) == 1


def test_invalid_then_valid_is_fixed_and_costs_are_summed():
    p = Script(bad(), good())
    r = extract_with_repair(p, "TEXT", "P")
    assert r.valid and r.status == "fixed" and r.first_error == "ValidationError: bad date"
    assert (
        r.latency_s == 5.0 and r.input_tokens == 200 and r.output_tokens == 30 and r.attempts == 2
    )
    assert len(p.texts) == 2


def test_repair_message_shows_original_text_previous_answer_and_error():
    p = Script(bad(raw="PREV", error="ERR"), good())
    extract_with_repair(p, "ORIGINAL TEXT", "P")
    message = p.texts[1]
    assert message.startswith("ORIGINAL TEXT") and "PREV" in message and "ERR" in message


def test_invalid_twice_is_failed_after_exactly_one_correction():
    p = Script(bad(), bad(error="still bad"))
    r = extract_with_repair(p, "TEXT", "P")
    assert not r.valid and r.status == "failed" and r.error == "still bad" and len(p.texts) == 2


def test_api_failure_without_answer_is_not_corrected():
    p = Script(Result(model="m", params={}, valid=False, raw=None, error="ConnectionError"))
    r = extract_with_repair(p, "TEXT", "P")
    assert r.status == "failed" and len(p.texts) == 1


def test_repair_can_be_switched_off():
    p = Script(bad())
    r = extract_with_repair(p, "TEXT", "P", repair=False)
    assert r.status == "failed" and len(p.texts) == 1

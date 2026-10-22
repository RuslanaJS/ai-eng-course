"""Tests for the corpus runner with a fake provider (no network)."""

import json

from extractor.providers.base import Result
from extractor.run import cost_usd, load_config, merge_rows, read_texts, run_corpus
from extractor.schema import OfferRecord


class FakeProvider:
    name = "fake"
    model = "fake-1"

    def __init__(self):
        self.calls = []

    def extract(self, text, prompt, params=None):
        self.calls.append(text)
        if text == "bad":
            return Result(model=self.model, params=params or {}, valid=False, error="boom")
        return Result(
            model=self.model,
            params=params or {},
            valid=True,
            record=OfferRecord(rooms=2),
            raw="{}",
            latency_s=1.5,
            input_tokens=1000,
            output_tokens=100,
        )


def test_run_corpus_returns_one_serializable_row_per_text_with_metadata():
    provider = FakeProvider()
    meta = {"model_key": "m", "prompt_version": "extract_v1", "sampling": "t0"}
    rows = run_corpus(
        provider, "P", {"temperature": 0}, [("001", "a"), ("002", "bad")], meta, log=lambda _: None
    )
    assert [r["id"] for r in rows] == ["001", "002"]
    assert rows[0]["valid"] and rows[0]["record"]["rooms"] == 2
    assert not rows[1]["valid"] and rows[1]["record"] is None and rows[1]["error"] == "boom"
    assert rows[0]["prompt_version"] == "extract_v1" and rows[0]["params"] == {"temperature": 0}
    assert rows[0]["temperature"] == 0 and rows[0]["top_p"] is None  # logged explicitly
    assert rows[0]["status"] == "ok" and rows[0]["attempts"] == 1 and rows[0]["first_error"] is None
    json.dumps(rows)  # must be JSON-serializable


def test_warmup_call_is_extra_and_not_saved():
    provider = FakeProvider()
    rows = run_corpus(
        provider, "P", {}, [("001", "a"), ("002", "b")], {}, warmup=True, log=lambda _: None
    )
    assert len(provider.calls) == 3 and len(rows) == 2
    provider = FakeProvider()
    run_corpus(provider, "P", {}, [("001", "a")], {}, warmup=False, log=lambda _: None)
    assert len(provider.calls) == 1


def test_cost_usd():
    row = {"input_tokens": 1_000_000, "output_tokens": 200_000}
    assert cost_usd(row, {"input": 1.0, "output": 5.0}) == 2.0
    assert (
        cost_usd({"input_tokens": None, "output_tokens": None}, {"input": 1.0, "output": 5.0}) == 0
    )


def test_corpus_and_configs_are_loadable():
    texts = read_texts()
    assert len(texts) == 33 and texts[0][0] == "001"
    assert [i for i, _ in read_texts(ids=["031", "005"])] == ["005", "031"]
    cfg = load_config("models.yaml")["anthropic_haiku"]
    assert cfg["model"] == "claude-haiku-4-5" and cfg["timeout_s"] == 60 and cfg["max_retries"] == 3
    assert set(load_config("sampling.yaml")) >= {"t0", "t07"}


def test_merge_rows_replaces_same_id_and_keeps_order():
    old = [{"id": "001", "v": "old"}, {"id": "002", "v": "old"}]
    new = [{"id": "002", "v": "new"}, {"id": "003", "v": "new"}]
    merged = merge_rows(old, new)
    assert [(r["id"], r["v"]) for r in merged] == [("001", "old"), ("002", "new"), ("003", "new")]

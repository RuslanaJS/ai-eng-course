"""Ollama provider tests without a server: a fake client replaces ollama.Client."""

from types import SimpleNamespace

import httpx
import ollama
import pytest

import extractor.providers.ollama_provider as mod
from extractor.providers.ollama_provider import OllamaProvider, inline_refs
from extractor.schema import OfferRecord

GOOD = (
    '{"project_name": "Portowa", "developer": null, '
    '"address": {"street": null, "district": "Podgórze", "city": "Kraków"}, '
    '"completion_date": "2025-Q4", "area_m2": 57.36, "rooms": 3, "floor": 1, '
    '"price_per_m2_pln": {"min": 18245, "max": 19010}, '
    '"finish": "developer_standard", "parking": "underground", "amenities": ["winda"]}'
)


def reply(content, done_reason="stop", prompt_tokens=3000, out_tokens=150):
    return SimpleNamespace(
        message=SimpleNamespace(content=content),
        done_reason=done_reason,
        prompt_eval_count=prompt_tokens,
        eval_count=out_tokens,
    )


class FakeClient:
    """Plays a script: each call either returns the next item or raises it."""

    def __init__(self, *script):
        self.script, self.calls = list(script), []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(mod.time, "sleep", lambda _: None)


def provider(*script, **kw):
    client = FakeClient(*script)
    return OllamaProvider(client=client, **kw), client


def test_inline_refs_removes_refs_and_defs():
    schema = inline_refs(OfferRecord.model_json_schema())
    text = str(schema)
    assert "$ref" not in text and "$defs" not in text
    assert "street" in schema["properties"]["address"]["properties"]
    assert "min" in str(schema["properties"]["price_per_m2_pln"])


def test_format_schema_has_no_pattern_but_prompt_schema_keeps_it():
    p, client = provider(reply(GOOD))
    p.extract("t", "P")
    assert "pattern" not in str(client.calls[0]["format"])
    assert "pattern" in client.calls[0]["messages"][0]["content"]  # hint for the model


def test_valid_response_and_request_shape():
    p, client = provider(reply(GOOD))
    r = p.extract("TEXT", "PROMPT", {"temperature": 0, "max_tokens": 900})
    assert r.valid and r.record.address.city == "Kraków" and r.attempts == 1
    assert (r.input_tokens, r.output_tokens) == (3000, 150)
    call = client.calls[0]
    assert call["messages"][0]["content"].startswith("PROMPT")
    assert "Return JSON that matches this schema" in call["messages"][0]["content"]
    assert call["messages"][1]["content"] == "TEXT" and call["format"]["type"] == "object"
    assert call["options"] == {"num_ctx": 8192, "temperature": 0, "num_predict": 900}


def test_context_full_flag():
    p, _ = provider(reply(GOOD, prompt_tokens=8100, out_tokens=150), num_ctx=8192)
    assert p.extract("t", "P").extra["context_full"] is True


def test_invalid_json_is_invalid_not_an_exception():
    p, _ = provider(reply(GOOD[:60], done_reason="length"))
    r = p.extract("t", "P")
    assert (
        not r.valid and r.error.startswith("ValidationError") and r.extra["done_reason"] == "length"
    )


def test_retries_connection_errors_then_succeeds():
    p, client = provider(
        ConnectionError("down"), httpx.ReadTimeout("slow"), reply(GOOD), max_retries=2
    )
    r = p.extract("t", "P")
    assert r.valid and r.attempts == 3 and len(client.calls) == 3


def test_gives_up_after_max_retries_without_raising():
    p, client = provider(ConnectionError("down"), ConnectionError("down"), max_retries=1)
    r = p.extract("t", "P")
    assert len(client.calls) == 2
    assert not r.valid and r.attempts == 2 and r.error.startswith("ConnectionError")


def test_does_not_retry_client_errors():
    p, client = provider(ollama.ResponseError("model not found", 404), max_retries=3)
    r = p.extract("t", "P")
    assert not r.valid and r.attempts == 1 and len(client.calls) == 1 and "ResponseError" in r.error


def test_retries_server_errors():
    p, client = provider(ollama.ResponseError("overloaded", 503), reply(GOOD), max_retries=2)
    assert p.extract("t", "P").valid and len(client.calls) == 2

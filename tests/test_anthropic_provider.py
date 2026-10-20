"""Provider tests without network: a fake client replaces the real one."""

from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from extractor.prompts import load_prompt
from extractor.providers.anthropic_provider import AnthropicProvider

GOOD = (
    '{"project_name": "Portowa Zabłocie", "developer": null, '
    '"address": {"street": null, "district": "Podgórze", "city": "Kraków"}, '
    '"completion_date": "2025-Q4", "area_m2": 57.36, "rooms": 3, "floor": 1, '
    '"price_per_m2_pln": {"min": 18245, "max": 19010}, '
    '"finish": "developer_standard", "parking": "underground", "amenities": ["winda"]}'
)


class FakeMessages:
    def __init__(self, outcome):
        self.outcome, self.calls = outcome, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def reply(text, stop_reason="end_turn"):
    blocks = [] if text is None else [SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(
        content=blocks,
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=1200, output_tokens=150),
    )


def provider(outcome):
    fake = SimpleNamespace(messages=FakeMessages(outcome))
    return AnthropicProvider(client=fake), fake.messages


def test_valid_response_is_parsed_and_request_is_structured():
    p, msgs = provider(reply(GOOD))
    r = p.extract("text", "PROMPT", {"temperature": 0})
    assert r.valid and r.error is None
    assert r.record.address.city == "Kraków" and r.record.rooms == 3
    assert (r.input_tokens, r.output_tokens) == (1200, 150)
    call = msgs.calls[0]
    assert call["system"] == "PROMPT" and call["messages"][0]["content"] == "text"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["extra_body"] == {"temperature": 0}


def test_no_sampling_params_means_no_extra_body():
    p, msgs = provider(reply(GOOD))
    p.extract("t", "P", {"max_tokens": 100})
    assert "extra_body" not in msgs.calls[0] and msgs.calls[0]["max_tokens"] == 100


def test_truncated_json_is_invalid_but_does_not_raise():
    p, _ = provider(reply(GOOD[:80], stop_reason="max_tokens"))
    r = p.extract("t", "P")
    assert not r.valid and r.raw == GOOD[:80]
    assert r.error.startswith("ValidationError") and r.extra["stop_reason"] == "max_tokens"


def test_schema_constraint_violation_is_invalid():
    p, _ = provider(reply(GOOD.replace("57.36", "-5")))
    r = p.extract("t", "P")
    assert not r.valid and r.record is None


def test_api_timeout_becomes_failed_result():
    err = anthropic.APITimeoutError(request=httpx2.Request("POST", "https://api.anthropic.com"))
    p, _ = provider(err)
    r = p.extract("t", "P")
    assert not r.valid and r.error.startswith("APITimeoutError")


def test_response_without_text_block():
    p, _ = provider(reply(None, stop_reason="refusal"))
    r = p.extract("t", "P")
    assert not r.valid and "no text block" in r.error


def test_schema_and_prompt_are_loaded():
    p, _ = provider(reply(GOOD))
    assert "address" in p._schema["properties"]
    assert load_prompt("extract_v1").startswith("You extract")


def test_missing_api_key_fails_loudly_not_as_invalid_result():
    err = TypeError('"Could not resolve authentication method. Expected one of api_key..."')
    p, _ = provider(err)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        p.extract("t", "P")


def test_timeout_and_retries_are_passed_to_the_sdk_client(monkeypatch):
    seen = {}

    def fake_client(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(messages=FakeMessages(reply(GOOD)))

    monkeypatch.setattr(anthropic, "Anthropic", fake_client)
    AnthropicProvider(timeout=12.5, max_retries=5)
    assert seen == {"timeout": 12.5, "max_retries": 5}

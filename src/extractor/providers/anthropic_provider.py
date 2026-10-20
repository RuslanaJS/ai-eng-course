"""Anthropic provider: structured output (JSON schema), timeout and retry.

Haiku 4.5, not 5.5: Haiku 5.5 rejects non-default temperature/top_p (HTTP 400), and we
need T=0 and T=0.7 to compare sampling.
"""

import time
from typing import Any

import anthropic
from dotenv import load_dotenv
from pydantic import ValidationError

from extractor.providers.base import Result
from extractor.schema import OfferRecord

SAMPLING_KEYS = ("temperature", "top_p", "top_k")


class AnthropicProvider:
    """Extracts an OfferRecord with Claude via the official Anthropic SDK.

    Retry and timeout are built into the SDK, we do not implement them ourselves:
    - timeout: each HTTP attempt is cancelled after `timeout` seconds.
    - retry: the SDK re-sends the request up to `max_retries` times on connection errors,
      timeouts and HTTP 408, 409, 429 and 5xx, waiting longer after each failure
      (exponential backoff). Other errors (e.g. 400, 401) are not retried.
    - worst case: one text can take about timeout * (max_retries + 1) seconds plus pauses.
    If all attempts fail, extract() returns a Result with valid=False and the error text.
    """

    name = "anthropic"

    def __init__(
        self,
        model: str = "claude-haiku-4-5",
        timeout: float = 60.0,
        max_retries: int = 3,
        client: Any = None,
    ):
        load_dotenv()  # picks up ANTHROPIC_API_KEY from .env
        self.model = model
        # timeout and max_retries are built into the SDK: it retries 408/409/429/5xx and
        # connection errors with exponential backoff, we only set the limits.
        self.client = client or anthropic.Anthropic(timeout=timeout, max_retries=max_retries)
        # JSON schema from the Pydantic model, reduced to the subset the API accepts
        self._schema = anthropic.transform_schema(OfferRecord)

    def extract(self, text: str, prompt: str, params: dict[str, Any] | None = None) -> Result:
        params = dict(params or {})
        # SDK 1.x removed temperature/top_p/top_k from the create() signature, but Haiku 4.5
        # accepts them, so we send them in the request body via extra_body.
        sampling = {k: params[k] for k in SAMPLING_KEYS if k in params}
        extra = {"extra_body": sampling} if sampling else {}
        start = time.perf_counter()
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=params.get("max_tokens", 4096),
                system=prompt,
                messages=[{"role": "user", "content": text}],
                output_config={"format": {"type": "json_schema", "schema": self._schema}},
                **extra,
            )
        except TypeError as e:
            # The SDK raises TypeError when the key is missing. This is a setup error, not a model
            # reply, so we do not hide it in Result: otherwise all 30 texts would silently turn
            # "invalid".
            if "authentication" in str(e):
                raise RuntimeError(
                    "No Anthropic key: put ANTHROPIC_API_KEY into .env (see .env.example)"
                ) from e
            raise
        except anthropic.APIError as e:  # incl. timeout and exhausted retries
            return Result(
                model=self.model,
                params=params,
                valid=False,
                error=f"{type(e).__name__}: {e}",
                latency_s=time.perf_counter() - start,
            )
        latency = time.perf_counter() - start

        raw = next((b.text for b in response.content if b.type == "text"), None)
        result = Result(
            model=self.model,
            params=params,
            valid=False,
            raw=raw,
            latency_s=latency,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            extra={"stop_reason": response.stop_reason},
        )
        if raw is None:
            result.error = f"no text block, stop_reason={response.stop_reason}"
            return result
        try:
            result.record = OfferRecord.model_validate_json(raw)
            result.valid = True
        except ValidationError as e:  # truncated JSON (max_tokens) or constraint violation
            result.error = f"ValidationError: {e.error_count()} errors: {str(e)[:300]}"
        return result

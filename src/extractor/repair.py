"""Validation with one correction attempt.

Every answer is validated against the schema by the provider (Result.valid). If it is invalid
and the model did answer, we ask once more, showing the model its previous answer and the
validation error. If that second answer is also invalid the text is marked "failed".
"""

from typing import Any

from extractor.providers.base import Provider, Result

MAX_RAW_CHARS = 4000

REPAIR_TEMPLATE = """{text}

---
Your previous answer to this text was invalid.

Previous answer:
{raw}

Validation error:
{error}

Return a corrected JSON object that follows the schema. Fix only what the error describes."""


def _sum(a: int | None, b: int | None) -> int | None:
    return None if a is None and b is None else (a or 0) + (b or 0)


def extract_with_repair(
    provider: Provider,
    text: str,
    prompt: str,
    params: dict[str, Any] | None = None,
    repair: bool = True,
) -> Result:
    """Return a Result whose status is "ok" (valid at once), "fixed" or "failed"."""
    first = provider.extract(text, prompt, params)
    if first.valid:
        first.status = "ok"
        return first
    first.status = "failed"
    # No raw answer means an API failure (after the provider's own retries): nothing to correct.
    if not repair or first.raw is None:
        return first

    message = REPAIR_TEMPLATE.format(
        text=text, raw=first.raw[:MAX_RAW_CHARS], error=first.error or "unknown error"
    )
    second = provider.extract(message, prompt, params)
    second.first_error = first.error
    second.status = "fixed" if second.valid else "failed"
    # The cost of both calls counts: latency, tokens and attempts are summed.
    second.latency_s += first.latency_s
    second.input_tokens = _sum(first.input_tokens, second.input_tokens)
    second.output_tokens = _sum(first.output_tokens, second.output_tokens)
    second.attempts += first.attempts
    return second

"""Shared provider interface: Provider.extract(text, prompt, params) -> Result.

A Protocol in Python is like an interface in TypeScript: a class fits if it has the
required attributes and methods, no inheritance needed.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from extractor.schema import OfferRecord


@dataclass
class Result:
    """Result of one model call. Errors are recorded here, not raised."""

    model: str
    params: dict[str, Any]
    valid: bool  # parsed and passed schema validation
    record: OfferRecord | None = None
    raw: str | None = None  # raw model reply
    error: str | None = None
    latency_s: float = 0.0
    input_tokens: int | None = None
    output_tokens: int | None = None
    attempts: int = 1  # model calls made (provider retries and the correction call included)
    status: str = "ok"  # ok = valid at once, fixed = valid after one correction, failed
    first_error: str | None = None  # error of the first answer when a correction was tried
    extra: dict[str, Any] = field(default_factory=dict)


class Provider(Protocol):
    name: str
    model: str

    def extract(self, text: str, prompt: str, params: dict[str, Any] | None = None) -> Result: ...

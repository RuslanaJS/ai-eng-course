"""Ollama provider: a small local model behind the same interface as the Anthropic one.

Structured output: Ollama constrains decoding with a JSON schema (`format=`). The local model
does not see that schema on its own, so we also append it to the system prompt.
"""

import json
import time
from typing import Any

import httpx
import ollama
from dotenv import load_dotenv
from pydantic import ValidationError

from extractor.providers.base import Result
from extractor.schema import OfferRecord

SAMPLING_KEYS = ("temperature", "top_p", "top_k", "seed")
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Replace every {"$ref": "#/$defs/X"} with the definition itself and drop "$defs".

    Ollama's schema-to-grammar converter does not follow $ref: without this the model
    literally writes a "$ref" key into the answer.
    """
    defs = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                extra = {k: v for k, v in node.items() if k != "$ref"}
                return {**walk(defs[node["$ref"].split("/")[-1]]), **walk(extra)}
            return {k: walk(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(schema)


def drop_keys(schema: Any, keys: set[str]) -> Any:
    """Return a copy of the schema without the given keywords (at any depth)."""
    if isinstance(schema, dict):
        return {k: drop_keys(v, keys) for k, v in schema.items() if k not in keys}
    if isinstance(schema, list):
        return [drop_keys(item, keys) for item in schema]
    return schema


def _retryable(error: Exception) -> bool:
    if isinstance(error, ollama.ResponseError):
        return error.status_code in RETRYABLE_STATUS
    return isinstance(error, (ConnectionError, httpx.TimeoutException))


class OllamaProvider:
    """Extracts an OfferRecord with a local model through the Ollama server.

    Unlike the Anthropic SDK, the Ollama client has no retry, so it is implemented here:
    - timeout: passed to the HTTP client, one attempt is cancelled after `timeout` seconds.
    - retry: connection errors, timeouts and HTTP 408/429/5xx are retried up to `max_retries`
      times with a growing pause (0.5 s, 1 s, 2 s, ...). Other errors (e.g. 404 model not
      found) are not retried.
    If all attempts fail, extract() returns a Result with valid=False and the error text.

    num_ctx is the context window in tokens. Ollama's default (2048) is smaller than our
    prompts (about 4-5k tokens), and a too small window silently cuts the start of the prompt.
    """

    name = "ollama"

    def __init__(
        self,
        model: str = "qwen2.5:3b-instruct",
        timeout: float = 180.0,
        max_retries: int = 2,
        num_ctx: int = 8192,
        client: Any = None,
    ):
        load_dotenv()  # OLLAMA_HOST from .env is read by the ollama client itself
        self.model = model
        self.max_retries = max_retries
        self.num_ctx = num_ctx
        self.client = client or ollama.Client(timeout=timeout)
        # Full schema goes into the prompt. The copy sent as `format=` must not contain
        # "pattern": found by experiment, with a regex pattern Ollama 0.6 silently ignores
        # the whole schema and the model answers in free text (markdown fences, prose).
        # The pattern is still enforced afterwards by Pydantic validation.
        self._schema = inline_refs(OfferRecord.model_json_schema())
        self._format_schema = drop_keys(self._schema, {"pattern"})

    def extract(self, text: str, prompt: str, params: dict[str, Any] | None = None) -> Result:
        params = dict(params or {})
        options: dict[str, Any] = {"num_ctx": self.num_ctx}
        options.update({k: params[k] for k in SAMPLING_KEYS if k in params})
        if "max_tokens" in params:
            options["num_predict"] = params["max_tokens"]
        system = f"{prompt}\n\nReturn JSON that matches this schema:\n{json.dumps(self._schema)}"

        start = time.perf_counter()
        response, error, attempts = None, None, 0
        for attempt in range(self.max_retries + 1):
            attempts = attempt + 1
            try:
                response = self.client.chat(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": text},
                    ],
                    format=self._format_schema,
                    options=options,
                    stream=False,
                )
                break
            except (ollama.ResponseError, ConnectionError, httpx.HTTPError) as e:
                error = e
                if not _retryable(e) or attempt == self.max_retries:
                    break
                time.sleep(0.5 * 2**attempt)
        latency = time.perf_counter() - start

        if response is None:
            return Result(
                model=self.model,
                params=params,
                valid=False,
                error=f"{type(error).__name__}: {error}",
                latency_s=latency,
                attempts=attempts,
            )

        raw = response.message.content
        prompt_tokens, output_tokens = response.prompt_eval_count, response.eval_count
        result = Result(
            model=self.model,
            params=params,
            valid=False,
            raw=raw,
            latency_s=latency,
            input_tokens=prompt_tokens,
            output_tokens=output_tokens,
            attempts=attempts,
            extra={
                "done_reason": response.done_reason,
                # True means the prompt (and answer) may not have fitted into the window
                "context_full": (prompt_tokens or 0) + (output_tokens or 0) >= self.num_ctx,
            },
        )
        try:
            result.record = OfferRecord.model_validate_json(raw)
            result.valid = True
        except ValidationError as e:  # truncated JSON (num_predict) or constraint violation
            result.error = f"ValidationError: {e.error_count()} errors: {str(e)[:300]}"
        return result

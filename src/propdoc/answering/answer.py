"""One cited answer: search, context within a budget, the model, and a check of the citations it gives."""

import re
import time

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel

from ..extraction.prompts import load_prompt
from ..retrieval.search import DEFAULT_FILTER
from .context import DEFAULT_BUDGET, build_context, format_context

PROMPT = "rag_answer_v1"
MODEL = "claude-haiku-4-5"  # 5.5 rejects a non-default temperature, and we run at 0
MAX_TOKENS = 1024
MARK = re.compile(r"\[(\d+)\]")


class Answer(BaseModel):
    found: bool
    answer: str
    sources: list[int]


def check_citations(answer, numbers, n_sources):
    """Source numbers that exist in the context, and the ones that do not (marks in the text or in the list)."""
    given = set(numbers) | {int(m) for m in MARK.findall(answer)}
    valid = sorted(n for n in given if 1 <= n <= n_sources)
    return valid, sorted(given - set(valid))


def citation(number, chunk):
    return {"n": number, "chunk_id": chunk["chunk_id"], "doc_id": chunk["doc_id"], "title": chunk["title"],
            "section": chunk["section"], "part": chunk["label"], "page": chunk["page_start"],
            "version": chunk["version"], "status": chunk["status"], "url": chunk["source_url"]}


class Answerer:
    def __init__(self, search, model=MODEL, prompt=PROMPT, budget=DEFAULT_BUDGET, client=None):
        load_dotenv()
        self.search, self.model, self.budget = search, model, budget
        self.prompt_name, self.prompt = prompt, load_prompt(prompt)
        self.client = client or anthropic.Anthropic(timeout=60.0, max_retries=3)
        self.schema = anthropic.transform_schema(Answer)

    def ask(self, question, history=False):
        """history=True also searches superseded versions of the documents."""
        filters = None if history else dict(DEFAULT_FILTER)
        retrieved = self.search(question, filters)
        used, dropped, tokens = build_context(retrieved, self.budget)
        result = {"question": question, "model": self.model, "prompt": self.prompt_name,
                  "retrieved": len(retrieved), "used": len(used), "dropped": dropped,
                  "context_tokens": tokens, "chunk_ids": [c["chunk_id"] for c in used]}
        message = f"<sources>\n{format_context(used)}\n</sources>\n\nQuestion: {question}"
        started = time.perf_counter()
        try:
            response = self.client.messages.create(
                model=self.model, max_tokens=MAX_TOKENS, system=self.prompt,
                messages=[{"role": "user", "content": message}],
                output_config={"format": {"type": "json_schema", "schema": self.schema}},
                extra_body={"temperature": 0})
        except anthropic.APIError as e:
            return {**result, "status": "error", "error": f"{type(e).__name__}: {e}", "found": False,
                    "answer": "", "citations": [], "invalid": []}
        result["latency_s"] = time.perf_counter() - started
        result["input_tokens"] = response.usage.input_tokens
        result["output_tokens"] = response.usage.output_tokens
        raw = next((b.text for b in response.content if b.type == "text"), "")
        try:
            parsed = Answer.model_validate_json(raw)
        except ValueError as e:
            return {**result, "status": "invalid_json", "error": str(e)[:200], "found": False,
                    "answer": raw, "citations": [], "invalid": []}
        valid, invalid = check_citations(parsed.answer, parsed.sources, len(used))
        status = "ok"
        if parsed.found and (invalid or not valid):
            status = "bad_citation"  # claims an answer without a source, or cites a source that was not given
        return {**result, "status": status, "found": parsed.found, "answer": parsed.answer,
                "citations": [citation(n, used[n - 1]) for n in valid], "invalid": invalid}

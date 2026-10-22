.PHONY: setup run run-all smoke metrics test lint clean clean-results

# Like `npm install`: creates .venv and installs dependencies from pyproject.toml
setup:
	uv sync

# Full pipeline for the recommended configuration: extract all texts with Haiku (prompt v2, T=0),
# validate, save to results/, print metrics. About 2 minutes and 0.2 USD (needs a key in .env).
run: setup
	uv run python -m extractor.run
	uv run python -m extractor.metrics

# Every model x prompt version x sampling, skipping configurations that already have results.
# The local Ollama runs take about 15-20 minutes each.
run-all: setup
	uv run python -m extractor.matrix
	uv run python -m extractor.metrics --set dev
	uv run python -m extractor.metrics --set test

# One text through Anthropic (needs a key in .env): make smoke ID=005
smoke: setup
	uv run python -m extractor.smoke $(ID)

test: setup
	uv run pytest

lint: setup
	uv run ruff check src tests

# Caches only: results/ is a committed snapshot, remove it with `make clean-results`
clean:
	rm -rf .pytest_cache .ruff_cache

clean-results:
	rm -f results/*.jsonl

# Metrics for all full runs in results/ vs the golden set
metrics: setup
	uv run python -m extractor.metrics

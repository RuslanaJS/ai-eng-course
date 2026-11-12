.PHONY: setup run run-all smoke metrics check-labels test lint clean clean-results fetch ingest check-ingest embed eval-retrieval search ask eval-answers

# Like `npm install`: creates .venv and installs dependencies from pyproject.toml
setup:
	uv sync

# Full pipeline for the recommended configuration: extract all texts with Haiku (prompt v2, T=0),
# validate, save to results/, print metrics. About 2 minutes and 0.2 USD (needs a key in .env).
run: setup
	uv run python -m propdoc.extraction.run
	uv run python -m propdoc.extraction.metrics

# Every model x prompt version x sampling, skipping configurations that already have results.
# The local Ollama runs take about 15-20 minutes each.
run-all: setup
	uv run python -m propdoc.extraction.matrix
	uv run python -m propdoc.extraction.metrics --set dev
	uv run python -m propdoc.extraction.metrics --set test

# One text through Anthropic (needs a key in .env): make smoke ID=005
smoke: setup
	uv run python -m propdoc.extraction.smoke $(ID)

# Every labeled value must be findable in its source text
check-labels: setup
	uv run python -m propdoc.extraction.check_labels

# HW2: download the open-licence corpus documents and record their provenance (data/fetch_log.jsonl).
# Preview first: make fetch ARGS=--dry-run
fetch: setup
	uv run python scripts/fetch_corpus.py $(ARGS)

# HW2: turn the downloaded documents into chunks (data/processed/chunks.jsonl), about 3 minutes
ingest: setup
	uv run python -m propdoc.ingest.build $(ARGS)

# Rules the real chunks must satisfy (headers, noise, sizes, versions); run after make ingest
check-ingest: setup
	uv run python -m propdoc.ingest.check

# HW2 step 2: embed all chunks with the local model and with Gemini (cached by text hash, a re-run costs nothing)
embed: setup
	uv run python -m propdoc.retrieval.embed $(ARGS)

# recall@5 and MRR of every search configuration on evals/retrieval_questions.json
eval-retrieval: setup
	uv run python -m propdoc.evaluation.retrieval $(ARGS)

# One query through a search configuration: make search Q="Czy cudzoziemiec potrzebuje zezwolenia?"
search: setup
	uv run python -m propdoc.retrieval.search "$(Q)" $(ARGS)

# A cited answer: make ask Q="Czy cudzoziemiec potrzebuje zezwolenia na zakup mieszkania?" (needs ANTHROPIC_API_KEY)
ask: setup
	uv run python -m propdoc.answering.ask "$(Q)" $(ARGS)

# Every test question through the bot, three times, scored without a model (about 0.3 USD)
eval-answers: setup
	uv run python -m propdoc.evaluation.answers --repeat 3 $(ARGS)

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
	uv run python -m propdoc.extraction.metrics

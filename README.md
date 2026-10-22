# PropDoc: Structured Extraction (HW1)

Extracts structured data about one apartment from "dirty" Polish and English real-estate texts
(web pages, PDF excerpts). Compares Anthropic Haiku 4.5 with the local `qwen2.5:3b-instruct`
(Ollama) on prompt versions v1 to v3 and two sampling configurations.

## Run

```bash
cp .env.example .env     # add ANTHROPIC_API_KEY
ollama pull qwen2.5:3b-instruct   # only for the local model
make run                 # Haiku, prompt v2, T=0 on all texts, then the metrics table (~2 min, ~0.2 USD)
make run-all             # every model x prompt x sampling, skips results that already exist
make metrics             # metrics table from results/ (dev set; use --set test for the test set)
make smoke ID=005        # one text through the model
make test                # unit tests (no network)
```

The local Ollama runs take about 15-20 minutes each, so `make run-all` takes over an hour the first time.

## How it works

```
data/texts/NNN.txt  --prompt (prompts/extract_vN.md)-->  model  -->  JSON
                                                                      |
   schema.py (OfferRecord) --JSON schema--> constrains / informs the model
                              --Pydantic---> validates the answer
   invalid answer -> one correction attempt (repair.py) -> status ok / fixed / failed
   results/<model>__<prompt>__<sampling>.jsonl  -->  metrics.py vs data/golden*/
```

- `src/extractor/schema.py`: the record (single source of truth for fields, types, enums).
- `src/extractor/providers/`: one interface (`Provider.extract`), two implementations
  (Anthropic with structured output, Ollama with a JSON-schema `format`); timeout and retry in both.
- `src/extractor/run.py`, `matrix.py`: runners. `repair.py`: validation with one correction attempt.
- `src/extractor/metrics.py`: field accuracy, valid answers, hallucinations, latency p50/p95, cost per 1000 documents.
- `prompts/`: prompt versions and `CHANGELOG.md` (what changed and why, with measured effects).
- `configs/`: models (price, timeout, retries) and sampling.
- `data/`: `texts/` (33 texts), `golden/` (10 labeled texts, development set), `golden_test/`
  (8 labeled texts, held-out test set), `sources.csv` (URL and date of every text).
- `results/`: committed snapshot of the 12 runs behind `REPORT.md` (JSON Lines, one row per text: model, prompt version, sampling, status, latency, tokens, raw and parsed answer). `make run-all` skips configurations that already have a file; run `uv run python -m extractor.matrix --force` to redo them (about 0.2 USD per Haiku run, 15-20 minutes per Ollama run).

## Working with Claude Code

`CLAUDE.md` holds the project rules and `.claude/skills/` three task skills (`run-experiment`,
`prompt-iteration`, `release-check`); both are committed so every clone has them.
`make check-labels` verifies that every labeled value can be found in its source text.

## Results so far

Accuracy over 12 schema fields, T=0, details and caveats in `prompts/CHANGELOG.md`:

| Model | Prompt | Valid answers | Dev accuracy | Test accuracy | Hallucinations (test) | p50 latency | $ / 1000 docs |
|---|---|---|---|---|---|---|---|
| Haiku 4.5 | v1 | 100% | 92.5% | 97.9% | 0/38 | 3.0 s | 5.05 |
| Haiku 4.5 | v2 | 100% | 100% | 100% | 0/38 | 3.1 s | 5.44 |
| qwen2.5:3b | v1 | 67% | 64.2% | 53.1% | 3/38 | 33.8 s | 0 |
| qwen2.5:3b | v2 | 100% | 95.8% | 93.8% | 3/38 | 21.2 s | 0 |

Limits: the labeled sets are small (10 and 8 texts) and every configuration was run once, so
differences of one or two fields can be noise. The apartment's own price is hidden on the source
site, so `price_per_m2_pln` is the price range of the whole development. The Ollama server was updated
from 0.6.1 to 0.40.5 between the first qwen runs (v1) and the later ones. Almost all texts are
Polish; the only English ones are market texts without an apartment.

The full table (all 12 configurations, dev and test side by side), the analysis of five errors and the
final choice for production are in [`REPORT.md`](REPORT.md).

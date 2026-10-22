---
name: run-experiment
description: Run, rerun or compare extraction experiments (model x prompt version x sampling) in this repo and read the metrics. Use whenever the user asks to run the pipeline, make run, rerun a configuration, test a new model or prompt, regenerate results, refresh the metrics or report table, or asks why a run looks different, even if they do not say "experiment".
---

# Run an experiment

One run = one model, one prompt version, one sampling config over the texts in `data/texts/`.
The result is one file `results/<model>__<prompt>__<sampling>.jsonl` (one row per text with model, prompt version, sampling, status, latency, tokens, raw and parsed answer). Metrics are computed against `data/golden` (dev) and `data/golden_test` (test).

## Before running

1. **Credentials.** For `anthropic_*` models check that `.env` has `ANTHROPIC_API_KEY` (check the variable exists, never print it). Without it the provider raises a clear error.
2. **Ollama.** For `ollama_*` models check `curl -s localhost:11434/api/version`. If the version differs from the one in `REPORT.md` limitations, mention it, results across server versions are not strictly comparable.
3. **Cost and time.** A Haiku run is about 0.2 USD and 2 minutes. An Ollama run is 15-20 minutes, so start it in the background and wait for the notification instead of holding a long foreground command.

## Commands

- `make run` default configuration (Haiku, prompt v2, T=0) plus the metrics table.
- `uv run python -m extractor.run --model <key> --prompt <extract_vN> --sampling <t0|t07>`: keys are in `configs/models.yaml` and `configs/sampling.yaml`.
- `--ids 031,032` runs only those texts and merges them into the normal file. `--limit N` writes a separate `__firstN` file, so a quick check never overwrites a full run.
- `make run-all` or `uv run python -m extractor.matrix [--models ... --prompts ... --samplings ... --force]` runs the whole matrix and skips configurations that already have results.

## After running

1. `make metrics` (dev), `uv run python -m extractor.metrics --set test`, and `--report` for the combined table used in `REPORT.md`.
2. Read the `WARNING` lines: they mean a labeled text has no result in that file (an interrupted or partial run), so the numbers are not comparable.
3. `results/` is a committed snapshot. If you rerun a configuration, the file changes: commit the new results separately and update the numbers in `README.md` and `REPORT.md`, otherwise the report no longer matches the data.

## Traps already hit in this project

- In zsh, a loop over a string such as `for cfg in "a t0"; do set -- $cfg` does not split words: nothing ran and the table looked fine. Write explicit commands.
- Ollama silently ignores a JSON schema that contains a regex `pattern` and cannot follow `$ref`; the provider already strips and inlines them, keep it that way.
- Ollama's default context (2048 tokens) cuts our 4-5k-token prompts; `num_ctx` is set to 8192 in `configs/models.yaml`.
- The first Anthropic structured-output call is slow (schema compilation, about 20 s); `run.py` makes an unsaved warm-up call so latency percentiles are not distorted.
- Haiku 5.5 and Sonnet 5.5 reject non-default temperature; use Haiku 4.5 when comparing sampling.

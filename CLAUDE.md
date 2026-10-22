# PropDoc HW1: structured extraction

Extracts one apartment record from dirty Polish real-estate texts and compares Anthropic Haiku 4.5
with a local qwen2.5:3b (Ollama). Part of the AI Engineering course project, see `PROJECT_PLAN.md`
(the plan is mirrored from a planning document) and `README.md` / `REPORT.md`.

## Commands

- `make test` unit tests (no network), `make lint` ruff.
- `make run` Haiku, prompt v2, T=0 on all texts, then metrics (about 0.2 USD, needs `ANTHROPIC_API_KEY` in `.env`).
- `make run-all` every model x prompt x sampling, skips configurations that already have results.
- `make metrics` dev-set table, `uv run python -m extractor.metrics --set test|--report`.
- `make check-labels` every labeled value must be findable in its source text.

## Rules of the repo

- **Language.** Everything in the repo (code, comments, docstrings, error strings, prompts, changelog, docs) is English. Chat with the user is Ukrainian; the gitignored `WORKING_NOTES.md` may be Ukrainian.
- **A record is one apartment.** Area, rooms and floor are single numbers; price per m2 is a `{min, max}` range of the whole development (the apartment's own price is hidden on the source site); there is no total price and no building-level field. `floor` is stored as written in the source (`Parter` = 0, `1 piętro` = 1), nothing is converted.
- **Do not invent.** A field that the text does not state is `null` (`not_stated` for enums). Never derive a price by multiplication.
- **Two labeled sets.** `data/golden` (dev) is used to find errors and write prompt rules; `data/golden_test` (held-out) is only for measuring. Do not tune on the test set; if you did look at it, say so in `prompts/CHANGELOG.md`.
- **Prompts are append-only.** A new version is a new file `prompts/extract_vN.md`; results and the changelog refer to version names.
- **Models.** Haiku 4.5 (`claude-haiku-4-5`), not 5.5: 5.5 rejects non-default temperature. The SDK has no `temperature` argument, it goes through `extra_body`.
- **Never commit** `.env`, `.claude/settings.local.json` or `WORKING_NOTES.md`. `results/*.jsonl` is a committed snapshot behind `REPORT.md`.
- **Git.** Work in a branch and merge it into `main` fast-forward only (`git merge --ff-only`, no merge commits); do not push short-lived branches to the public remote. Keep commits logical. Moving a tag or force-pushing needs the user's explicit OK and a backup tag first.

## Skills (`.claude/skills/`)

- `run-experiment` how to run, rerun and compare configurations safely.
- `prompt-iteration` how to improve a prompt without overfitting to the test set.
- `release-check` what to verify before tagging, submitting or posting the link.

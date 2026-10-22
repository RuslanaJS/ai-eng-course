---
name: prompt-iteration
description: Improve or create an extraction prompt (prompts/extract_vN.md) in this repo without overfitting. Use whenever the user wants to fix extraction errors, raise accuracy, write a new prompt version (v4 and later), change a prompt rule, add examples to a prompt, or interpret why a prompt change helped or hurt, even if they only say "the model gets X wrong".
---

# Iterate on a prompt

The goal is a prompt whose gain holds on texts it was not written for. The labeled sets are small (10 dev, 8 test), so discipline matters more than the number of iterations.

## Rules and why

- **New version = new file.** Never edit an existing `extract_vN.md`: results, the changelog and the report refer to the version name, an edit would silently change what the old numbers mean.
- **Find errors on dev only.** Use `data/golden` plus the unlabeled texts, never `data/golden_test` (texts 009, 014, 021, 028, 029 and the negative controls 031-033). The test set exists to show whether the fix generalizes; once it guided a rule it can no longer show that. If you did look at test outputs, write it in the changelog (column "Where it was seen") and treat gains on those points as optimistic.
- **Every rule answers an observed error.** For each rule note the error, the model, how many texts. A rule without an observed error adds length and risk, skip it.
- **No concrete example values taken from real texts.** qwen copied `ul. Srebrna 5`, `Wola`, `Warszawa` and area `57.36` from the prompt into texts that had no apartment. Describe the format instead (`YYYY-QN`) or use obviously fake placeholders, and re-check negative texts after adding any example.
- **Do not add "always fill" pressure without a counterweight.** Weak models then write something on texts that have no apartment; check the hallucination column.
- **Small samples.** A difference of one or two fields is noise. Say what was measured and what cannot be concluded.

## Procedure

1. Run the current version (see the `run-experiment` skill) and list wrong fields per model on dev: `uv run python -m extractor.metrics --set dev` and compare each result file with the labels. Group errors by cause.
2. Write the new file with only the rules the errors justify.
3. Run both models, both samplings. Check dev and test, valid answers, hallucinations on the negative texts.
4. Add a section to `prompts/CHANGELOG.md`: rules with the error each fixes and counts, measured effect (before/after table for each model), the decision (adopt, keep as experiment, drop) and caveats.
5. Commit the prompt, the changelog and the new results together in one branch.

Stop when a further iteration would be fitted to the same few texts; record the decision instead of chasing the last point.

---
name: release-check
description: Checklist before tagging, submitting the homework, posting the repo link, merging to main for a deadline, or restructuring git history in this repo. Use whenever the user says release, tag, submit, "check from scratch", fresh clone, squash commits, force push, make the repo public, or asks whether the repo is ready to share.
---

# Release check

A reviewer clones the repo with none of your local files (`.env`, `results`, `.venv`, notes). This check reproduces that.

## 1. Local state

- `git status` is clean, `make lint` and `make test` pass, `make check-labels` reports 0 mismatches.
- `README.md`, `REPORT_HW1.md` and `REPORT_HW2.md` numbers match their data: HW1 equals `uv run python -m propdoc.extraction.metrics --report` for the committed `results/` snapshot, HW2 equals the files in `evals/runs/`.
- No secret in any commit: `git grep -n -E "sk-ant-[A-Za-z0-9_-]{20,}" $(git rev-list --all)` returns nothing (the `sk-ant-...` placeholder in `.env.example` is fine).

## 2. Fresh clone

1. Clone into a temporary folder (the session scratchpad), run `make test`.
2. For `make run` (HW2, about 0.1 USD, 3 minutes), copy `.env` into the clone only with the user's agreement, run it, then delete the whole temporary folder so the key copy does not stay around.
3. Expect `make run` to give the open-corpus metrics close to `evals/baseline_open.json` (`make eval-gate` passes).

## 3. Git actions that need explicit OK

- **Moving a tag or force-pushing** changes published history. Ask first, create a local backup tag first, and use `--force-with-lease=<branch>:<expected remote sha>` (take the sha from `git ls-remote`, not from your local branch, a wrong lease is rejected).
- **Squashing history.** Rebuild logical commits from the final tree on an orphan branch (`git checkout --orphan`, `git rm -r --cached .`, then `git add` per group), verify `git diff <old> <new>` is empty and run the tests at every commit using temporary worktrees.
- **Branches on the public remote** stay visible to everyone: merge locally and push `main`; do not push scratch or backup branches to a public repo (an old full-history branch had to be deleted for this reason).
- Check repository visibility before posting a link: `curl -s https://api.github.com/repos/<owner>/<repo>` shows `"private"`.

## 4. What to tell the user

State what was checked, what failed, and what was not checked. A tag should point at the commit the user posts.

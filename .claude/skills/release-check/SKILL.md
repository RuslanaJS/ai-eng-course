---
name: release-check
description: Checklist before tagging, submitting the homework, posting the repo link, merging to main for a deadline, or restructuring git history in this repo. Use whenever the user says release, tag, submit, "check from scratch", fresh clone, squash commits, force push, make the repo public, or asks whether the repo is ready to share.
---

# Release check

A reviewer clones the repo with none of your local files (`.env`, `results`, `.venv`, notes). This check reproduces that.

## 1. Local state

- `git status` is clean, `make lint` and `make test` pass, `make check-labels` reports 0 mismatches.
- `REPORT.md` and `README.md` numbers equal `uv run python -m extractor.metrics --report` for the committed `results/` snapshot.
- No secret in any commit: `git grep -n -E "sk-ant-[A-Za-z0-9_-]{20,}" $(git rev-list --all)` returns nothing (the `sk-ant-...` placeholder in `.env.example` is fine).

## 2. Fresh clone

1. Clone into a temporary folder (the session scratchpad), run `make test`.
2. For `make run`, copy `.env` into the clone only with the user's agreement, run it (about 0.2 USD, 2 minutes), then delete the whole temporary folder so the key copy does not stay around.
3. Expect 33/33 valid answers and the same metrics as in the report.

## 3. Git actions that need explicit OK

- **Moving a tag or force-pushing** changes published history. Ask first, create a local backup tag first, and use `--force-with-lease=<branch>:<expected remote sha>` (take the sha from `git ls-remote`, not from your local branch, a wrong lease is rejected).
- **Squashing history.** Rebuild logical commits from the final tree on an orphan branch (`git checkout --orphan`, `git rm -r --cached .`, then `git add` per group), verify `git diff <old> <new>` is empty and run the tests at every commit using temporary worktrees.
- **Branches on the public remote** stay visible to everyone: merge locally and push `main`; do not push scratch or backup branches to a public repo (an old full-history branch had to be deleted for this reason).
- Check repository visibility before posting a link: `curl -s https://api.github.com/repos/<owner>/<repo>` shows `"private"`.

## 4. What to tell the user

State what was checked, what failed, and what was not checked. A tag should point at the commit the user posts.

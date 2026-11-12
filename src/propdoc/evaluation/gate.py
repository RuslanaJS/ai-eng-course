"""Checks that run in CI: the test set itself (lint) and a new run against the baseline (gate).

Lint finds mechanical errors before any number is trusted: duplicate ids, unknown documents, quotes that
are not in the chunks of their documents, answerable questions without key facts. Documents that are only
on the owner's disk (reports) are skipped when their chunks are missing, as in CI.

Gate (lesson 9): a metric that falls more than TOLERANCE below the baseline, false abstain that rises more
than TOLERANCE, or a question that passed every time in the baseline and now fails, gives exit code 1.
"""

import csv
from collections import Counter

from ..ingest.fetch import ROOT
from .retrieval import norm

TOLERANCE = 0.05  # about one question of twenty: noise of one case passes, a fall of two does not
HIGHER_IS_BETTER = ("pass@1", "facts", "recall@5", "in_context", "cited", "abstain")
LOWER_IS_BETTER = ("false_abstain",)
MANIFEST = ROOT / "data" / "manifest.csv"


def lint(questions, chunks, manifest=MANIFEST):
    """Problems of the test set, one string each; empty means it is clean. Also returns the skipped quotes."""
    known = {row["id"] for row in csv.DictReader(manifest.open(encoding="utf-8"))}
    texts = {}
    for c in chunks:
        texts.setdefault(c["doc_id"], []).append(norm(c["text"]))
    problems, skipped = [], 0
    for qid, n in Counter(q["id"] for q in questions).items():
        if n > 1:
            problems.append(f"{qid}: duplicate id")
    for q in questions:
        if q["answerable"] and not (q["docs"] and q["quotes"] and q["must"] and all(q["must"])):
            problems.append(f"{q['id']}: answerable but without documents, quotes or key facts")
        if not q["answerable"] and (q["docs"] or q["quotes"]):
            problems.append(f"{q['id']}: no answer expected but documents or quotes given")
        for doc in q["docs"]:
            if doc not in known:
                problems.append(f"{q['id']}: unknown document {doc}")
        for quote in q["quotes"]:
            docs = [d for d in q["docs"] if d in texts]
            if not docs:
                skipped += 1  # a local-only document: its chunks are not in this checkout
            elif not any(norm(quote) in t for d in docs for t in texts[d]):
                problems.append(f"{q['id']}: quote not found in {', '.join(docs)}: {quote[:60]}")
    return problems, skipped


def open_subset(questions, chunks):
    """Questions that the committed corpus can answer, plus all questions without an answer."""
    present = {c["doc_id"] for c in chunks}
    return [q for q in questions if not q["answerable"] or set(q["docs"]) <= present]


def case_rates(scores):
    by_case = {}
    for s in scores:
        by_case.setdefault(s["id"], []).append(s["pass"])
    return {case: sum(p) / len(p) for case, p in by_case.items()}


def gate(result, rates, baseline, tolerance=TOLERANCE):
    """Violations of a run against the baseline; empty means the run may go on."""
    violations = []
    for key in HIGHER_IS_BETTER:
        if baseline.get(key) is not None and result.get(key) is not None \
                and result[key] < baseline[key] - tolerance:
            violations.append(f"{key}: {result[key]} < baseline {baseline[key]}")
    for key in LOWER_IS_BETTER:
        if baseline.get(key) is not None and result.get(key) is not None \
                and result[key] > baseline[key] + tolerance:
            violations.append(f"{key}: {result[key]} > baseline {baseline[key]}")
    for case, rate in sorted(baseline.get("case_pass", {}).items()):
        if rate == 1 and rates.get(case, 1) < 1:
            violations.append(f"regression: {case}")
    return violations

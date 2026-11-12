"""Deterministic scores of one answer and the metrics of a whole run. No model calls.

Per answer (lesson 9): facts (every `must` group has a variant in the answer), recall@5 (a relevant chunk
was retrieved), in_context (it reached the prompt), cited (the answer cites it), abstain on questions
without an answer and false abstain on questions with one. A chunk is relevant when it comes from one of
the question's documents and contains one of its quotes, the same rule as the retrieval eval.
"""

from statistics import mean, quantiles

from ..answering.answer import cost_usd
from .retrieval import is_relevant, norm


def has_facts(answer, must):
    text = norm(answer)
    return all(any(norm(variant) in text for variant in group) for group in must)


def score(row, question, chunks):
    """Scores of one answer; `chunks` maps chunk_id to chunk."""
    ok = row["status"] == "ok"
    found = row["found"]
    s = {"id": question["id"], "repeat": row.get("repeat", 0), "answerable": question["answerable"],
         "status": row["status"], "found": found}
    if not question["answerable"]:
        s["abstained"] = not found
        s["pass"] = ok and not found
        return s

    def relevant(ids):
        return any(is_relevant(chunks[i], question) for i in ids if i in chunks)

    s["facts"] = found and has_facts(row["answer"], question["must"])
    s["recall"] = relevant(row["retrieved_ids"])
    s["in_context"] = relevant(row["chunk_ids"])
    s["cited"] = relevant(c["chunk_id"] for c in row["citations"])
    s["abstained"] = not found
    s["pass"] = ok and s["facts"] and s["cited"]
    return s


def share(values):
    values = list(values)
    return round(sum(values) / len(values), 3) if values else None


def metrics(rows, scores):
    """Run metrics: pass@1, cases that passed every repeat, flaky cases, RAG stages, cost and latency."""
    by_case = {}
    for s in scores:
        by_case.setdefault(s["id"], []).append(s["pass"])
    rates = {case: sum(p) / len(p) for case, p in by_case.items()}
    answerable = [s for s in scores if s["answerable"]]
    no_answer = [s for s in scores if not s["answerable"]]
    latencies = [r["latency_s"] for r in rows if r.get("latency_s")]
    return {
        "questions": len(by_case),
        "repeats": max(len(p) for p in by_case.values()),
        "pass@1": round(mean(rates.values()), 3),
        "pass_every_time": share(rate == 1 for rate in rates.values()),
        "flaky": sorted(case for case, rate in rates.items() if 0 < rate < 1),
        "failed_every_time": sorted(case for case, rate in rates.items() if rate == 0),
        "facts": share(s["facts"] for s in answerable),
        "recall@5": share(s["recall"] for s in answerable),
        "in_context": share(s["in_context"] for s in answerable),
        "cited": share(s["cited"] for s in answerable),
        "abstain": share(s["abstained"] for s in no_answer),
        "false_abstain": share(s["abstained"] for s in answerable),
        "invalid": sum(r["status"] != "ok" for r in rows),
        "latency_p50_s": round(quantiles(latencies, n=100)[49], 2) if len(latencies) > 1 else None,
        "latency_p95_s": round(quantiles(latencies, n=100)[94], 2) if len(latencies) > 1 else None,
        "cost_per_1000_questions_usd": round(1000 * mean(cost_usd(r) for r in rows), 2),
    }

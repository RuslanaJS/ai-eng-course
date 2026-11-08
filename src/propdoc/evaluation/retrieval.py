"""Retrieval evaluation: recall@5 and MRR of every search configuration on the questions.

python -m propdoc.evaluation.retrieval [--embedders gemini bge-m3] [--chunks structural|fixed]
A retrieved chunk is relevant when it comes from one of the question's documents and contains one of its
quotes (several passages can answer one question), so the labels survive a change of chunking. Superseded
versions are filtered out unless the question asks for an old version (history), as the product would do;
a question can add its own filters, for example a period.
"""

import argparse
import json
import re
import time
import unicodedata

from ..ingest.fetch import ROOT
from ..retrieval.search import K, make_configs
from ..retrieval.store import load_chunks

QUESTIONS = ROOT / "evals" / "retrieval_questions.json"
RUNS = ROOT / "evals" / "runs"
DEFAULT_FILTER = {"status": ["current", "upcoming"]}


def norm(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).lower()


def is_relevant(chunk, question):
    text = norm(chunk["text"])
    return chunk["doc_id"] in question["docs"] and any(norm(quote) in text for quote in question["quotes"])


def question_filters(question):
    filters = None if question["history"] else dict(DEFAULT_FILTER)
    if question.get("filters"):
        filters = {**(filters or {}), **question["filters"]}
    return filters


def evaluate(search, questions, k=K):
    """recall@k: the share of questions with a relevant chunk in the top k; MRR: mean of 1 / rank."""
    ranks, times = {}, []
    for q in questions:
        filters = question_filters(q)
        started = time.perf_counter()
        results = search(q["question"], filters)[:k]
        times.append((time.perf_counter() - started) * 1000)
        ranks[q["id"]] = next((i for i, c in enumerate(results, 1) if is_relevant(c, q)), None)
    found = [r for r in ranks.values() if r]
    return {"recall": len(found) / len(questions), "mrr": sum(1 / r for r in found) / len(questions),
            "ms": sum(times) / len(times), "ranks": ranks,
            "misses": [i for i, r in ranks.items() if not r]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embedders", nargs="+", default=["gemini", "bge-m3"])
    parser.add_argument("--chunks", default="structural")
    parser.add_argument("--no-rerank", action="store_true")
    args = parser.parse_args(argv)
    questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    chunks = load_chunks(args.chunks)
    configs = make_configs(chunks, args.embedders, rerank=not args.no_rerank)
    results = {name: evaluate(search, questions) for name, search in configs.items()}
    print(f"{len(questions)} questions, {len(chunks)} chunks ({args.chunks}), recall@{K} and MRR\n")
    print("| configuration | recall@5 | MRR | ms per query | missed |\n|---|---|---|---|---|")
    for name, r in results.items():
        print(f"| {name} | {r['recall']:.2f} | {r['mrr']:.2f} | {r['ms']:.0f} | {', '.join(r['misses']) or '-'} |")
    RUNS.mkdir(parents=True, exist_ok=True)
    out = RUNS / f"retrieval_{args.chunks}.json"
    out.write_text(json.dumps({"chunks": args.chunks, "n_chunks": len(chunks), "k": K,
                               "results": results}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

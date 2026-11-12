"""Answer evaluation: every test question through the RAG bot, scored without a model.

python -m propdoc.evaluation.answers [--repeat 3] [--prompt rag_answer_v1] [--ids q01 q05]
python -m propdoc.evaluation.answers --score evals/runs/answers_rag_answer_v1.jsonl   # score a saved run

Writes every answer to evals/runs/answers_<prompt>.jsonl and the metrics to answers_<prompt>_metrics.json.
"""

import argparse
import json
from pathlib import Path

from ..answering.answer import CONFIG, MODEL, PROMPT, Answerer
from ..ingest.fetch import ROOT
from ..retrieval.search import make_configs
from ..retrieval.store import load_chunks
from .scorers import metrics, score

QUESTIONS = ROOT / "evals" / "questions.json"
RUNS = ROOT / "evals" / "runs"


def load_questions(ids=None):
    questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    return [q for q in questions if not ids or q["id"] in ids]


def run(answerer, questions, repeat):
    rows = []
    for r in range(repeat):
        for q in questions:
            row = answerer.ask(q["question"], q["history"], q.get("filters"))
            rows.append({"id": q["id"], "repeat": r, **row})
            print(f"  {q['id']} run {r + 1}: {row['status']}, found={row['found']}", flush=True)
    return rows


def report(rows, questions, chunks):
    by_id = {q["id"]: q for q in questions}
    scores = [score(row, by_id[row["id"]], chunks) for row in rows]
    return metrics(rows, scores), scores


def show(result, scores):
    for key, value in result.items():
        print(f"{key:28} {value}")
    print("\nfailed answers:")
    for s in scores:
        if not s["pass"]:
            why = [k for k in ("facts", "recall", "in_context", "cited") if s.get(k) is False]
            if not s["answerable"]:
                why = ["answered a question without an answer"]
            print(f"  {s['id']} run {s['repeat'] + 1}: {', '.join(why) or s['status']}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--prompt", default=PROMPT)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--ids", nargs="*")
    parser.add_argument("--score", help="score a saved run instead of asking the model")
    args = parser.parse_args(argv)
    chunks = load_chunks()
    by_chunk = {c["chunk_id"]: c for c in chunks}
    questions = load_questions(args.ids)
    if args.score:
        rows = [json.loads(line) for line in Path(args.score).read_text(encoding="utf-8").splitlines()]
        out = None
    else:
        search = make_configs(chunks, [CONFIG.split("[")[1].rstrip("]")])[CONFIG]
        rows = run(Answerer(search, args.model, args.prompt), questions, args.repeat)
        RUNS.mkdir(parents=True, exist_ok=True)
        out = RUNS / f"answers_{args.prompt}.jsonl"
        out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    result, scores = report(rows, questions, by_chunk)
    show(result, scores)
    if out:
        meta = {"prompt": args.prompt, "model": args.model, "search": CONFIG, **result}
        out.with_name(f"answers_{args.prompt}_metrics.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Answer evaluation: every test question through the RAG bot, scored without a model.

python -m propdoc.evaluation.answers [--repeat 3] [--prompt rag_answer_v1] [--ids q01 q05]
python -m propdoc.evaluation.answers --score evals/runs/answers_rag_answer_v1.jsonl   # score a saved run
python -m propdoc.evaluation.answers --lint                     # check the test set, no model calls
python -m propdoc.evaluation.answers --open --gate              # CI: laws only, compare with the baseline

Writes every answer to evals/runs/answers_<prompt>.jsonl and the metrics to answers_<prompt>_metrics.json.
"""

import argparse
import json
from pathlib import Path

from ..answering.answer import CONFIG, MODEL, PROMPT, Answerer
from ..ingest.fetch import ROOT
from ..retrieval.search import make_configs
from ..retrieval.store import load_chunks
from .gate import case_rates, gate, lint, open_subset
from .scorers import metrics, score

QUESTIONS = ROOT / "evals" / "questions.json"
RUNS = ROOT / "evals" / "runs"
BASELINE = ROOT / "evals" / "baseline.json"  # the full corpus, run locally
BASELINE_OPEN = ROOT / "evals" / "baseline_open.json"  # the committed corpus, the one CI compares with


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
    parser.add_argument("--open", action="store_true",
                        help="only the committed corpus (the laws) and the questions it can answer, as in CI")
    parser.add_argument("--lint", action="store_true", help="check the test set itself, no model calls")
    parser.add_argument("--gate", action="store_true", help="exit 1 if the run is worse than the baseline")
    parser.add_argument("--save-baseline", action="store_true", help="make this run the new baseline")
    args = parser.parse_args(argv)
    chunks = load_chunks(open_only=args.open)
    by_chunk = {c["chunk_id"]: c for c in chunks}
    questions = load_questions(args.ids)
    if args.lint:
        problems, skipped = lint(questions, chunks)
        print(f"{len(questions)} questions, {len(problems)} problems, {skipped} quotes skipped "
              "(documents not in this checkout)")
        for p in problems:
            print("  " + p)
        return 1 if problems else 0
    if args.open:
        questions = open_subset(questions, chunks)
    name = f"answers_{args.prompt}" + ("_open" if args.open else "")
    if args.score:
        rows = [json.loads(line) for line in Path(args.score).read_text(encoding="utf-8").splitlines()]
        out = None
    else:
        search = make_configs(chunks, [CONFIG.split("[")[1].rstrip("]")])[CONFIG]
        rows = run(Answerer(search, args.model, args.prompt), questions, args.repeat)
        RUNS.mkdir(parents=True, exist_ok=True)
        out = RUNS / f"{name}.jsonl"
        out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    result, scores = report(rows, questions, by_chunk)
    show(result, scores)
    meta = {"prompt": args.prompt, "model": args.model, "search": CONFIG,
            "corpus": "open" if args.open else "full", **result, "case_pass": case_rates(scores)}
    if out:
        out.with_name(f"{name}_metrics.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    baseline_path = BASELINE_OPEN if args.open else BASELINE
    if args.save_baseline:
        baseline_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"\nbaseline saved to {baseline_path.relative_to(ROOT)}")
    if args.gate:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        violations = gate(result, meta["case_pass"], baseline)
        print("\nGATE " + ("FAILED" if violations else "PASSED") + f" against {baseline_path.relative_to(ROOT)}")
        for v in violations:
            print("  " + v)
        return 1 if violations else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

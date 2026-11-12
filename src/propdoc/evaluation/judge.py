"""LLM judge: is an answer correct against the reference, and is every claim in its cited sources.

python -m propdoc.evaluation.judge evals/runs/answers_rag_answer_v1.jsonl   # judge a saved run
python -m propdoc.evaluation.judge --calibrate evals/labels.json             # judge against human labels

The judge is a stronger model than the bot (Opus 5.5 judges Haiku 4.5). Only answers that claim a fact are
sent to it: "not found" on a question without an answer is correct and "not found" on a question with one
is incorrect without a model call. Identical answers of repeated runs are judged once.
"""

import argparse
import json
from pathlib import Path
from typing import Literal

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel

from ..extraction.prompts import load_prompt
from ..retrieval.store import load_chunks
from .answers import RUNS, load_questions

JUDGE_MODEL = "claude-opus-5-5"
EFFORT = "medium"  # set explicitly: the default of this model, written down so a change is visible
CORRECT_PROMPT = "judge_correct_v1"
GROUNDED_PROMPT = "judge_grounded_v2"
PRICE = {"claude-opus-5-5": (4.0, 20.0)}  # USD per million input and output tokens
MAX_TOKENS = 16000  # thinking is always on for this model and counts towards max_tokens


class Verdict(BaseModel):
    reason: str  # first, so the verdict is written after the explanation
    verdict: Literal["correct", "incorrect"]


class Claim(BaseModel):
    claim: str
    supported: bool


class Claims(BaseModel):
    claims: list[Claim]


class Judge:
    def __init__(self, model=JUDGE_MODEL, client=None):
        load_dotenv()
        self.model = model
        self.client = client or anthropic.Anthropic(timeout=120.0, max_retries=3)
        self.prompts = {"correct": load_prompt(CORRECT_PROMPT), "grounded": load_prompt(GROUNDED_PROMPT)}
        self.schemas = {"correct": anthropic.transform_schema(Verdict),
                        "grounded": anthropic.transform_schema(Claims)}
        self.tokens = {"input": 0, "output": 0}

    def _ask(self, kind, message, schema_model):
        response = self.client.beta.messages.create(
            model=self.model, max_tokens=MAX_TOKENS, system=self.prompts[kind],
            messages=[{"role": "user", "content": message}],
            output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": self.schemas[kind]}},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        self.tokens["input"] += response.usage.input_tokens
        self.tokens["output"] += response.usage.output_tokens
        if response.stop_reason != "end_turn":
            return None, f"stop_reason={response.stop_reason}"
        raw = next((b.text for b in response.content if b.type == "text"), "")
        return schema_model.model_validate_json(raw), response.model

    def correct(self, question, reference, answer):
        message = (f"Question: {question}\n\nReference answer: {reference}\n\n"
                   f"Assistant's answer: {answer}")
        parsed, model = self._ask("correct", message, Verdict)
        if parsed is None:
            return {"verdict": None, "reason": model}
        return {"verdict": parsed.verdict, "reason": parsed.reason, "judge_model": model}

    def grounded(self, question, answer, sources):
        texts = "\n\n".join(f'<source id="{i}">\n{text}\n</source>' for i, text in enumerate(sources, 1))
        message = f"<sources>\n{texts}\n</sources>\n\nQuestion: {question}\n\nAnswer: {answer}"
        parsed, model = self._ask("grounded", message, Claims)
        if parsed is None:
            return {"grounded": None, "claims": [], "reason": model}
        claims = [c.model_dump() for c in parsed.claims]
        return {"grounded": all(c["supported"] for c in claims), "claims": claims, "judge_model": model}

    def cost_usd(self):
        price_in, price_out = PRICE.get(self.model, (0.0, 0.0))
        return (self.tokens["input"] * price_in + self.tokens["output"] * price_out) / 1e6


def judge_row(judge, row, question, chunks):
    """Verdicts for one answer: correct (bool) and grounded (bool or None when the bot did not answer)."""
    if not row["found"]:
        return {"correct": not question["answerable"], "grounded": None, "by": "rule"}
    if not question["answerable"]:
        return {"correct": False, "grounded": None, "by": "rule",
                "reason": "answered a question that the documents do not answer"}
    verdict = judge.correct(question["question"], question["reference"], row["answer"])
    sources = [chunks[c["chunk_id"]]["text"] for c in row["citations"] if c["chunk_id"] in chunks]
    ground = judge.grounded(question["question"], row["answer"], sources)
    correct = None if verdict["verdict"] is None else verdict["verdict"] == "correct"
    return {"correct": correct, "grounded": ground["grounded"], "by": "judge",
            "reason": verdict["reason"], "claims": ground["claims"],
            "unsupported": [c["claim"] for c in ground["claims"] if not c["supported"]]}


def judge_rows(judge, rows, questions, chunks):
    """Judges every row; repeated identical answers to the same question reuse one verdict."""
    by_id = {q["id"]: q for q in questions}
    seen, out = {}, []
    for row in rows:
        key = (row["id"], row["found"], row["answer"])
        if key not in seen:
            seen[key] = judge_row(judge, row, by_id[row["id"]], chunks)
            print(f"  {row['id']}: correct={seen[key]['correct']} grounded={seen[key]['grounded']}", flush=True)
        out.append({"id": row["id"], "repeat": row.get("repeat", 0), **seen[key]})
    return out


def share(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 3) if values else None


def agreement(labels, verdicts, field):
    """How often the judge agrees with the human labels; false pass is the more dangerous error."""
    pairs = [(lab[field], ver[field]) for lab, ver in zip(labels, verdicts, strict=True)
             if lab.get(field) is not None and ver[field] is not None]
    if not pairs:
        return {}
    wrong = [p for p in pairs if not p[0]]
    right = [p for p in pairs if p[0]]
    return {"n": len(pairs), "agreement": share(h == j for h, j in pairs),
            "false_pass": share(j for _, j in wrong) if wrong else None,
            "false_fail": share(not j for _, j in right) if right else None}


def calibration(labels, verdicts, judge_model, cost):
    return {"judge": judge_model, "prompts": [CORRECT_PROMPT, GROUNDED_PROMPT], "labels": len(labels),
            "correct": agreement(labels, verdicts, "correct"),
            "grounded": agreement(labels, verdicts, "grounded"),
            "disagreements": [{"id": lab["id"], "field": f, "human": lab[f], "judge": ver[f],
                               "reason": ver.get("reason", "") if f == "correct"
                               else "; ".join(ver.get("unsupported", []))}
                              for lab, ver in zip(labels, verdicts, strict=True)
                              for f in ("correct", "grounded")
                              if lab.get(f) is not None and ver[f] is not None and lab[f] != ver[f]],
            "cost_usd": cost, "verdicts": verdicts}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", nargs="?", help="answers file to judge")
    parser.add_argument("--calibrate", help="human labels: JSON list of answers with correct and grounded")
    parser.add_argument("--rescore", help="human labels to compare with the verdicts of the last calibration")
    args = parser.parse_args(argv)
    chunks = {c["chunk_id"]: c for c in load_chunks()}
    questions = load_questions()
    out = RUNS / f"calibration_{CORRECT_PROMPT}_{GROUNDED_PROMPT}.json"
    if args.rescore:
        # labels changed after the review of disagreements: compare them with the saved verdicts, no model calls
        labels = json.loads(Path(args.rescore).read_text(encoding="utf-8"))
        saved = json.loads(out.read_text(encoding="utf-8"))
        result = calibration(labels, saved["verdicts"], saved["judge"], saved.get("cost_usd", 0))
        out = out.with_name(out.stem + "_relabeled.json")
    elif args.calibrate:
        labels = json.loads(Path(args.calibrate).read_text(encoding="utf-8"))
        judge = Judge()
        verdicts = judge_rows(judge, labels, questions, chunks)
        result = calibration(labels, verdicts, judge.model, round(judge.cost_usd(), 3))
    else:
        judge = Judge()
        rows = [json.loads(line) for line in Path(args.run).read_text(encoding="utf-8").splitlines()]
        verdicts = judge_rows(judge, rows, questions, chunks)
        result = {"judge": judge.model, "prompts": [CORRECT_PROMPT, GROUNDED_PROMPT],
                  "judge_correct": share(v["correct"] for v in verdicts),
                  "grounded": share(v["grounded"] for v in verdicts),
                  "incorrect": sorted({v["id"] for v in verdicts if v["correct"] is False}),
                  "not_grounded": sorted({v["id"] for v in verdicts if v["grounded"] is False}),
                  "cost_usd": round(judge.cost_usd(), 3)}
        out = Path(args.run).with_name(Path(args.run).stem + "_judged.json")
        result["verdicts"] = verdicts
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "verdicts"}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

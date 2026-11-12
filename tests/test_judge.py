from types import SimpleNamespace

from propdoc.evaluation.judge import Judge, agreement, judge_row

Q = {"id": "q03", "question": "Max fee?", "reference": "1%.", "answerable": True}
NA = {"id": "q25", "question": "How many?", "reference": "Not in the documents.", "answerable": False}
CHUNKS = {"D007#56": {"text": "nie może przekraczać 1 %"}}


class FakeClient:
    """Answers the correctness call with `verdict` and the groundedness call with `claims`."""

    def __init__(self, verdict="correct", supported=True):
        def create(**kwargs):
            if "reference" in kwargs["system"].lower():
                text = f'{{"reason": "r", "verdict": "{verdict}"}}'
            else:
                text = f'{{"claims": [{{"claim": "c", "supported": {str(supported).lower()}}}]}}'
            usage = SimpleNamespace(input_tokens=100, output_tokens=10)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], usage=usage,
                                   stop_reason="end_turn", model="m")
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=create))


def row(found=True, answer="Do 1% [1].", cited=("D007#56",)):
    return {"found": found, "answer": answer, "citations": [{"chunk_id": c} for c in cited]}


def test_abstaining_is_judged_by_rule_without_a_model_call():
    judge = Judge(client=FakeClient())
    assert judge_row(judge, row(found=False), NA, CHUNKS)["correct"] is True
    assert judge_row(judge, row(found=False), Q, CHUNKS)["correct"] is False
    assert judge_row(judge, row(), NA, CHUNKS)["correct"] is False
    assert judge.tokens["input"] == 0


def test_a_found_answer_gets_both_verdicts_from_the_judge():
    verdict = judge_row(Judge(client=FakeClient("incorrect", supported=False)), row(), Q, CHUNKS)
    assert verdict["correct"] is False and verdict["grounded"] is False and verdict["by"] == "judge"


def test_agreement_separates_false_pass_from_false_fail():
    labels = [{"correct": True}, {"correct": True}, {"correct": False}, {"correct": False}]
    judged = [{"correct": True}, {"correct": False}, {"correct": True}, {"correct": False}]
    result = agreement(labels, judged, "correct")
    assert result == {"n": 4, "agreement": 0.5, "false_pass": 0.5, "false_fail": 0.5}

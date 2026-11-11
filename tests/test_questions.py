import json

from propdoc.ingest.fetch import ROOT

QUESTIONS = json.loads((ROOT / "evals" / "questions.json").read_text(encoding="utf-8"))
FIELDS = {"id", "type", "lang", "question", "answerable", "docs", "quotes", "must", "reference", "history"}


def test_the_answer_test_set_has_at_least_20_questions_with_unique_ids():
    ids = [q["id"] for q in QUESTIONS]
    assert len(ids) >= 20 and len(set(ids)) == len(ids)


def test_every_question_has_the_required_fields():
    for q in QUESTIONS:
        assert FIELDS <= q.keys(), q["id"]
        assert q["lang"] in ("pl", "en") and q["reference"].strip(), q["id"]


def test_answerable_questions_name_sources_and_facts_and_the_others_name_none():
    for q in QUESTIONS:
        if q["answerable"]:
            assert q["docs"] and q["quotes"] and all(q["must"]), q["id"]
        else:
            assert not q["docs"] and not q["quotes"], q["id"]


def test_the_set_covers_the_cases_the_course_asks_for():
    types = {q["type"] for q in QUESTIONS}
    assert {"no_answer", "multi_doc", "stale_period", "upcoming", "cross_language"} <= types
    assert {q["lang"] for q in QUESTIONS} == {"pl", "en"}

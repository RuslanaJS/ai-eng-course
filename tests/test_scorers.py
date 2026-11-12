from propdoc.evaluation.scorers import has_facts, metrics, score

CHUNK = {"chunk_id": "D007#56", "doc_id": "D007", "text": "Wysokość opłaty rezerwacyjnej nie może przekraczać 1 % ceny."}
OTHER = {"chunk_id": "D007#1", "doc_id": "D007", "text": "Inny przepis."}
CHUNKS = {c["chunk_id"]: c for c in (CHUNK, OTHER)}
QUESTION = {"id": "q03", "answerable": True, "docs": ["D007"], "must": [["1%", "1 %"]],
            "quotes": ["opłaty rezerwacyjnej nie może przekraczać 1 %"]}
NO_ANSWER = {"id": "q25", "answerable": False, "docs": [], "must": [], "quotes": []}


def row(found=True, answer="Najwyżej 1% ceny [1].", cited=("D007#56",), used=("D007#56", "D007#1"), **extra):
    return {"status": "ok", "found": found, "answer": answer, "retrieved_ids": list(used),
            "chunk_ids": list(used), "citations": [{"chunk_id": c} for c in cited], "model": "x", **extra}


def test_facts_need_one_variant_of_every_group_and_ignore_case_and_spaces():
    assert has_facts("Opłata do 1 % ceny", [["1%", "1 %"], ["ceny"]])
    assert not has_facts("Opłata do 1 % ", [["1%", "1 %"], ["ceny"]])


def test_a_correct_cited_answer_passes():
    s = score(row(), QUESTION, CHUNKS)
    assert s["pass"] and s["recall"] and s["in_context"] and s["cited"]


def test_citing_the_wrong_chunk_fails_although_the_fact_is_right():
    s = score(row(cited=("D007#1",)), QUESTION, CHUNKS)
    assert s["facts"] and not s["cited"] and not s["pass"]


def test_not_found_on_a_question_with_an_answer_is_a_false_abstain():
    s = score(row(found=False, answer="Brak danych.", cited=()), QUESTION, CHUNKS)
    assert s["abstained"] and not s["pass"]


def test_a_question_without_an_answer_passes_only_when_the_bot_abstains():
    assert score(row(found=False, cited=()), NO_ANSWER, CHUNKS)["pass"]
    assert not score(row(), NO_ANSWER, CHUNKS)["pass"]


def test_metrics_find_flaky_cases_across_repeats():
    rows = [row(latency_s=1.0), row(found=False, cited=(), latency_s=2.0), row(latency_s=1.5)]
    scores = [score(r, QUESTION, CHUNKS) for r in rows]
    m = metrics(rows, scores)
    assert m["flaky"] == ["q03"] and m["pass@1"] == round(2 / 3, 3) and m["pass_every_time"] == 0

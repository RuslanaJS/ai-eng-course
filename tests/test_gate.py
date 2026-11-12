from propdoc.evaluation.gate import gate, lint, open_subset

CHUNKS = [{"doc_id": "D001", "text": "Nie wymaga uzyskania zezwolenia nabycie lokalu."}]


def question(qid="q01", answerable=True, docs=("D001",), quotes=("nie wymaga uzyskania zezwolenia",), must=(("nie",),)):
    return {"id": qid, "answerable": answerable, "docs": list(docs), "quotes": list(quotes),
            "must": [list(g) for g in must]}


def test_lint_accepts_a_clean_set_and_skips_documents_not_in_the_checkout():
    problems, skipped = lint([question(), question("q02", docs=("D009",), quotes=("ceny",))], CHUNKS)
    assert problems == [] and skipped == 1


def test_lint_finds_a_missing_quote_a_duplicate_and_an_unknown_document():
    problems, _ = lint([question(quotes=("czego nie ma",)), question(), question("q03", docs=("D999",))], CHUNKS)
    assert any("quote not found" in p for p in problems)
    assert any("duplicate id" in p for p in problems)
    assert any("unknown document D999" in p for p in problems)


def test_open_subset_keeps_questions_without_an_answer():
    qs = [question(), question("q02", docs=("D009",)), question("q25", answerable=False, docs=(), quotes=(), must=())]
    assert [q["id"] for q in open_subset(qs, CHUNKS)] == ["q01", "q25"]


def test_gate_tolerates_noise_but_catches_a_fall_a_rise_and_a_regression():
    baseline = {"pass@1": 0.9, "cited": 0.9, "false_abstain": 0.0, "case_pass": {"q01": 1.0, "q02": 0.0}}
    assert gate({"pass@1": 0.86, "cited": 0.9, "false_abstain": 0.04}, {"q01": 1.0, "q02": 0.0}, baseline) == []
    violations = gate({"pass@1": 0.8, "cited": 0.9, "false_abstain": 0.1}, {"q01": 0.0}, baseline)
    assert violations == ["pass@1: 0.8 < baseline 0.9", "false_abstain: 0.1 > baseline 0.0", "regression: q01"]

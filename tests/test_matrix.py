"""Tests for the matrix runner planning (no model calls)."""

from extractor import matrix
from extractor.run import ROOT, output_path


def test_output_path_naming():
    assert output_path("m", "extract_v2", "t0") == ROOT / "results" / "m__extract_v2__t0.jsonl"
    assert output_path("m", "p", "s", "__first5").name == "m__p__s__first5.jsonl"


def test_prompt_versions_are_discovered():
    assert matrix.prompt_versions()[:3] == ["extract_v1", "extract_v2", "extract_v3"]


def test_planned_runs_skip_existing_results_unless_forced(tmp_path, monkeypatch):
    monkeypatch.setattr(
        matrix, "output_path", lambda m, p, s, suffix="": tmp_path / f"{m}_{p}_{s}.jsonl"
    )
    (tmp_path / "a_p1_t0.jsonl").write_text("{}\n")
    todo = matrix.planned_runs(["a"], ["p1", "p2"], ["t0", "t07"])
    assert todo == [("a", "p1", "t07"), ("a", "p2", "t0"), ("a", "p2", "t07")]
    assert len(matrix.planned_runs(["a"], ["p1", "p2"], ["t0", "t07"], force=True)) == 4

"""Tests for retrieval metrics. Every expected value is computed by hand."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from code_atlas.eval.metrics import (
    files_from_chunks,
    hit_at_k,
    recall_at_k,
    reciprocal_rank_at_k,
)

RANKING = ["a", "b", "c", "d"]
GOLD = {"c", "x"}  # "c" is at rank 3; "x" is gold but never retrieved


# --- Worked example ---------------------------------------------------------------------


def test_recall_at_1() -> None:
    # top-1 = {a}: 0 of 2 gold found.
    assert recall_at_k(RANKING, GOLD, k=1) == 0.0


def test_recall_at_3() -> None:
    # top-3 = {a, b, c}: 1 of 2 gold found.
    assert recall_at_k(RANKING, GOLD, k=3) == 0.5


def test_recall_at_5_with_k_past_end_of_ranking() -> None:
    # Only 4 results; k=5 uses all of them. Still 1 of 2 gold. Denominator is |gold|, not k.
    assert recall_at_k(RANKING, GOLD, k=5) == 0.5


def test_recall_all_gold_found() -> None:
    # top-2 = {a, b}, gold = {a, b}: 2 of 2.
    assert recall_at_k(RANKING, {"a", "b"}, k=2) == 1.0


def test_hit_at_k() -> None:
    assert hit_at_k(RANKING, GOLD, k=2) == 0.0  # c is at rank 3
    assert hit_at_k(RANKING, GOLD, k=3) == 1.0
    assert hit_at_k(RANKING, GOLD, k=5) == 1.0


def test_reciprocal_rank() -> None:
    # First gold item "c" is at 1-based rank 3.
    assert reciprocal_rank_at_k(RANKING, GOLD, k=10) == pytest.approx(1 / 3)


def test_reciprocal_rank_first_position() -> None:
    assert reciprocal_rank_at_k(RANKING, {"a"}, k=10) == 1.0


def test_reciprocal_rank_uses_first_gold_only() -> None:
    # Gold at ranks 2 and 4: only the first one counts.
    assert reciprocal_rank_at_k(RANKING, {"b", "d"}, k=10) == 0.5


def test_reciprocal_rank_gold_just_past_cutoff() -> None:
    # "c" is at rank 3; with k=2 it is outside the cutoff.
    assert reciprocal_rank_at_k(RANKING, GOLD, k=2) == 0.0
    assert reciprocal_rank_at_k(RANKING, GOLD, k=3) == pytest.approx(1 / 3)


def test_reciprocal_rank_independent_of_output_length() -> None:
    # Gold at rank 50. A top-100 retriever and a top-10 retriever ranked it the same,
    # so at k=10 both must score 0. Without the cutoff the longer list would score 0.02.
    long_ranking = [f"f{i}" for i in range(1, 101)]  # f50 is at rank 50
    short_ranking = long_ranking[:10]
    assert reciprocal_rank_at_k(long_ranking, {"f50"}, k=10) == 0.0
    assert reciprocal_rank_at_k(short_ranking, {"f50"}, k=10) == 0.0


# --- Single gold item: recall and hit agree (always the case at file level) -------------


@pytest.mark.parametrize("k", [1, 2, 3, 4, 10])
def test_recall_equals_hit_with_one_gold(k: int) -> None:
    gold = {"c"}
    assert recall_at_k(RANKING, gold, k) == hit_at_k(RANKING, gold, k)


# --- Gold may be any read-only set ------------------------------------------------------


def test_frozenset_gold_accepted() -> None:
    gold = frozenset({"c", "x"})
    assert recall_at_k(RANKING, gold, k=3) == 0.5
    assert hit_at_k(RANKING, gold, k=3) == 1.0
    assert reciprocal_rank_at_k(RANKING, gold, k=3) == pytest.approx(1 / 3)


# --- Legitimate empty input: scores 0, does not raise -----------------------------------


def test_empty_ranking_scores_zero() -> None:
    assert recall_at_k([], GOLD, k=5) == 0.0
    assert hit_at_k([], GOLD, k=5) == 0.0
    assert reciprocal_rank_at_k([], GOLD, k=5) == 0.0


def test_no_gold_retrieved_scores_zero() -> None:
    assert recall_at_k(RANKING, {"x"}, k=10) == 0.0
    assert hit_at_k(RANKING, {"x"}, k=10) == 0.0
    assert reciprocal_rank_at_k(RANKING, {"x"}, k=10) == 0.0


# --- Caller bugs: raise ValueError ------------------------------------------------------

Metric = Callable[[list[str], set[str], int], float]
METRICS: list[Metric] = [recall_at_k, hit_at_k, reciprocal_rank_at_k]


@pytest.mark.parametrize("metric", METRICS)
def test_empty_gold_raises(metric: Metric) -> None:
    with pytest.raises(ValueError):
        metric(RANKING, set(), 5)


@pytest.mark.parametrize("metric", METRICS)
def test_duplicate_in_ranking_raises(metric: Metric) -> None:
    # Without this check, "c" at ranks 1 and 2 could be counted twice: recall 2/2 for 1 item.
    with pytest.raises(ValueError):
        metric(["c", "c", "a"], GOLD, 5)


@pytest.mark.parametrize("metric", METRICS)
@pytest.mark.parametrize("k", [0, -1])
def test_nonpositive_k_raises(metric: Metric, k: int) -> None:
    with pytest.raises(ValueError):
        metric(RANKING, GOLD, k)


# --- Chunks to files --------------------------------------------------------------------


def test_files_from_chunks_keeps_first_occurrence() -> None:
    chunks = ["a.py::f", "b.py::g", "a.py::h", "c.py::k", "a.py::m"]
    assert files_from_chunks(chunks) == ["a.py", "b.py", "c.py"]


def test_files_from_chunks_module_chunk() -> None:
    # Module chunks use "<module>" as the qualified name.
    assert files_from_chunks(["a.py::<module>", "a.py::f"]) == ["a.py"]


def test_files_from_chunks_nested_path() -> None:
    assert files_from_chunks(["django/db/models/query.py::QuerySet.get"]) == [
        "django/db/models/query.py"
    ]


def test_files_from_chunks_empty() -> None:
    assert files_from_chunks([]) == []


def test_files_from_chunks_rejects_file_path() -> None:
    # Passing a file ranking where a chunk ranking is expected is a caller bug.
    with pytest.raises(ValueError, match="not a chunk id"):
        files_from_chunks(["a.py::f", "b.py"])

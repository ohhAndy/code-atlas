"""Reciprocal rank fusion: combine several rankings using only each item's rank."""

from __future__ import annotations


def rrf(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    """Fused score of every id that appears in at least one ranking.

    score(id) = sum over the rankings that contain id of 1 / (k + rank), with rank
    1-based. A ranking that does not contain an id adds nothing for it.

    Raises `ValueError` if `k < 0` or if any ranking contains the same id twice (that is a
    caller bug: the id would be counted twice).
    """
    if k < 0:
        raise ValueError(f"k must be >= 0, got {k}")

    scores: dict[str, float] = {}
    for ranking in rankings:
        seen: set[str] = set()
        for rank, doc_id in enumerate(ranking, start=1):
            if doc_id in seen:
                raise ValueError(f"Duplicate id {doc_id!r} in ranking")
            seen.add(doc_id)
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)

    return scores

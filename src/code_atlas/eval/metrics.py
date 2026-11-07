"""Retrieval metrics for one query. The runner averages them over queries.

A `ranking` is a retriever's output, best first: file paths at file level, chunk ids at
function level. `gold` is the set of correct items for that query.

Input rules (raise ValueError on violation; they mean the caller has a bug):
- `gold` is not empty. Instances with no function-level gold are scored at file level only.
- `ranking` has no duplicates.
- `k` >= 1.
An empty `ranking` is legitimate (the retriever found nothing) and scores 0.
"""

from __future__ import annotations

from collections.abc import Sequence
from collections.abc import Set as AbstractSet


def _validate(ranking: Sequence[str], gold: AbstractSet[str], k: int) -> None:
    """Enforce the input rules above."""
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    if not gold:
        raise ValueError("gold is empty; score this instance at file level only")
    if len(set(ranking)) != len(ranking):
        raise ValueError("ranking contains duplicate items")


def recall_at_k(ranking: Sequence[str], gold: AbstractSet[str], k: int) -> float:
    """Fraction of gold items that appear in the top k: |gold ∩ top-k| / |gold|."""
    _validate(ranking, gold, k)
    count = 0
    for item in ranking[:k]:
        if item in gold:
            count += 1
    return count / len(gold)


def hit_at_k(ranking: Sequence[str], gold: AbstractSet[str], k: int) -> float:
    """1.0 if any gold item appears in the top k, else 0.0."""
    _validate(ranking, gold, k)
    for item in ranking[:k]:
        if item in gold:
            return 1.0
    return 0.0


def reciprocal_rank_at_k(ranking: Sequence[str], gold: AbstractSet[str], k: int) -> float:
    """1 / (1-based rank of the first gold item in the top k), or 0.0 if none is there.

    The cutoff makes the score independent of how many results a retriever returns:
    without it, a gold item at rank 50 scores 0.02 from a top-100 retriever and 0 from a
    top-10 one, so MRR would reward longer output rather than better ranking.
    """
    _validate(ranking, gold, k)
    for rank, item in enumerate(ranking[:k], start=1):
        if item in gold:
            return 1 / rank
    return 0.0


def files_from_chunks(chunk_ids: Sequence[str]) -> list[str]:
    """Turn a chunk ranking into a file ranking: each file at its best-ranked chunk.

    Chunk ids look like "path::QualifiedName". Keep each path the first time it appears.
    Example: ["a.py::f", "b.py::g", "a.py::h"] -> ["a.py", "b.py"]
    Raises ValueError on an id without "::" (a caller bug, e.g. passing file paths).
    """
    files: list[str] = []  # keeps rank order
    seen: set[str] = set()  # O(1) "already ranked?" check
    for cid in chunk_ids:
        if "::" not in cid:
            raise ValueError(f"not a chunk id (expected 'path::QualifiedName'): {cid!r}")
        path, _ = cid.split("::", 1)
        if path not in seen:
            seen.add(path)
            files.append(path)
    return files

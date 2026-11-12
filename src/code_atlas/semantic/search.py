"""Brute-force vector search: unit-normalize the vectors, score by dot product, take top k."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

Vectors = NDArray[np.float32]


def normalize(vectors: Vectors) -> Vectors:
    """Scale each vector (along the last axis) to unit L2 norm.

    Works on a single vector (shape `(d,)`) and on a matrix of row vectors (shape `(n, d)`).
    Returns a new array; the input is not modified.
    """
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("Cannot normalize zero-norm vector")
    return vectors / norms


def top_k(matrix: Vectors, query: Vectors, k: int) -> list[tuple[int, float]]:
    """The `k` rows of `matrix` with the highest dot product with `query`, best first, as
    (row index, score) pairs.

    Both inputs are expected to be unit-normalized already, so the score is the cosine
    similarity. Returns all rows if `k` exceeds the row count. Ties are broken by lower
    row index, so results are reproducible. Raises `ValueError` if `k < 1`.
    """
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")

    n = matrix.shape[0]
    if n == 0:
        return []
    k = min(k, n)
    scores = matrix @ query

    # Partition plain float scores to find the k-th highest value
    kth_idx = np.argpartition(-scores, k - 1)[k - 1]
    threshold = scores[kth_idx]

    # Every row at or above the threshold, so rows tied at the cutoff are all candidates.
    # flatnonzero returns them in ascending row order, and a stable sort keeps that order
    # among equal scores, so ties go to the lower row index.
    candidates = np.flatnonzero(scores >= threshold)
    top_indices = candidates[np.argsort(-scores[candidates], kind="stable")][:k]

    return [(int(idx), float(scores[idx])) for idx in top_indices]

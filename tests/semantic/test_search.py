"""Tests for normalize and top_k. Expected values are computed by hand; the arithmetic is
in the comments.

Unit-length rows used below:
    r0 = (1, 0)
    r1 = (0, 1)
    r2 = (0.6, 0.8)
    r3 = (0.8, -0.6)
Query q = (0.6, 0.8). Dot products:
    r0: 0.6    r1: 0.8    r2: 0.36 + 0.64 = 1.0    r3: 0.48 - 0.48 = 0.0
So the full ranking is r2, r1, r0, r3.
"""

from __future__ import annotations

import numpy as np
import pytest

from code_atlas.semantic.search import normalize, top_k

MATRIX = np.array([[1, 0], [0, 1], [0.6, 0.8], [0.8, -0.6]], dtype=np.float32)
QUERY = np.array([0.6, 0.8], dtype=np.float32)


# --- normalize ---------------------------------------------------------------------------


def test_normalize_single_vector() -> None:
    # |(3, 4)| = 5
    assert normalize(np.array([3, 4], dtype=np.float32)) == pytest.approx([0.6, 0.8])


def test_normalize_each_row_separately() -> None:
    # Row norms 5 and 2.
    out = normalize(np.array([[3, 4], [0, 2]], dtype=np.float32))
    assert out.shape == (2, 2)
    assert out[0] == pytest.approx([0.6, 0.8])
    assert out[1] == pytest.approx([0.0, 1.0])


def test_normalize_gives_unit_norm_rows() -> None:
    rng = np.random.default_rng(0)
    out = normalize(rng.normal(size=(50, 8)).astype(np.float32))
    assert np.linalg.norm(out, axis=1) == pytest.approx(np.ones(50), abs=1e-6)


def test_normalize_rejects_zero_vector() -> None:
    # A zero row has no direction. From a real model it means an upstream bug (e.g. a
    # matrix row that was never filled), so it must fail loudly, not score 0 forever.
    with pytest.raises(ValueError):
        normalize(np.array([[3, 4], [0, 0]], dtype=np.float32))
    with pytest.raises(ValueError):
        normalize(np.zeros(2, dtype=np.float32))


def test_normalize_does_not_modify_input() -> None:
    vectors = np.array([[3, 4]], dtype=np.float32)
    normalize(vectors)
    assert vectors.tolist() == [[3.0, 4.0]]


# --- top_k -------------------------------------------------------------------------------


def test_top_k_hand_computed() -> None:
    result = top_k(MATRIX, QUERY, k=2)
    assert [i for i, _ in result] == [2, 1]
    assert [s for _, s in result] == pytest.approx([1.0, 0.8])


def test_top_k_full_ranking_best_first() -> None:
    result = top_k(MATRIX, QUERY, k=4)
    assert [i for i, _ in result] == [2, 1, 0, 3]
    assert [s for _, s in result] == pytest.approx([1.0, 0.8, 0.6, 0.0], abs=1e-6)


def test_top_k_larger_than_row_count_returns_every_row() -> None:
    assert [i for i, _ in top_k(MATRIX, QUERY, k=10)] == [2, 1, 0, 3]


def test_top_k_scores_are_python_floats() -> None:
    _, score = top_k(MATRIX, QUERY, k=1)[0]
    assert type(score) is float


def test_top_k_ties_broken_by_lower_row_index() -> None:
    # Rows 1 and 3 are identical, so they tie (0.8) behind row 0 (1.0).
    matrix = np.array([[0.6, 0.8], [0, 1], [1, 0], [0, 1]], dtype=np.float32)
    assert [i for i, _ in top_k(matrix, QUERY, k=3)] == [0, 1, 3]


def test_top_k_ties_at_the_cutoff_keep_lowest_row_indices() -> None:
    # Rows 5, 500 and 999 score 1.0 with q; the other 997 rows all score 0.6 and tie for
    # the last 2 of the 5 slots. The tie rule says rows 0 and 1 get them. A partition that
    # keeps an arbitrary member of the tie fails here.
    matrix = np.zeros((1000, 2), dtype=np.float32)
    matrix[:, 0] = 1.0
    matrix[[5, 500, 999]] = [0.6, 0.8]
    assert [i for i, _ in top_k(matrix, QUERY, k=5)] == [5, 500, 999, 0, 1]


def test_top_k_empty_matrix_returns_nothing() -> None:
    assert top_k(np.zeros((0, 2), dtype=np.float32), QUERY, k=10) == []


def test_top_k_rejects_k_below_one() -> None:
    with pytest.raises(ValueError):
        top_k(MATRIX, QUERY, k=0)


def test_top_k_matches_a_full_sort() -> None:
    # A larger random case, so a top-k shortcut that returns the right rows in the wrong
    # order (or misses one) is caught. Random float scores have no ties.
    rng = np.random.default_rng(0)
    matrix = normalize(rng.normal(size=(1000, 16)).astype(np.float32))
    query = normalize(rng.normal(size=16).astype(np.float32))
    expected = np.argsort(-(matrix @ query))[:10].tolist()
    assert [i for i, _ in top_k(matrix, query, k=10)] == expected


def test_normalizing_lets_direction_beat_length() -> None:
    # Raw dot products with q: (10, 0) -> 6.0, (0.6, 0.8) -> 1.0, so the long vector wins.
    # After normalizing, (10, 0) becomes (1, 0) -> 0.6, and the row pointing the same way
    # as q wins with 1.0.
    raw = np.array([[10, 0], [0.6, 0.8]], dtype=np.float32)
    assert top_k(raw, QUERY, k=1)[0][0] == 0
    assert top_k(normalize(raw), QUERY, k=1)[0][0] == 1

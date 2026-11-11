"""Tests for idf and bm25_scores on a three-chunk corpus. Expected values are computed by
hand; the arithmetic is in the comments.

Corpus: N = 3, average length = (4 + 2 + 3) / 3 = 3.0.
Defaults k1 = 1.2, b = 0.75, so the length term k1 * (1 - b + b * dl / avgdl) is
    d1 (dl 4): 1.2 * (0.25 + 0.75 * 4/3) = 1.5
    d2 (dl 2): 1.2 * (0.25 + 0.75 * 2/3) = 0.9
    d3 (dl 3): 1.2 * (0.25 + 0.75 * 3/3) = 1.2
"""

from __future__ import annotations

import math

import pytest

from code_atlas.lexical.bm25 import bm25_scores, idf
from code_atlas.lexical.index import build_index

DOCS = {
    "d1": ["get", "create", "object", "create"],
    "d2": ["get", "value"],
    "d3": ["delete", "object", "value"],
}
INDEX = build_index(DOCS)

IDF_DF1 = math.log(1 + 2.5 / 1.5)  # ln(2.667) ~ 0.9808
IDF_DF2 = math.log(1 + 1.5 / 2.5)  # ln(1.6)   ~ 0.4700


def test_idf_rare_token_weighs_more() -> None:
    assert idf(1, 3) == pytest.approx(0.980829, abs=1e-6)
    assert idf(2, 3) == pytest.approx(0.470004, abs=1e-6)


def test_idf_stays_positive_for_token_in_every_chunk() -> None:
    # ln(1 + 0.5 / 3.5) ~ 0.1335
    assert idf(3, 3) == pytest.approx(0.133531, abs=1e-6)


def test_scores_two_token_query() -> None:
    scores = bm25_scores(INDEX, ["create", "object"])
    # d1: create tf 2 -> 2 * 2.2 / (2 + 1.5) = 1.2571; object tf 1 -> 2.2 / 2.5 = 0.88
    #     1.2571 * 0.9808 + 0.88 * 0.4700 = 1.6466
    # d3: object tf 1 -> 2.2 / (1 + 1.2) = 1.0; 1.0 * 0.4700 = 0.4700
    assert scores == pytest.approx({"d1": 1.646646, "d3": 0.470004}, abs=1e-6)


def test_chunks_with_no_matching_token_are_left_out() -> None:
    assert "d2" not in bm25_scores(INDEX, ["create", "object"])


def test_unknown_query_token_contributes_nothing() -> None:
    assert bm25_scores(INDEX, ["missing"]) == {}
    assert bm25_scores(INDEX, ["create", "missing"]) == bm25_scores(INDEX, ["create"])


def test_repeated_query_token_counts_once() -> None:
    assert bm25_scores(INDEX, ["create", "create", "object"]) == bm25_scores(
        INDEX, ["create", "object"]
    )


def test_length_normalization_favors_shorter_chunk() -> None:
    # Same tf (1) for "object" in d1 (dl 4) and d3 (dl 3): the shorter chunk scores higher.
    scores = bm25_scores(INDEX, ["object"])
    assert scores["d3"] > scores["d1"]


def test_b_zero_turns_off_length_normalization() -> None:
    scores = bm25_scores(INDEX, ["object"], b=0.0)
    assert scores["d1"] == pytest.approx(scores["d3"])
    assert scores["d1"] == pytest.approx(IDF_DF2)


def test_k1_zero_ignores_term_frequency() -> None:
    # k1 = 0: tf * 1 / tf = 1, so d1's two "create"s score the same as one would.
    assert bm25_scores(INDEX, ["create"], k1=0.0) == pytest.approx({"d1": IDF_DF1})

"""Tests for reciprocal rank fusion. Expected values are computed by hand; the arithmetic is
in the comments. Ranks are 1-based: the first item of a ranking has rank 1."""

from __future__ import annotations

import pytest

from code_atlas.fusion.rrf import rrf


def test_two_rankings_hand_computed() -> None:
    # A = [a, b, c], B = [b, d], k = 60
    #   a: 1/61                 ~ 0.016393
    #   b: 1/62 (A) + 1/61 (B)  ~ 0.032522
    #   c: 1/63                 ~ 0.015873
    #   d: 1/62 (B)             ~ 0.016129
    scores = rrf([["a", "b", "c"], ["b", "d"]], k=60)
    assert scores == pytest.approx({"a": 1 / 61, "b": 1 / 62 + 1 / 61, "c": 1 / 63, "d": 1 / 62})


def test_ranks_start_at_one() -> None:
    # The top item scores 1 / (k + 1), not 1 / k.
    assert rrf([["a"]], k=60) == pytest.approx({"a": 1 / 61})


def test_item_in_both_rankings_beats_item_first_in_one() -> None:
    scores = rrf([["a", "b"], ["b", "c"]], k=60)
    # b: 1/62 + 1/61 ~ 0.0325 > a: 1/61 ~ 0.0164
    assert scores["b"] > scores["a"]


def test_k_controls_one_strong_vote_vs_agreement() -> None:
    # x is rank 1 in A only; y is rank 3 in both.
    rankings = [["x", "p", "y"], ["q", "r", "y"]]
    # k = 0:  x = 1/1 = 1.0,      y = 2/3 ~ 0.667       -> x wins
    low = rrf(rankings, k=0)
    assert low["x"] > low["y"]
    # k = 60: x = 1/61 ~ 0.0164,  y = 2/63 ~ 0.0317     -> y wins
    high = rrf(rankings, k=60)
    assert high["y"] > high["x"]


def test_scores_only_items_that_appear() -> None:
    assert set(rrf([["a"], ["b"]], k=60)) == {"a", "b"}


def test_no_rankings_or_empty_rankings_give_no_scores() -> None:
    assert rrf([], k=60) == {}
    assert rrf([[], []], k=60) == {}


def test_single_ranking_keeps_its_order() -> None:
    scores = rrf([["c", "a", "b"]], k=60)
    assert sorted(scores, key=lambda i: -scores[i]) == ["c", "a", "b"]


def test_duplicate_id_in_a_ranking_raises() -> None:
    with pytest.raises(ValueError):
        rrf([["a", "b", "a"]], k=60)


def test_negative_k_raises() -> None:
    with pytest.raises(ValueError):
        rrf([["a"]], k=-1)

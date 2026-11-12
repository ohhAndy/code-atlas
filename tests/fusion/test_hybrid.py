"""Tests for HybridRetriever with two fake retrievers that return fixed rankings.
Expected values are computed by hand; the arithmetic is in the comments. Ranks are
1-based, k = 60 unless stated."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from code_atlas.fusion.hybrid import HybridRetriever
from code_atlas.types import Hit, Level


@dataclass
class FixedRetriever:
    """Returns the first `k` ids of a fixed ranking, with descending dummy scores."""

    ranking: list[str]
    level: Level = "chunk"
    requested: list[int] = field(default_factory=list)

    def search(self, query: str, k: int) -> list[Hit]:
        self.requested.append(k)
        return [Hit(id=i, score=float(-n)) for n, i in enumerate(self.ranking[:k])]


def ids(hits: list[Hit]) -> list[str]:
    return [h.id for h in hits]


def test_hand_computed_fusion() -> None:
    # A = [a, b, c], B = [b, d]
    #   b: 1/62 + 1/61 ~ 0.03252   a: 1/61 ~ 0.01639   d: 1/62 ~ 0.01613   c: 1/63 ~ 0.01587
    hybrid = HybridRetriever(FixedRetriever(["a", "b", "c"]), FixedRetriever(["b", "d"]))
    hits = hybrid.search("q", k=10)
    assert ids(hits) == ["b", "a", "d", "c"]
    assert [h.score for h in hits] == pytest.approx([1 / 62 + 1 / 61, 1 / 61, 1 / 62, 1 / 63])


def test_returns_at_most_k() -> None:
    hybrid = HybridRetriever(FixedRetriever(["a", "b", "c"]), FixedRetriever(["b", "d"]))
    assert ids(hybrid.search("q", k=2)) == ["b", "a"]


def test_each_retriever_is_asked_for_depth_not_k() -> None:
    first, second = FixedRetriever(["a"]), FixedRetriever(["b"])
    HybridRetriever(first, second, depth=100).search("q", k=10)
    assert first.requested == [100]
    assert second.requested == [100]


def test_near_miss_in_both_lists_beats_a_single_top_hit() -> None:
    # gold is 15th in the first ranking and 12th in the second; x is 1st in the first only.
    #   gold: 1/75 + 1/72 ~ 0.02722   x: 1/61 ~ 0.01639
    first = [f"f{i}" for i in range(1, 15)]  # f1 .. f14
    first[0] = "x"
    first.append("gold")  # rank 15
    second = [f"s{i}" for i in range(1, 12)] + ["gold"]  # gold at rank 12
    hits = HybridRetriever(FixedRetriever(first), FixedRetriever(second)).search("q", k=1)
    assert ids(hits) == ["gold"]
    assert hits[0].score == pytest.approx(1 / 75 + 1 / 72)


def test_depth_cuts_what_each_retriever_contributes() -> None:
    # Same setup, but depth 10: gold is outside both top-10 lists and is never seen.
    first = ["x"] + [f"f{i}" for i in range(2, 15)] + ["gold"]
    second = [f"s{i}" for i in range(1, 12)] + ["gold"]
    hybrid = HybridRetriever(FixedRetriever(first), FixedRetriever(second), depth=10)
    assert "gold" not in ids(hybrid.search("q", k=100))


def test_rrf_k_is_passed_through() -> None:
    # k = 0: a = 1/1 = 1.0 (first only), b = 1/2 + 1/1 = 1.5 (both).
    hybrid = HybridRetriever(FixedRetriever(["a", "b"]), FixedRetriever(["b"]), rrf_k=0)
    assert [h.score for h in hybrid.search("q", k=10)] == pytest.approx([1.5, 1.0])


def test_ties_broken_by_chunk_id() -> None:
    # z and a are both rank 1 in one list only: 1/61 each. The tie goes to "a".
    hybrid = HybridRetriever(FixedRetriever(["z"]), FixedRetriever(["a"]))
    assert ids(hybrid.search("q", k=10)) == ["a", "z"]


def test_both_empty_returns_nothing() -> None:
    assert HybridRetriever(FixedRetriever([]), FixedRetriever([])).search("q", k=10) == []


def test_rejects_a_file_level_retriever() -> None:
    with pytest.raises(ValueError):
        HybridRetriever(FixedRetriever(["a"], level="file"), FixedRetriever(["b"]))

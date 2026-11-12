"""Tests for the RRF k selection rule and the search memo used by the sweep."""

from __future__ import annotations

from dataclasses import dataclass, field

from code_atlas.eval.rrf_sweep import DEFAULT_K, MemoRetriever, choose_k
from code_atlas.types import Hit, Level


def test_keeps_default_when_gain_is_below_margin() -> None:
    assert choose_k({10: 0.315, 30: 0.300, DEFAULT_K: 0.300, 100: 0.290}) == DEFAULT_K


def test_takes_best_when_gain_reaches_margin() -> None:
    assert choose_k({10: 0.330, 30: 0.300, DEFAULT_K: 0.300, 100: 0.290}) == 10


def test_default_wins_when_it_is_best() -> None:
    assert choose_k({10: 0.250, 30: 0.280, DEFAULT_K: 0.300, 100: 0.290}) == DEFAULT_K


def test_tie_for_best_goes_to_smaller_k() -> None:
    assert choose_k({10: 0.200, 30: 0.350, DEFAULT_K: 0.300, 100: 0.350}) == 30


@dataclass
class CountingRetriever:
    level: Level = "chunk"
    calls: list[tuple[str, int]] = field(default_factory=list)

    def search(self, query: str, k: int) -> list[Hit]:
        self.calls.append((query, k))
        return [Hit(id=f"{query}-{i}", score=float(-i)) for i in range(k)]


def test_memo_searches_once_per_query_and_k() -> None:
    inner = CountingRetriever()
    memo = MemoRetriever(inner)
    first = memo.search("q", 3)
    assert memo.search("q", 3) == first
    memo.search("q", 5)
    memo.search("other", 3)
    assert inner.calls == [("q", 3), ("q", 5), ("other", 3)]


def test_memo_reports_the_inner_level() -> None:
    assert MemoRetriever(CountingRetriever(level="file")).level == "file"

"""Tests for BM25Retriever on a fake three-file repo. Expected rankings hold whether or
not the chunk's path and qualified name are indexed: the query words only appear in
function bodies, and the two tied chunks have names and paths of equal token length."""

from __future__ import annotations

from pathlib import Path

import pytest

from code_atlas.lexical.retriever import BM25Retriever

FILES = {
    "a.py": "def f():\n    return frobnicate()\n",
    "b.py": "def g():\n    return frobnicate()\n",
    "c.py": "def parse_header(raw):\n    return raw.split(':')\n",
}


@pytest.fixture
def retriever(tmp_path: Path) -> BM25Retriever:
    for name, text in FILES.items():
        (tmp_path / name).write_text(text)
    return BM25Retriever(tmp_path)


def test_level_is_chunk(retriever: BM25Retriever) -> None:
    assert retriever.level == "chunk"


def test_matching_chunk_ranks_first(retriever: BM25Retriever) -> None:
    hits = retriever.search("the header is broken", k=10)
    assert [h.id for h in hits] == ["c.py::parse_header"]


def test_ties_broken_by_chunk_id(retriever: BM25Retriever) -> None:
    hits = retriever.search("frobnicate fails", k=10)
    assert [h.id for h in hits] == ["a.py::f", "b.py::g"]
    assert hits[0].score == pytest.approx(hits[1].score)


def test_returns_at_most_k(retriever: BM25Retriever) -> None:
    assert len(retriever.search("frobnicate fails", k=1)) == 1


def test_scores_are_descending(retriever: BM25Retriever) -> None:
    scores = [h.score for h in retriever.search("frobnicate the raw header", k=10)]
    assert scores == sorted(scores, reverse=True)


def test_no_matching_token_returns_nothing(retriever: BM25Retriever) -> None:
    assert retriever.search("zzz qqq", k=10) == []

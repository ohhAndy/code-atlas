"""Tests for SemanticRetriever on a fake three-file repo with a fake embedder. Expected
values are computed by hand; the arithmetic is in the comments.

The fake embedder (tests/semantic/fakes.py) maps a text to
(count of "frobnicate", count of "header", count of "raw", 0.1), counting tokens from the
BM25 tokenizer. Each file holds one function, so there are no module chunks. Chunk vectors:
    a.py::f            "a.py f / def f(): return frobnicate()"      -> (1, 0, 0, 0.1)
    b.py::g            same shape as f                               -> (1, 0, 0, 0.1)
    c.py::parse_header parse_header x2 gives header x2; raw x2       -> (0, 2, 2, 0.1)
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from code_atlas.semantic.retriever import SemanticRetriever
from tests.semantic.fakes import FakeEmbedder

FILES = {
    "a.py": "def f():\n    return frobnicate()\n",
    "b.py": "def g():\n    return frobnicate()\n",
    "c.py": "def parse_header(raw):\n    return raw.split(':')\n",
}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    for name, text in FILES.items():
        (repo / name).write_text(text)
    return repo


@pytest.fixture
def retriever(repo: Path) -> SemanticRetriever:
    return SemanticRetriever(repo, FakeEmbedder())


def test_level_is_chunk(retriever: SemanticRetriever) -> None:
    assert retriever.level == "chunk"


def test_hand_computed_ranking_and_scores(retriever: SemanticRetriever) -> None:
    # Query "the header is broken" -> q = (0, 1, 0, 0.1), |q| = sqrt(1.01).
    #   c: (0*0 + 2*1 + 2*0 + 0.1*0.1) / (sqrt(8.01) * sqrt(1.01)) = 2.01 / 2.8443 ~ 0.7067
    #   a, b: 0.01 / (sqrt(1.01) * sqrt(1.01)) = 0.01 / 1.01 ~ 0.0099
    hits = retriever.search("the header is broken", k=10)
    assert [h.id for h in hits] == ["c.py::parse_header", "a.py::f", "b.py::g"]
    assert hits[0].score == pytest.approx(2.01 / math.sqrt(8.01 * 1.01), abs=1e-5)
    assert hits[1].score == pytest.approx(0.01 / 1.01, abs=1e-5)


def test_ties_keep_chunk_order(retriever: SemanticRetriever) -> None:
    # f and g have identical vectors; f's row comes first.
    hits = retriever.search("frobnicate fails", k=10)
    assert [h.id for h in hits[:2]] == ["a.py::f", "b.py::g"]
    assert hits[0].score == pytest.approx(hits[1].score)


def test_returns_at_most_k(retriever: SemanticRetriever) -> None:
    assert len(retriever.search("frobnicate fails", k=1)) == 1


def test_scores_chunks_that_share_no_word_with_the_query(retriever: SemanticRetriever) -> None:
    # Unlike BM25, every chunk gets a cosine score, so k hits come back even with no
    # shared word. q = (0, 0, 0, 0.1): every chunk scores > 0 through the bias dimension.
    assert len(retriever.search("zzz qqq", k=10)) == 3


def test_scores_are_cosines_in_descending_order(retriever: SemanticRetriever) -> None:
    scores = [h.score for h in retriever.search("frobnicate the raw header", k=10)]
    assert scores == sorted(scores, reverse=True)
    assert all(-1.0 - 1e-6 <= s <= 1.0 + 1e-6 for s in scores)


def test_query_goes_through_embed_query(repo: Path) -> None:
    embedder = FakeEmbedder()
    SemanticRetriever(repo, embedder).search("raw header", k=10)
    assert embedder.queries_embedded == ["raw header"]
    assert "raw header" not in embedder.documents_embedded


def test_empty_repo_returns_nothing(tmp_path: Path) -> None:
    assert SemanticRetriever(tmp_path, FakeEmbedder()).search("header", k=10) == []


def test_second_build_reads_the_cache(repo: Path, tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    SemanticRetriever(repo, FakeEmbedder(), cache_dir=cache_dir)
    embedder = FakeEmbedder()
    cached = SemanticRetriever(repo, embedder, cache_dir=cache_dir)
    assert embedder.documents_embedded == []
    assert [h.id for h in cached.search("the header is broken", k=1)] == ["c.py::parse_header"]


def test_test_files_are_excluded_unless_asked(repo: Path) -> None:
    (repo / "tests").mkdir()
    (repo / "tests" / "test_a.py").write_text("def test_f():\n    assert frobnicate()\n")
    assert "tests/test_a.py::test_f" not in SemanticRetriever(repo, FakeEmbedder()).ids
    with_tests = SemanticRetriever(repo, FakeEmbedder(), include_tests=True)
    assert "tests/test_a.py::test_f" in with_tests.ids

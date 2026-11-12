"""Tests for the embedding cache, with a fake embedder in a temporary directory."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest

from code_atlas.semantic.cache import (
    EmbeddingCache,
    cache_path,
    embed_with_cache,
    text_key,
)
from code_atlas.semantic.search import Vectors
from tests.semantic.fakes import FakeEmbedder, bag_of_words


def test_vectors_match_the_embedder_in_input_order(tmp_path: Path) -> None:
    texts = ["raw raw", "header", "frobnicate"]
    with EmbeddingCache(tmp_path / "c.sqlite") as cache:
        vectors = embed_with_cache(FakeEmbedder(), texts, cache)
    np.testing.assert_allclose(vectors, [bag_of_words(t) for t in texts], rtol=1e-6)
    assert vectors.dtype == np.float32


def test_second_call_embeds_nothing(tmp_path: Path) -> None:
    texts = ["raw", "header"]
    path = tmp_path / "c.sqlite"
    with EmbeddingCache(path) as cache:
        first = embed_with_cache(FakeEmbedder(), texts, cache)
    embedder = FakeEmbedder()
    with EmbeddingCache(path) as cache:  # reopened: the vectors are on disk
        second = embed_with_cache(embedder, texts, cache)
    assert embedder.documents_embedded == []
    assert second.tolist() == first.tolist()


def test_only_new_texts_are_embedded(tmp_path: Path) -> None:
    with EmbeddingCache(tmp_path / "c.sqlite") as cache:
        embed_with_cache(FakeEmbedder(), ["raw", "header"], cache)
        embedder = FakeEmbedder()
        embed_with_cache(embedder, ["header", "frobnicate", "raw"], cache)
    assert embedder.documents_embedded == ["frobnicate"]


def test_repeated_text_is_embedded_once(tmp_path: Path) -> None:
    embedder = FakeEmbedder()
    with EmbeddingCache(tmp_path / "c.sqlite") as cache:
        vectors = embed_with_cache(embedder, ["raw", "raw", "header"], cache)
    assert embedder.documents_embedded == ["raw", "header"]
    assert vectors.shape == (3, 4)
    assert vectors[0].tolist() == vectors[1].tolist()


def test_key_includes_the_model_id(tmp_path: Path) -> None:
    assert text_key("a@1", "raw") != text_key("a@2", "raw")
    with EmbeddingCache(tmp_path / "c.sqlite") as cache:
        embed_with_cache(FakeEmbedder("a@1"), ["raw"], cache)
        other = FakeEmbedder("a@2")
        embed_with_cache(other, ["raw"], cache)
    assert other.documents_embedded == ["raw"]


def test_one_file_per_model() -> None:
    a = cache_path(Path("/c"), "Qwen/Qwen3-Embedding-0.6B@97b0c61")
    b = cache_path(Path("/c"), "voyage-code-4")
    assert a != b
    assert a.parent == Path("/c") and "/" not in a.name


def test_batches_and_progress(tmp_path: Path) -> None:
    calls: list[tuple[int, int]] = []
    texts = [f"raw {i}" for i in range(5)]
    with EmbeddingCache(tmp_path / "c.sqlite") as cache:
        embed_with_cache(
            FakeEmbedder(), texts, cache, batch_size=2, progress=lambda d, t: calls.append((d, t))
        )
    assert calls == [(2, 5), (4, 5), (5, 5)]


class FailsOnSecondBatch(FakeEmbedder):
    def __init__(self) -> None:
        super().__init__()
        self.batches = 0

    def embed_documents(self, texts: Sequence[str]) -> Vectors:
        self.batches += 1
        if self.batches == 2:
            raise RuntimeError("simulated crash")
        return super().embed_documents(texts)


def test_interrupted_run_keeps_finished_batches(tmp_path: Path) -> None:
    path = tmp_path / "c.sqlite"
    with EmbeddingCache(path) as cache, pytest.raises(RuntimeError):
        embed_with_cache(FailsOnSecondBatch(), ["raw", "header", "frobnicate"], cache, batch_size=2)
    with EmbeddingCache(path) as cache:
        assert len(cache) == 2
        embedder = FakeEmbedder()
        embed_with_cache(embedder, ["raw", "header", "frobnicate"], cache)
    assert embedder.documents_embedded == ["frobnicate"]


def test_no_texts(tmp_path: Path) -> None:
    with EmbeddingCache(tmp_path / "c.sqlite") as cache:
        assert embed_with_cache(FakeEmbedder(), [], cache).shape[0] == 0


def test_lookup_of_many_keys(tmp_path: Path) -> None:
    # More keys than one SELECT takes, so the lookup is split.
    texts = [f"raw {i}" for i in range(1200)]
    with EmbeddingCache(tmp_path / "c.sqlite") as cache:
        embed_with_cache(FakeEmbedder(), texts, cache)
        embedder = FakeEmbedder()
        assert embed_with_cache(embedder, texts, cache).shape == (1200, 4)
    assert embedder.documents_embedded == []

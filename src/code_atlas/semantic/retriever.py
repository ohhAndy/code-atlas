"""Semantic chunk retriever: one embedding matrix per snapshot, brute-force cosine search."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from code_atlas.parse.chunks import chunk_file
from code_atlas.parse.files import iter_corpus_files
from code_atlas.semantic.cache import EmbeddingCache, cache_path, embed_with_cache
from code_atlas.semantic.embed import Embedder, embedded_text
from code_atlas.semantic.search import normalize, top_k
from code_atlas.types import Hit, Level


def _report(done: int, total: int) -> None:
    print(f"  embedded {done}/{total} new chunks", file=sys.stderr)


class SemanticRetriever:
    """Chunk-level retriever. The constructor chunks every corpus file, embeds each chunk's
    text (through the on-disk cache when `cache_dir` is given) and stores the unit-normalized
    matrix, row i = chunk `ids[i]`. `search` only embeds the query and scores against it.

    `include_tests=True` also indexes files in `tests` directories; it exists only to
    measure what excluding them changes.
    """

    level: Level = "chunk"

    def __init__(
        self,
        repo_dir: Path,
        embedder: Embedder,
        *,
        cache_dir: Path | None = None,
        include_tests: bool = False,
    ) -> None:
        self.embedder = embedder
        chunks = [
            c
            for path, src in iter_corpus_files(repo_dir, include_tests=include_tests)
            for c in chunk_file(path, src)
        ]
        self.ids = [c.id for c in chunks]
        texts = [embedded_text(c) for c in chunks]
        if cache_dir is None:
            vectors = embedder.embed_documents(texts) if texts else np.zeros((0, 0), np.float32)
        else:
            with EmbeddingCache(cache_path(cache_dir, embedder.model_id)) as cache:
                vectors = embed_with_cache(embedder, texts, cache, progress=_report)
        # Normalized once here, so each search is a single matrix-vector product.
        self.matrix = normalize(vectors)

    def search(self, query: str, k: int) -> list[Hit]:
        """Top k chunk ids by cosine similarity with the query, best first; ties broken by
        row order. Every chunk has a score, so this returns min(k, number of chunks) hits."""
        if k < 1:
            raise ValueError(f"k must be >= 1, got {k}")
        if not self.ids:
            return []

        q_vec = normalize(self.embedder.embed_query(query))
        matches = top_k(self.matrix, q_vec, k)
        return [Hit(id=self.ids[idx], score=score) for idx, score in matches]

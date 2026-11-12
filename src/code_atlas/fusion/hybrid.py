"""Hybrid chunk retriever: reciprocal rank fusion of two chunk retrievers."""

from __future__ import annotations

from code_atlas.fusion.rrf import rrf
from code_atlas.types import Hit, Level, Retriever

DEPTH = 100  # chunks each retriever contributes before fusion


class HybridRetriever:
    """Fuses the rankings of two chunk retrievers (BM25 and semantic search) with RRF.

    Both retrievers are already built for the same snapshot; this class does no indexing
    of its own. Each contributes its top `depth` chunks; a chunk missing from one list
    gets nothing from it.
    """

    level: Level = "chunk"

    def __init__(
        self, first: Retriever, second: Retriever, *, rrf_k: int = 60, depth: int = DEPTH
    ) -> None:
        if first.level != "chunk" or second.level != "chunk":
            raise ValueError("both retrievers must rank chunks")
        self.first = first
        self.second = second
        self.rrf_k = rrf_k
        self.depth = depth

    def search(self, query: str, k: int) -> list[Hit]:
        """Top k chunk ids by fused RRF score, best first; ties broken by chunk id. The
        hit's score is the fused score."""
        if k < 1:
            raise ValueError(f"k must be >= 1, got {k}")

        first_hits = self.first.search(query, self.depth)
        second_hits = self.second.search(query, self.depth)

        fused = rrf(
            [
                [hit.id for hit in first_hits],
                [hit.id for hit in second_hits],
            ],
            k=self.rrf_k,
        )

        ranked = sorted(fused.items(), key=lambda item: (-item[1], item[0]))[:k]
        return [Hit(id=chunk_id, score=score) for chunk_id, score in ranked]

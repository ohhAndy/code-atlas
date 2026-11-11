"""BM25 chunk retriever: one inverted index per snapshot."""

from __future__ import annotations

from pathlib import Path

from code_atlas.lexical.bm25 import bm25_scores
from code_atlas.lexical.index import InvertedIndex, build_index
from code_atlas.lexical.tokenizer import tokenize
from code_atlas.parse.chunks import Chunk, chunk_file
from code_atlas.parse.files import iter_corpus_files
from code_atlas.types import Hit, Level


def document_tokens(chunk: Chunk) -> list[str]:
    """The tokens indexed for one chunk."""
    full_text = f"{chunk.path} {chunk.qualified_name}\n{chunk.text}"
    return tokenize(full_text)


class BM25Retriever:
    """Chunk-level retriever. The constructor chunks every corpus file of the snapshot and
    builds the inverted index once; `search` only scores against it."""

    level: Level = "chunk"

    def __init__(self, repo_dir: Path, k1: float = 1.2, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        docs: dict[str, list[str]] = {}
        for path, source in iter_corpus_files(repo_dir):
            for chunk in chunk_file(path, source):
                docs[chunk.id] = document_tokens(chunk)
        self.index: InvertedIndex = build_index(docs)

    def search(self, query: str, k: int) -> list[Hit]:
        """Top k chunk ids by BM25 score, best first; ties broken by chunk id so results
        are reproducible. Chunks that match no query token are never returned."""
        scores = bm25_scores(self.index, tokenize(query), k1=self.k1, b=self.b)
        # Sort descending by score (-score), then ascending by chunk_id for deterministic ties
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:k]
        return [Hit(id=chunk_id, score=score) for chunk_id, score in ranked]

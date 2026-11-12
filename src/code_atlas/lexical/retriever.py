"""BM25 chunk retriever: one inverted index per snapshot."""

from __future__ import annotations

from pathlib import Path

from code_atlas.lexical.bm25 import bm25_scores
from code_atlas.lexical.cache import load_or_build
from code_atlas.lexical.index import InvertedIndex, build_index
from code_atlas.lexical.tokenizer import tokenize
from code_atlas.parse.chunks import Chunk, chunk_file
from code_atlas.parse.files import iter_corpus_files
from code_atlas.types import Hit, Level


def document_tokens(chunk: Chunk, with_path_and_name: bool = True) -> list[str]:
    """The tokens indexed for one chunk: its path, qualified name and text, or the text
    alone when `with_path_and_name` is False."""
    if not with_path_and_name:
        return tokenize(chunk.text)
    full_text = f"{chunk.path} {chunk.qualified_name}\n{chunk.text}"
    return tokenize(full_text)


def build_snapshot_index(
    repo_dir: Path, with_path_and_name: bool = True, *, include_tests: bool = False
) -> InvertedIndex:
    """Chunk every corpus file under `repo_dir` and index the chunks' tokens."""
    docs: dict[str, list[str]] = {}
    for path, source in iter_corpus_files(repo_dir, include_tests=include_tests):
        for chunk in chunk_file(path, source):
            docs[chunk.id] = document_tokens(chunk, with_path_and_name)
    return build_index(docs)


class BM25Retriever:
    """Chunk-level retriever. The constructor builds the snapshot's inverted index once (or
    loads it from `cache_dir`, if given); `search` only scores against it.

    `with_path_and_name=False` indexes chunk text alone. It exists only to measure how much
    indexing paths and qualified names changes the scores. `include_tests=True` also
    indexes files in `tests` directories; it exists only to measure what excluding them
    changes.
    """

    level: Level = "chunk"

    def __init__(
        self,
        repo_dir: Path,
        k1: float = 1.2,
        b: float = 0.75,
        *,
        with_path_and_name: bool = True,
        cache_dir: Path | None = None,
        include_tests: bool = False,
    ) -> None:
        self.k1 = k1
        self.b = b

        def build() -> InvertedIndex:
            return build_snapshot_index(repo_dir, with_path_and_name, include_tests=include_tests)

        if cache_dir is None:
            self.index = build()
        else:
            variant = "path-name-text" if with_path_and_name else "text"
            if include_tests:
                variant += "-with-tests"
            self.index = load_or_build(repo_dir, variant, build, cache_dir)

    def search(self, query: str, k: int) -> list[Hit]:
        """Top k chunk ids by BM25 score, best first; ties broken by chunk id so results
        are reproducible. Chunks that match no query token are never returned."""
        scores = bm25_scores(self.index, tokenize(query), k1=self.k1, b=self.b)
        # Sort descending by score (-score), then ascending by chunk_id for deterministic ties
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:k]
        return [Hit(id=chunk_id, score=score) for chunk_id, score in ranked]

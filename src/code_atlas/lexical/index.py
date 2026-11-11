"""Inverted index over tokenized chunks: the statistics BM25 needs."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class InvertedIndex:
    """Token -> postings, plus document lengths.

    postings:       token -> [(chunk id, term frequency)], one entry per chunk that contains
                    the token. Document frequency of a token = len(postings[token]).
    doc_lengths:    chunk id -> number of tokens in that chunk, counting duplicates.
    avg_doc_length: mean of doc_lengths.
    """

    postings: dict[str, list[tuple[str, int]]]
    doc_lengths: dict[str, int]
    avg_doc_length: float

    @property
    def num_docs(self) -> int:
        return len(self.doc_lengths)


def build_index(docs: Mapping[str, list[str]]) -> InvertedIndex:
    """Build an inverted index from chunk id -> that chunk's tokens."""
    postings: dict[str, list[tuple[str, int]]] = defaultdict(list)
    doc_lengths: dict[str, int] = {}
    total_tokens = 0

    for chunk_id, tokens in docs.items():
        doc_len = len(tokens)
        doc_lengths[chunk_id] = doc_len
        total_tokens += doc_len

        # Count term frequency within the document
        counts = Counter(tokens)
        for token, tf in counts.items():
            postings[token].append((chunk_id, tf))

    num_docs = len(doc_lengths)
    avg_doc_length = (total_tokens / num_docs) if num_docs > 0 else 0.0

    return InvertedIndex(
        postings=dict(postings),
        doc_lengths=doc_lengths,
        avg_doc_length=avg_doc_length,
    )

"""Tests for build_index on a three-chunk corpus with hand-computed statistics. Postings
are compared as dicts (chunk id -> tf) because BM25 does not use their order."""

from __future__ import annotations

from code_atlas.lexical.index import InvertedIndex, build_index

DOCS = {
    "d1": ["get", "create", "object", "create"],
    "d2": ["get", "value"],
    "d3": ["delete", "object", "value"],
}


def postings_of(index: InvertedIndex, token: str) -> dict[str, int]:
    return dict(index.postings.get(token, []))


def test_postings_hold_term_frequency_per_chunk() -> None:
    index = build_index(DOCS)
    assert postings_of(index, "create") == {"d1": 2}
    assert postings_of(index, "object") == {"d1": 1, "d3": 1}
    assert postings_of(index, "get") == {"d1": 1, "d2": 1}
    assert postings_of(index, "value") == {"d2": 1, "d3": 1}
    assert postings_of(index, "delete") == {"d3": 1}


def test_vocabulary_is_exactly_the_tokens_seen() -> None:
    index = build_index(DOCS)
    assert set(index.postings) == {"get", "create", "object", "value", "delete"}


def test_unknown_token_has_no_postings() -> None:
    assert postings_of(build_index(DOCS), "missing") == {}


def test_doc_lengths_count_duplicates() -> None:
    index = build_index(DOCS)
    assert index.doc_lengths == {"d1": 4, "d2": 2, "d3": 3}
    assert index.num_docs == 3


def test_average_doc_length() -> None:
    assert build_index(DOCS).avg_doc_length == 3.0


def test_empty_corpus_has_zero_average_length() -> None:
    """An empty corpus has no postings, so nothing is ever scored against the 0.0."""
    index = build_index({})
    assert index.postings == {}
    assert index.num_docs == 0
    assert index.avg_doc_length == 0.0

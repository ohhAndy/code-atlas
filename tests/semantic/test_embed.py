"""Tests for the embedding client code that needs no model download or API key: the
embedded text, request batching, and the Voyage client against a fake API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from code_atlas.lexical.retriever import document_tokens
from code_atlas.lexical.tokenizer import tokenize
from code_atlas.parse.chunks import chunk_file
from code_atlas.semantic.embed import (
    QWEN_QUERY_PROMPT,
    VOYAGE_INPUT_LIMIT,
    VOYAGE_MODEL,
    VoyageEmbedder,
    embedded_text,
    token_batches,
)

SOURCE = b"class QuerySet:\n    def get_or_create(self):\n        return 1\n"

# --- embedded_text ------------------------------------------------------------------------


def test_embedded_text_is_the_text_bm25_indexes() -> None:
    for chunk in chunk_file("django/db/models/query.py", SOURCE):
        assert tokenize(embedded_text(chunk)) == document_tokens(chunk)


def test_embedded_text_starts_with_path_and_name() -> None:
    method = next(
        c for c in chunk_file("app/q.py", SOURCE) if c.qualified_name == "QuerySet.get_or_create"
    )
    assert embedded_text(method).startswith("app/q.py QuerySet.get_or_create\n")


def test_qwen_query_prompt_uses_the_documented_format() -> None:
    # Qwen3-Embedding's own prompt is "Instruct: <task>\nQuery:"; only the task changes.
    assert QWEN_QUERY_PROMPT.startswith("Instruct: ")
    assert QWEN_QUERY_PROMPT.endswith("\nQuery:")
    assert "web search" not in QWEN_QUERY_PROMPT


# --- token_batches ------------------------------------------------------------------------


def test_batches_split_on_token_budget() -> None:
    # 4 + 4 = 8 fits a budget of 10; adding 4 more would make 12, so a new batch starts.
    assert token_batches([4, 4, 4, 4], max_texts=100, max_tokens=10) == [range(0, 2), range(2, 4)]


def test_batches_split_on_text_count() -> None:
    assert token_batches([1] * 5, max_texts=2, max_tokens=100) == [
        range(0, 2),
        range(2, 4),
        range(4, 5),
    ]


def test_oversized_text_gets_its_own_batch() -> None:
    assert token_batches([2, 50, 2], max_texts=100, max_tokens=10) == [
        range(0, 1),
        range(1, 2),
        range(2, 3),
    ]


def test_batches_cover_every_text_once_in_order() -> None:
    counts = [3, 7, 1, 9, 2, 2, 8, 5]
    batches = token_batches(counts, max_texts=3, max_tokens=10)
    assert [i for b in batches for i in b] == list(range(len(counts)))
    assert all(len(b) <= 3 and sum(counts[i] for i in b) <= 10 for b in batches)


def test_no_texts_no_batches() -> None:
    assert token_batches([], max_texts=10, max_tokens=10) == []


# --- VoyageEmbedder against a fake API -------------------------------------------------------


@dataclass
class FakeEncoding:
    ids: list[int]


@dataclass
class FakeResult:
    embeddings: list[list[float]]
    total_tokens: int


@dataclass
class FakeVoyage:
    """Tokens = whitespace-separated words; the vector of a text is (number of words,
    1 if embedded as a query else 0)."""

    calls: list[tuple[list[str], str]] = field(default_factory=list)

    def tokenize(self, texts: list[str], model: str) -> list[FakeEncoding]:
        assert model == VOYAGE_MODEL
        return [FakeEncoding(ids=[0] * len(t.split())) for t in texts]

    def embed(self, texts: list[str], **kwargs: Any) -> FakeResult:
        assert kwargs["model"] == VOYAGE_MODEL
        input_type = kwargs["input_type"]
        self.calls.append((texts, input_type))
        flag = 1.0 if input_type == "query" else 0.0
        return FakeResult(
            embeddings=[[float(len(t.split())), flag] for t in texts],
            total_tokens=sum(len(t.split()) for t in texts),
        )


def test_documents_and_queries_use_their_input_type() -> None:
    fake = FakeVoyage()
    embedder = VoyageEmbedder(client=fake)
    docs = embedder.embed_documents(["a b", "c"])
    query = embedder.embed_query("x y z")
    assert docs.tolist() == [[2.0, 0.0], [1.0, 0.0]]
    assert query.tolist() == [3.0, 1.0]
    assert [t for _, t in fake.calls] == ["document", "query"]


def test_vectors_are_float32_rows_in_input_order() -> None:
    texts = [" ".join(["w"] * n) for n in (3, 1, 2)]
    vectors = VoyageEmbedder(client=FakeVoyage()).embed_documents(texts)
    assert vectors.dtype == np.float32
    assert vectors[:, 0].tolist() == [3.0, 1.0, 2.0]


def test_large_input_is_sent_in_several_requests_and_billed() -> None:
    # Each text is at the input limit, so a 120k-token request holds 3 of them.
    fake = FakeVoyage()
    embedder = VoyageEmbedder(client=fake)
    texts = [" ".join(["w"] * VOYAGE_INPUT_LIMIT)] * 7
    vectors = embedder.embed_documents(texts)
    assert vectors.shape == (7, 2)
    assert [len(batch) for batch, _ in fake.calls] == [3, 3, 1]
    assert embedder.tokens_billed == 7 * VOYAGE_INPUT_LIMIT


def test_no_documents_makes_no_request() -> None:
    fake = FakeVoyage()
    assert VoyageEmbedder(client=fake).embed_documents([]).shape[0] == 0
    assert fake.calls == []

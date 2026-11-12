"""A deterministic fake embedder for tests: no model download, hand-computable vectors."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from code_atlas.lexical.tokenizer import tokenize
from code_atlas.semantic.search import Vectors

VOCAB = ("frobnicate", "header", "raw")
BIAS = 0.1  # a constant last dimension, so no text maps to the zero vector


def bag_of_words(text: str) -> list[float]:
    """Counts of each VOCAB token in `tokenize(text)`, then BIAS."""
    tokens = tokenize(text)
    return [float(tokens.count(word)) for word in VOCAB] + [BIAS]


class FakeEmbedder:
    def __init__(self, model_id: str = "fake@1") -> None:
        self.model_id = model_id
        self.max_tokens = 10_000
        self.documents_embedded: list[str] = []
        self.queries_embedded: list[str] = []

    def embed_documents(self, texts: Sequence[str]) -> Vectors:
        self.documents_embedded.extend(texts)
        return np.array([bag_of_words(t) for t in texts], dtype=np.float32)

    def embed_query(self, text: str) -> Vectors:
        self.queries_embedded.append(text)
        return np.array(bag_of_words(text), dtype=np.float32)

    def count_tokens(self, texts: Sequence[str]) -> list[int]:
        return [len(tokenize(t)) for t in texts]

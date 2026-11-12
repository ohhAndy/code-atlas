"""Embedding clients: turn chunk text and queries into vectors with a pretrained model.

Both clients return raw float32 vectors, one row per text; normalizing is the caller's job
(`code_atlas.semantic.search.normalize`). Both models embed a query differently from a
document, so queries must go through `embed_query`, never `embed_documents`.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any, Protocol

import numpy as np

from code_atlas.parse.chunks import Chunk
from code_atlas.semantic.search import Vectors

QWEN_MODEL = "Qwen/Qwen3-Embedding-0.6B"
# Pinned Hugging Face commit, so the weights cannot change under the results.
QWEN_REVISION = "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"
# Prepended to every query (documents get nothing), in the model's documented
# "Instruct: <task>\nQuery:" format. Fixed before any retrieval run; changing it changes
# every query vector, so it is a new method with its own runs.
QWEN_TASK = (
    "Given a GitHub issue describing a bug, retrieve the Python code that must be changed to fix it"
)
QWEN_QUERY_PROMPT = f"Instruct: {QWEN_TASK}\nQuery:"

VOYAGE_MODEL = "voyage-code-4"
VOYAGE_INPUT_LIMIT = 32_000  # tokens per text; longer texts are truncated by the API
# Per-request limits. 1000 texts is documented; 120k total tokens is the documented limit
# for earlier Voyage code models, used here as a conservative bound.
VOYAGE_MAX_TEXTS = 1000
VOYAGE_MAX_TOKENS = 120_000


def embedded_text(chunk: Chunk) -> str:
    """The text embedded for one chunk: path, qualified name and chunk text, the same text
    the BM25 retriever indexes."""
    return f"{chunk.path} {chunk.qualified_name}\n{chunk.text}"


class Embedder(Protocol):
    model_id: str  # model name plus pinned version; part of every cache key
    max_tokens: int  # input limit per text; longer texts are truncated

    def embed_documents(self, texts: Sequence[str]) -> Vectors: ...

    def embed_query(self, text: str) -> Vectors: ...

    def count_tokens(self, texts: Sequence[str]) -> list[int]: ...


def token_batches(token_counts: Sequence[int], max_texts: int, max_tokens: int) -> list[range]:
    """Split texts, in order, into consecutive batches of at most `max_texts` texts and at
    most `max_tokens` total tokens. A single text over `max_tokens` gets a batch of its own.
    """
    batches: list[range] = []
    start = 0
    total = 0
    for i, count in enumerate(token_counts):
        if i > start and (i - start == max_texts or total + count > max_tokens):
            batches.append(range(start, i))
            start, total = i, 0
        total += count
    if start < len(token_counts):
        batches.append(range(start, len(token_counts)))
    return batches


class QwenEmbedder:
    """Qwen3-Embedding-0.6B, run locally with sentence-transformers (MPS on Apple silicon
    when available). Queries get `query_prompt` prepended; documents get nothing."""

    def __init__(
        self,
        *,
        device: str | None = None,
        batch_size: int = 16,
        query_prompt: str = QWEN_QUERY_PROMPT,
    ) -> None:
        # Imported here: torch and transformers take seconds to import, and nothing else
        # in the package needs them.
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(QWEN_MODEL, revision=QWEN_REVISION, device=device)
        self.model_id = f"{QWEN_MODEL}@{QWEN_REVISION}"
        max_tokens = self.model.max_seq_length
        if max_tokens is None:
            raise RuntimeError(f"{QWEN_MODEL} reports no input limit")
        self.max_tokens = max_tokens
        self.batch_size = batch_size
        self.query_prompt = query_prompt

    def _encode(self, texts: Sequence[str], prompt: str) -> Vectors:
        vectors = self.model.encode(
            list(texts),
            prompt=prompt,
            batch_size=self.batch_size,
            convert_to_numpy=True,
            normalize_embeddings=False,
        )
        return np.asarray(vectors, dtype=np.float32)

    def embed_documents(self, texts: Sequence[str]) -> Vectors:
        return self._encode(texts, prompt="")

    def embed_query(self, text: str) -> Vectors:
        return np.asarray(self._encode([text], prompt=self.query_prompt)[0], dtype=np.float32)

    def count_tokens(self, texts: Sequence[str]) -> list[int]:
        ids = self.model.tokenizer(list(texts), add_special_tokens=True)["input_ids"]
        return [len(x) for x in ids]


class VoyageEmbedder:
    """voyage-code-4 through Voyage's API. Needs `VOYAGE_API_KEY` in the environment (or an
    explicit key). Token counting uses Voyage's tokenizer locally and needs no key.

    `tokens_billed` adds up the token counts the API reports, for cost accounting.
    """

    def __init__(self, *, api_key: str | None = None, client: Any = None) -> None:
        if client is None:
            from voyageai.client import Client

            client = Client(api_key=api_key or os.environ.get("VOYAGE_API_KEY"), max_retries=3)
        self.client = client
        self.model_id = VOYAGE_MODEL
        self.max_tokens = VOYAGE_INPUT_LIMIT
        self.tokens_billed = 0

    def _embed(self, texts: Sequence[str], input_type: str) -> Vectors:
        # Texts over the input limit are truncated by the API, so they count as the limit.
        counts = [min(c, self.max_tokens) for c in self.count_tokens(texts)]
        rows: list[list[float]] = []
        for batch in token_batches(counts, VOYAGE_MAX_TEXTS, VOYAGE_MAX_TOKENS):
            result = self.client.embed(
                [texts[i] for i in batch],
                model=VOYAGE_MODEL,
                input_type=input_type,
                truncation=True,
            )
            rows.extend(result.embeddings)
            self.tokens_billed += result.total_tokens
        return np.asarray(rows, dtype=np.float32)

    def embed_documents(self, texts: Sequence[str]) -> Vectors:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        return self._embed(texts, input_type="document")

    def embed_query(self, text: str) -> Vectors:
        return np.asarray(self._embed([text], input_type="query")[0], dtype=np.float32)

    def count_tokens(self, texts: Sequence[str]) -> list[int]:
        return [len(enc.ids) for enc in self.client.tokenize(list(texts), model=VOYAGE_MODEL)]

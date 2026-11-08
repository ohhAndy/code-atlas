"""Shared types for retrievers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

Level = Literal["file", "chunk"]


@dataclass(frozen=True)
class Hit:
    """One ranked result. `id` is a repo-relative file path or a chunk id ("path::Name")."""

    id: str
    score: float


class Retriever(Protocol):
    """Built once per snapshot (the constructor does any indexing), then searched.

    `level` says what kind of ids `search` returns, so the runner scores them against the
    matching gold: "file" -> file gold; "chunk" -> function gold (and file gold via
    `files_from_chunks`).
    """

    level: Level

    def search(self, query: str, k: int) -> list[Hit]:
        """Return at most `k` hits, best first, with no duplicate ids."""
        ...

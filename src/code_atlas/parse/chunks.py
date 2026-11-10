"""Turn a file into chunks: one per definition, plus the module (top-level code)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from code_atlas.parse.definitions import Definition, extract_definitions

MODULE_NAME = "<module>"

ChunkKind = Literal["function", "method", "class", "module"]
Span = tuple[str, int, int]  # (name, start_line, end_line), 1-based inclusive


@dataclass(frozen=True)
class Chunk:
    """One retrievable unit. `text` holds only the lines this chunk owns: a class chunk
    has no method lines, the module chunk has no definition lines."""

    id: str  # "path::name", e.g. "pkg/models.py::Session.request"
    path: str  # repo-relative
    qualified_name: str  # e.g. "Session.request", "C.name#2", "<module>"
    kind: ChunkKind
    start_line: int
    end_line: int
    text: str
    content_hash: str  # sha256 of text


def chunk_spans(source: bytes) -> list[Span]:
    """(name, start_line, end_line) for every chunk, 1-based and inclusive.

    "<module>" comes first and spans the whole file; then each definition in source
    order. Duplicate names get "#2", "#3", ... in source order. Empty source -> [].
    """
    if not source:
        return []
    return _spans(source, extract_definitions(source))


def _spans(source: bytes, definitions: list[Definition]) -> list[Span]:
    total_lines = len(source.splitlines())
    spans: list[Span] = [(MODULE_NAME, 1, total_lines)]

    counts: dict[str, int] = {}
    for d in definitions:
        count = counts.get(d.qualified_name, 0) + 1
        counts[d.qualified_name] = count
        name = d.qualified_name if count == 1 else f"{d.qualified_name}#{count}"
        spans.append((name, d.start_line, d.end_line))

    return spans


def owner(line: int, spans: list[Span]) -> str | None:
    """spans: (name, start_line, end_line), 1-based inclusive.
    Return the name of the smallest span containing `line`, or None if no span contains it
    (e.g. a pure insertion at the end of a file records a line past the last one).

    spans must list a container before anything inside it (source order, as chunk_spans
    returns them): on a tie in length, the later span is the inner one and wins."""
    containing = [span for span in reversed(spans) if span[1] <= line <= span[2]]
    best = min(containing, key=lambda span: span[2] - span[1], default=None)
    return best[0] if best is not None else None


def chunk_texts(source: bytes, spans: list[Span]) -> dict[str, str]:
    """{span name: the text of the lines that span owns}, for every span.

    A line belongs to exactly one chunk (see `owner`), so the texts of all chunks together
    contain every line of the file exactly once.
    """
    buckets: dict[str, list[str]] = {name: [] for name, _, _ in spans}
    lines = source.splitlines(keepends=True)

    for line_no, line in enumerate(lines, start=1):
        span_name = owner(line_no, spans)
        if span_name is not None:
            buckets[span_name].append(line.decode("utf-8", errors="replace"))

    return {name: "".join(owned_lines) for name, owned_lines in buckets.items()}


def chunk_file(path: str, source: bytes) -> list[Chunk]:
    """All chunks of one file, module chunk first. The module chunk is left out if its
    text is only whitespace (e.g. an empty `__init__.py`, or a file that is one class)."""
    if not source:
        return []
    definitions = extract_definitions(source)
    spans = _spans(source, definitions)
    kinds: list[ChunkKind] = ["module", *(d.kind for d in definitions)]
    texts = chunk_texts(source, spans)

    chunks: list[Chunk] = []
    for (name, start, end), kind in zip(spans, kinds, strict=True):
        text = texts[name]
        if kind == "module" and not text.strip():
            continue
        chunks.append(
            Chunk(
                id=f"{path}::{name}",
                path=path,
                qualified_name=name,
                kind=kind,
                start_line=start,
                end_line=end,
                text=text,
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
        )
    return chunks

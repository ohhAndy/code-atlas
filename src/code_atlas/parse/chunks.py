"""Turn a file's definitions into chunk spans: one per definition, plus the module."""

from __future__ import annotations

from code_atlas.parse.definitions import extract_definitions

MODULE_NAME = "<module>"


def chunk_spans(source: bytes) -> list[tuple[str, int, int]]:
    """(name, start_line, end_line) for every chunk, 1-based and inclusive.

    "<module>" comes first and spans the whole file; then each definition in source
    order. Duplicate names get "#2", "#3", ... in source order. Empty source -> [].
    """
    if not source:
        return []
    definitions = extract_definitions(source)

    total_lines = len(source.splitlines())
    spans: list[tuple[str, int, int]] = [(MODULE_NAME, 1, total_lines)]

    counts: dict[str, int] = {}
    for d in definitions:
        count = counts.get(d.qualified_name, 0) + 1
        counts[d.qualified_name] = count
        name = d.qualified_name if count == 1 else f"{d.qualified_name}#{count}"
        spans.append((name, d.start_line, d.end_line))

    return spans

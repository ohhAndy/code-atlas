"""Gold labels from a SWE-bench `patch`.

`changed_lines` maps each file the patch changes to the old-file line numbers it touches.
- The dict keys are the file-level gold.
- The line numbers are matched against chunk line ranges in Phase 1 for function-level gold.

Line rules:
- A "-" line records its own old line number.
- A run of "+" lines with no "-" lines (pure insertion) records both old neighbors:
  the old line before it and the old line after it. Line 0 does not exist.
- Context lines record nothing.
- Files the patch adds are skipped: they don't exist at base_commit.
"""

from __future__ import annotations

from unidiff.patch import PatchSet


def changed_lines(patch: str) -> dict[str, set[int]]:
    """Return {repo-relative path: old-file line numbers the patch touches}."""
    result: dict[str, set[int]] = {}
    for pf in PatchSet(patch):
        if pf.is_added_file:
            continue  # not in the base_commit snapshot, so no retriever can return it
        lines: set[int] = set()
        for hunk in pf:
            last_old = hunk.source_start - 1
            in_add = False
            saw_remove = False

            for line in hunk:
                if line.is_removed:
                    line_no = line.source_line_no
                    assert line_no is not None
                    lines.add(line_no)
                    last_old = line_no
                    saw_remove = True
                elif line.is_added:
                    in_add = True
                elif line.is_context:
                    line_no = line.source_line_no
                    assert line_no is not None
                    if in_add and not saw_remove:
                        if last_old > 0:
                            lines.add(last_old)
                        lines.add(line_no)

                    last_old = line_no
                    in_add = False
                    saw_remove = False

            if in_add and not saw_remove:
                if last_old > 0:
                    lines.add(last_old)
                lines.add(last_old + 1)

        result[pf.path] = lines
    return result


def owner(line: int, spans: list[tuple[str, int, int]]) -> str | None:
    """spans: (name, start_line, end_line), 1-based inclusive.
    Return the name of the smallest span containing `line`, or None if no span contains it
    (e.g. a pure insertion at the end of a file records a line past the last one).

    spans must list a container before anything inside it (source order, as chunk_spans
    returns them): on a tie in length, the later span is the inner one and wins."""
    containing = [span for span in reversed(spans) if span[1] <= line <= span[2]]
    best = min(containing, key=lambda span: span[2] - span[1], default=None)
    return best[0] if best is not None else None

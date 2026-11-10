"""Ripgrep baseline: rank files (or chunks) by how often they contain identifiers from the
issue text."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from code_atlas.parse.chunks import Span, chunk_file, owner
from code_atlas.types import Hit, Level

CANDIDATE_RE = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")


def extract_identifiers(text: str) -> list[str]:
    """Return the code-looking words in `text`.

    A word is kept only if its shape shows it is code:
    - contains an underscore:                       get_or_create
    - has a capital letter after the first char:   QuerySet, assertEqual
    - is a dotted name:                             models.Model
    Everything else is dropped: Value, count, self, the.

    A dotted name also contributes each part that passes the rule on its own, because code
    rarely spells out `QuerySet.get_or_create` (it writes `self.get_or_create`):
    QuerySet.get_or_create -> QuerySet.get_or_create, QuerySet, get_or_create.
    """
    code_words: list[str] = []
    for word in CANDIDATE_RE.findall(text):
        if not _looks_like_code(word):
            continue
        code_words.append(word)
        if "." in word:
            code_words.extend(part for part in word.split(".") if _looks_like_code(part))
    return list(dict.fromkeys(code_words))  # dedupe, keep first-seen order


def _looks_like_code(word: str) -> bool:
    """True if the word's shape shows it is code (see the identifier rule)."""
    return (
        "_" in word  # get_or_create
        or "." in word  # models.Model
        or (  # QuerySet, assertEqual; but not acronyms like HTTP, OK, API
            any(c.isupper() for c in word[1:]) and any(c.islower() for c in word)
        )
    )


class RipgrepRetriever:
    """File-level retriever: one per snapshot. Has no index, so the constructor only
    remembers which directory to search.

    `include_tests=True` also searches files inside `tests` directories. It exists only to
    measure how much excluding test files changes the scores; the default is the baseline.
    """

    level: Level = "file"

    def __init__(self, repo_dir: Path, include_tests: bool = False) -> None:
        self.repo_dir = repo_dir
        self.include_tests = include_tests

    def search(self, query: str, k: int) -> list[Hit]:
        """Score each file by its total matching lines over all identifiers; top k first.

        Ties are broken by path so results are reproducible (rg's output order is not).
        """
        identifiers = extract_identifiers(query)
        total_counts: dict[str, int] = {}
        for identifier in identifiers:
            counts = _count_matches(self.repo_dir, identifier, self.include_tests)
            for key, v in counts.items():
                total_counts[key] = total_counts.get(key, 0) + v

        top_k_counts = sorted(total_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
        top_k_files = [Hit(id=path, score=float(count)) for path, count in top_k_counts]
        return top_k_files


def _count_matches(repo_dir: Path, identifier: str, include_tests: bool = False) -> dict[str, int]:
    """Run ripgrep for one identifier; return {repo-relative path: matching line count}.

    Searches .py files (outside `tests` directories unless `include_tests`) for the
    identifier as a literal whole word. rg exits 0 on matches, 1 on none (not an error),
    2 on error.
    """
    cmd = [
        "rg",
        "--count",  # one output line per file: "path:N", N = number of matching lines
        "--fixed-strings",  # "models.Model" is literal text, not a regex ("." = any char)
        "--word-regexp",  # "get" must not match inside "get_or_create"
        "--type",
        "py",  # only .py files
    ]
    if not include_tests:
        cmd += ["--glob", "!**/tests/**"]  # skip any directory named exactly `tests`
    cmd += [
        "--",  # everything after this is a pattern or path, never a flag
        identifier,
        ".",  # search the current dir; with no path, rg reads stdin and can hang
    ]
    result = subprocess.run(
        cmd,
        cwd=repo_dir,
        stdin=subprocess.DEVNULL,  # never wait for input
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 1:  # ran fine, no file matched
        return {}
    if result.returncode != 0:  # 2 = real error (bad flag, unreadable dir, ...)
        raise RuntimeError(f"rg failed for {identifier!r}: {result.stderr.strip()}")

    counts: dict[str, int] = {}
    for line in result.stdout.splitlines():
        path, n = line.rsplit(":", 1)  # split on the LAST ":"; a path could contain one
        counts[path.removeprefix("./")] = int(n)  # "./pkg/a.py" -> "pkg/a.py", as in gold
    return counts


class RipgrepChunkRetriever:
    """Chunk-level retriever: the file-level baseline's matches, credited to the chunk
    that owns each matching line. One per snapshot; chunks a file only when it first has
    a match, and keeps the chunks for later queries.

    Score of a chunk = its matching lines summed over all identifiers (the file baseline's
    rule, one level down). No length normalization: a long chunk has more lines that can
    match, so module and class chunks of big files are favored.
    """

    level: Level = "chunk"

    def __init__(self, repo_dir: Path) -> None:
        self.repo_dir = repo_dir
        # path -> (chunk id, start_line, end_line) for each chunk chunk_file emits; the span
        # name is the chunk id, so `owner` returns ids directly.
        self._spans: dict[str, list[Span]] = {}

    def search(self, query: str, k: int) -> list[Hit]:
        """Top k chunk ids by score; ties broken by chunk id so results are reproducible."""
        totals: dict[str, int] = {}
        for identifier in extract_identifiers(query):
            for path, line_numbers in _matching_lines(self.repo_dir, identifier).items():
                spans = self._spans_for(path)
                for line_no in line_numbers:
                    chunk_id = owner(line_no, spans)
                    if chunk_id is None:  # only if rg and tree-sitter count lines differently
                        continue
                    totals[chunk_id] = totals.get(chunk_id, 0) + 1

        top = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
        return [Hit(id=chunk_id, score=float(count)) for chunk_id, count in top]

    def _spans_for(self, path: str) -> list[Span]:
        if path not in self._spans:
            chunks = chunk_file(path, (self.repo_dir / path).read_bytes())
            self._spans[path] = [(c.id, c.start_line, c.end_line) for c in chunks]
        return self._spans[path]


def _matching_lines(repo_dir: Path, identifier: str) -> dict[str, list[int]]:
    """Run ripgrep for one identifier; return {repo-relative path: matching line numbers}.

    Same search as `_count_matches` (literal whole word, .py files, no `tests` dirs), but
    one output line per matching line: "path\\0line:text". Output is read as bytes: the
    matched text can be invalid UTF-8, and only the path and line number are used.
    """
    cmd = [
        "rg",
        "--line-number",
        "--no-heading",  # "path:line:text" on every line, not grouped under the path
        "--null",  # NUL after the path, so a ":" in the path cannot confuse the split
        "--fixed-strings",
        "--word-regexp",
        "--type",
        "py",
        "--glob",
        "!**/tests/**",
        "--",
        identifier,
        ".",
    ]
    result = subprocess.run(
        cmd, cwd=repo_dir, stdin=subprocess.DEVNULL, capture_output=True, check=False
    )
    if result.returncode == 1:
        return {}
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"rg failed for {identifier!r}: {stderr}")

    lines: dict[str, list[int]] = {}
    for row in result.stdout.splitlines():
        raw_path, rest = row.split(b"\0", 1)
        path = raw_path.decode("utf-8").removeprefix("./")
        lines.setdefault(path, []).append(int(rest.split(b":", 1)[0]))
    return lines

"""Ripgrep baseline: rank files by how often they contain identifiers from the issue text."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

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
    remembers which directory to search."""

    level: Level = "file"

    def __init__(self, repo_dir: Path) -> None:
        self.repo_dir = repo_dir

    def search(self, query: str, k: int) -> list[Hit]:
        """Score each file by its total matching lines over all identifiers; top k first.

        Ties are broken by path so results are reproducible (rg's output order is not).
        """
        identifiers = extract_identifiers(query)
        total_counts: dict[str, int] = {}
        for identifier in identifiers:
            counts = _count_matches(self.repo_dir, identifier)
            for key, v in counts.items():
                total_counts[key] = total_counts.get(key, 0) + v

        top_k_counts = sorted(total_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
        top_k_files = [Hit(id=path, score=float(count)) for path, count in top_k_counts]
        return top_k_files


def _count_matches(repo_dir: Path, identifier: str) -> dict[str, int]:
    """Run ripgrep for one identifier; return {repo-relative path: matching line count}.

    Searches .py files outside `tests` directories for the identifier as a
    literal whole word. rg exits 0 on matches, 1 on none (not an error), 2 on error.
    """
    cmd = [
        "rg",
        "--count",  # one output line per file: "path:N", N = number of matching lines
        "--fixed-strings",  # "models.Model" is literal text, not a regex ("." = any char)
        "--word-regexp",  # "get" must not match inside "get_or_create"
        "--type",
        "py",  # only .py files
        "--glob",
        "!**/tests/**",  # skip any directory named exactly `tests`
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

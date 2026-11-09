"""Which files of a repo snapshot are in the corpus, and reading them."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path


def is_test_file(path: str) -> bool:
    """True if any directory component (not the file name) is exactly `tests`.

    `path` is repo-relative with "/" separators: "pkg/tests/test_x.py" is a test file;
    "django/test/client.py" and "pkg/unittests/x.py" are not.
    """
    return "tests" in path.split("/")[:-1]


def iter_corpus_files(repo_dir: Path) -> Iterator[tuple[str, bytes]]:
    """Yield (repo-relative path, raw bytes) for every corpus .py file, sorted by path.

    Corpus = .py files outside test directories and outside `.git`. Bytes are returned
    undecoded, because the parser works on bytes and some repos contain files that are not
    valid UTF-8. Symlinks are skipped so a file is never read twice under two paths.
    """
    for file in sorted(repo_dir.rglob("*.py")):
        rel = file.relative_to(repo_dir).as_posix()
        if ".git" in rel.split("/") or is_test_file(rel):
            continue
        if file.is_symlink() or not file.is_file():
            continue
        yield rel, file.read_bytes()

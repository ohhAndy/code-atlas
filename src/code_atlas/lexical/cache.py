"""On-disk cache of built BM25 indexes, one file per (snapshot commit, index variant, code).

A cached index is valid only if it was built from the same source tree by the same code.
The key therefore has three parts:
- the snapshot's git commit (the corpus),
- the variant (which text of each chunk is indexed),
- a fingerprint of the code that decides an index's contents (the tokenizer, the index,
  the chunker, the corpus file rule) and the tree-sitter versions. Editing any of that code
  changes the fingerprint, so a stale index is never loaded; nobody has to remember to
  clear the cache.

Files are Python pickles. Pickle can run code when loaded, which is acceptable only
because this cache is written and read by this program on the local machine.
"""

from __future__ import annotations

import hashlib
import os
import pickle
import subprocess
import tempfile
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path

from code_atlas.lexical.index import InvertedIndex

ROOT = Path(__file__).resolve().parents[3]
INDEX_CACHE_DIR = ROOT / ".cache" / "bm25"

_PACKAGE = Path(__file__).resolve().parents[1]  # src/code_atlas
# Every module whose code changes what an index contains.
_INDEX_SOURCES = (
    "lexical/tokenizer.py",
    "lexical/index.py",
    "lexical/retriever.py",
    "parse/parser.py",
    "parse/definitions.py",
    "parse/chunks.py",
    "parse/files.py",
)


def code_fingerprint() -> str:
    """Short hash of the index-building source files and the tree-sitter versions."""
    digest = hashlib.sha256()
    for rel in _INDEX_SOURCES:
        digest.update(rel.encode())
        digest.update((_PACKAGE / rel).read_bytes())
    for package in ("tree-sitter", "tree-sitter-python"):
        digest.update(f"{package}=={version(package)}".encode())
    return digest.hexdigest()[:16]


def snapshot_commit(repo_dir: Path) -> str | None:
    """The commit checked out at `repo_dir`, or None if `repo_dir` is not the top of a git
    checkout. A plain directory inside some other repo returns None, not that repo's HEAD."""
    out = subprocess.run(
        ["git", "-C", str(repo_dir), "rev-parse", "--show-toplevel", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        return None
    toplevel, commit = out.stdout.split()
    if Path(toplevel).resolve() != repo_dir.resolve():
        return None
    return commit


def load_or_build(
    repo_dir: Path, variant: str, build: Callable[[], InvertedIndex], cache_dir: Path
) -> InvertedIndex:
    """Load the cached index for this snapshot and variant, or build and cache it.

    A directory that is not a git checkout has no stable identity, so it is always built
    and never cached.
    """
    commit = snapshot_commit(repo_dir)
    if commit is None:
        return build()

    path = cache_dir / f"{commit}-{variant}-{code_fingerprint()}.pkl"
    if path.exists():
        with path.open("rb") as f:
            index: InvertedIndex = pickle.load(f)
        return index

    index = build()
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Write to a temporary file, then rename: a crash mid-write never leaves a truncated
    # file under the real name.
    fd, tmp = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            pickle.dump(index, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return index

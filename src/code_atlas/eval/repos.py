"""Repo cache: one bare clone per repo, one git worktree per base commit.

Layout under the cache directory (gitignored):

    <owner>__<name>/
        bare.git/            bare clone: the shared object database, no working tree
        snapshots/<sha>/     worktree checked out at <sha> (detached HEAD)
        snapshots/<sha>.ok   marker, written last, only after the worktree is verified

Invariants:
- A snapshot is used only if its marker exists. The marker is written after the worktree
  is checked out and verified, so an interrupted build never leaves a folder that looks valid.
- The marker sits next to the worktree, not inside it, so it never shows up as an
  untracked file in `git status`.
- Snapshots are exact copies of the commit. Corpus policy (e.g. excluding test files,
  ADR 002) is applied later, when the corpus is built, never here.
- Not safe for two processes building the same snapshot at the same time.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parents[3] / ".cache" / "repos"

_FULL_SHA = re.compile(r"[0-9a-f]{40}")


def github_url(repo: str) -> str:
    """Clone URL for a SWE-bench repo name like "django/django"."""
    return f"https://github.com/{repo}.git"


def snapshot(
    repo: str,
    commit: str,
    cache_dir: Path = CACHE_DIR,
    url: str | None = None,
) -> Path:
    """Return a directory containing `repo` exactly as of `commit`, building it if needed.

    `url` overrides the clone source (tests use a local repo).
    """
    if not _FULL_SHA.fullmatch(commit):
        # Snapshots and markers are keyed by commit, so a branch name or short SHA would
        # silently alias different code over time.
        raise ValueError(f"expected a full 40-character commit SHA, got {commit!r}")

    root = cache_dir / repo.replace("/", "__")
    path = root / "snapshots" / commit
    marker = root / "snapshots" / f"{commit}.ok"
    if marker.exists():
        return path

    bare = _ensure_clone(root / "bare.git", url or github_url(repo))
    _ensure_commit(bare, commit)
    _remove_partial(bare, path)

    path.parent.mkdir(parents=True, exist_ok=True)
    _git("worktree", "add", "--detach", str(path), commit, cwd=bare)
    _verify(path, commit)
    marker.write_text(commit + "\n")
    return path


def _ensure_clone(bare: Path, url: str) -> Path:
    """Clone once. Clone into a temp dir and rename, so a killed clone is never reused."""
    if bare.exists():
        return bare
    tmp = bare.with_name(bare.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)  # left over from an interrupted clone
    bare.parent.mkdir(parents=True, exist_ok=True)
    _git("clone", "--bare", url, str(tmp))
    tmp.rename(bare)  # atomic on the same filesystem
    return bare


def _ensure_commit(bare: Path, commit: str) -> None:
    """Make sure `commit` is in the object database, fetching it by SHA if needed.

    Some base commits are not reachable from any branch in a fresh clone. Fail loudly
    rather than skip, since a skipped instance would silently shrink the eval set.
    """
    if _has_commit(bare, commit):
        return
    _git("fetch", "origin", commit, cwd=bare)
    if not _has_commit(bare, commit):
        raise RuntimeError(f"commit {commit} not found in {bare} even after fetching it")


def _has_commit(bare: Path, commit: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=bare,
        capture_output=True,
    )
    return result.returncode == 0


def _remove_partial(bare: Path, path: Path) -> None:
    """Remove a snapshot folder that has no marker (an interrupted or failed build)."""
    if path.exists():
        # May fail if git never registered the worktree; rmtree below covers that case.
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(path)],
            cwd=bare,
            capture_output=True,
        )
        if path.exists():
            shutil.rmtree(path)
    # Drop git's record of worktrees whose folders are gone, or `worktree add` refuses.
    _git("worktree", "prune", cwd=bare)


def _verify(path: Path, commit: str) -> None:
    """Check the worktree is at `commit` and has no changes before marking it valid."""
    head = _git("rev-parse", "HEAD", cwd=path)
    if head != commit:
        raise RuntimeError(f"{path}: HEAD is {head}, expected {commit}")
    status = _git("status", "--porcelain", cwd=path)
    if status:
        # e.g. paths that differ only by case on a case-insensitive filesystem (macOS).
        raise RuntimeError(f"{path}: worktree is not clean after checkout:\n{status}")


def _git(*args: str, cwd: Path | None = None) -> str:
    """Run git and return stripped stdout. Raises with git's stderr on failure."""
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout.strip()

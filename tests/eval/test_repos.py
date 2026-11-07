"""Tests for the repo cache. No network: the "remote" is a local git repo in tmp_path."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from code_atlas.eval.repos import snapshot

REPO = "owner/proj"

# Fixed identity so commits work on CI machines with no git config.
GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, env=GIT_ENV, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def commit_file(src: Path, name: str, content: str) -> str:
    (src / name).write_text(content)
    git("add", name, cwd=src)
    git("commit", "-q", "-m", f"write {name}", cwd=src)
    return git("rev-parse", "HEAD", cwd=src)


@pytest.fixture
def src(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    git("init", "-q", cwd=src)
    return src


@pytest.fixture
def cache(tmp_path: Path) -> Path:
    return tmp_path / "cache"


def test_snapshot_contains_files_at_each_commit(src: Path, cache: Path) -> None:
    c1 = commit_file(src, "a.py", "v1\n")
    c2 = commit_file(src, "a.py", "v2\n")

    p1 = snapshot(REPO, c1, cache_dir=cache, url=str(src))
    p2 = snapshot(REPO, c2, cache_dir=cache, url=str(src))

    assert p1 != p2
    assert (p1 / "a.py").read_text() == "v1\n"
    assert (p2 / "a.py").read_text() == "v2\n"


def test_cached_snapshot_is_reused_without_git(src: Path, cache: Path) -> None:
    c1 = commit_file(src, "a.py", "v1\n")
    path = snapshot(REPO, c1, cache_dir=cache, url=str(src))

    # With the clone and the source gone, only the marker can satisfy the second call.
    shutil.rmtree(cache / "owner__proj" / "bare.git")
    shutil.rmtree(src)

    assert snapshot(REPO, c1, cache_dir=cache, url="unused") == path


def test_snapshot_without_marker_is_rebuilt(src: Path, cache: Path) -> None:
    c1 = commit_file(src, "a.py", "v1\n")
    path = snapshot(REPO, c1, cache_dir=cache, url=str(src))

    # Simulate a build killed after checkout started but before the marker was written.
    (cache / "owner__proj" / "snapshots" / f"{c1}.ok").unlink()
    (path / "a.py").unlink()

    rebuilt = snapshot(REPO, c1, cache_dir=cache, url=str(src))
    assert (rebuilt / "a.py").read_text() == "v1\n"


def test_commit_added_after_clone_is_fetched(src: Path, cache: Path) -> None:
    c1 = commit_file(src, "a.py", "v1\n")
    snapshot(REPO, c1, cache_dir=cache, url=str(src))

    c2 = commit_file(src, "a.py", "v2\n")  # not in the existing clone
    p2 = snapshot(REPO, c2, cache_dir=cache, url=str(src))

    assert (p2 / "a.py").read_text() == "v2\n"


def test_unknown_commit_fails_loudly(src: Path, cache: Path) -> None:
    commit_file(src, "a.py", "v1\n")
    with pytest.raises(RuntimeError):
        snapshot(REPO, "0" * 40, cache_dir=cache, url=str(src))


@pytest.mark.parametrize("commit", ["main", "abc123", "A" * 40])
def test_rejects_anything_but_a_full_lowercase_sha(cache: Path, commit: str) -> None:
    with pytest.raises(ValueError):
        snapshot(REPO, commit, cache_dir=cache, url="unused")

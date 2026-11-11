"""Tests for the on-disk index cache, on a throwaway git repo."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from code_atlas.lexical.cache import code_fingerprint, load_or_build, snapshot_commit
from code_atlas.lexical.index import InvertedIndex, build_index

INDEX = build_index({"a.py::f": ["f", "frobnicate"]})


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def f():\n    return frobnicate()\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


class CountingBuild:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> InvertedIndex:
        self.calls += 1
        return INDEX


def test_fingerprint_is_stable_hex() -> None:
    assert code_fingerprint() == code_fingerprint()
    assert len(code_fingerprint()) == 16
    int(code_fingerprint(), 16)


def test_snapshot_commit_of_git_checkout(repo: Path) -> None:
    assert snapshot_commit(repo) == _git(repo, "rev-parse", "HEAD")


def test_snapshot_commit_of_plain_directory_is_none(tmp_path: Path) -> None:
    assert snapshot_commit(tmp_path) is None


def test_subdirectory_of_checkout_is_not_a_snapshot(repo: Path) -> None:
    sub = repo / "pkg"
    sub.mkdir()
    assert snapshot_commit(sub) is None


def test_second_load_reads_cache(repo: Path, tmp_path: Path) -> None:
    build = CountingBuild()
    cache = tmp_path / "cache"
    first = load_or_build(repo, "v", build, cache)
    second = load_or_build(repo, "v", build, cache)
    assert build.calls == 1
    assert first == second == INDEX
    assert len(list(cache.glob("*.pkl"))) == 1
    assert not list(cache.glob("*.tmp"))


def test_variants_are_cached_separately(repo: Path, tmp_path: Path) -> None:
    build = CountingBuild()
    cache = tmp_path / "cache"
    load_or_build(repo, "v1", build, cache)
    load_or_build(repo, "v2", build, cache)
    assert build.calls == 2


def test_new_commit_is_a_new_entry(repo: Path, tmp_path: Path) -> None:
    build = CountingBuild()
    cache = tmp_path / "cache"
    load_or_build(repo, "v", build, cache)
    (repo / "b.py").write_text("x = 1\n")
    _git(repo, "add", "b.py")
    _git(repo, "commit", "-q", "-m", "second")
    load_or_build(repo, "v", build, cache)
    assert build.calls == 2


def test_plain_directory_is_built_and_not_cached(tmp_path: Path) -> None:
    build = CountingBuild()
    cache = tmp_path / "cache"
    load_or_build(tmp_path, "v", build, cache)
    load_or_build(tmp_path, "v", build, cache)
    assert build.calls == 2
    assert not cache.exists()

"""Tests for the parser wrapper and corpus file selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from code_atlas.parse.files import is_test_file, iter_corpus_files
from code_atlas.parse.parser import parse

# --- parse -------------------------------------------------------------------------------


def test_parses_valid_source() -> None:
    root = parse(b"def f():\n    pass\n").root_node
    assert root.type == "module"
    assert not root.has_error
    assert [c.type for c in root.children] == ["function_definition"]


def test_syntax_error_does_not_raise() -> None:
    root = parse(b"def f(:\n    pass\ndef g(): pass\n").root_node
    assert root.has_error


def test_columns_count_bytes_not_characters() -> None:
    # "é" is 1 character but 2 UTF-8 bytes, so `x` sits at character 9 but byte 10.
    source = 's = "é"; x = 1\n'.encode()
    # named_children skips anonymous tokens such as the ";" between the two statements.
    x = parse(source).root_node.named_children[1].named_children[0].named_children[0]
    assert x.text == b"x"
    assert source.decode().index("x") == 9
    assert x.start_point.column == 10
    assert source[x.start_byte : x.end_byte] == b"x"


# --- corpus files ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/test_a.py", True),
        ("pkg/tests/test_a.py", True),
        ("pkg/sub/tests/helpers.py", True),
        ("pkg/test/client.py", False),  # library code, e.g. django/test/
        ("pkg/unittests/a.py", False),
        ("pkg/tests.py", False),  # only directory components count
        ("a.py", False),
    ],
)
def test_is_test_file(path: str, expected: bool) -> None:
    assert is_test_file(path) is expected


def test_iter_corpus_files(tmp_path: Path) -> None:
    (tmp_path / "pkg" / "tests").mkdir(parents=True)
    (tmp_path / ".git").mkdir()
    (tmp_path / "pkg" / "b.py").write_bytes(b"b = 1\n")
    (tmp_path / "pkg" / "a.py").write_bytes(b"a = 1\n")
    (tmp_path / "pkg" / "notes.txt").write_bytes(b"not python\n")
    (tmp_path / "pkg" / "tests" / "test_a.py").write_bytes(b"t = 1\n")
    (tmp_path / ".git" / "hook.py").write_bytes(b"h = 1\n")
    (tmp_path / "link.py").symlink_to(tmp_path / "pkg" / "a.py")

    assert list(iter_corpus_files(tmp_path)) == [
        ("pkg/a.py", b"a = 1\n"),
        ("pkg/b.py", b"b = 1\n"),
    ]


def test_iter_corpus_files_can_include_tests(tmp_path: Path) -> None:
    (tmp_path / "pkg" / "tests").mkdir(parents=True)
    (tmp_path / ".git").mkdir()
    (tmp_path / "pkg" / "a.py").write_bytes(b"a = 1\n")
    (tmp_path / "pkg" / "tests" / "test_a.py").write_bytes(b"t = 1\n")
    (tmp_path / ".git" / "hook.py").write_bytes(b"h = 1\n")

    assert [p for p, _ in iter_corpus_files(tmp_path, include_tests=True)] == [
        "pkg/a.py",
        "pkg/tests/test_a.py",
    ]


def test_iter_corpus_files_keeps_invalid_utf8(tmp_path: Path) -> None:
    (tmp_path / "latin1.py").write_bytes(b"s = '\xe9'\n")  # not valid UTF-8
    assert list(iter_corpus_files(tmp_path)) == [("latin1.py", b"s = '\xe9'\n")]

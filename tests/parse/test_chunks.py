"""Tests for chunk_spans. Line numbers are 1-based and inclusive; each source line is
numbered in a comment."""

from __future__ import annotations

from code_atlas.eval.gold import owner
from code_atlas.parse.chunks import chunk_spans

BASIC = b"""\
import os

class Foo:
    x = 1

    def bar(self):
        return 1

def baz():
    pass
"""
# 1 import os
# 2
# 3 class Foo:
# 4     x = 1
# 5
# 6     def bar(self):
# 7         return 1
# 8
# 9 def baz():
# 10    pass


def test_module_span_then_definitions_in_source_order() -> None:
    assert chunk_spans(BASIC) == [
        ("<module>", 1, 10),
        ("Foo", 3, 7),
        ("Foo.bar", 6, 7),
        ("baz", 9, 10),
    ]


def test_module_span_with_and_without_trailing_newline() -> None:
    assert chunk_spans(b"x = 1\ny = 2\n") == [("<module>", 1, 2)]
    assert chunk_spans(b"x = 1\ny = 2") == [("<module>", 1, 2)]


def test_empty_source_has_no_spans() -> None:
    assert chunk_spans(b"") == []


PROPERTY = b"""\
class C:
    @property
    def name(self):
        return 1

    @name.setter
    def name(self, v):
        pass
"""
# 1 class C:
# 2     @property
# 3     def name(self):
# 4         return 1
# 5
# 6     @name.setter
# 7     def name(self, v):
# 8         pass


def test_property_getter_and_setter_get_ordinal_suffix() -> None:
    assert chunk_spans(PROPERTY) == [
        ("<module>", 1, 8),
        ("C", 1, 8),
        ("C.name", 2, 4),
        ("C.name#2", 6, 8),
    ]


COMPAT = b"""\
if A:
    def compat():
        pass
elif B:
    def compat():
        pass
else:
    def compat():
        pass
"""


def test_three_duplicates_number_in_source_order() -> None:
    assert chunk_spans(COMPAT) == [
        ("<module>", 1, 9),
        ("compat", 2, 3),
        ("compat#2", 5, 6),
        ("compat#3", 8, 9),
    ]


def test_owner_of_line_in_setter() -> None:
    assert owner(7, chunk_spans(PROPERTY)) == "C.name#2"


def test_owner_of_class_header_when_class_spans_whole_file() -> None:
    assert owner(1, chunk_spans(PROPERTY)) == "C"

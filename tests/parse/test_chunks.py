"""Tests for chunk_spans, chunk_texts and chunk_file. Line numbers are 1-based and
inclusive; each source line is numbered in a comment."""

from __future__ import annotations

from code_atlas.eval.gold import owner
from code_atlas.parse.chunks import chunk_file, chunk_spans, chunk_texts

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


# chunk_texts: each chunk's text is the lines it owns, newlines kept.


def test_texts_follow_line_ownership() -> None:
    assert chunk_texts(BASIC, chunk_spans(BASIC)) == {
        "<module>": "import os\n\n\n",  # lines 1, 2, 8
        "Foo": "class Foo:\n    x = 1\n\n",  # lines 3, 4, 5 (not the method)
        "Foo.bar": "    def bar(self):\n        return 1\n",  # lines 6, 7
        "baz": "def baz():\n    pass\n",  # lines 9, 10
    }


def test_texts_contain_every_character_exactly_once() -> None:
    texts = chunk_texts(BASIC, chunk_spans(BASIC))
    assert sum(len(t) for t in texts.values()) == len(BASIC.decode("utf-8"))


NON_ASCII = 'def café():\n    return "naïve"\n'.encode()


def test_texts_of_non_ascii_source() -> None:
    assert chunk_texts(NON_ASCII, chunk_spans(NON_ASCII)) == {
        "<module>": "",
        "café": 'def café():\n    return "naïve"\n',
    }


def test_text_of_property_setter() -> None:
    texts = chunk_texts(PROPERTY, chunk_spans(PROPERTY))
    assert texts["C.name#2"] == "    @name.setter\n    def name(self, v):\n        pass\n"


# chunk_file


def test_chunk_file_ids_and_kinds() -> None:
    chunks = chunk_file("pkg/a.py", BASIC)
    assert [(c.id, c.kind) for c in chunks] == [
        ("pkg/a.py::<module>", "module"),
        ("pkg/a.py::Foo", "class"),
        ("pkg/a.py::Foo.bar", "method"),
        ("pkg/a.py::baz", "function"),
    ]


def test_chunk_file_skips_whitespace_only_module() -> None:
    chunks = chunk_file("pkg/a.py", PROPERTY)
    assert [c.qualified_name for c in chunks] == ["C", "C.name", "C.name#2"]


def test_chunk_file_empty_source() -> None:
    assert chunk_file("pkg/__init__.py", b"") == []


# A form feed (\x0c) is a line break for str.splitlines() but not for tree-sitter.
FORM_FEED = b"x = 1\x0c\n\ndef f():\n    return 1\n"


def test_texts_with_form_feed_keep_tree_sitter_lines() -> None:
    assert chunk_texts(FORM_FEED, chunk_spans(FORM_FEED)) == {
        "<module>": "x = 1\x0c\n\n",
        "f": "def f():\n    return 1\n",
    }

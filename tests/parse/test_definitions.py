"""Tests for extract_definitions. Expected lines are 1-based and inclusive, counted by hand."""

from __future__ import annotations

from code_atlas.parse.definitions import Definition, extract_definitions


def defs(source: str) -> list[Definition]:
    return extract_definitions(source.encode())


# --- basic shapes ------------------------------------------------------------------------


def test_top_level_function() -> None:
    assert defs("def f():\n    pass\n") == [Definition("f", "function", 1, 2)]


def test_async_function_is_a_function() -> None:
    assert defs("async def f():\n    pass\n") == [Definition("f", "function", 1, 2)]


def test_method() -> None:
    source = "class A:\n    def m(self):\n        pass\n"
    assert defs(source) == [
        Definition("A", "class", 1, 3),
        Definition("A.m", "method", 2, 3),
    ]


def test_async_method() -> None:
    source = "class A:\n    async def m(self):\n        pass\n"
    assert defs(source) == [
        Definition("A", "class", 1, 3),
        Definition("A.m", "method", 2, 3),
    ]


def test_nested_classes() -> None:
    source = "class A:\n    class B:\n        def m(self):\n            pass\n"
    assert defs(source) == [
        Definition("A", "class", 1, 4),
        Definition("A.B", "class", 2, 4),
        Definition("A.B.m", "method", 3, 4),
    ]


def test_source_order() -> None:
    source = "def a(): pass\nclass B: pass\ndef c(): pass\n"
    assert defs(source) == [
        Definition("a", "function", 1, 1),
        Definition("B", "class", 2, 2),
        Definition("c", "function", 3, 3),
    ]


# --- decorators: the span starts at the first decorator ---------------------------------


def test_decorated_method_starts_at_decorator() -> None:
    source = "class A:\n    @property\n    def m(self):\n        return 1\n"
    assert defs(source) == [
        Definition("A", "class", 1, 4),
        Definition("A.m", "method", 2, 4),
    ]


def test_stacked_decorators_on_class() -> None:
    assert defs("@a\n@b\nclass C:\n    pass\n") == [Definition("C", "class", 1, 4)]


# --- function bodies are not searched ----------------------------------------------------


def test_nested_function_and_class_are_part_of_parent() -> None:
    source = (
        "def f():\n"  # 1
        "    def inner():\n"  # 2
        "        pass\n"  # 3
        "    class C:\n"  # 4
        "        def m(self):\n"  # 5
        "            pass\n"  # 6
        "    return inner\n"  # 7
    )
    assert defs(source) == [Definition("f", "function", 1, 7)]


def test_nested_function_in_method_is_part_of_method() -> None:
    source = "class A:\n    def m(self):\n        def inner():\n            pass\n"
    assert defs(source) == [
        Definition("A", "class", 1, 4),
        Definition("A.m", "method", 2, 4),
    ]


# --- no definitions ----------------------------------------------------------------------


def test_empty_source() -> None:
    assert defs("") == []


def test_module_code_only() -> None:
    assert defs("x = 1\nprint(x)\n") == []


# --- non-ASCII: line numbers must not shift ----------------------------------------------


def test_non_ascii_before_definition() -> None:
    source = "s = 'é😀'\ndef f():\n    return 'ü'\n"
    assert defs(source) == [Definition("f", "function", 2, 3)]


def test_non_ascii_identifier() -> None:
    assert defs("def café():\n    pass\n") == [Definition("café", "function", 1, 2)]


# --- syntax errors -----------------------------------------------------------------------


def test_syntax_error_does_not_hide_later_definitions() -> None:
    result = defs("def f(:\n    pass\ndef g(): pass\n")
    assert Definition("g", "function", 3, 3) in result


def test_syntax_error_inside_method() -> None:
    source = (
        "class A:\n"  # 1
        "    def m(self):\n"  # 2
        "        x = (\n"  # 3, unclosed
        "    def n(self):\n"  # 4
        "        pass\n"  # 5
    )
    assert Definition("A.n", "method", 4, 5) in defs(source)


# --- definitions under compound statements: if/try/... don't create a scope -------------


def test_function_under_if() -> None:
    assert defs("if True:\n    def f():\n        pass\n") == [Definition("f", "function", 2, 3)]


def test_function_under_except() -> None:
    source = "try:\n    import x\nexcept ImportError:\n    def x():\n        pass\n"
    assert defs(source) == [Definition("x", "function", 4, 5)]


def test_method_under_if_in_class() -> None:
    source = "class A:\n    if True:\n        def m(self):\n            pass\n"
    assert defs(source) == [
        Definition("A", "class", 1, 4),
        Definition("A.m", "method", 3, 4),
    ]

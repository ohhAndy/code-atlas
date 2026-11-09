"""Extract function, method and class definitions from a syntax tree."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from tree_sitter import Node

from code_atlas.parse.parser import parse

DefinitionKind = Literal["function", "method", "class"]


@dataclass(frozen=True)
class Definition:
    """One definition found in a file. Lines are 1-based and inclusive, like gold lines."""

    qualified_name: str  # e.g. "Session.request"
    kind: DefinitionKind
    start_line: int
    end_line: int


def extract_definitions(source: bytes) -> list[Definition]:
    """Return every function, method and class in `source`, in source order.

    Class bodies are searched (methods and nested classes are returned); function bodies
    are not: a definition inside a function is part of that function, not its own entry.
    """
    tree = parse(source)
    results: list[Definition] = []

    def walk_block(block: Node, prefix: str = "") -> None:
        for child in block.children:
            span_node = child
            def_node = child

            if child.type == "decorated_definition":
                inner = child.child_by_field_name("definition")
                if inner is None:
                    continue
                def_node = inner

            if def_node.type not in ("function_definition", "class_definition"):
                # if/try/with/for/... don't create a scope: look inside with the same prefix.
                walk_block(child, prefix)
                continue

            name_node = def_node.child_by_field_name("name")
            if name_node is None or name_node.text is None:
                continue

            name = name_node.text.decode("utf-8")
            qname = f"{prefix}.{name}" if prefix else name
            start_line = span_node.start_point[0] + 1
            end_line = span_node.end_point[0] + 1

            if def_node.type == "class_definition":
                results.append(Definition(qname, "class", start_line, end_line))
                body = def_node.child_by_field_name("body")
                if body is not None:
                    walk_block(body, prefix=qname)
            else:  # function_definition
                kind: DefinitionKind = "method" if prefix else "function"
                results.append(Definition(qname, kind, start_line, end_line))
                # Do not recurse into function bodies

    walk_block(tree.root_node)
    return results

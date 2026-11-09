"""Parse Python source into a tree-sitter syntax tree."""

from __future__ import annotations

import tree_sitter_python as tsp
from tree_sitter import Language, Parser, Tree

# Built once: creating a Parser loads the grammar, and parse() does not mutate it.
_PARSER = Parser(Language(tsp.language()))


def parse(source: bytes) -> Tree:
    """Parse UTF-8 Python source.

    Takes bytes, not str: every offset in the tree (start_byte, end_byte, and the column in
    start_point / end_point) counts bytes of this input. Rows are 0-based line numbers.

    Never raises on invalid Python: syntax errors become ERROR or MISSING nodes and set
    `tree.root_node.has_error`.
    """
    return _PARSER.parse(source)

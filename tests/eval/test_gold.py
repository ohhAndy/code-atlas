"""Tests for changed_lines. Expected values are worked out by hand from each patch.

Careful: unidiff checks the counts in each @@ header. "-40,6" means the hunk covers
6 old lines (context + "-"), "+40,8" means 8 new lines (context + "+").
Old line numbers are noted in comments as (N).
"""

from __future__ import annotations

from pathlib import Path

from code_atlas.eval.gold import changed_lines, function_gold

SAVE_INSERT = """\
--- a/app/models.py
+++ b/app/models.py
@@ -40,6 +40,8 @@ def save(self):
     name = self.name
     value = self.value
     slug = self.slug
+    if value is None:
+        raise ValueError("value required")
     self._write(name, value)
     self._flush()
     return True
"""


def test_pure_insertion_records_both_neighbors() -> None:
    # Inserted between old 42 (slug) and old 43 (_write).
    assert changed_lines(SAVE_INSERT) == {"app/models.py": {42, 43}}


SAVE_REPLACE = """\
--- a/app/models.py
+++ b/app/models.py
@@ -40,8 +40,8 @@ def save(self):
     value = self.value
     slug = self.slug
-    name = self.nameBug
+    name = self.name
     if value is None:
         raise ValueError("value required")
     self._write(name, value)
     self._flush()
     return True
"""


def test_replacement_records_only_removed_lines() -> None:
    # value (40), slug (41), removed name (42). The "+" must not add neighbors 41/43.
    assert changed_lines(SAVE_REPLACE) == {"app/models.py": {42}}


DELETE = """\
--- a/app/models.py
+++ b/app/models.py
@@ -40,5 +40,3 @@
 a = 1
-b = 2
-c = 3
 d = 4
 e = 5
"""


def test_pure_deletion_records_deleted_lines() -> None:
    # a (40), b (41), c (42), d (43), e (44).
    assert changed_lines(DELETE) == {"app/models.py": {41, 42}}


TOP_INSERT = """\
--- a/app/models.py
+++ b/app/models.py
@@ -1,2 +1,3 @@
+import os
 x = 1
 y = 2
"""


def test_insertion_at_top_of_file_skips_line_zero() -> None:
    # Inserted before old 1. There is no old line 0, so only the line after counts.
    assert changed_lines(TOP_INSERT) == {"app/models.py": {1}}


END_INSERT = """\
--- a/app/models.py
+++ b/app/models.py
@@ -8,2 +8,3 @@
 a = 1
 b = 2
+c = 3
"""


def test_insertion_at_end_of_hunk_records_both_neighbors() -> None:
    # a (8), b (9), insert after 9. The run ends with the hunk, not at a context line,
    # so this covers the after-the-loop branch. 10 may be past end of file; harmless.
    assert changed_lines(END_INSERT) == {"app/models.py": {9, 10}}


TWO_HUNKS = """\
--- a/app/models.py
+++ b/app/models.py
@@ -10,3 +10,3 @@
 a = 1
-b = 2
+b = 20
 c = 3
@@ -50,3 +50,4 @@
 d = 4
 e = 5
+new = 6
 f = 7
"""


def test_two_hunks_in_one_file_are_unioned() -> None:
    # Hunk 1: a (10), removed b (11), c (12). Hunk 2: d (50), e (51), insert, f (52).
    assert changed_lines(TWO_HUNKS) == {"app/models.py": {11, 51, 52}}


TWO_FILES = """\
--- a/one.py
+++ b/one.py
@@ -1,2 +1,2 @@
-a = 1
+a = 10
 b = 2
--- a/two.py
+++ b/two.py
@@ -5,2 +5,1 @@
 c = 3
-d = 4
"""


def test_two_files_give_two_keys() -> None:
    # one.py: removed a (1). two.py: c (5), removed d (6).
    assert changed_lines(TWO_FILES) == {"one.py": {1}, "two.py": {6}}


NEW_FILE = """\
--- /dev/null
+++ b/app/new.py
@@ -0,0 +1,2 @@
+x = 1
+y = 2
"""


def test_new_file_is_excluded() -> None:
    # The file does not exist at base_commit, so no retriever can return it.
    assert changed_lines(NEW_FILE) == {}


# function_gold: the base_commit file is written to a temporary snapshot directory.

MODELS = """\
import os

class Foo:
    x = 1

    def bar(self):
        return 1

def baz():
    pass
"""
# (1) import os
# (2)
# (3) class Foo:
# (4)     x = 1
# (5)
# (6)     def bar(self):
# (7)         return 1
# (8)
# (9) def baz():
# (10)    pass


def _snapshot(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    return tmp_path


CHANGE_IN_METHOD = """\
--- a/app/models.py
+++ b/app/models.py
@@ -6,2 +6,2 @@
     def bar(self):
-        return 1
+        return 2
"""


def test_change_in_method_is_the_method_only(tmp_path: Path) -> None:
    repo = _snapshot(tmp_path, {"app/models.py": MODELS})
    assert function_gold(CHANGE_IN_METHOD, repo) == {"app/models.py::Foo.bar"}


CHANGE_CLASS_ATTRIBUTE = """\
--- a/app/models.py
+++ b/app/models.py
@@ -4,1 +4,1 @@
-    x = 1
+    x = 2
"""


def test_change_in_class_body_is_the_class(tmp_path: Path) -> None:
    repo = _snapshot(tmp_path, {"app/models.py": MODELS})
    assert function_gold(CHANGE_CLASS_ATTRIBUTE, repo) == {"app/models.py::Foo"}


CHANGE_IMPORT_AND_FUNCTION = """\
--- a/app/models.py
+++ b/app/models.py
@@ -1,1 +1,1 @@
-import os
+import sys
@@ -10,1 +10,1 @@
-    pass
+    return None
"""


def test_changes_in_two_chunks(tmp_path: Path) -> None:
    repo = _snapshot(tmp_path, {"app/models.py": MODELS})
    assert function_gold(CHANGE_IMPORT_AND_FUNCTION, repo) == {
        "app/models.py::<module>",
        "app/models.py::baz",
    }


# Pure insertion between old (8) blank and old (9) def baz: both neighbors are gold, so
# the blank line pulls in the module chunk. This is the boundary cost logged for Phase 1.
INSERT_BEFORE_BAZ = (
    "--- a/app/models.py\n"
    "+++ b/app/models.py\n"
    "@@ -8,2 +8,4 @@\n"
    " \n"
    "+def qux():\n"
    "+    pass\n"
    " def baz():\n"
)


def test_insertion_between_definitions_gets_both_neighbors(tmp_path: Path) -> None:
    repo = _snapshot(tmp_path, {"app/models.py": MODELS})
    assert function_gold(INSERT_BEFORE_BAZ, repo) == {
        "app/models.py::<module>",
        "app/models.py::baz",
    }


# Pure insertion after the last line records (10) and (11); (11) is past the end of file.
APPEND_AT_END = """\
--- a/app/models.py
+++ b/app/models.py
@@ -9,2 +9,4 @@
 def baz():
     pass
+
+X = 1
"""


def test_line_past_end_of_file_adds_nothing(tmp_path: Path) -> None:
    repo = _snapshot(tmp_path, {"app/models.py": MODELS})
    assert function_gold(APPEND_AT_END, repo) == {"app/models.py::baz"}


ONE_CLASS = """\
class C:
    x = 1

    y = 2
"""
# (1) class C:
# (2)     x = 1
# (3)
# (4)     y = 2

# Replaces the blank line (3) inside the class: owned by C, not by a module chunk.
CHANGE_BLANK_IN_CLASS = "--- a/app/c.py\n+++ b/app/c.py\n@@ -3,1 +3,1 @@\n-\n+    # note\n"


def test_blank_line_inside_class_is_the_class(tmp_path: Path) -> None:
    repo = _snapshot(tmp_path, {"app/c.py": ONE_CLASS})
    assert function_gold(CHANGE_BLANK_IN_CLASS, repo) == {"app/c.py::C"}


TWO_FUNCTIONS = """\
def f():
    pass


def g():
    pass
"""
# (1) def f():
# (2)     pass
# (3)
# (4)
# (5) def g():
# (6)     pass

# Removes blank line (4). Only blank lines are outside f and g, so there is no module
# chunk and line (4) has no owner.
REMOVE_BLANK_BETWEEN_FUNCTIONS = "--- a/app/fg.py\n+++ b/app/fg.py\n@@ -3,2 +3,1 @@\n \n-\n"


def test_unowned_blank_line_gives_empty_gold(tmp_path: Path) -> None:
    repo = _snapshot(tmp_path, {"app/fg.py": TWO_FUNCTIONS})
    assert function_gold(REMOVE_BLANK_BETWEEN_FUNCTIONS, repo) == set()

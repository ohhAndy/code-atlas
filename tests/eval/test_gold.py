"""Tests for changed_lines. Expected values are worked out by hand from each patch.

Careful: unidiff checks the counts in each @@ header. "-40,6" means the hunk covers
6 old lines (context + "-"), "+40,8" means 8 new lines (context + "+").
Old line numbers are noted in comments as (N).
"""

from __future__ import annotations

from code_atlas.eval.gold import changed_lines, owner

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


# owner: spans are (name, start_line, end_line), 1-based inclusive.
OWNER_SPANS = [
    ("<module>", 1, 100),
    ("Foo", 10, 60),
    ("Foo.bar", 20, 30),
]


def test_owner_line_in_method() -> None:
    assert owner(25, OWNER_SPANS) == "Foo.bar"


def test_owner_line_in_class_body_outside_methods() -> None:
    assert owner(15, OWNER_SPANS) == "Foo"


def test_owner_top_level_line() -> None:
    assert owner(5, OWNER_SPANS) == "<module>"


def test_owner_first_line_of_method() -> None:
    assert owner(20, OWNER_SPANS) == "Foo.bar"


def test_owner_last_line_of_method() -> None:
    assert owner(30, OWNER_SPANS) == "Foo.bar"


def test_owner_line_in_no_span_is_none() -> None:
    # e.g. a pure insertion at the end of a hunk records last_old + 1, past the file end.
    assert owner(150, OWNER_SPANS) is None

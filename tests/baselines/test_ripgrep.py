"""Tests for the ripgrep baseline. Expected rankings are worked out by hand from the fake repo."""

from __future__ import annotations

from pathlib import Path

import pytest

from code_atlas.baselines.ripgrep import RipgrepRetriever, extract_identifiers
from code_atlas.types import Hit

# --- extract_identifiers: one case per row of the identifier-rule table ----------------


@pytest.mark.parametrize(
    "word",
    ["get_or_create", "QuerySet", "IntegrityError", "models.Model", "assertEqual"],
)
def test_keeps_code_words(word: str) -> None:
    assert word in extract_identifiers(f"I called {word} and it broke.")


@pytest.mark.parametrize("word", ["Value", "count", "self", "the", "HTTP", "OK", "API"])
def test_drops_plain_words(word: str) -> None:
    assert word not in extract_identifiers(f"{word} is here.")


def test_all_caps_constant_kept_only_with_underscore() -> None:
    # SECRET_KEY passes via its underscore; DEBUG has no code shape once acronyms are out.
    assert extract_identifiers("Set SECRET_KEY and DEBUG") == ["SECRET_KEY"]


def test_duplicates_kept_once_in_first_seen_order() -> None:
    # Repeating a word in the issue must not multiply its rg counts.
    text = "QuerySet breaks get_or_create, and QuerySet again."
    assert extract_identifiers(text) == ["QuerySet", "get_or_create"]


def test_trailing_punctuation_not_part_of_word() -> None:
    assert extract_identifiers("It fails in QuerySet.") == ["QuerySet"]


def test_traceback_line() -> None:
    line = 'File "django/db/models/query.py", line 573, in get_or_create'
    # "django", "db", "models", "line", "in" have no code shape; "query.py" is dotted.
    assert extract_identifiers(line) == ["query.py", "get_or_create"]


def test_dotted_name_adds_code_looking_parts() -> None:
    assert extract_identifiers("QuerySet.get_or_create fails") == [
        "QuerySet.get_or_create",
        "QuerySet",
        "get_or_create",
    ]


def test_dotted_name_drops_plain_parts() -> None:
    # models, Model, save have no code shape on their own; only the whole name is kept.
    assert extract_identifiers("models.Model.save fails") == ["models.Model.save"]


def test_part_already_seen_is_not_repeated() -> None:
    assert extract_identifiers("QuerySet and QuerySet.get_or_create") == [
        "QuerySet",
        "QuerySet.get_or_create",
        "get_or_create",
    ]


def test_no_identifiers() -> None:
    assert extract_identifiers("it is broken and the value is wrong") == []


# --- RipgrepRetriever on a tiny fake repo ------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A fake repo whose ranking can be computed by hand.

    Matching lines per identifier (rg --count counts lines, not occurrences):
                         QuerySet   get_or_create
      pkg/query.py           2            1        -> total 3
      pkg/other.py           1            0        -> total 1
      pkg/tests/...         (excluded: inside a `tests` directory)
    """
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "query.py").write_text(
        "class QuerySet:\n    def get_or_create(self):\n        QuerySet()\n"
    )
    (tmp_path / "pkg" / "other.py").write_text("from pkg.query import QuerySet\n")
    (tmp_path / "pkg" / "tests").mkdir()
    (tmp_path / "pkg" / "tests" / "test_query.py").write_text("QuerySet QuerySet QuerySet\n")
    return tmp_path


def test_level_is_file(repo: Path) -> None:
    assert RipgrepRetriever(repo).level == "file"


def test_ranks_by_summed_line_counts(repo: Path) -> None:
    hits = RipgrepRetriever(repo).search("QuerySet and get_or_create are broken", k=10)
    assert hits == [Hit(id="pkg/query.py", score=3.0), Hit(id="pkg/other.py", score=1.0)]


def test_k_limits_results(repo: Path) -> None:
    hits = RipgrepRetriever(repo).search("QuerySet and get_or_create are broken", k=1)
    assert hits == [Hit(id="pkg/query.py", score=3.0)]


def test_test_directories_excluded(repo: Path) -> None:
    # test_query.py has the most QuerySet text of any file, yet must never appear.
    ids = [h.id for h in RipgrepRetriever(repo).search("QuerySet", k=10)]
    assert all("/tests/" not in i for i in ids)


def test_include_tests_searches_test_directories(repo: Path) -> None:
    # test_query.py: 1 matching line (rg counts lines), so it ties pkg/other.py and the
    # tie is broken by path.
    hits = RipgrepRetriever(repo, include_tests=True).search("QuerySet", k=10)
    assert hits == [
        Hit(id="pkg/query.py", score=2.0),
        Hit(id="pkg/other.py", score=1.0),
        Hit(id="pkg/tests/test_query.py", score=1.0),
    ]


def test_count_is_lines_not_occurrences(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("QuerySet(QuerySet(QuerySet()))\n")
    assert RipgrepRetriever(tmp_path).search("QuerySet", k=10) == [Hit(id="a.py", score=1.0)]


def test_whole_word_only(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("my_get_or_create_helper()\n")
    assert RipgrepRetriever(tmp_path).search("get_or_create", k=10) == []


def test_ties_broken_by_path(tmp_path: Path) -> None:
    # Same count in both files: order must be by path, not by rg's (parallel) output order.
    for name in ["b.py", "a.py", "c.py"]:
        (tmp_path / name).write_text("QuerySet\n")
    ids = [h.id for h in RipgrepRetriever(tmp_path).search("QuerySet", k=10)]
    assert ids == ["a.py", "b.py", "c.py"]


def test_dotted_name_found_through_its_parts(repo: Path) -> None:
    # The code never writes "QuerySet.get_or_create" (0 hits), but its parts QuerySet and
    # get_or_create are searched too, giving the same totals as the plain-word query.
    hits = RipgrepRetriever(repo).search("QuerySet.get_or_create is broken", k=10)
    assert hits == [Hit(id="pkg/query.py", score=3.0), Hit(id="pkg/other.py", score=1.0)]


def test_query_without_identifiers_returns_empty(repo: Path) -> None:
    assert RipgrepRetriever(repo).search("it is broken", k=10) == []


def test_identifier_with_no_matches_returns_empty(repo: Path) -> None:
    # rg exits with code 1 when nothing matches; that is not an error.
    assert RipgrepRetriever(repo).search("NoSuchThing", k=10) == []

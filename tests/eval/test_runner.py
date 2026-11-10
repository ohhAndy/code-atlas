"""Tests for the evaluation runner. No network or real repos: a fake retriever stands in."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from code_atlas.eval import runner
from code_atlas.eval.dataset import Instance
from code_atlas.types import Hit, Level, Retriever

# --- file_ranking: the level branch ------------------------------------------------------


def test_file_level_hits_are_used_as_is() -> None:
    hits = [Hit("b.py", 3.0), Hit("a.py", 1.0)]
    assert runner.file_ranking(hits, "file") == ["b.py", "a.py"]


def test_chunk_level_hits_become_files_at_best_chunk() -> None:
    hits = [Hit("b.py::f", 3.0), Hit("a.py::g", 2.0), Hit("b.py::h", 1.0)]
    assert runner.file_ranking(hits, "chunk") == ["b.py", "a.py"]


def test_empty_hits() -> None:
    assert runner.file_ranking([], "file") == []
    assert runner.file_ranking([], "chunk") == []


# --- evaluate, summarize, table, JSON ----------------------------------------------------


def _patch(path: str) -> str:
    """A minimal unified diff that changes line 1 of `path`."""
    return f"--- a/{path}\n+++ b/{path}\n@@ -1,1 +1,1 @@\n-old\n+new\n"


def _instance(iid: str, repo: str, patch: str) -> Instance:
    return Instance(iid, repo, "0" * 40, f"issue {iid}", patch, "2020-01-01")


class FakeRetriever:
    """Returns a fixed file ranking, whatever the query."""

    level: Level = "file"

    def __init__(self, ranking: list[str]) -> None:
        self.ranking = ranking

    def search(self, query: str, k: int) -> list[Hit]:
        return [Hit(p, float(len(self.ranking) - i)) for i, p in enumerate(self.ranking[:k])]


def _make(ranking: list[str]) -> Callable[[Path], Retriever]:
    return lambda repo_dir: FakeRetriever(ranking)


def test_evaluate_scores_each_instance() -> None:
    instances = [
        _instance("x-1", "org/x", _patch("a.py")),  # gold a.py at rank 1
        _instance("x-2", "org/x", _patch("c.py")),  # gold c.py at rank 3
    ]
    results, skipped = runner.evaluate(
        instances, _make(["a.py", "b.py", "c.py"]), lambda inst: Path("/unused")
    )
    assert skipped == []
    assert [r.scores for r in results] == [
        {"recall@1": 1.0, "recall@5": 1.0, "recall@10": 1.0, "mrr@10": 1.0},
        {"recall@1": 0.0, "recall@5": 1.0, "recall@10": 1.0, "mrr@10": pytest.approx(1 / 3)},
    ]
    assert results[1].gold_files == ["c.py"]
    assert results[1].ranking == ["a.py", "b.py", "c.py"]


def test_evaluate_skips_instance_with_no_gold() -> None:
    added_only = "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1,1 @@\n+x\n"
    instances = [_instance("x-1", "org/x", added_only)]
    results, skipped = runner.evaluate(instances, _make(["a.py"]), lambda inst: Path("/unused"))
    assert results == []
    assert skipped == ["x-1"]


def test_summarize_is_macro_average_per_repo() -> None:
    instances = [
        _instance("x-1", "org/x", _patch("a.py")),  # MRR 1
        _instance("x-2", "org/x", _patch("b.py")),  # MRR 1/2
        _instance("y-1", "org/y", _patch("z.py")),  # miss: MRR 0
    ]
    results, _ = runner.evaluate(instances, _make(["a.py", "b.py"]), lambda inst: Path("/u"))
    summary = runner.summarize(results)
    assert summary["overall"]["n"] == 3
    assert summary["overall"]["mrr@10"] == pytest.approx((1 + 0.5 + 0) / 3)
    assert summary["org/x"]["mrr@10"] == pytest.approx(0.75)
    assert summary["org/y"]["recall@10"] == 0.0
    assert list(summary) == ["overall", "org/x", "org/y"]


def test_summarize_groups_by_category_after_repos() -> None:
    instances = [
        _instance("x-1", "org/x", _patch("a.py")),  # MRR 1
        _instance("x-2", "org/x", _patch("b.py")),  # MRR 1/2
        _instance("y-1", "org/y", _patch("z.py")),  # miss, unlabeled
    ]
    results, _ = runner.evaluate(
        instances, _make(["a.py", "b.py"]), lambda inst: Path("/u"), {"x-1": 2, "x-2": 1}
    )
    summary = runner.summarize(results)
    assert list(summary) == ["overall", "org/x", "org/y", "category 1", "category 2"]
    assert summary["category 1"]["n"] == 1
    assert summary["category 1"]["mrr@10"] == 0.5
    assert summary["category 2"]["mrr@10"] == 1.0
    assert [r.category for r in results] == [2, 1, None]


def test_summarize_empty() -> None:
    assert runner.summarize([]) == {}


def test_format_table_has_a_row_per_group() -> None:
    results, _ = runner.evaluate(
        [_instance("x-1", "org/x", _patch("a.py"))], _make(["a.py"]), lambda inst: Path("/u")
    )
    table = runner.format_table(runner.summarize(results))
    assert "overall" in table and "org/x" in table and "mrr@10" in table


def test_write_results_json(tmp_path: Path) -> None:
    results, _ = runner.evaluate(
        [_instance("x-1", "org/x", _patch("a.py"))], _make(["a.py"]), lambda inst: Path("/u")
    )
    path = runner.write_results("fake", "dev", results, ["skipped-1"], out_dir=tmp_path)
    data = json.loads(path.read_text())
    assert path.name.startswith("fake_dev_")
    assert data["meta"]["method"] == "fake"
    assert data["meta"]["split"] == "dev"
    assert len(data["meta"]["codeatlas"]["commit"]) == 40
    assert data["meta"]["skipped_no_gold"] == ["skipped-1"]
    assert data["meta"]["ripgrep"].startswith("ripgrep ")
    assert data["summary"]["overall"]["recall@1"] == 1.0
    assert data["instances"][0]["instance_id"] == "x-1"


# --- function level: chunk retrievers ------------------------------------------------------

MODULE = "import os\n\ndef f():\n    return 1\n\ndef g():\n    return 2\n"
# (1) import os  (2)  (3) def f():  (4) return 1  (5)  (6) def g():  (7) return 2


def _change(path: str, line: int, old: str) -> str:
    """A unified diff that replaces old line `line` of `path`."""
    return f"--- a/{path}\n+++ b/{path}\n@@ -{line},1 +{line},1 @@\n-{old}\n+changed\n"


class FakeChunkRetriever:
    """Returns a fixed chunk ranking, whatever the query."""

    level: Level = "chunk"

    def __init__(self, ranking: list[str]) -> None:
        self.ranking = ranking

    def search(self, query: str, k: int) -> list[Hit]:
        return [Hit(c, float(len(self.ranking) - i)) for i, c in enumerate(self.ranking[:k])]


def _make_chunks(ranking: list[str]) -> Callable[[Path], Retriever]:
    return lambda repo_dir: FakeChunkRetriever(ranking)


def _repo(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "m.py").write_text(MODULE)
    return tmp_path


def test_chunk_retriever_is_scored_at_function_level(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    inst = _instance("x-1", "org/x", _change("m.py", 7, "    return 2"))  # gold m.py::g
    results, _ = runner.evaluate(
        [inst], _make_chunks(["m.py::f", "m.py::g", "m.py::<module>"]), lambda i: repo
    )
    r = results[0]
    assert r.gold_chunks == ["m.py::g"]
    assert r.chunk_ranking == ["m.py::f", "m.py::g", "m.py::<module>"]
    assert r.ranking == ["m.py"]
    assert r.scores["recall@1"] == 1.0  # file level: m.py is first
    assert r.function_scores == {
        "recall@1": 0.0,
        "recall@5": 1.0,
        "recall@10": 1.0,
        "mrr@10": 0.5,
        "hit@1": 0.0,
        "hit@5": 1.0,
        "hit@10": 1.0,
    }


def test_file_retriever_gets_no_function_level_fields() -> None:
    results, _ = runner.evaluate(
        [_instance("x-1", "org/x", _patch("a.py"))], _make(["a.py"]), lambda i: Path("/u")
    )
    assert results[0].gold_chunks is None
    assert results[0].function_scores is None
    assert runner.summarize(results, "function") == {}


def test_instance_without_function_gold_is_file_level_only(tmp_path: Path) -> None:
    (tmp_path / "fg.py").write_text("def f():\n    pass\n\n\ndef g():\n    pass\n")
    blank = "--- a/fg.py\n+++ b/fg.py\n@@ -4,1 +4,1 @@\n-\n+# x\n"  # unowned blank line
    scored = _instance("x-2", "org/x", _change("fg.py", 2, "    pass"))  # gold fg.py::f
    results, _ = runner.evaluate(
        [_instance("x-1", "org/x", blank), scored],
        _make_chunks(["fg.py::f"]),
        lambda i: tmp_path,
    )
    assert results[0].gold_chunks == []
    assert results[0].function_scores is None
    assert results[0].scores["recall@1"] == 1.0
    summary = runner.summarize(results, "function")
    assert summary["overall"]["n"] == 1
    assert summary["overall"]["hit@1"] == 1.0


def test_write_results_records_function_level(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    inst = _instance("x-1", "org/x", _change("m.py", 4, "    return 1"))  # gold m.py::f
    results, _ = runner.evaluate([inst], _make_chunks(["m.py::f"]), lambda i: repo)
    path = runner.write_results("fake", "dev", results, [], out_dir=tmp_path / "out")
    data = json.loads(path.read_text())
    assert data["meta"]["level_scored"] == "file+function"
    assert data["meta"]["no_function_gold"] == []
    assert data["function_summary"]["overall"]["mrr@10"] == 1.0
    assert "hit@10" in runner.format_table(runner.summarize(results, "function"))

"""Tests for the category labeling loop. Input is scripted; nothing is typed by hand."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from code_atlas.eval.categories import Label, label_loop, load_labels, save_labels
from code_atlas.eval.dataset import Instance


def _inst(iid: str, text: str = "issue text", patch: str = "SECRET-PATCH") -> Instance:
    return Instance(iid, "org/x", "0" * 40, text, patch, "2020-01-01")


def _scripted(answers: list[str]) -> Callable[[str], str]:
    it = iter(answers)
    return lambda prompt: next(it)


def _run(
    instances: list[Instance],
    answers: list[str],
    path: Path,
    labels: dict[str, Label] | None = None,
) -> tuple[dict[str, Label], list[str]]:
    shown: list[str] = []
    result = label_loop(instances, labels or {}, path, ask=_scripted(answers), show=shown.append)
    return result, shown


def test_labels_and_notes_are_saved(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    _run([_inst("a"), _inst("b")], ["1", "", "3", "borderline"], path)
    assert load_labels(path) == {
        "a": {"category": 1, "note": ""},
        "b": {"category": 3, "note": "borderline"},
    }


def test_invalid_input_asks_again(tmp_path: Path) -> None:
    labels, shown = _run([_inst("a")], ["4", "x", "2", ""], tmp_path / "c.json")
    assert labels["a"]["category"] == 2
    assert shown.count("Type 1, 2, 3, s or q.") == 2


def test_skip_leaves_instance_unlabeled(tmp_path: Path) -> None:
    labels, _ = _run([_inst("a"), _inst("b")], ["s", "2", ""], tmp_path / "c.json")
    assert set(labels) == {"b"}


def test_quit_keeps_earlier_answers(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    _run([_inst("a"), _inst("b"), _inst("c")], ["1", "", "q"], path)
    assert set(load_labels(path)) == {"a"}


def test_resume_only_asks_unlabeled(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    done: dict[str, Label] = {"a": {"category": 1, "note": ""}}
    save_labels(done, path)
    labels, shown = _run([_inst("a"), _inst("b")], ["3", ""], path, labels=load_labels(path))
    assert labels == {"a": {"category": 1, "note": ""}, "b": {"category": 3, "note": ""}}
    assert not any("  a  (" in s for s in shown)  # "a" was never shown again


def test_patch_is_never_shown(tmp_path: Path) -> None:
    _, shown = _run(
        [_inst("a", text="the issue", patch="SECRET-PATCH")], ["3", ""], tmp_path / "c.json"
    )
    assert any("the issue" in s for s in shown)
    assert not any("SECRET-PATCH" in s for s in shown)


def test_load_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_labels(tmp_path / "nope.json") == {}

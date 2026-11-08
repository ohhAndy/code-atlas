"""Query category labels: one hand-assigned category per instance, stored in a JSON file.

Categories (when several apply, the lowest number wins):
    1  a traceback, a file path in the repo, or a dotted name that spells out repo
       modules (`django.utils.autoreload`, `from sklearn.linear_model import ...`)
    2  names a function, class, method, attribute, setting or management command of the
       project (not the reporter's own names)
    3  describes behavior only

Labeling shows only the issue text, never the patch, so the gold fix can't bias a label.
The file is saved after every answer, so a session can stop and resume.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal, TypedDict

from code_atlas.eval.dataset import Instance

CATEGORIES_PATH = Path(__file__).resolve().parents[3] / "splits" / "categories.json"

Category = Literal[1, 2, 3]
_VALID: dict[str, Category] = {"1": 1, "2": 2, "3": 3}

LEGEND = (
    "[1] traceback or file path   [2] names an identifier   [3] behavior only\n"
    "[s] skip for now             [q] save and quit"
)


class Label(TypedDict):
    category: Category
    note: str


def load_labels(path: Path = CATEGORIES_PATH) -> dict[str, Label]:
    if not path.exists():
        return {}
    labels: dict[str, Label] = json.loads(path.read_text())
    return labels


def save_labels(labels: dict[str, Label], path: Path = CATEGORIES_PATH) -> None:
    """Write atomically: a crash mid-write leaves the previous file intact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(labels, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def label_loop(
    instances: Sequence[Instance],
    labels: dict[str, Label],
    path: Path = CATEGORIES_PATH,
    ask: Callable[[str], str] = input,
    show: Callable[[str], None] = print,
) -> dict[str, Label]:
    """Ask for a category for each unlabeled instance, saving after every answer."""
    todo = [inst for inst in instances if inst.instance_id not in labels]
    show(f"{len(labels)} already labeled, {len(todo)} to go.")
    for n, inst in enumerate(todo, 1):
        show("\n" + "=" * 88)
        show(f"[{n}/{len(todo)}]  {inst.instance_id}  ({inst.repo})")
        show("=" * 88)
        show(inst.problem_statement.strip())
        show("-" * 88)
        show(LEGEND)

        while True:
            answer = ask("category> ").strip().lower()
            if answer in _VALID or answer in {"s", "q"}:
                break
            show("Type 1, 2, 3, s or q.")

        if answer == "q":
            break
        if answer == "s":
            continue
        note = ask("note (optional, Enter to skip)> ").strip()
        labels[inst.instance_id] = {"category": _VALID[answer], "note": note}
        save_labels(labels, path)

    show(f"\n{len(labels)} labeled. Saved to {path}")
    return labels

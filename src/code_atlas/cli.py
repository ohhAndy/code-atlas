"""Command-line entry point: `codeatlas <command>`."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from code_atlas.eval.dataset import load_instances, read_split
from code_atlas.eval.repos import snapshot


def prepare(split: str) -> None:
    """Build (or reuse) the repo snapshot for every instance in `split`."""
    splits = read_split()
    wanted = [
        inst for inst in load_instances() if split == "all" or splits.get(inst.instance_id) == split
    ]
    for i, inst in enumerate(wanted, 1):
        start = time.perf_counter()
        path = snapshot(inst.repo, inst.base_commit)
        elapsed = time.perf_counter() - start
        print(f"[{i}/{len(wanted)}] {inst.instance_id}  {elapsed:6.1f}s  {path}")


def evaluate(method: str, split: str, final: bool) -> None:
    """Run `method` on `split`, write a results JSON, and print the summary table."""
    from code_atlas.eval import categories, runner

    if split == "test" and not final:
        raise SystemExit(
            "The test split is for logged final runs only. Tune on dev; pass --final to run test."
        )
    splits = read_split()
    wanted = [inst for inst in load_instances() if splits.get(inst.instance_id) == split]
    results, skipped = runner.evaluate(
        wanted,
        runner.RETRIEVERS[method],
        lambda inst: snapshot(inst.repo, inst.base_commit),
        {iid: label["category"] for iid, label in categories.load_labels().items()},
    )
    path = runner.write_results(method, split, results, skipped)
    print()
    print(runner.format_table(runner.summarize(results)))
    if skipped:
        print(f"\nSkipped (no file-level gold): {', '.join(skipped)}")
    print(f"\nWrote {path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path}")
    if split == "test":
        print("TEST RUN: record it in the project log (date, commit, method, why).")


def label(split: str) -> None:
    """Hand-label query categories for every instance in `split` (resumable)."""
    from code_atlas.eval import categories

    splits = read_split()
    wanted = sorted(
        (inst for inst in load_instances() if inst.instance_id in splits),
        key=lambda inst: inst.instance_id,
    )
    if split != "all":
        wanted = [inst for inst in wanted if splits[inst.instance_id] == split]
    try:
        categories.label_loop(wanted, categories.load_labels())
    except (KeyboardInterrupt, EOFError):
        print("\nStopped. Every answer so far is saved.")


def main() -> None:
    from code_atlas.eval.runner import RETRIEVERS

    parser = argparse.ArgumentParser(prog="codeatlas")
    commands = parser.add_subparsers(dest="command", required=True)

    p = commands.add_parser("prepare", help="build repo snapshots for a split")
    p.add_argument("--split", choices=["dev", "test", "all"], default="dev")

    e = commands.add_parser("eval", help="evaluate a retriever on a split")
    e.add_argument("--method", choices=sorted(RETRIEVERS), required=True)
    e.add_argument("--split", choices=["dev", "test"], default="dev")
    e.add_argument("--final", action="store_true", help="required to run the test split")

    lab = commands.add_parser("label", help="hand-label query categories")
    lab.add_argument("--split", choices=["dev", "test", "all"], default="all")

    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.split)
    elif args.command == "eval":
        evaluate(args.method, args.split, args.final)
    elif args.command == "label":
        label(args.split)

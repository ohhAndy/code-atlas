"""Command-line entry point: `codeatlas <command>`."""

from __future__ import annotations

import argparse
import time

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


def main() -> None:
    parser = argparse.ArgumentParser(prog="codeatlas")
    commands = parser.add_subparsers(dest="command", required=True)

    p = commands.add_parser("prepare", help="build repo snapshots for a split")
    p.add_argument("--split", choices=["dev", "test", "all"], default="dev")

    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.split)

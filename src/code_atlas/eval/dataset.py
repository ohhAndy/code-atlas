"""Load SWE-bench Lite, sample the evaluation subset, and write the dev/test split.

Run once to (re)generate the committed split file:

    uv run python -m code_atlas.eval.dataset

The split file is the source of truth for which instances are in dev and test.
Regenerating it with the same seed and quotas must produce an identical file.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from datasets import load_dataset

DATASET_NAME = "princeton-nlp/SWE-bench_Lite"
# Pinned Hugging Face dataset commit, so a fresh clone loads exactly the same rows.
DATASET_REVISION = "6ec7bb89b9342f664a54a6e0a6ea6501d3437cc2"
HF_SPLIT = "test"  # SWE-bench's own split. Our dev/test split is carved out of it.

SEED = 42
DEV_FRACTION = 0.3

# Instances sampled per repo.
QUOTAS: dict[str, int] = {
    "django/django": 46,
    "sympy/sympy": 31,
    "scikit-learn/scikit-learn": 23,
}

SPLIT_PATH = Path(__file__).resolve().parents[3] / "splits" / "split.json"

Split = Literal["dev", "test"]


@dataclass(frozen=True)
class Instance:
    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    patch: str
    created_at: str


def load_instances() -> list[Instance]:
    """Load every SWE-bench Lite instance, keeping only the fields we use."""
    rows = load_dataset(DATASET_NAME, split=HF_SPLIT, revision=DATASET_REVISION)
    return [
        Instance(
            instance_id=r["instance_id"],
            repo=r["repo"],
            base_commit=r["base_commit"],
            problem_statement=r["problem_statement"],
            patch=r["patch"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


def dev_count(n: int, fraction: float = DEV_FRACTION) -> int:
    """Number of dev instances for a repo with n sampled instances.

    Rounds half up explicitly. Python's round() uses banker's rounding
    (round(2.5) == 2), which makes the rule harder to state.
    """
    return int(n * fraction + 0.5)


def make_split(
    instances: list[Instance],
    quotas: dict[str, int] = QUOTAS,
    seed: int = SEED,
) -> dict[str, Split]:
    """Sample `quotas[repo]` instances per repo and assign each to dev or test.

    Each repo gets its own RNG derived from the seed, so changing one repo's quota
    does not reshuffle the others.
    """
    by_repo: dict[str, list[str]] = defaultdict(list)
    for inst in instances:
        by_repo[inst.repo].append(inst.instance_id)

    assignment: dict[str, Split] = {}
    for repo, quota in sorted(quotas.items()):
        ids = sorted(by_repo[repo])
        if len(ids) < quota:
            raise ValueError(f"{repo}: quota {quota} exceeds {len(ids)} available instances")

        rng = random.Random(f"{seed}:{repo}")
        sampled = rng.sample(ids, quota)  # random order, so the first k are a random dev set
        n_dev = dev_count(quota)
        for i, instance_id in enumerate(sampled):
            assignment[instance_id] = "dev" if i < n_dev else "test"

    return assignment


def write_split(assignment: dict[str, Split], instances: list[Instance], path: Path) -> None:
    """Write the split file, sorted by instance id so diffs stay readable."""
    repo_of = {inst.instance_id: inst.repo for inst in instances}
    payload = {
        "dataset": DATASET_NAME,
        "dataset_revision": DATASET_REVISION,
        "hf_split": HF_SPLIT,
        "seed": SEED,
        "dev_fraction": DEV_FRACTION,
        "quotas": QUOTAS,
        "instances": [
            {"instance_id": iid, "repo": repo_of[iid], "split": assignment[iid]}
            for iid in sorted(assignment)
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def read_split(path: Path = SPLIT_PATH) -> dict[str, Split]:
    """Read the committed split file: instance id -> "dev" | "test"."""
    payload = json.loads(path.read_text())
    return {row["instance_id"]: row["split"] for row in payload["instances"]}


def main() -> None:
    instances = load_instances()
    assignment = make_split(instances)
    write_split(assignment, instances, SPLIT_PATH)

    counts: dict[tuple[str, str], int] = defaultdict(int)
    repo_of = {inst.instance_id: inst.repo for inst in instances}
    for iid, split in assignment.items():
        counts[(repo_of[iid], split)] += 1
    for repo in sorted(QUOTAS):
        print(f"{repo:28} dev={counts[(repo, 'dev')]:3}  test={counts[(repo, 'test')]:3}")
    print(f"wrote {len(assignment)} instances to {SPLIT_PATH}")


if __name__ == "__main__":
    main()

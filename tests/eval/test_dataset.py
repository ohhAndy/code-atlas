"""Tests for subset sampling and the dev/test split. No network: instances are fabricated."""

from __future__ import annotations

import pytest

from code_atlas.eval.dataset import (
    SPLIT_PATH,
    Instance,
    dev_count,
    make_split,
    read_split,
)


def fake_instances(repo: str, n: int) -> list[Instance]:
    return [
        Instance(
            instance_id=f"{repo.replace('/', '__')}-{i}",
            repo=repo,
            base_commit=f"commit{i}",
            problem_statement="",
            patch="",
            created_at="",
        )
        for i in range(n)
    ]


@pytest.mark.parametrize(
    ("n", "expected"),
    [(46, 14), (31, 9), (23, 7), (10, 3), (5, 2)],  # 5 * 0.3 = 1.5 rounds up, not to even
)
def test_dev_count_rounds_half_up(n: int, expected: int) -> None:
    assert dev_count(n) == expected


def test_make_split_respects_quotas_and_dev_fraction() -> None:
    instances = fake_instances("a/a", 20) + fake_instances("b/b", 10)
    split = make_split(instances, quotas={"a/a": 10, "b/b": 5}, seed=0)

    a = [s for iid, s in split.items() if iid.startswith("a__a")]
    b = [s for iid, s in split.items() if iid.startswith("b__b")]
    assert len(a) == 10 and a.count("dev") == 3
    assert len(b) == 5 and b.count("dev") == 2


def test_make_split_is_deterministic() -> None:
    instances = fake_instances("a/a", 20)
    assert make_split(instances, {"a/a": 10}, seed=1) == make_split(instances, {"a/a": 10}, seed=1)


def test_make_split_ignores_input_order() -> None:
    instances = fake_instances("a/a", 20)
    forward = make_split(instances, {"a/a": 10}, seed=1)
    backward = make_split(list(reversed(instances)), {"a/a": 10}, seed=1)
    assert forward == backward


def test_changing_one_quota_does_not_reshuffle_other_repos() -> None:
    instances = fake_instances("a/a", 20) + fake_instances("b/b", 20)
    before = make_split(instances, {"a/a": 10, "b/b": 10}, seed=1)
    after = make_split(instances, {"a/a": 5, "b/b": 10}, seed=1)

    def only_b(split: dict[str, str]) -> dict[str, str]:
        return {k: v for k, v in split.items() if k.startswith("b__b")}

    assert only_b(dict(before)) == only_b(dict(after))


def test_quota_larger_than_repo_raises() -> None:
    with pytest.raises(ValueError):
        make_split(fake_instances("a/a", 3), {"a/a": 5}, seed=0)


def test_committed_split_file_matches_decision() -> None:
    split = read_split(SPLIT_PATH)
    assert len(split) == 100
    assert sum(1 for s in split.values() if s == "dev") == 30

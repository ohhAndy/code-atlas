"""Evaluation runner: run one retriever over a split, score it, write JSON, print a table.

Scores at file level only for now: function-level gold needs the chunker.

Per instance:
    repo_dir = snapshot at base_commit
    retriever = RETRIEVERS[method](repo_dir)        # build: any indexing happens here (timed)
    hits = retriever.search(problem_statement, K)   # search (timed)
    score the file ranking against the files the gold patch changes
"""

from __future__ import annotations

import json
import subprocess
import time
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from code_atlas.baselines.ripgrep import RipgrepRetriever
from code_atlas.eval.dataset import DATASET_REVISION, Instance
from code_atlas.eval.gold import changed_lines
from code_atlas.eval.metrics import files_from_chunks, recall_at_k, reciprocal_rank_at_k
from code_atlas.types import Hit, Level, Retriever

ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = ROOT / "results"

K = 10  # retrieval depth; also the largest cutoff any metric uses (MRR@10, Recall@10)
METRICS = ("recall@1", "recall@5", "recall@10", "mrr@10")

# Method name -> how to build a retriever for one snapshot directory.
RETRIEVERS: dict[str, Callable[[Path], Retriever]] = {
    "rg": RipgrepRetriever,
}


@dataclass(frozen=True)
class InstanceResult:
    instance_id: str
    repo: str
    category: int | None  # hand-labeled query category; None if unlabeled
    gold_files: list[str]
    ranking: list[str]  # file ranking that was scored, best first
    scores: dict[str, float]
    build_seconds: float
    search_seconds: float


def file_ranking(hits: Sequence[Hit], level: Level) -> list[str]:
    """Turn a retriever's hits into a file ranking, best first.

    "file":  hit ids are already file paths.
    "chunk": hit ids are chunk ids ("path::Name"); each file takes its best chunk's rank.
    """
    ids = [hit.id for hit in hits]
    if level == "file":
        return ids
    return files_from_chunks(ids)


def file_scores(ranking: Sequence[str], gold: set[str]) -> dict[str, float]:
    """All file-level metrics for one instance."""
    return {
        "recall@1": recall_at_k(ranking, gold, 1),
        "recall@5": recall_at_k(ranking, gold, 5),
        "recall@10": recall_at_k(ranking, gold, 10),
        "mrr@10": reciprocal_rank_at_k(ranking, gold, 10),
    }


def evaluate(
    instances: Sequence[Instance],
    make_retriever: Callable[[Path], Retriever],
    repo_dir_for: Callable[[Instance], Path],
    categories: Mapping[str, int] | None = None,
) -> tuple[list[InstanceResult], list[str]]:
    """Run and score every instance. Returns (results, ids skipped for having no gold)."""
    categories = categories or {}
    results: list[InstanceResult] = []
    skipped: list[str] = []
    for i, inst in enumerate(instances, 1):
        gold = set(changed_lines(inst.patch))
        if not gold:  # the patch only adds files; nothing at base_commit to retrieve
            skipped.append(inst.instance_id)
            continue

        repo_dir = repo_dir_for(inst)
        start = time.perf_counter()
        retriever = make_retriever(repo_dir)
        built = time.perf_counter()
        hits = retriever.search(inst.problem_statement, K)
        searched = time.perf_counter()

        ranking = file_ranking(hits, retriever.level)
        result = InstanceResult(
            instance_id=inst.instance_id,
            repo=inst.repo,
            category=categories.get(inst.instance_id),
            gold_files=sorted(gold),
            ranking=ranking,
            scores=file_scores(ranking, gold),
            build_seconds=round(built - start, 4),
            search_seconds=round(searched - built, 4),
        )
        results.append(result)
        print(
            f"[{i}/{len(instances)}] {inst.instance_id}  "
            f"R@10={result.scores['recall@10']:.0f}  MRR@10={result.scores['mrr@10']:.2f}"
        )
    return results, skipped


def _mean_scores(results: Sequence[InstanceResult]) -> dict[str, float]:
    """Macro average: every instance counts once."""
    return {m: sum(r.scores[m] for r in results) / len(results) for m in METRICS}


def summarize(results: Sequence[InstanceResult]) -> dict[str, dict[str, float]]:
    """Mean of each metric overall, per repo and per query category, plus the count `n`."""
    if not results:
        return {}
    by_repo: dict[str, list[InstanceResult]] = defaultdict(list)
    by_category: dict[str, list[InstanceResult]] = defaultdict(list)
    for r in results:
        by_repo[r.repo].append(r)
        if r.category is not None:
            by_category[f"category {r.category}"].append(r)
    summary = {"overall": {"n": float(len(results)), **_mean_scores(results)}}
    for groups in (by_repo, by_category):
        for name in sorted(groups):
            summary[name] = {"n": float(len(groups[name])), **_mean_scores(groups[name])}
    return summary


def format_table(summary: dict[str, dict[str, float]]) -> str:
    header = f"{'':28} {'n':>4} " + " ".join(f"{m:>9}" for m in METRICS)
    lines = [header, "-" * len(header)]
    for name, row in summary.items():
        cells = " ".join(f"{row[m]:>9.3f}" for m in METRICS)
        lines.append(f"{name:28} {int(row['n']):>4} {cells}")
    return "\n".join(lines)


def git_state() -> dict[str, Any]:
    """The CodeAtlas commit that produced a result, and whether the tree had edits."""
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return {"commit": commit, "dirty": bool(status.strip())}


def write_results(
    method: str,
    split: str,
    results: Sequence[InstanceResult],
    skipped: Sequence[str],
    out_dir: Path = RESULTS_DIR,
) -> Path:
    """Write one run to <out_dir>/<method>_<split>_<UTC time>.json and return its path."""
    now = datetime.now(UTC)
    payload = {
        "meta": {
            "method": method,
            "split": split,
            "k": K,
            "level_scored": "file",
            "created_at": now.isoformat(timespec="seconds"),
            "codeatlas": git_state(),
            "dataset_revision": DATASET_REVISION,
            "skipped_no_gold": list(skipped),
        },
        "summary": summarize(results),
        "instances": [asdict(r) for r in results],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{method}_{split}_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path

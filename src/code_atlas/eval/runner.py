"""Evaluation runner: run one retriever over a split, score it, write JSON, print a table.

Per instance:
    repo_dir = snapshot at base_commit
    retriever = RETRIEVERS[method](repo_dir)        # build: any indexing happens here (timed)
    hits = retriever.search(problem_statement, K)   # search (timed)
    score the file ranking against the files the gold patch changes
    chunk retrievers only: score the chunk ranking against the chunks the patch changes
    (function-level gold). An instance with no function-level gold is scored at file level
    only.
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
from typing import Any, Literal

from code_atlas.baselines.ripgrep import RipgrepChunkRetriever, RipgrepRetriever
from code_atlas.eval.dataset import DATASET_REVISION, Instance
from code_atlas.eval.gold import changed_lines, function_gold
from code_atlas.eval.metrics import (
    files_from_chunks,
    hit_at_k,
    recall_at_k,
    reciprocal_rank_at_k,
)
from code_atlas.types import Hit, Level, Retriever

ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = ROOT / "results"

K = 10  # retrieval depth; also the largest cutoff any metric uses (MRR@10, Recall@10)
METRICS = ("recall@1", "recall@5", "recall@10", "mrr@10")
# Hit@k only at function level: file gold is always one file, where Hit@k = Recall@k.
FUNCTION_METRICS = (*METRICS, "hit@1", "hit@5", "hit@10")
ScoreLevel = Literal["file", "function"]

# Method name -> how to build a retriever for one snapshot directory.
RETRIEVERS: dict[str, Callable[[Path], Retriever]] = {
    "rg": RipgrepRetriever,
    # rg's matches credited to the chunk owning each matching line: function-level baseline.
    "rg-chunks": RipgrepChunkRetriever,
    # Dev-only measurement of the test-file exclusion; never a method to compare or tune.
    "rg-with-tests": lambda repo_dir: RipgrepRetriever(repo_dir, include_tests=True),
}


@dataclass(frozen=True)
class InstanceResult:
    instance_id: str
    repo: str
    category: int | None  # hand-labeled query category; None if unlabeled
    gold_files: list[str]
    ranking: list[str]  # file ranking that was scored, best first
    scores: dict[str, float]  # file level
    # Function level, chunk retrievers only (None for file retrievers). An empty
    # gold_chunks means no function-level gold, and function_scores is then None.
    gold_chunks: list[str] | None
    chunk_ranking: list[str] | None
    function_scores: dict[str, float] | None
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


def function_scores(ranking: Sequence[str], gold: set[str]) -> dict[str, float]:
    """All function-level metrics for one instance."""
    return {
        **file_scores(ranking, gold),
        "hit@1": hit_at_k(ranking, gold, 1),
        "hit@5": hit_at_k(ranking, gold, 5),
        "hit@10": hit_at_k(ranking, gold, 10),
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
        gold_chunks: set[str] | None = None
        chunk_ranking: list[str] | None = None
        fn_scores: dict[str, float] | None = None
        if retriever.level == "chunk":
            gold_chunks = function_gold(inst.patch, repo_dir)
            chunk_ranking = [hit.id for hit in hits]
            if gold_chunks:
                fn_scores = function_scores(chunk_ranking, gold_chunks)
        result = InstanceResult(
            instance_id=inst.instance_id,
            repo=inst.repo,
            category=categories.get(inst.instance_id),
            gold_files=sorted(gold),
            ranking=ranking,
            scores=file_scores(ranking, gold),
            gold_chunks=sorted(gold_chunks) if gold_chunks is not None else None,
            chunk_ranking=chunk_ranking,
            function_scores=fn_scores,
            build_seconds=round(built - start, 4),
            search_seconds=round(searched - built, 4),
        )
        results.append(result)
        print(
            f"[{i}/{len(instances)}] {inst.instance_id}  "
            f"R@10={result.scores['recall@10']:.0f}  MRR@10={result.scores['mrr@10']:.2f}"
        )
    return results, skipped


def _scores(r: InstanceResult, level: ScoreLevel) -> dict[str, float]:
    if level == "file":
        return r.scores
    assert r.function_scores is not None
    return r.function_scores


def _mean_scores(results: Sequence[InstanceResult], level: ScoreLevel) -> dict[str, float]:
    """Macro average: every instance counts once."""
    metrics = METRICS if level == "file" else FUNCTION_METRICS
    return {m: sum(_scores(r, level)[m] for r in results) / len(results) for m in metrics}


def summarize(
    results: Sequence[InstanceResult], level: ScoreLevel = "file"
) -> dict[str, dict[str, float]]:
    """Mean of each metric overall, per repo and per query category, plus the count `n`.

    level "file": every instance. level "function": only instances with function-level
    scores (chunk retrievers, non-empty function gold), so `n` can be smaller.
    """
    if level == "function":
        results = [r for r in results if r.function_scores is not None]
    if not results:
        return {}
    by_repo: dict[str, list[InstanceResult]] = defaultdict(list)
    by_category: dict[str, list[InstanceResult]] = defaultdict(list)
    for r in results:
        by_repo[r.repo].append(r)
        if r.category is not None:
            by_category[f"category {r.category}"].append(r)
    summary = {"overall": {"n": float(len(results)), **_mean_scores(results, level)}}
    for groups in (by_repo, by_category):
        for name in sorted(groups):
            summary[name] = {"n": float(len(groups[name])), **_mean_scores(groups[name], level)}
    return summary


def format_table(summary: dict[str, dict[str, float]]) -> str:
    """One row per group; the columns are whichever metrics the summary has."""
    if not summary:
        return "(no instances)"
    metrics = [m for m in next(iter(summary.values())) if m != "n"]
    header = f"{'':28} {'n':>4} " + " ".join(f"{m:>9}" for m in metrics)
    lines = [header, "-" * len(header)]
    for name, row in summary.items():
        cells = " ".join(f"{row[m]:>9.3f}" for m in metrics)
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


def ripgrep_version() -> str | None:
    """Installed ripgrep version, e.g. "ripgrep 15.2.0"; a different version could count
    matches differently, so it is part of a result's provenance."""
    try:
        out = subprocess.run(["rg", "--version"], capture_output=True, text=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return out.stdout.splitlines()[0].strip()


def write_results(
    method: str,
    split: str,
    results: Sequence[InstanceResult],
    skipped: Sequence[str],
    out_dir: Path = RESULTS_DIR,
) -> Path:
    """Write one run to <out_dir>/<method>_<split>_<UTC time>.json and return its path."""
    now = datetime.now(UTC)
    function_scored = any(r.gold_chunks is not None for r in results)
    payload = {
        "meta": {
            "method": method,
            "split": split,
            "k": K,
            "level_scored": "file+function" if function_scored else "file",
            "created_at": now.isoformat(timespec="seconds"),
            "codeatlas": git_state(),
            "dataset_revision": DATASET_REVISION,
            "ripgrep": ripgrep_version(),
            "skipped_no_gold": list(skipped),
            # Chunk retrievers: scored at file level only, for lack of function-level gold.
            "no_function_gold": [r.instance_id for r in results if r.gold_chunks == []],
        },
        "summary": summarize(results),
        "function_summary": summarize(results, "function"),
        "instances": [asdict(r) for r in results],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{method}_{split}_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path

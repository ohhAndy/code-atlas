"""Grid search over the RRF constant k for the hybrid (BM25 + semantic) retriever.

k only enters when the two rankings are fused, so each retriever is built and searched
once per instance (top `DEPTH` chunks), and every k fuses those same two lists. The k is
chosen by function-level MRR@10 with a noise margin: another k replaces the default only
if it beats it by at least MARGIN; a tie for best goes to the smaller k.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from code_atlas.eval.dataset import DATASET_REVISION, Instance
from code_atlas.eval.gold import changed_lines, function_gold
from code_atlas.eval.runner import (
    RESULTS_DIR,
    InstanceResult,
    K,
    git_state,
    score_instance,
    summarize,
)
from code_atlas.fusion.hybrid import DEPTH, HybridRetriever
from code_atlas.types import Hit, Level, Retriever

K_GRID = (10, 30, 60, 100)
DEFAULT_K = 60
METRIC = "mrr@10"  # function level
MARGIN = 0.02  # about one query's rank change on 30 queries


def choose_k(scores: Mapping[int, float]) -> int:
    """The best-scoring k, or DEFAULT_K if the best beats it by less than MARGIN. Ties for
    best go to the smaller k."""
    best = max(sorted(scores), key=lambda k: scores[k])  # max keeps the first of equals
    if scores[best] - scores[DEFAULT_K] < MARGIN:
        return DEFAULT_K
    return best


@dataclass
class MemoRetriever:
    """Wraps a retriever so a repeated (query, k) search is answered from memory. The
    sweep fuses the same two rankings once per k; this keeps it to one search each (one
    paid query embedding for Voyage)."""

    inner: Retriever
    level: Level = field(init=False)
    _memo: dict[tuple[str, int], list[Hit]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.level = self.inner.level

    def search(self, query: str, k: int) -> list[Hit]:
        if (query, k) not in self._memo:
            self._memo[(query, k)] = self.inner.search(query, k)
        return self._memo[(query, k)]


def sweep(
    instances: Sequence[Instance],
    repo_dir_for: Callable[[Instance], Path],
    make_first: Callable[[Path], Retriever],
    make_second: Callable[[Path], Retriever],
    categories: Mapping[str, int] | None = None,
) -> dict[int, list[InstanceResult]]:
    """Score every k in the grid on every instance; one build and one search per
    retriever per instance."""
    categories = categories or {}
    results: dict[int, list[InstanceResult]] = {k: [] for k in K_GRID}
    for i, inst in enumerate(instances, 1):
        gold = set(changed_lines(inst.patch))
        if not gold:
            continue
        repo_dir = repo_dir_for(inst)
        first = MemoRetriever(make_first(repo_dir))
        second = MemoRetriever(make_second(repo_dir))
        gold_chunks = function_gold(inst.patch, repo_dir)
        for rrf_k in K_GRID:
            hybrid = HybridRetriever(first, second, rrf_k=rrf_k, depth=DEPTH)
            hits = hybrid.search(inst.problem_statement, K)
            results[rrf_k].append(
                score_instance(
                    inst,
                    hits,
                    hybrid.level,
                    gold,
                    gold_chunks,
                    category=categories.get(inst.instance_id),
                )
            )
        print(f"[{i}/{len(instances)}] {inst.instance_id}")
    return results


def summarize_sweep(
    results: Mapping[int, Sequence[InstanceResult]],
) -> tuple[dict[int, dict[str, Any]], int]:
    """Per k: function- and file-level summaries. Plus the chosen k."""
    per_k = {
        k: {"function": summarize(rs, "function"), "file": summarize(rs)}
        for k, rs in results.items()
    }
    metric = {k: v["function"]["overall"][METRIC] for k, v in per_k.items()}
    return per_k, choose_k(metric)


def format_grid(per_k: Mapping[int, dict[str, Any]]) -> str:
    """Function-level MRR@10 and Hit@10 per k."""
    lines = [f"{'k':>5} {'MRR@10':>8} {'Hit@10':>8}", "-" * 23]
    for k in K_GRID:
        row = per_k[k]["function"]["overall"]
        lines.append(f"{k:>5} {row[METRIC]:>8.3f} {row['hit@10']:>8.3f}")
    return "\n".join(lines)


def write_sweep(
    split: str,
    methods: tuple[str, str],
    results: Mapping[int, Sequence[InstanceResult]],
    per_k: Mapping[int, dict[str, Any]],
    chosen: int,
    out_dir: Path = RESULTS_DIR,
) -> Path:
    """Write results/hybrid-sweep_<split>_<UTC time>.json and return its path."""
    now = datetime.now(UTC)
    payload = {
        "meta": {
            "method": "hybrid-sweep",
            "split": split,
            "k": K,
            "created_at": now.isoformat(timespec="seconds"),
            "codeatlas": git_state(),
            "dataset_revision": DATASET_REVISION,
            "fused": list(methods),
            "depth": DEPTH,
            "rrf_k_grid": list(K_GRID),
            "default": DEFAULT_K,
            "metric": f"function {METRIC}",
            "margin": MARGIN,
            "chosen": chosen,
        },
        "settings": [
            {
                "rrf_k": k,
                "function_summary": per_k[k]["function"],
                "summary": per_k[k]["file"],
                # Per-instance chunk ranking and function MRR@10, for comparing k values
                # and the single methods query by query.
                "instances": {
                    r.instance_id: {
                        METRIC: (r.function_scores or {}).get(METRIC),
                        "chunk_ranking": r.chunk_ranking,
                    }
                    for r in results[k]
                },
            }
            for k in results
        ],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"hybrid-sweep_{split}_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path

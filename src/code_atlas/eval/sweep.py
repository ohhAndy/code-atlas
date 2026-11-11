"""Grid search over BM25's k1 and b.

k1 and b only enter at scoring time, so each snapshot's index is built once and every
setting is scored against it. The setting is chosen by function-level MRR@10 with a noise
margin: the best setting replaces the defaults only if it beats them by at least MARGIN.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from typing import Any

from code_atlas.eval.dataset import DATASET_REVISION, Instance
from code_atlas.eval.gold import changed_lines, function_gold
from code_atlas.eval.runner import (
    RESULTS_DIR,
    InstanceResult,
    K,
    file_ranking,
    file_scores,
    function_scores,
    git_state,
    summarize,
)
from code_atlas.lexical.retriever import BM25Retriever

K1_GRID = (0.6, 0.9, 1.2, 1.5, 2.0)
B_GRID = (0.25, 0.5, 0.75, 1.0)
DEFAULTS = (1.2, 0.75)
METRIC = "mrr@10"  # function level
MARGIN = 0.02  # about one query's rank change on 30 queries

Setting = tuple[float, float]  # (k1, b)


def choose_setting(scores: Mapping[Setting, float]) -> Setting:
    """The best-scoring setting, or the defaults if the best beats them by less than
    MARGIN. Ties for best go to the first setting in grid order (k1, then b)."""
    best = max(sorted(scores), key=lambda s: scores[s])  # max keeps the first of equals
    if scores[best] - scores[DEFAULTS] < MARGIN:
        return DEFAULTS
    return best


def sweep(
    instances: Sequence[Instance],
    repo_dir_for: Callable[[Instance], Path],
    categories: Mapping[str, int] | None = None,
) -> dict[Setting, list[InstanceResult]]:
    """Score every grid setting on every instance; one index build per instance."""
    categories = categories or {}
    settings = list(product(K1_GRID, B_GRID))
    results: dict[Setting, list[InstanceResult]] = {s: [] for s in settings}
    for i, inst in enumerate(instances, 1):
        gold = set(changed_lines(inst.patch))
        if not gold:
            continue
        repo_dir = repo_dir_for(inst)
        retriever = BM25Retriever(repo_dir)
        gold_chunks = function_gold(inst.patch, repo_dir)
        for k1, b in settings:
            # Same index, new scoring parameters.
            retriever.k1, retriever.b = k1, b
            hits = retriever.search(inst.problem_statement, K)
            chunk_ranking = [hit.id for hit in hits]
            ranking = file_ranking(hits, retriever.level)
            results[(k1, b)].append(
                InstanceResult(
                    instance_id=inst.instance_id,
                    repo=inst.repo,
                    category=categories.get(inst.instance_id),
                    gold_files=sorted(gold),
                    ranking=ranking,
                    scores=file_scores(ranking, gold),
                    gold_chunks=sorted(gold_chunks),
                    chunk_ranking=chunk_ranking,
                    function_scores=(
                        function_scores(chunk_ranking, gold_chunks) if gold_chunks else None
                    ),
                    build_seconds=0.0,
                    search_seconds=0.0,
                )
            )
        print(f"[{i}/{len(instances)}] {inst.instance_id}")
    return results


def summarize_sweep(
    results: Mapping[Setting, Sequence[InstanceResult]],
) -> tuple[dict[Setting, dict[str, Any]], Setting]:
    """Per setting: function- and file-level summaries. Plus the chosen setting."""
    per_setting = {
        s: {"function": summarize(rs, "function"), "file": summarize(rs)}
        for s, rs in results.items()
    }
    metric = {s: v["function"]["overall"][METRIC] for s, v in per_setting.items()}
    return per_setting, choose_setting(metric)


def format_grid(per_setting: Mapping[Setting, dict[str, Any]]) -> str:
    """Function-level MRR@10 as a k1 x b table."""
    header = "k1 \\ b " + "".join(f"{b:>8}" for b in B_GRID)
    lines = [header, "-" * len(header)]
    for k1 in K1_GRID:
        cells = "".join(
            f"{per_setting[(k1, b)]['function']['overall'][METRIC]:>8.3f}" for b in B_GRID
        )
        lines.append(f"{k1:<7}{cells}")
    return "\n".join(lines)


def write_sweep(
    split: str,
    results: Mapping[Setting, Sequence[InstanceResult]],
    per_setting: Mapping[Setting, dict[str, Any]],
    chosen: Setting,
    out_dir: Path = RESULTS_DIR,
) -> Path:
    """Write results/bm25-sweep_<split>_<UTC time>.json and return its path."""
    now = datetime.now(UTC)
    payload = {
        "meta": {
            "method": "bm25-sweep",
            "split": split,
            "k": K,
            "created_at": now.isoformat(timespec="seconds"),
            "codeatlas": git_state(),
            "dataset_revision": DATASET_REVISION,
            "k1_grid": list(K1_GRID),
            "b_grid": list(B_GRID),
            "defaults": list(DEFAULTS),
            "metric": f"function {METRIC}",
            "margin": MARGIN,
            "chosen": {"k1": chosen[0], "b": chosen[1]},
        },
        "settings": [
            {
                "k1": k1,
                "b": b,
                "function_summary": per_setting[(k1, b)]["function"],
                "summary": per_setting[(k1, b)]["file"],
                # Per-instance function MRR@10, for comparing settings query by query.
                "instances": {
                    r.instance_id: (r.function_scores or {}).get(METRIC) for r in results[(k1, b)]
                },
            }
            for k1, b in results
        ],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"bm25-sweep_{split}_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path

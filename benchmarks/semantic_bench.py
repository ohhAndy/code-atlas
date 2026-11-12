"""Semantic and hybrid search benchmark: snapshot load, matrix size, and query latency
split into its parts (query embedding, vector top-k, full hybrid search).

Run: uv run python benchmarks/semantic_bench.py [--instance ID] [--runs N] [--reps R]
Needs VOYAGE_API_KEY, and the snapshot's chunk vectors already in the embedding cache
(run `codeatlas eval --method semantic-voyage --split dev` first). Each dev query is
embedded R + 1 times through the API (a few hundred thousand tokens in all).

Method, all on one snapshot (default: the largest dev corpus), in this process:
- load: build a SemanticRetriever with a warm embedding cache: chunk every corpus file,
  read every vector from SQLite, stack and normalize. 1 warm-up + N timed runs.
- matrix: rows, dimensions and bytes of the normalized float32 matrix (exact, not RSS).
- Per dev query (30), each latency the median of R timed calls after 1 warm-up:
    embed:  voyage-code-4 `embed_query`, one API request (network included)
    top_k:  `top_k` of the pre-embedded query against the matrix, k = 10
    hybrid: `HybridRetriever.search` as registered (BM25 top 100 + embed + top 100 +
            RRF), 1 timed call per query (it re-embeds the query each time)
  Reported: p50 / p95 / max over queries.
- Writes results/semantic_bench_<UTC time>.json and prints a summary.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from importlib.metadata import version

from code_atlas.eval.dataset import load_instances, read_split
from code_atlas.eval.repos import snapshot
from code_atlas.eval.runner import RESULTS_DIR, RETRIEVERS, K, _voyage, git_state
from code_atlas.semantic.cache import EMBEDDING_CACHE_DIR
from code_atlas.semantic.retriever import SemanticRetriever
from code_atlas.semantic.search import normalize, top_k

DEFAULT_INSTANCE = "sympy__sympy-22840"  # largest dev corpus


def _percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile, q in (0, 100]."""
    ordered = sorted(values)
    rank = max(1, round(q / 100 * len(ordered)))
    return ordered[rank - 1]


def _latency(values: list[float]) -> dict[str, float]:
    return {
        "n": len(values),
        "p50_ms": _percentile(values, 50),
        "p95_ms": _percentile(values, 95),
        "max_ms": max(values),
    }


def _median_ms(fn: Callable[[], object], reps: int) -> float:
    """Median of `reps` timed calls after one warm-up, in milliseconds."""
    fn()
    times = []
    for _ in range(reps):
        start = time.perf_counter()
        fn()
        times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times)


def _hardware() -> dict[str, str]:
    info = {"machine": platform.machine(), "system": platform.platform()}
    if sys.platform == "darwin":
        for key, name in (("cpu", "machdep.cpu.brand_string"), ("memory_bytes", "hw.memsize")):
            info[key] = subprocess.run(
                ["sysctl", "-n", name], capture_output=True, text=True, check=False
            ).stdout.strip()
    return info


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--instance", default=DEFAULT_INSTANCE)
    parser.add_argument("--runs", type=int, default=3, help="timed loads (after 1 warm-up)")
    parser.add_argument("--reps", type=int, default=3, help="timed calls per query")
    args = parser.parse_args()

    instances = load_instances()
    splits = read_split()
    dev = [i for i in instances if splits.get(i.instance_id) == "dev"]
    target = next(i for i in instances if i.instance_id == args.instance)
    target_dir = snapshot(target.repo, target.base_commit)
    embedder = _voyage()

    def load() -> SemanticRetriever:
        return SemanticRetriever(target_dir, embedder, cache_dir=EMBEDDING_CACHE_DIR)

    print(f"{target.instance_id}: load, 1 warm-up + {args.runs} runs")
    retriever = load()
    load_seconds = []
    for _ in range(args.runs):
        start = time.perf_counter()
        load()
        load_seconds.append(time.perf_counter() - start)
    matrix = retriever.matrix

    print(f"query latency: {len(dev)} dev queries x {args.reps} reps")
    embed_ms: list[float] = []
    topk_ms: list[float] = []
    for inst in dev:
        query = inst.problem_statement
        embed_ms.append(_median_ms(partial(embedder.embed_query, query), args.reps))
        q_vec = normalize(embedder.embed_query(query))
        topk_ms.append(_median_ms(partial(top_k, matrix, q_vec, K), args.reps))

    print(f"hybrid latency: {len(dev)} dev queries, 1 call each")
    hybrid = RETRIEVERS["hybrid"](target_dir)
    hybrid.search(dev[0].problem_statement, K)  # warm-up
    hybrid_ms = []
    for inst in dev:
        start = time.perf_counter()
        hybrid.search(inst.problem_statement, K)
        hybrid_ms.append((time.perf_counter() - start) * 1000)

    summary = {
        "matrix": {
            "rows": int(matrix.shape[0]),
            "dims": int(matrix.shape[1]),
            "bytes": int(matrix.nbytes),
        },
        "load_seconds": {
            "median": statistics.median(load_seconds),
            "min": min(load_seconds),
            "max": max(load_seconds),
        },
        "query_embed": _latency(embed_ms),
        "top_k": _latency(topk_ms),
        "hybrid_search": _latency(hybrid_ms),
    }
    now = datetime.now(UTC)
    ids = [i.instance_id for i in dev]
    payload = {
        "meta": {
            "benchmark": "semantic_bench",
            "instance": target.instance_id,
            "base_commit": target.base_commit,
            "model": embedder.model_id,
            "runs": args.runs,
            "reps_per_query": args.reps,
            "k": K,
            "cache": "warm (embedding cache filled; OS page cache warm after 1 load)",
            "created_at": now.isoformat(timespec="seconds"),
            "codeatlas": git_state(),
            "python": platform.python_version(),
            "numpy": version("numpy"),
            "voyageai": version("voyageai"),
            "hardware": _hardware(),
        },
        "summary": summary,
        "query_ms": {
            "embed": dict(zip(ids, embed_ms, strict=True)),
            "top_k": dict(zip(ids, topk_ms, strict=True)),
            "hybrid": dict(zip(ids, hybrid_ms, strict=True)),
        },
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"semantic_bench_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()

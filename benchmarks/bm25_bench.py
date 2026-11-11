"""BM25 benchmark: index build time and memory, cache load time, and query latency.

Run: uv run python benchmarks/bm25_bench.py [--instance ID] [--runs N] [--reps R]

Method:
- Build and cache load are measured on one snapshot (default: the largest dev corpus).
  Each run is a fresh Python process, so peak RSS (resident memory) belongs to that run
  alone. One warm-up run of each is discarded, so source files and the cache file are in
  the OS page cache (warm cache).
    build: chunk every corpus file, tokenize, build the inverted index (no disk cache)
    load:  read the pickled index from the on-disk cache
- Query latency is measured in this process on every dev query, each against its own
  snapshot's index (loaded from the cache beforehand, so only search is timed). Per query:
  1 untimed warm-up search, then R timed searches; the query's latency is the median of
  the R. Reported: p50 / p95 / max over queries. A second pass runs every dev query
  against the largest index, so corpus size is held fixed.
- search() includes tokenizing the query, scoring and sorting, k = 10.
- Writes results/bm25_bench_<UTC time>.json and prints a summary.
"""

from __future__ import annotations

import argparse
import json
import pickle
import platform
import resource
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from code_atlas.eval.dataset import load_instances, read_split
from code_atlas.eval.repos import snapshot
from code_atlas.eval.runner import RESULTS_DIR, K, git_state
from code_atlas.lexical.cache import INDEX_CACHE_DIR, code_fingerprint, snapshot_commit
from code_atlas.lexical.index import InvertedIndex
from code_atlas.lexical.retriever import BM25Retriever, build_snapshot_index

DEFAULT_INSTANCE = "sympy__sympy-22840"  # largest dev corpus: 903 files, ~524k lines


def _peak_rss_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024  # macOS: bytes; Linux: KiB


def _percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile, q in (0, 100]."""
    ordered = sorted(values)
    rank = max(1, round(q / 100 * len(ordered)))
    return ordered[rank - 1]


@dataclass(frozen=True)
class Run:
    seconds: float
    rss_after_imports_bytes: int
    peak_rss_bytes: int


def worker(mode: str, repo_dir: Path) -> Run:
    """One measured build or cache load, in this (fresh) process."""
    rss_after_imports = _peak_rss_bytes()
    start = time.perf_counter()
    if mode == "build":
        build_snapshot_index(repo_dir)
    else:
        BM25Retriever(repo_dir, cache_dir=INDEX_CACHE_DIR)
    seconds = time.perf_counter() - start
    return Run(seconds, rss_after_imports, _peak_rss_bytes())


def _run_worker(mode: str, repo_dir: Path) -> Run:
    out = subprocess.run(
        [sys.executable, __file__, "--worker", mode, str(repo_dir)],
        capture_output=True,
        text=True,
        check=True,
    )
    return Run(**json.loads(out.stdout))


def _hardware() -> dict[str, str]:
    info = {"machine": platform.machine(), "system": platform.platform()}
    if sys.platform == "darwin":
        for key, name in (("cpu", "machdep.cpu.brand_string"), ("memory_bytes", "hw.memsize")):
            info[key] = subprocess.run(
                ["sysctl", "-n", name], capture_output=True, text=True, check=False
            ).stdout.strip()
    return info


def _index_stats(index: InvertedIndex) -> dict[str, float]:
    return {
        "chunks": index.num_docs,
        "vocabulary": len(index.postings),
        "postings_entries": sum(len(p) for p in index.postings.values()),
        "total_tokens": sum(index.doc_lengths.values()),
        "avg_doc_length": index.avg_doc_length,
    }


def _time_query(retriever: BM25Retriever, query: str, reps: int) -> float:
    """Median of `reps` timed searches after one warm-up, in milliseconds."""
    retriever.search(query, K)
    times = []
    for _ in range(reps):
        start = time.perf_counter()
        retriever.search(query, K)
        times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times)


def _latency(values: list[float]) -> dict[str, float]:
    return {
        "n": len(values),
        "p50_ms": _percentile(values, 50),
        "p95_ms": _percentile(values, 95),
        "max_ms": max(values),
    }


def _seconds(values: list[float]) -> dict[str, float]:
    return {"median": statistics.median(values), "min": min(values), "max": max(values)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--instance", default=DEFAULT_INSTANCE)
    parser.add_argument("--runs", type=int, default=5, help="measured runs (after 1 warm-up)")
    parser.add_argument("--reps", type=int, default=5, help="timed searches per query")
    parser.add_argument("--worker", nargs=2, metavar=("MODE", "DIR"), help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.worker:
        mode, repo_dir = args.worker
        print(json.dumps(asdict(worker(mode, Path(repo_dir)))))
        return

    instances = load_instances()
    splits = read_split()
    dev = [i for i in instances if splits.get(i.instance_id) == "dev"]
    target = next(i for i in instances if i.instance_id == args.instance)
    target_dir = snapshot(target.repo, target.base_commit)

    # Build and load, each in fresh processes.
    print(f"{target.instance_id}: build, 1 warm-up + {args.runs} runs")
    _run_worker("build", target_dir)
    builds = [_run_worker("build", target_dir) for _ in range(args.runs)]
    target_retriever = BM25Retriever(target_dir, cache_dir=INDEX_CACHE_DIR)  # fills cache
    print(f"{target.instance_id}: cache load, 1 warm-up + {args.runs} runs")
    _run_worker("load", target_dir)
    loads = [_run_worker("load", target_dir) for _ in range(args.runs)]
    cache_file = (
        INDEX_CACHE_DIR / f"{snapshot_commit(target_dir)}-path-name-text-{code_fingerprint()}.pkl"
    )

    # Query latency, warm: every index loaded before any search is timed.
    print(f"query latency: {len(dev)} dev queries x {args.reps} reps")
    retrievers = {
        inst.instance_id: BM25Retriever(
            snapshot(inst.repo, inst.base_commit), cache_dir=INDEX_CACHE_DIR
        )
        for inst in dev
    }
    own_ms = [
        _time_query(retrievers[inst.instance_id], inst.problem_statement, args.reps) for inst in dev
    ]
    largest_ms = [_time_query(target_retriever, inst.problem_statement, args.reps) for inst in dev]

    def mib(values: list[int]) -> float:
        return statistics.median(values) / 2**20

    summary = {
        "index": {
            **_index_stats(target_retriever.index),
            "pickle_bytes": cache_file.stat().st_size,
            "in_memory_pickle_bytes": len(pickle.dumps(target_retriever.index)),
        },
        "build_seconds": _seconds([r.seconds for r in builds]),
        "build_peak_rss_mib": mib([r.peak_rss_bytes for r in builds]),
        "build_rss_after_imports_mib": mib([r.rss_after_imports_bytes for r in builds]),
        "load_seconds": _seconds([r.seconds for r in loads]),
        "load_peak_rss_mib": mib([r.peak_rss_bytes for r in loads]),
        "query_own_snapshot": _latency(own_ms),
        "query_largest_index": _latency(largest_ms),
    }
    now = datetime.now(UTC)
    payload = {
        "meta": {
            "benchmark": "bm25_bench",
            "instance": target.instance_id,
            "base_commit": target.base_commit,
            "runs": args.runs,
            "warmup_runs": 1,
            "reps_per_query": args.reps,
            "k": K,
            "k1": target_retriever.k1,
            "b": target_retriever.b,
            "cache": "warm (OS page cache; indexes loaded before queries are timed)",
            "created_at": now.isoformat(timespec="seconds"),
            "codeatlas": git_state(),
            "python": platform.python_version(),
            "tree_sitter": version("tree-sitter"),
            "tree_sitter_python": version("tree-sitter-python"),
            "hardware": _hardware(),
        },
        "summary": summary,
        "builds": [asdict(r) for r in builds],
        "loads": [asdict(r) for r in loads],
        "query_ms": {
            "own_snapshot": dict(zip([i.instance_id for i in dev], own_ms, strict=True)),
            "largest_index": dict(zip([i.instance_id for i in dev], largest_ms, strict=True)),
        },
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"bm25_bench_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()

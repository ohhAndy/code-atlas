"""Parse and chunk benchmark on one repo snapshot: wall time and peak memory.

Run: uv run python benchmarks/parse_bench.py [--instance ID] [--runs N]

Method:
- Each run is a fresh Python process, so peak RSS (resident memory) belongs to that run
  alone. The process first reads every corpus file into memory (timed separately: disk,
  not parsing), then times two passes over the in-memory bytes:
    parse:  tree-sitter parse of every file
    chunk:  chunk_file on every file (parse + definitions + chunk text), keeping all
            chunks in memory, as an index build would
- One warm-up run is discarded, so the files are in the OS page cache for the measured runs
  (warm cache).
- Reported per pass: median / min / max wall time over runs, and p50 / p95 per-file time
  from the median run. Peak RSS is reported with the RSS after imports, before any file is
  read, so the cost of the work itself is visible.
- Writes results/parse_bench_<UTC time>.json and prints a summary.
"""

from __future__ import annotations

import argparse
import json
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

from code_atlas.eval.dataset import load_instances
from code_atlas.eval.repos import snapshot
from code_atlas.eval.runner import RESULTS_DIR, git_state
from code_atlas.parse.chunks import Chunk, chunk_file
from code_atlas.parse.files import iter_corpus_files
from code_atlas.parse.parser import parse

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
    files: int
    lines: int
    bytes: int
    chunks: int
    read_seconds: float
    parse_seconds: float
    chunk_seconds: float
    parse_ms_per_file: list[float]
    chunk_ms_per_file: list[float]
    rss_after_imports_bytes: int
    peak_rss_bytes: int


def worker(repo_dir: Path) -> Run:
    """One measured run: timings, counts and memory."""
    rss_after_imports = _peak_rss_bytes()

    start = time.perf_counter()
    files = list(iter_corpus_files(repo_dir))
    read_seconds = time.perf_counter() - start

    parse_ms: list[float] = []
    for _, source in files:
        t = time.perf_counter()
        parse(source)
        parse_ms.append((time.perf_counter() - t) * 1000)

    chunk_ms: list[float] = []
    chunks: list[Chunk] = []
    for path, source in files:
        t = time.perf_counter()
        chunks.extend(chunk_file(path, source))
        chunk_ms.append((time.perf_counter() - t) * 1000)

    return Run(
        files=len(files),
        lines=sum(source.count(b"\n") for _, source in files),
        bytes=sum(len(source) for _, source in files),
        chunks=len(chunks),
        read_seconds=read_seconds,
        parse_seconds=sum(parse_ms) / 1000,
        chunk_seconds=sum(chunk_ms) / 1000,
        parse_ms_per_file=parse_ms,
        chunk_ms_per_file=chunk_ms,
        rss_after_imports_bytes=rss_after_imports,
        peak_rss_bytes=_peak_rss_bytes(),
    )


def _run_worker(repo_dir: Path) -> Run:
    out = subprocess.run(
        [sys.executable, __file__, "--worker", str(repo_dir)],
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--instance", default=DEFAULT_INSTANCE)
    parser.add_argument("--runs", type=int, default=5, help="measured runs (after 1 warm-up)")
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.worker:
        print(json.dumps(asdict(worker(args.worker))))
        return

    inst = next(i for i in load_instances() if i.instance_id == args.instance)
    repo_dir = snapshot(inst.repo, inst.base_commit)

    print(f"{inst.instance_id} @ {inst.base_commit[:10]}: 1 warm-up + {args.runs} runs")
    _run_worker(repo_dir)  # warm-up: fills the OS page cache; discarded
    runs = [_run_worker(repo_dir) for _ in range(args.runs)]

    def seconds(values: list[float]) -> dict[str, float]:
        return {
            "median": statistics.median(values),
            "min": min(values),
            "max": max(values),
        }

    median_run = sorted(runs, key=lambda r: r.chunk_seconds)[len(runs) // 2]

    def per_file(values: list[float]) -> dict[str, float]:
        return {
            "p50_ms": _percentile(values, 50),
            "p95_ms": _percentile(values, 95),
            "max_ms": max(values),
        }

    summary = {
        "corpus": {
            "files": median_run.files,
            "lines": median_run.lines,
            "bytes": median_run.bytes,
            "chunks": median_run.chunks,
        },
        "read_seconds": seconds([r.read_seconds for r in runs]),
        "parse_seconds": seconds([r.parse_seconds for r in runs]),
        "chunk_seconds": seconds([r.chunk_seconds for r in runs]),
        "parse_per_file": per_file(median_run.parse_ms_per_file),
        "chunk_per_file": per_file(median_run.chunk_ms_per_file),
        "peak_rss_mib": statistics.median(r.peak_rss_bytes for r in runs) / 2**20,
        "rss_after_imports_mib": statistics.median(r.rss_after_imports_bytes for r in runs) / 2**20,
    }
    now = datetime.now(UTC)
    payload = {
        "meta": {
            "benchmark": "parse_bench",
            "instance": inst.instance_id,
            "base_commit": inst.base_commit,
            "runs": args.runs,
            "warmup_runs": 1,
            "cache": "warm (OS page cache, after 1 discarded run)",
            "created_at": now.isoformat(timespec="seconds"),
            "codeatlas": git_state(),
            "python": platform.python_version(),
            "tree_sitter": version("tree-sitter"),
            "tree_sitter_python": version("tree-sitter-python"),
            "hardware": _hardware(),
        },
        "summary": summary,
        "runs": [{k: v for k, v in asdict(r).items() if not k.endswith("_per_file")} for r in runs],
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"parse_bench_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()

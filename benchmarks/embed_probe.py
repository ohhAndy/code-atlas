"""Embedding probe: workload size, token counts and throughput for the two embedding
model candidates, measured before any retrieval run.

Run: uv run --env-file .env python benchmarks/embed_probe.py [--sample N] [--skip-voyage]

Method:
- Workload: chunk every dev snapshot (test files excluded, as for retrieval) and collect
  each chunk's embedded text. Texts are counted per snapshot and as distinct texts; the
  embedding cache is keyed by text, so distinct texts are what gets embedded.
- Tokens: every distinct text is counted with each model's own tokenizer (both run
  locally, no API call). Reported: p50 / p95 / max per text, total, and texts over the
  model's input limit (those would be truncated).
- Throughput: N distinct texts drawn at random (seed 0). Qwen runs locally after 1
  untimed warm-up batch; Voyage is called through the API if VOYAGE_API_KEY is set.
  Throughput is in tokens per second, so the estimate for the whole workload accounts for
  text length. The longest distinct text is also embedded alone with Qwen, to check that
  the largest input fits in memory.
- The Voyage cost is an estimate: total tokens times a price from a third-party listing.
- Writes results/embed_probe_<UTC time>.json and prints a summary.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import resource
import statistics
import sys
import time
from datetime import UTC, datetime
from importlib.metadata import version
from typing import Any

from code_atlas.eval.dataset import load_instances, read_split
from code_atlas.eval.repos import snapshot
from code_atlas.eval.runner import RESULTS_DIR, git_state
from code_atlas.parse.chunks import chunk_file
from code_atlas.parse.files import iter_corpus_files
from code_atlas.semantic.embed import (
    VOYAGE_MODEL,
    Embedder,
    QwenEmbedder,
    VoyageEmbedder,
    embedded_text,
)

# Third-party listing for voyage-code-4, checked 2026-11-11; not Voyage's own page.
VOYAGE_PRICE_PER_MILLION = 0.12
COUNT_BATCH = 1000


def _peak_rss_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024  # macOS: bytes; Linux: KiB


def _percentile(values: list[int], q: float) -> int:
    """Nearest-rank percentile, q in (0, 100]."""
    ordered = sorted(values)
    rank = max(1, round(q / 100 * len(ordered)))
    return ordered[rank - 1]


def dev_workload() -> tuple[list[str], dict[str, Any]]:
    """Distinct embedded texts over all dev snapshots, plus per-snapshot counts."""
    split = read_split()
    instances = [i for i in load_instances() if split.get(i.instance_id) == "dev"]
    distinct: dict[str, None] = {}
    per_snapshot: dict[str, int] = {}
    for inst in sorted(instances, key=lambda i: i.instance_id):
        repo_dir = snapshot(inst.repo, inst.base_commit)
        count = 0
        for path, source in iter_corpus_files(repo_dir):
            for chunk in chunk_file(path, source):
                distinct[embedded_text(chunk)] = None
                count += 1
        per_snapshot[inst.instance_id] = count
        print(f"  {inst.instance_id}: {count} chunks", file=sys.stderr)
    total = sum(per_snapshot.values())
    stats = {
        "snapshots": len(per_snapshot),
        "chunks_over_all_snapshots": total,
        "distinct_texts": len(distinct),
        "distinct_fraction": round(len(distinct) / total, 4) if total else None,
        "chunks_per_snapshot": per_snapshot,
    }
    return list(distinct), stats


def token_stats(embedder: Embedder, texts: list[str]) -> tuple[list[int], dict[str, Any]]:
    counts: list[int] = []
    for start in range(0, len(texts), COUNT_BATCH):
        counts.extend(embedder.count_tokens(texts[start : start + COUNT_BATCH]))
    over = [c for c in counts if c > embedder.max_tokens]
    return counts, {
        "input_limit": embedder.max_tokens,
        "p50": _percentile(counts, 50),
        "p95": _percentile(counts, 95),
        "max": max(counts),
        "mean": round(statistics.fmean(counts), 1),
        "total": sum(counts),
        "texts_over_limit": len(over),
        "tokens_past_limit": sum(c - embedder.max_tokens for c in over),
    }


def time_embedding(embedder: Embedder, sample: list[str], sample_tokens: int) -> dict[str, Any]:
    start = time.perf_counter()
    vectors = embedder.embed_documents(sample)
    seconds = time.perf_counter() - start
    return {
        "texts": len(sample),
        "tokens": sample_tokens,
        "seconds": round(seconds, 3),
        "tokens_per_second": round(sample_tokens / seconds, 1),
        "dimensions": int(vectors.shape[1]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sample", type=int, default=200, help="texts for the timing runs")
    parser.add_argument("--skip-voyage", action="store_true", help="never call the API")
    args = parser.parse_args()

    print("chunking dev snapshots...", file=sys.stderr)
    texts, workload = dev_workload()

    print("loading Qwen...", file=sys.stderr)
    qwen = QwenEmbedder()
    voyage_key = os.environ.get("VOYAGE_API_KEY")
    use_voyage_api = bool(voyage_key) and not args.skip_voyage
    # Token counting needs no key; the client is only used for tokenize() without one.
    voyage = VoyageEmbedder(api_key=voyage_key or "unused")

    print(f"counting tokens for {len(texts)} distinct texts...", file=sys.stderr)
    qwen_counts, qwen_tokens = token_stats(qwen, texts)
    voyage_counts, voyage_tokens = token_stats(voyage, texts)
    voyage_tokens["estimated_cost_usd"] = round(
        voyage_tokens["total"] / 1e6 * VOYAGE_PRICE_PER_MILLION, 2
    )

    rng = random.Random(0)
    sample_idx = rng.sample(range(len(texts)), min(args.sample, len(texts)))
    sample = [texts[i] for i in sample_idx]

    print("timing Qwen...", file=sys.stderr)
    qwen.embed_documents(sample[:8])  # warm-up: weights onto the device, kernels compiled
    qwen_rss_before = _peak_rss_bytes()
    qwen_timing = time_embedding(qwen, sample, sum(qwen_counts[i] for i in sample_idx))
    qwen_timing["peak_rss_mib"] = round(_peak_rss_bytes() / 2**20)
    qwen_timing["estimated_hours_for_workload"] = round(
        qwen_tokens["total"] / qwen_timing["tokens_per_second"] / 3600, 2
    )

    longest = max(range(len(texts)), key=lambda i: qwen_counts[i])
    print(f"embedding the longest text ({qwen_counts[longest]} tokens)...", file=sys.stderr)
    try:
        start = time.perf_counter()
        qwen.embed_documents([texts[longest]])
        qwen_longest: dict[str, Any] = {
            "tokens": qwen_counts[longest],
            "seconds": round(time.perf_counter() - start, 3),
            "peak_rss_mib": round(_peak_rss_bytes() / 2**20),
        }
    except RuntimeError as err:  # out of memory on the device surfaces as RuntimeError
        qwen_longest = {"tokens": qwen_counts[longest], "error": str(err)[:500]}

    voyage_timing: dict[str, Any] | None = None
    if use_voyage_api:
        print("timing Voyage...", file=sys.stderr)
        voyage_timing = time_embedding(voyage, sample, sum(voyage_counts[i] for i in sample_idx))
        voyage_timing["tokens_billed"] = voyage.tokens_billed
        voyage_timing["estimated_hours_for_workload"] = round(
            voyage_tokens["total"] / voyage_timing["tokens_per_second"] / 3600, 2
        )

    import torch

    result = {
        "benchmark": "embed_probe",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "code": git_state(),
        "environment": {
            "machine": platform.machine(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "torch": torch.__version__,
            "sentence_transformers": version("sentence-transformers"),
            "voyageai": version("voyageai"),
            "qwen_device": str(qwen.model.device),
        },
        "split": "dev",
        "workload": workload,
        "models": {
            qwen.model_id: {
                "tokens": qwen_tokens,
                "timing": qwen_timing,
                "rss_before_timing_mib": round(qwen_rss_before / 2**20),
                "longest_text": qwen_longest,
            },
            VOYAGE_MODEL: {
                "tokens": voyage_tokens,
                "price_per_million_usd": VOYAGE_PRICE_PER_MILLION,
                "timing": voyage_timing or "skipped: no VOYAGE_API_KEY or --skip-voyage",
            },
        },
    }
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS_DIR / f"embed_probe_{stamp}.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "workload"}, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

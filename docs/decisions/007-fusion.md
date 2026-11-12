# ADR 007: Fusion method

**Status:** Accepted; k = 10 chosen on dev, and the hybrid did not beat semantic search
(see Outcome)
**Date:** 2026-11-12

## Context
BM25 and semantic search fail on different queries. BM25 needs shared words: it missed
`django-15388` because the issue says "templates" and "restart" and the code says
`template` and `autoreload`. Semantic search matches meaning but can blur an exact
identifier or path, which is what category-1 queries carry. A hybrid that combines the
two rankings can recover a chunk that either method finds.

The two methods' scores cannot be added directly:
- BM25 scores are unbounded (0 to about 30 here) and grow with query length, so they
  differ in scale from query to query.
- Cosine scores lie in [-1, 1], and each embedding model spreads them differently.

So fusion has to make the two rankings comparable. This ADR fixes how, before any
semantic or hybrid result is seen.

## Options considered
- **Reciprocal rank fusion (RRF):** score(id) = sum over rankings of 1 / (k + rank). Uses
  only ranks, so the two scales never meet. Discards how far ahead a top result was
  (30 vs 5 and 10.1 vs 10.0 look the same), which hurts when one method is very sure.
- **Min-max score fusion:** rescale each method's scores to [0, 1] per query and add
  them, possibly weighted. Keeps score gaps, but one outlier score compresses all others
  towards 0, and a weight is one more parameter to tune on 30 queries. Not built: parked
  in `docs/later.md` for time, since RRF needs no calibration.
- **Learned fusion or a reranker:** needs training data or another model; out of scope.

## Decision

### Method
RRF over two rankings: BM25 and the embedding model chosen under ADR 006. Not BM25 plus
both models: a three-way fusion is a further candidate, and each extra combination tried
on 30 dev queries is another chance to pick a winner by noise.

### Depth
Each method contributes its top **100** chunks; the hybrid returns the top 10 of the
fused scores. Why: a chunk ranked 15th by BM25 and 12th by semantic search scores
1/75 + 1/72 ≈ 0.0272 with k = 60, above a chunk ranked 1st by one method alone
(1/61 ≈ 0.0164). With a depth of 10 it would get 0 from both and could never be rescued.
Past rank 100, 1/(k + rank) is small enough to change little. The cost is negligible:
both methods already score every candidate chunk. Fixed, not tuned.

Ties in the fused score are broken by chunk id, as in BM25, so results are reproducible.

### Tuning `k` (fixed before any hybrid run)
- Dev split only. Metric: function-level MRR@10.
- Grid: k in {10, 30, 60, 100}. Default 60, the value in the original RRF paper
  (Cormack et al., 2009).
- Rule: keep k = 60 unless another k beats it by 0.02 MRR@10 or more; on a tie for
  best, the smaller k. Same margin as `k1` / `b` and ADR 006: about one query's rank
  change on 30 queries.
- The grid, metric and rule do not change after results are seen.

### When the hybrid counts as better
The hybrid becomes the headline method only if it beats **the better of BM25 and
semantic search** by 0.02 MRR@10 or more on dev. Otherwise the result is reported as
"fusion did not help on this data" and the simpler single method is the headline. Either
way, all three methods are reported per query category, since each may win on a
different kind of query.

## Consequences
- RRF ignores score gaps, so a query where one method is very confident (an exact
  function name from a traceback) gets no extra weight for it.
- Fusion is computed only over chunks in at least one top-100 list; a chunk outside both
  scores 0.
- A larger k favors chunks found by both methods; a smaller k lets one method's top
  results win alone. The sweep shows which this data prefers; it is not a claim about
  code search in general.
- Changing the depth, the tie rule, or the fused methods is a new method with its own
  runs.

## Outcome
**Fusion did not help on this data. The headline method is `semantic-voyage`.**

Sweep: `results/hybrid-sweep_dev_20261112T220543Z.json` (commit `7da957e`, clean), RRF
of `bm25` and `semantic-voyage`, depth 100.

| Function level, dev (n = 30) | MRR@10 | Hit@10 |
|---|---|---|
| `bm25` | 0.290 | 0.567 |
| `semantic-voyage` | **0.767** | **0.900** |
| hybrid, k = 10 | 0.614 | 0.867 |
| hybrid, k = 30 | 0.546 | 0.867 |
| hybrid, k = 60 | 0.531 | 0.800 |
| hybrid, k = 100 | 0.530 | 0.800 |

- Chosen k: 10. It beats the default 60 by 0.083, over the 0.02 margin.
- The hybrid at k = 10 is 0.153 *below* `semantic-voyage`, and below it in every repo and
  both categories. Under this ADR's rule it is not the headline method.
- Why: RRF weights both lists equally, and on dev BM25 is much weaker than voyage-code-4
  and finds no instance that voyage misses. A chunk ranked 1st by voyage alone scores
  1/(k + 1), less than a chunk both lists put around 5th (2/(k + 5)), for every k in the
  grid. A smaller k only narrows that gap, which is why k = 10 does best.
- Per instance at k = 10 against voyage alone: 2 instances improve and 11 get worse.
  9 of the 11 lose a rank-1 hit, and django-16820 drops out of the top 10.
- The hybrid stays registered as `hybrid` (k = 10) so it can be reported next to the
  single methods. Weighted fusion, which this ADR did not include, is parked (see
  `docs/later.md`).

# CodeAtlas

Code retrieval for Python repositories, evaluated on SWE-bench Lite: given a GitHub issue,
rank the files and functions most likely to need changing. Methods: a ripgrep baseline,
BM25 over Tree-sitter chunks, embedding search, and a reciprocal-rank-fusion hybrid.

## Results

70 test issues from SWE-bench Lite: django 32, sympy 22, scikit-learn 16. Every method
was tuned on a separate 30-issue dev split. Each test number below was produced once, by
a logged final run, from a clean commit. Test files (`tests/` directories) are excluded
from the corpus.

**Function level.** The gold is the functions, methods and classes that the fix changes.
"Hit@10" is the share of issues with at least one gold function in the top 10.

| Method | MRR@10 | Recall@1 | Recall@5 | Recall@10 | Hit@10 |
|---|---|---|---|---|---|
| ripgrep, credited to chunks (`rg-chunks`) | 0.117 | 0.071 | 0.150 | 0.214 | 0.229 |
| BM25 (`bm25`) | 0.262 | 0.140 | 0.367 | 0.438 | 0.500 |
| Semantic, voyage-code-4 (`semantic-voyage`) | **0.603** | **0.412** | **0.740** | **0.840** | **0.871** |
| Hybrid, RRF of BM25 + semantic, k = 10 (`hybrid`) | 0.486 | 0.283 | 0.650 | 0.755 | 0.800 |

**File level.** The gold is the files that the fix changes.

| Method | MRR@10 | Recall@1 | Recall@10 |
|---|---|---|---|
| ripgrep (`rg`) | 0.454 | 0.371 | 0.643 |
| `bm25` | 0.641 | 0.571 | 0.771 |
| `semantic-voyage` | **0.880** | **0.843** | **0.929** |
| `hybrid` | 0.798 | 0.714 | 0.900 |

**By query category** (function-level MRR@10). Category 1 issues contain a traceback or a
file path. Category 2 issues name a code identifier but have neither. No issue in this
subset describes behavior alone, so there is no category 3.

| Category | n | `bm25` | `semantic-voyage` | `hybrid` |
|---|---|---|---|---|
| 1: traceback or path | 38 | 0.296 | **0.641** | 0.558 |
| 2: identifier only | 32 | 0.221 | **0.559** | 0.401 |

**By repository** (function-level MRR@10):

| Repo | n | `bm25` | `semantic-voyage` | `hybrid` |
|---|---|---|---|---|
| django | 32 | 0.377 | **0.601** | 0.544 |
| scikit-learn | 16 | 0.265 | **0.735** | 0.550 |
| sympy | 22 | 0.092 | **0.511** | 0.355 |

Results files: `results/{rg,rg-chunks,bm25,semantic-voyage,hybrid}_test_*.json`.

### What the results show
- **Semantic search is the best method on every slice.** It more than doubles BM25's
  function-level MRR@10 (0.262 to 0.603), and its Hit@10 is 0.871 against 0.500. The
  biggest gain is on sympy (0.092 to 0.511). There, issues paste REPL sessions and math,
  and the code that needs changing is named differently from anything in the issue.
- **Fusion made results worse, not better.** The hybrid is 0.117 below semantic search
  alone on test. On dev it was 0.153 below, so it was not adopted as the main method
  ([ADR 007](docs/decisions/007-fusion.md)). RRF counts both rankings equally, so when
  BM25 is much weaker, its votes push down chunks that semantic search alone had ranked
  correctly. A chunk ranked 1st by one list scores less than a chunk both lists rank
  5th, for every k tried. On test the hybrid ranks gold higher than semantic search on 8
  issues, and lower on 29.
- **Semantic search wins on mismatched wording.** django-15851: the issue says "dbshell
  additional parameters should be passed before dbname on PostgreSQL". The fix is in
  `DatabaseClient.settings_to_cmd_args_env`, whose name shares no word with the issue.
  Semantic search ranks it 1st. BM25's top results match the pasted shell output.
- **BM25 wins on exact identifiers.** django-15902: the issue title names
  `ManagementForm`, the gold class. BM25 ranks it 1st, while semantic search ranks it 9th,
  below general template-rendering code that matches the topic but not the class.
  BM25 ranks gold above semantic search on 6 of the 70 test issues.
- **When the two methods agree, the hybrid can beat both.** In sympy-17139, BM25 ranks the
  gold function 4th and semantic search 5th; the hybrid ranks it 1st. Cases like this are
  why fusion is usually expected to help, but here they are outnumbered.
- **Dev numbers were optimistic.** Semantic search scored 0.767 on dev and 0.603 on test.
  The embedding model, the RRF k and BM25's parameters were all chosen on dev, so some
  of the dev score is selection on 30 issues.
- **What can't be claimed.** Only one embedding model was fused, and only with
  equal-weight RRF, so this doesn't show that hybrid search fails in general. Why
  voyage-code-4 beat the local candidate, Qwen3-Embedding-0.6B (0.767 vs 0.454 on dev), is
  also unknown: model size, training data and the API vs local setup all differ
  ([ADR 006](docs/decisions/006-embedding-model.md)). And django, scikit-learn and sympy
  are probably in the model's training data.

### Speed and memory
Measured on an Apple M4 Pro (24 GB), on the largest dev snapshot: sympy, 31,502 chunks.
The source is `results/semantic_bench_20261112T223245Z.json`.

| Step | p50 | p95 |
|---|---|---|
| Embed the query (voyage-code-4 API call) | 140 ms | 191 ms |
| Vector top-k (brute force, 31,502 × 1,024) | 2.2 ms | 2.6 ms |
| Full hybrid search (BM25 + embed + top-k + RRF) | 211 ms | 278 ms |

- **Query time is the API call.** The vector search itself is about 1% of it, so brute
  force is fine at this size.
- **Memory:** the vector matrix takes 129 MB as float32. Loading a snapshot from the
  embedding cache takes 3.1 s.

## Reproduce the results

Prerequisites: [uv](https://docs.astral.sh/uv/), `git`, and
[ripgrep](https://github.com/BurntSushi/ripgrep) (`rg`) on your `PATH`.

```bash
git clone <this repo> && cd code-atlas
uv run codeatlas eval --method rg --split dev
```

That one command installs the Python dependencies, downloads the pinned SWE-bench Lite
revision, clones each repository and checks out every base commit it needs (into `.cache/`,
gitignored), runs the ripgrep baseline, prints the table and writes
`results/rg_dev_<UTC time>.json`.

The first run takes a while and needs disk space: about 0.7 GB of bare clones for django,
sympy and scikit-learn plus about 1.1 GB of dev snapshots (all 100 snapshots: roughly
4.5 GB, estimated). Later runs reuse the cache.

To reproduce the reported numbers exactly, check out the commit recorded in the results
file (`meta.codeatlas.commit`) and use the same ripgrep version (`meta.ripgrep`).

The test split is for final, logged runs only:

```bash
uv run codeatlas eval --method rg --split test --final
```

Other methods are `rg-chunks`, `bm25`, `semantic-voyage` and `hybrid`. `bm25` needs nothing
extra. `semantic-voyage` and `hybrid` call Voyage's embedding API, so they need a key in
the environment:

```bash
export VOYAGE_API_KEY=...
uv run codeatlas eval --method semantic-voyage --split dev
uv run codeatlas sweep-rrf        # the RRF k sweep on dev
```

The first semantic run embeds every chunk of every snapshot: about 24 M tokens for dev
(estimated from a local token count; within Voyage's free allowance when this was run).
Vectors are cached in `.cache/embeddings/`, so later runs only pay for query embeddings.
`semantic-qwen` runs the local candidate (Qwen3-Embedding-0.6B) with no key. It took
several hours on an M4 Pro for dev.

## Development

```bash
uv run pytest
uv run ruff check && uv run ruff format --check
uv run mypy
```

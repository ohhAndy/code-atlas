# CodeAtlas: Plan

> A Python code retrieval engine, evaluated on real bug reports.
> **Stack:** Python 3.12+, Tree-sitter, NumPy, pytest, ruff, mypy
> **Collaboration rules:** see [AGENTS.md](AGENTS.md)
> **Last updated:** 2026-11-11

---

## 1. Goal

CodeAtlas answers one question: **given a natural-language problem description, which functions in this repository are relevant?**

It implements several retrieval methods and measures them against ground truth taken from real GitHub issues (SWE-bench Lite). The measured comparison is the product. The search tool is the vehicle.

### Why this project

- Puts verifiable Python work on my resume, aimed at applied LLM and retrieval roles.
- Builds skills my resume has no evidence for yet: retrieval, evaluation methodology, performance measurement.
- Produces a project I can defend line by line in a technical deep-dive.

### Success criteria (MVP = Phases 0 to 3)

1. One command reproduces the results table from a clean clone.
2. The results table compares a ripgrep baseline, BM25, semantic search and hybrid search on a held-out test set, at file level and function level.
3. A written analysis explains where each method wins and fails, with concrete examples.
4. Latency, build time and memory are measured with a stated method and hardware.
5. I can explain every core component (metrics, chunking, tokenizer, inverted index, BM25, vector search, RRF) and its tradeoffs without notes.

### Non-goals

- Languages other than Python
- Vector databases, LangChain, or other retrieval frameworks
- Library implementations of core components (e.g. `rank_bm25`). Building these is the point.
- TUI or web UI
- Incremental re-indexing or file watching
- Exact call resolution

Anything outside this list goes in `docs/later.md`, not into the current phase.

---

## 2. Time Budget

- **5 to 6 hours/week.** Career priority #2, after DSA (7 to 8 h/week).
- All estimates below are rough guesses.

| Phase | Est. hours |
|---|---|
| 0. Evaluation harness | 10 to 15 |
| 1. Parsing and chunking | 15 to 20 |
| 2. Lexical search | 15 to 20 |
| 3. Semantic and hybrid | 20 to 25 |
| 4. Graph expansion (stretch) | 15 to 20 |
| 5. Interface (stretch) | 5 to 10 |

---

## 3. Architecture

```text
 SWE-bench Lite instance
 (issue text, repo, base commit, gold patch)
          |
          v
 +-------------------+      checkout at base commit      +------------------+
 |  Eval harness     | --------------------------------> |  Repo snapshot   |
 |  gold labels,     |                                   +--------+---------+
 |  metrics, runner  |                                            |
 +---------+---------+                                            v
           |                                         +------------------------+
           |                                         | Parser + chunker       |
           |                                         | (Tree-sitter, Python)  |
           |                                         +-----------+------------+
           |                                                     | chunks
           |                         +---------------------------+-------------+
           |                         v                                         v
           |              +---------------------+               +------------------------+
           |              | Lexical index       |               | Embedding store        |
           |              | tokenizer, inverted |               | content-hash cache,    |
           |              | index, BM25         |               | normalized matrix      |
           |              +----------+----------+               +-----------+------------+
           |                         |                                      |
           |                         +------------------+-------------------+
           |                                            v
           |                                 +---------------------+
           |   query = issue text            |  Fusion (RRF)       |
           +-------------------------------> |  [graph expansion]  |
                                             +----------+----------+
                                                        v
                                               ranked chunks -> scored by harness
```

### Key interfaces

```python
@dataclass(frozen=True)
class Chunk:
    id: str                 # stable, e.g. "path::QualifiedName"
    path: str               # repo-relative
    qualified_name: str     # e.g. "Session.request", "<module>"
    kind: Literal["function", "method", "class", "module"]
    start_line: int
    end_line: int
    text: str
    content_hash: str

@dataclass(frozen=True)
class Hit:
    id: str                 # file path or chunk id, per the retriever's level
    score: float

class Retriever(Protocol):
    level: Literal["file", "chunk"]
    def search(self, query: str, k: int) -> list[Hit]: ...
```

The harness depends only on `Retriever`. A new method is a new class plus one registry entry. Each retriever is constructed per snapshot (`Retriever(repo_dir)`), and the constructor does any indexing. See [ADR 003](docs/decisions/003-retriever-interface.md).

---

## 4. Repository Layout

```text
src/code_atlas/
  eval/        dataset loading, repo checkout, gold labels, metrics, runner, categories
  baselines/   ripgrep baseline
  parse/       tree-sitter parsing, symbol extraction, chunking
  lexical/     tokenizer, inverted index, BM25
  semantic/    embedding client, cache, vector search
  fusion/      RRF (and later, graph expansion)
  cli.py
tests/
benchmarks/
results/       generated JSON, never hand-edited
splits/        dev/test split and query categories
notebooks/     data exploration
docs/
  decisions/   ADRs
  log.md       per-phase log: work, decisions, findings, problems, retro
  later.md     parked ideas
```

---

## 5. Evaluation Protocol

This is defined in Phase 0 and frozen before Phase 2 starts.

### Dataset

- SWE-bench Lite (`princeton-nlp/SWE-bench_Lite` on Hugging Face).
- Fields used: `instance_id`, `repo`, `base_commit`, `problem_statement`, `patch`. Test changes live in `test_patch` and are ignored.
- **Subset:** 50 to 100 instances from 2 to 3 repos. Choose them after inspecting per-repo counts and repo size, since every distinct base commit has to be indexed.

### Gold labels

- **File level:** files modified by `patch`.
- **Function level:** functions, methods and classes that exist at the base commit and whose line range overlaps a modified hunk.
  - Hunks in top-level code map to that file's module chunk.
  - Functions the patch adds are excluded, because they don't exist when the query runs.
- Instances with no function-level gold are scored at file level only. Record how many there are.
- Function-level gold must be produced by the same chunker the retrievers use, so labels and retrieval units match.

### Split

- **Dev:** about 30% of instances. **Test:** the rest. Split by instance with a fixed seed.
- All tuning happens on dev only. This includes tokenizer choices, `k1`, `b`, chunk size, the embedding model and the RRF `k`.
- The test set is run only to report results, and every test run is logged.

### Metrics

- Recall@1, Recall@5, Recall@10 and MRR@10, at file level and function level. MRR is cut at 10 so it does not depend on how many results a retriever returns.
- Hit@1, Hit@5, Hit@10 at function level only (an instance can have several gold functions; at file level Hit@k = Recall@k).
- File-level scores for chunk retrievers: rank each file by its best-ranked chunk.

### Query categories

Label these once in Phase 0, before seeing any results. Write down the labeling rule.

1. Contains a traceback or file path
2. Names a code identifier
3. Describes behavior only

Tracebacks leak file paths and inflate lexical scores, so results are always reported per category as well as overall.

### Reproducibility

- Pinned dependencies and a fixed seed.
- Cached repo checkouts.
- Each results JSON records the CodeAtlas git commit, method config and split.

---

## 6. Phases

### Phase 0: Evaluation Harness

**Goal:** a scoreboard that every later method is measured against.

**Learn:** retrieval metrics, evaluation design, data leakage, git checkouts at specific commits.

**Tasks**

- [x] Project skeleton: `pyproject.toml`, ruff, `mypy --strict`, pytest, GitHub Actions CI.
- [x] Load SWE-bench Lite, inspect per-repo counts, choose the subset, and write the dev/test split to a file (ADR 001).
- [x] Repo cache: clone each repo once and check out each `base_commit` into a working directory.
- [x] Parse `patch` into modified files and old-file line ranges per hunk. A diff library such as `unidiff` is fine here.
- [x] Implement metrics, with unit tests against hand-computed examples.
- [x] Define the `Retriever` protocol and a ripgrep baseline: extract identifiers from the issue text, count `rg` hits per file, rank files.
- [x] Build the runner: `codeatlas eval --method rg --split dev` writes JSON and prints a table.
- [x] Label query categories.

**Done when**

- File-level baseline numbers are reported for dev and test.
- Metric tests pass.
- A fresh clone reproduces the numbers with one command.

### Phase 1: Parsing and Chunking

**Goal:** turn a repo snapshot into function-level chunks, and make function-level evaluation possible.

**Learn:** syntax trees, scope tracking, byte vs character offsets, edge-case testing, parse benchmarking.

**Tasks**

- [x] Integrate `tree-sitter` with the Python grammar.
- [x] Walk the tree and extract functions, methods, classes and decorated definitions. Build qualified names with a scope stack.
- [x] Chunking policy (ADR 004):
  - One chunk per function or method.
  - Class chunk = header, docstring and class-level attributes, without method bodies.
  - Module chunk = top-level code outside definitions.
  - A rule for oversized functions.
- [x] Generate function-level gold labels (ADR 002).
- [x] Map ripgrep hits to their enclosing chunks to get a function-level baseline.
- [x] Tests for:
  - nested classes and nested functions
  - decorators and `async def`
  - files with syntax errors (`ERROR` nodes)
  - non-ASCII source, since tree-sitter uses byte offsets and Python `str` uses characters
- [x] Benchmark parse and chunk time, plus peak memory, on the largest repo in the subset.

**Done when**

- Tests pass.
- Function-level gold labels and the function-level baseline are reported.
- The parse benchmark is recorded.

### Phase 2: Lexical Search

**Goal:** BM25 built from scratch on code-aware tokens.

**Learn:** inverted indexes, BM25 and its parameters, latency measurement.

**Tasks**

- [x] Tokenizer (ADR 005):
  - Split on non-alphanumerics, `camelCase` and `snake_case`.
  - Lowercase.
  - Keep the full identifier alongside its parts.
  - Decide whether to drop stopwords.
  - Apply the same tokenizer to queries.
- [x] Inverted index: token to postings (chunk id, term frequency), plus document lengths and average length.
- [x] BM25, with unit tests against hand-computed scores.
- [x] Cache built indexes on disk per (repo, commit).
- [x] Tune `k1` and `b` on dev.
- [x] Measure:
  - Index build time and memory.
  - Query latency at p50 and p95 over all queries, with a warm cache and stated hardware.
- [ ] Failure analysis: read 10 dev misses and write down why each one failed.

**Done when**

- BM25 and baseline results are reported side by side.
- The latency table is recorded.
- The failure analysis is written.

### Phase 3: Semantic and Hybrid Search

**Goal:** find relevant code that shares no words with the query, and combine both methods.

**Learn:** embeddings, normalization and cosine similarity, matrix operations, caching, rank fusion.

**Tasks**

- [ ] Choose an embedding model (ADR 006):
  - At most 2 candidates, e.g. one local open model and one API such as Cohere Embed.
  - Compare dev quality, cost, speed and reproducibility.
- [ ] Decide what text gets embedded per chunk (path, qualified name, code) and how to handle the model's input-length limit.
- [ ] Build an embedding cache keyed by a hash of (chunk text, model id). Most functions are unchanged across commits of the same repo, so this cache matters.
- [ ] Brute-force vector search: normalize the vectors, do a matrix-vector product, use `argpartition` for top-k.
- [ ] RRF fusion of BM25 and semantic results, with `k` tuned on dev (ADR 007). Comparing against min-max score fusion is optional.
- [ ] Optional: a reranker on the top N results, only if time allows.
- [ ] Final test-set run.
- [ ] Write the results table, the per-category breakdown and the analysis with examples in the README.

**Done when**

- The README has the final table and analysis.
- The full pipeline reproduces from a clean clone.
- The defense checklist for Phases 0 to 3 is answered.

### Phase 4 (Stretch): Graph Expansion

- [ ] Import graph: modules to the in-repo modules they import.
- [ ] Heuristic call references: call names matched to defined symbols. Document what this misses.
- [ ] Expansion: add neighbors of the top N hits with a decayed score, tuned on dev.
- [ ] **Done when:** a test-set result is reported, positive or null, with an explanation.

### Phase 5 (Stretch): Interface

- [ ] `codeatlas index <path>` and `codeatlas search "<query>"` on any local Python repo.
- [ ] Optional MCP server exposing search to coding agents.
- [ ] **Done when:** documented in the README and usable on a repo outside the benchmark.

---

## 7. Engineering Standards

- `mypy --strict`, ruff and pytest run in CI on every push.
- Every core component has unit tests with hand-computed expected values where possible.
- Every benchmark states hardware, Python version, warm or cold cache, N, and p50/p95.
- Results files are generated by code and never edited by hand.
- Each nontrivial decision gets a short ADR in `docs/decisions/` covering context, options, decision and consequences.

### Planned ADRs

| # | Decision |
|---|---|
| 001 | Eval subset and dev/test split |
| 002 | Gold label mapping |
| 003 | Retriever interface |
| 004 | Chunking policy |
| 005 | Tokenizer |
| 006 | Embedding model |
| 007 | Fusion method |

---

## 8. Defense Checklist

A phase is not done until I can answer its questions without notes.

**Phase 0**
- Why recall@k and MRR instead of accuracy? What does each one miss?
- Why a dev/test split with only about 100 queries? What goes wrong without one?
- How could the gold labels be wrong?

**Phase 1**
- Why do byte offsets and string indices differ, and where would that cause a bug?
- Why function-level chunks instead of fixed-size windows? What do I lose?
- How does the scope stack handle nested functions inside methods?

**Phase 2**
- What are the time and space complexities of index build and query?
- What do `k1` and `b` do, including at their extremes?
- Why does IDF use a logarithm?
- Why did BM25 fail on the misses I analyzed?

**Phase 3**
- Why normalize vectors before taking a dot product?
- At what corpus size does brute force stop being acceptable? What replaces it (approximate nearest neighbor search such as HNSW), and what does it cost?
- Why RRF instead of adding raw scores?
- Which query categories favor which method, and why?

**Phase 4**
- Why are static call graphs imprecise in Python?

---

## 9. Resume Target

Every number must come from a test-set results file. If the results differ, the bullets change.

**CodeAtlas** | Python, Tree-sitter, NumPy, pytest

- Built a code search engine in Python that ranks functions by relevance to natural-language bug reports, combining a custom BM25 inverted index with embedding search through reciprocal rank fusion.
- Evaluated retrieval on N real GitHub issues from SWE-bench Lite. Hybrid search improved function-level recall@5 from X% (BM25) to Y%, with analysis showing [pattern actually observed].
- Indexed a Z-line codebase with Tree-sitter in A seconds and served queries in B ms at p95 using brute-force vector search sized to the corpus.
- *(Only if Phase 4 or 5 ships)* Added call-graph expansion that changed recall@10 by C points, or exposed search as an MCP server for coding agents.
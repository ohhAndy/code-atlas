# ADR 002: Gold labels and corpus scope

**Status:** In progress (test-file scope accepted; function-level mapping comes in Phase 1)
**Date:** 2026-11-06

## Part 1: Test files in the corpus

### Context
SWE-bench splits each fix into `patch` (non-test changes) and `test_patch` (test changes).
Gold labels come only from `patch`, so a test file can never be gold. Test files that
exist at `base_commit` would still be indexed, and they repeat the names of the functions
they test, so they can rank high and always count as misses.

### Options considered
- **A) Exclude test files from the corpus.** Needs a rule for what a test file is.
- **B) Keep them and count hits on them as misses.**
- **C) Keep them and report results both with and without them.**

### Decision
A: exclude test files from the corpus, plus one dev-only run of the ripgrep baseline with
test files included, to put a number on the effect.

Why not B: the eval measures whether a method finds the code a fix changes. Test files
repeat the identifiers of the code they test, so they pull lexical methods toward
never-gold documents more than semantic ones. Under B, a gap between methods would partly
reflect how easily each one is distracted by tests, not how well it ranks the code that matters.

Why not C: C doubles every table (per method, per split, per category) for a question one
measurement can answer: does including tests change the numbers much? The dev run gives
that size for a lexical method. If the effect is small, C adds nothing; if it is large,
the run is repeated per method on dev and reported. Limitation: the run measures the effect
for ripgrep only, not for BM25 or embeddings.

**Rule:** a path is a test file if any of its directory components (not the file name) is
exactly `tests`.

```python
def is_test_file(path: str) -> bool:
    return "tests" in path.split("/")[:-1]
```

Matches `tests/...` (django), `sympy/*/tests/...` and `sklearn/*/tests/...`. Does not match
`django/test/` (library code, shipped to users) or `unittests/`.

### Evidence
Checked on all 100 subset instances in `notebooks/test_file_rule.ipynb`:

- (a) `patch` files the rule excludes: **0 / 100**. No gold file is ever excluded.
- (b) `test_patch` files the rule does not exclude: **1 / 127**:
  `sympy/testing/quality_unicode.py` (sympy__sympy-24102), test-support code under
  `sympy/testing/`. Accepted: one non-gold file, and widening the rule to `testing` risks
  excluding library code.


### Consequences
- **Absolute scores are optimistic.** Removing test files removes strong distractors, so
  recall is higher than in a tests-included setting. The headline claim is the comparison
  between methods on the same corpus, not absolute recall. The rule was fixed before any
  retrieval results and validated only against gold labels, not tuned on scores. The dev
  run reports how large the effect is. Every results table states that tests are excluded.
- **Check (b) is a sample, not a full audit.** It only sees test files that some
  `test_patch` changed. Test code outside a `tests/` directory that no fix touched (e.g.
  `tests.py` modules inside a package) stays in the corpus, and its amount is not measured.
- **The rule is validated for these 100 instances only.** (a) = 0 says nothing about other
  repos or commits. Phase 5 (indexing arbitrary repos) should make test exclusion a flag,
  not a fixed rule.
- **Smaller indexes.** Django's top-level `tests/` is a large part of the repo, so excluding
  it reduces parse, index and embedding cost. Not measured yet

## Part 2: Function-level gold mapping

To be written in Phase 1.

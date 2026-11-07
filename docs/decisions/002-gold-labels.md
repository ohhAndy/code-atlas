# ADR 002: Gold labels and corpus scope

**Status:** In progress (Parts 1 and 2 accepted; Part 3, mapping lines to chunks, comes in Phase 1)
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
  it reduces parse, index and embedding cost. Not measured yet.

## Part 2: Changed lines from a patch

Implemented in `code_atlas.eval.gold.changed_lines`, tested in `tests/eval/test_gold.py`.

### Context
Function-level gold (Phase 1) marks a chunk as gold if the fix touched a line inside it.
Chunks are built from the old file (the snapshot at `base_commit`), so "touched" has to be
expressed as **old-file line numbers**. A unified diff contains three kinds of lines:
context (unchanged, shown for readability), `-` (exists in the old file) and `+` (exists
only in the new file, so it has no old line number).

### Decision
- **Output:** `dict[str, set[int]]`, mapping repo-relative path to old line numbers.
  The keys are the file-level gold. A set because Phase 1 asks "is line N in here?" for
  every chunk line (O(1)), and because the same line can be recorded twice (a deletion
  and a neighboring insertion).
- **Context lines record nothing.** Counting them would make a function next to the real
  change gold.
- **`-` lines record their own old line number.**
- **A run of `+` lines next to a `-` line (a replacement) records nothing extra.** The `-`
  lines already locate the change. Adding neighbors would pull in the next unchanged line,
  possibly in the next function.
- **A run of `+` lines with no `-` line (a pure insertion) records both old neighbors:** the
  old line before it and the old line after it. Line 0 does not exist and is skipped.
- **Files the patch adds are skipped.** They don't exist at `base_commit`, so no retriever
  can return them. This matches PLAN §5, which excludes functions the patch adds.

Why both neighbors for a pure insertion: "line before" or "line after" alone can silently
drop the function that was actually edited (e.g. code inserted as the first line of a
function body). "Both neighbors" never drops it. Its only error is labeling an extra function
when the insertion sits exactly on a boundary between two functions, which is less common and
measurable once Phase 1 chunks exist.

### Evidence
- 0 of the 100 subset patches add or delete a file, so the new-file rule changes no current
  numbers.
- Every subset patch changes exactly one file (see `docs/log.md`).

### Consequences
- Some instances may get an extra gold function from boundary insertions. Phase 1 should
  count how many and report it.
- More gold functions per instance interacts with the function-level recall definition
  (fraction of gold found vs. any gold found). Decide that in the metrics task.
- The "end of hunk" neighbor (`last_old + 1`) can point past the end of the file. That is
  harmless: no chunk contains it.

## Part 3: Mapping changed lines to chunks

To be written in Phase 1, once the chunker exists.

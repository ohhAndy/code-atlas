# ADR 002: Gold labels and corpus scope

**Status:** Accepted (Parts 1 and 2 on 2026-11-06; Part 3 on 2026-11-09)
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

Implemented in `code_atlas.eval.gold.function_gold`, tested in `tests/eval/test_gold.py`.
Counts from `notebooks/gold_stats.py`.

### Context
Part 2 gives old-file line numbers per changed file. Function-level gold needs chunk ids
that a chunk retriever can return. The chunks nest (method inside class inside module), so
one changed line is inside several chunk line ranges, and the mapping has to pick.

### Options considered
- **A) Every chunk whose line range contains the line.** A change in `Foo.bar` also makes
  `Foo` and the module gold.
- **B) The innermost chunk that contains the line (its owner).**
- **C) Like B, but for a pure insertion at a chunk boundary keep only one neighbor's
  owner** (e.g. the enclosing class, dropping the next method).

### Decision
B. Each line has exactly one owner: the smallest chunk whose range contains it. Gold for
an instance is the set of owners of its changed lines, over the chunks `chunk_file`
actually emits for the file at `base_commit`. A line with no owner adds nothing.

Why B over A: under A, nearly every instance would have its module chunk as gold, and a
retriever returning the module would score a hit for any change in the file. That turns
function-level scores back into file-level scores. B labels the unit the fix changed.

Why the chunks `chunk_file` emits, not every span: the module chunk is dropped when its
text is only whitespace. Mapping over all spans would give a blank line in such a file the
gold id `path::<module>`, which is not in the corpus, so no retriever could ever find it
and recall would drop for a reason unrelated to retrieval. Gold must only contain ids the
retrievers can return.

Why not C (yet): Part 2's both-neighbors rule was fixed before any chunks existed, and its
cost was expected to be small. The counts below confirm it is small (2 / 30 dev instances),
and C would add a rule written after looking at those 2 instances. Revisit if the test
split, once run, shows the same pattern at a larger scale.

### Evidence (dev, 30 instances)
- Gold chunks per instance: 1 chunk in 19 instances, 2 in 9, 3 in 2 (43 gold chunks).
- By kind: 25 methods, 12 functions, 4 module chunks, 2 classes.
- Instances with no function-level gold: 0.
- Changed files with tree-sitter parse errors: 0.
- Pure-insertion runs: 25. Runs whose two neighbors have different owners (a chunk
  boundary): 3, in 2 instances. Every other run sits inside one chunk, so its gold is right.
- Gold chunks reached only through a boundary run: 5, in the same 2 instances. Both fixes
  add a new method to a class:
  - django__django-14752 adds `serialize_result`. Gold: `AutocompleteJsonView.get` (really
    changed), plus `AutocompleteJsonView` (blank line before the insertion) and
    `AutocompleteJsonView.get_paginator` (unchanged method after it).
  - sympy__sympy-15308 adds `_print_Basic` and `_print_Trace` and changes nothing else.
    Gold: `LatexPrinter`, `LatexPrinter._print_bool`, `LatexPrinter._print_Adjoint`; the
    two methods are unchanged neighbors.

### Consequences
- **Boundary insertions mislabel a little.** In those 2 instances, unchanged neighbor
  methods are gold. Recall@k is harder there (3 gold chunks, 1 really changed in 14752);
  Hit@k is easier (a retriever that returns the unchanged neighbor gets a hit). The effect
  is limited to 2 / 30 dev instances and is reported, not hidden.
- **The class chunk as gold for "add a method" fixes is arguably right.** The class is
  where the new method goes, and the class chunk is the only existing chunk about it.
- **Nested functions map to their parent function** (they are not chunks, ADR 004), so gold
  for a fix inside a nested helper is the whole parent.
- **Gold depends on the chunker.** Any change to the chunking policy changes function-level
  gold, and earlier function-level results are no longer comparable.
- **Counts are dev only.** Test-split gold was not inspected.

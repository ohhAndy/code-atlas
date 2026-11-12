# Engineering Log

One section per phase. Add to the current phase as you go; write the retro when
the phase ends. Task checkboxes live in PLAN.md; this file records what actually
happened and why.

<!--
## Phase N: Name

**Status:** not started | in progress | done

### Work done
-

### Decisions
- Decision, and why. Link the ADR if there is one.

### Findings
- Facts learned about the data, the code, or a method. Numbers only from generated files.

### Problems and dead ends
- What went wrong or got abandoned, the root cause, and what changed.

### Open questions
-

### Retro (at phase end)
- What I'd do differently:
-->

## Phase 0: Evaluation Harness

**Status:** done (2026-11-08)

### Work done
- Wrote PLAN.md and AGENTS.md. Created package skeleton with empty module stubs.
- Configured pyproject: uv, ruff, mypy --strict, pytest. Added GitHub Actions CI running
  ruff, ruff format, mypy and pytest on every push.
- Loaded SWE-bench Lite (HF `test` split) into `notebooks/explore.ipynb`.
- Dropped columns not needed for retrieval eval.
- Sampled the 100-instance subset and wrote the dev/test split to `splits/split.json`
  (ADR 001).
- Repo cache: bare clone per repo, git worktree per base commit (`codeatlas prepare`).
- Patch parsing into changed old-file lines per file (ADR 002 Part 2).
- Metrics: Recall@k, Hit@k, MRR@10, and chunk-to-file ranking, with hand-computed tests.
- `Retriever` protocol (ADR 003) and the ripgrep baseline.
- Runner and CLI: `codeatlas eval --method rg --split dev|test [--final]` prints a table
  and writes a results JSON with commit, config and split.
- Labeled query categories for all 100 instances (`splits/categories.json`).
- Ripgrep baseline runs on dev and on test (final, logged). Reproduced dev from a fresh
  clone.

### Decisions
- Dropped `hints_text`: Mostly noisy text like automated bot messages, or pings to ask maintainers to look at. Could also contain leakage. 
- Dropped `test_patch`, `FAIL_TO_PASS`, `PASS_TO_PASS`: Test_patch is what the devs write after fixing the bug, so it will cause leakage, same with FAIL_TO_PASS and PASS_TO_PASS. 
- Dropped `version`, `environment_setup_commit`: Since we don't need this information to build any features of our projects.
- Subset: 100 instances. All 23 scikit-learn, 46 django, 31 sympy (django/sympy in proportion
  to their SWE-bench counts). Sampled randomly with a fixed seed; dev/test split 30/70 within
  each repo. Why: limits indexing cost while keeping a realistic mix of real issues.
  scikit-learn over matplotlib because it's the larger codebase.
- Test files are excluded from the corpus: a path is a test file if a directory component is
  exactly `tests`. One dev-only ripgrep run with tests included will measure the effect.
  See [ADR 002](decisions/002-gold-labels.md).
- Query category precedence: 1 (traceback or file path) > 2 (names an identifier) >
  3 (behavior only). Each query gets the strongest lexical signal it contains, so every
  query where a path may leak the answer lands in category 1 and can be reported separately.
  Categories are mutually exclusive, so per-category counts sum to the total.
- Query category labeling rule. Judge the issue text only (never the patch, never the repo).
  Ask in order and stop at the first yes:
  1. **Traceback or path.** Any traceback (`Traceback (most recent call last)` or
     `File "...", line N`, even if every frame is `<stdin>` or user code); a file path in the
     repo (`django/db/models/query.py`); or a dotted name whose parts spell out repo
     directories/modules, with or without the top-level package (`django.utils.autoreload`,
     `contrib.admin.views.autocomplete`, `tests.model_fields.test_jsonfield...`,
     `sklearn.linear_model`). Import lines count (`from sklearn.utils.validation import ...`).
  2. **Names project code.** A function, class, method, attribute, setting or management
     command of the project (`QuerySet.none()`, `db_table`, `TEMPLATES`, `dbshell`), in
     prose, the title, or a code snippet that uses the API.
  3. **Otherwise:** behavior only.

  Not a path: two-part attribute access (`models.Model`), the top-level package alone
  (`from sympy import *`, `sympy.sympify`), model labels (`app.Model.field`), the reporter's
  own files (`manage.py`, `settings.py`), bare filenames without a directory (`default.html`),
  CLI flags (`--traceback`). Not an identifier: the reporter's own names (classes and
  variables the snippet defines), code-sounding words in plain prose without backticks or
  `()`, and an exception class name on its own. Why the lean toward 1: a query that may leak
  a path must not inflate category 2, the category whose results matter most.
- Repo cache: one bare clone per repo plus one git worktree per base commit, built on first
  use. A worktree keeps every snapshot on disk and stays verifiable (HEAD and clean status).
  A done-marker next to each worktree is written last, so an interrupted build is never
  reused. Snapshots keep test files; corpus policy (ADR 002) is applied at indexing time.
- Changed lines from a patch: `-` lines record their old line; a pure insertion records
  both old neighbors; context records nothing; added files are skipped.
  See [ADR 002 Part 2](decisions/002-gold-labels.md).
- Metrics are computed per query and macro-averaged over queries by the runner.
- Metric input rules: empty `gold`, duplicates in `ranking`, or `k < 1` raise `ValueError`
  (they mean the caller has a bug and would silently corrupt scores, e.g. a duplicated gold
  item counted twice gives recall above its true value). An empty `ranking` is legitimate
  and scores 0. Instances with no function-level gold are scored at file level only.
- Hit@k is reported at function level only. With several gold functions, Recall@k gives
  partial credit (1 of 3 found = 0.33) while Hit@k asks "did retrieval surface any entry
  point into the fix?". At file level gold is always one file, so Hit@k = Recall@k there
  and is not reported.
- File ranking from a chunk ranking: each file takes the rank of its best-ranked chunk
  (first occurrence wins), so chunk retrievers get file-level scores without a separate run.
  A chunk id without `::` raises, which catches passing a file ranking by mistake.
- MRR is MRR@10, with the cutoff inside the metric (`reciprocal_rank_at_k`). Without it a
  gold item at rank 50 scores 0.02 from a top-100 retriever and 0 from a top-10 one, so MRR
  would reward longer output, not better ranking. Putting it in the metric rather than the
  runner means no caller can forget it. Cost: a hit at rank 11+ is worth nothing, same as
  Recall@10.
- Retriever interface: each retriever declares `level` ("file" or "chunk") so the runner
  scores against the matching gold, and is constructed once per snapshot so indexing
  happens in the constructor. See [ADR 003](decisions/003-retriever-interface.md).
- Ripgrep baseline, identifier rule: keep a word from the issue text only if its shape
  shows it is code: it contains `_` (`get_or_create`), has a capital after the first
  character (`QuerySet`, `assertEqual`), or is a dotted name (`models.Model`, searched
  whole as a fixed string). Everything else is dropped (`Value`, `count`, `self`, `the`).
  Why: English words match thousands of lines and drown the counts. Dropping them loses
  some real identifiers that look like English (`count`); a baseline accepts that for a
  rule that is simple and explainable.
  A dotted name also adds each part that passes the rule on its own
  (`QuerySet.get_or_create` -> also `QuerySet`, `get_or_create`), because code rarely
  spells the dotted form out (it writes `self.get_or_create`), so the whole string alone
  usually matches nothing. Decided before any baseline results were seen.
  The inner-capital rule also needs a lowercase letter, so prose acronyms (`HTTP`, `OK`,
  `API`, `README`) are dropped. Cost: all-caps constants without `_` (`DEBUG`) are dropped
  too; ones with `_` (`SECRET_KEY`) still pass. Also decided before any results.
- Test-file exclusion effect counts as large: an MRR@10 drop of 0.18 (0.419 -> 0.239) on dev
  (see Findings). So, per ADR 002, BM25 (Phase 2) and semantic search (Phase 3) each get one
  dev run with test files included, reported next to their tests-excluded numbers. ADR 002
  never set a threshold for "large"; this drop is far past any reasonable one, but a
  smaller effect would have needed a rule fixed in advance.
- `rg-with-tests` is a separate registered method (not a flag on `rg`) so the results JSON
  records which variant ran. The CLI refuses it on the test split.

### Findings
- SWE-bench Lite (HF `test` split): 300 instances across 12 repos.
- Per-repo instance counts and distinct `base_commit`s (from `notebooks/explore.ipynb`):

  | Repo | Instances | Distinct commits | Python files (HEAD) | Python lines (HEAD) |
  |---|---|---|---|---|
  | django/django | 114 | 114 | 2,943 | 531,495 |
  | sympy/sympy | 77 | 74 | 1,610 | 812,378 |
  | matplotlib/matplotlib | 23 | 23 | 914 | 283,321 |
  | scikit-learn/scikit-learn | 23 | 23 | 1,037 | 453,087 |
  | pytest-dev/pytest | 17 | 17 | 274 | 117,465 |
  | sphinx-doc/sphinx | 16 | 16 | 775 | 148,222 |
  | astropy, requests, pylint, xarray, seaborn, flask | 3 to 6 each | same as instances | not measured | not measured |

- Distinct commits ≈ instances: nearly every instance needs its own checkout and index.
  Indexing cost scales with (instances sampled) × (repo size), not with number of repos.
- Sizes measured with a shallow clone of HEAD on 2026-11-06, counting all `.py` files
  (tests included). This overestimates size at the older base commits; use only for relative comparison.
- Sphinx contains deliberately mis-encoded fixture files (`tests/roots/*/wrongenc.inc`); git warned
  on checkout. Real repos have unusual encodings, which is relevant to the Phase 1 non-ASCII tests.
- Every subset instance's `patch` changes exactly one file (100 files across 100 instances,
  from `notebooks/test_file_rule.ipynb`). File-level gold is always a single file, so
  file-level Recall@k is "is that file in the top k" and MRR@10 is 1 / its rank (0 past 10).
- Repo cache, dev split (30 snapshots, `codeatlas prepare --split dev`, measured with `du -sh`):

  | Repo | Bare clone | Dev snapshots | Avg per snapshot |
  |---|---|---|---|
  | django | 317 MB | 729 MB (14) | ~52 MB |
  | sympy | 224 MB | 277 MB (9) | ~31 MB |
  | scikit-learn | 202 MB | 129 MB (7) | ~18 MB |

  1.8 GB total on disk. Estimate (not measured) for all 100 snapshots: ~4.5 GB. Worktrees
  store history once per repo; 46 separate django clones would hold ~14.6 GB of history alone.
  All 30 snapshots verified clean on macOS (no case-collision failures).
- 0 of the 100 subset patches add or delete a file (checked with unidiff `is_added_file` /
  `is_removed_file`), so excluding added files from gold changes no current numbers.
- Pure insertions in the subset patches (one-off unidiff script over the 100 `patch`es,
  patch text only, no chunker; 2026-11-08). A pure-insertion run is a run of `+` lines with
  no `-` lines, whose gold is its two old neighbor lines.
  - 85 runs in 60 / 100 instances.
  - 18 runs in 16 / 100 instances insert a new `def` / `class` / decorator. The new
    definition is excluded from gold (it doesn't exist at base_commit), so these
    instances' function-level gold leans on whatever code happens to sit next to it.
  - 5 more runs have a `def` / `class` / decorator line as an old neighbor.
  - 21 more runs have only a blank-line neighbor. Many of these blanks are inside function
    bodies, so this count is an upper bound on real boundary cases.
  - Exact effect on function-level gold needs the Phase 1 chunker; re-measure then.
- Test-file rule check (`notebooks/test_file_rule.ipynb`): 0 / 100 `patch` files excluded;
  1 / 127 `test_patch` files not excluded (`sympy/testing/quality_unicode.py`).
- Query categories (`splits/categories.json`, all 100 labeled before any results):

  | Split | Cat 1 | Cat 2 | Cat 3 |
  |---|---|---|---|
  | dev | 16 | 14 | 0 |
  | test | 38 | 32 | 0 |

  By repo (cat 1 / cat 2): django 20 / 26, sympy 15 / 16, scikit-learn 19 / 4.
- No issue is behavior-only: every one names some project code. Per-category results are
  therefore cat 1 vs cat 2 only, and this subset cannot say anything about behavior-only
  queries. scikit-learn is nearly all cat 1 (mostly `from sklearn.x import` lines), so its
  cat 2 numbers rest on 4 issues.
- Category 1 mixes strong and weak leaks: tracebacks and paths to the fixed file
  (`Django.db.models.deletion:276-281`, `django.contrib.admin.utils.display_for_field`)
  next to import lines that only name a package (`from sklearn.preprocessing import`).
- Several category-2 issues quote source text verbatim (an error format string, check ids
  `models.E028` / `fields.E304`, a `hint=` message, the body of `Mod.eval`). Not paths, but
  a grep for them hits the file directly. Hypothesis, untested: these make some category-2
  queries easier for lexical search than the category suggests.
- Consistency check after labeling: a script flagged labels that disagreed with the
  mechanical category-1 signals (traceback, repo path, `django.`/`sklearn.`/`sympy.` dotted
  names). 5 of 8 flags were labeling slips (category 2 -> 1), fixed before any results.
- Ripgrep baseline, file level (k = 10, ripgrep 15.2.0):

  | Split | Commit | n | R@1 | R@5 | R@10 | MRR@10 | File |
  |---|---|---|---|---|---|---|---|
  | dev | `bd05c00` | 30 | 0.333 | 0.567 | 0.600 | 0.419 | `results/rg_dev_20261108T215637Z.json` |
  | test | `384b6fe` | 70 | 0.371 | 0.557 | 0.643 | 0.454 | `results/rg_test_20261108T220107Z.json` |

  Per-repo and per-category rows are in the results files. Between the two commits only the
  results metadata changed (ripgrep version added). The dev run was reproduced from a fresh
  clone at `384b6fe` with identical per-instance rankings.
- Same method, different split: django MRR@10 is 0.309 on dev (n = 14) and 0.595 on test
  (n = 32). With this few queries per repo, per-repo differences of this size can be split
  noise; no per-repo claim without more data.
- Test-file exclusion effect (ADR 002 Part 1), dev only, file level (k = 10, ripgrep 15.2.0).
  `rg-with-tests` is the `rg` baseline without the `tests` glob:

  | Method | n | R@1 | R@5 | R@10 | MRR@10 | File |
  |---|---|---|---|---|---|---|
  | rg | 30 | 0.333 | 0.567 | 0.600 | 0.419 | `results/rg_dev_20261108T215637Z.json` |
  | rg-with-tests | 30 | 0.167 | 0.300 | 0.433 | 0.239 | `results/rg-with-tests_dev_20261109T011552Z.json` |

  - Per repo, MRR@10 drops most on django: 0.309 -> 0.070 (n = 14). scikit-learn
    0.548 -> 0.476 (n = 7), sympy 0.489 -> 0.317 (n = 9).
  - MRR@10 changed on 13 / 30 instances, and never went up: test files only push gold
    files down. 159 of the 300 top-10 slots were test files.
  - The run was made at `781982d` with the `rg-with-tests` change not yet committed
    (`dirty: true` in the file). In the same session, `rg` re-run on that tree gave
    per-instance rankings identical to the committed dev run, so the default baseline
    did not change.
  - Only ripgrep was measured. Whether BM25 (IDF) or embeddings are distracted as much is a
    hypothesis.

### Test-split runs
- 2026-11-08, commit `384b6fe`, `rg`, `results/rg_test_20261108T220107Z.json`. Why: final
  Phase 0 baseline. ripgrep baseline is frozen from here; any change to it needs a new
  logged test run and a reason.

### Problems and dead ends
- Query category labeling slips: a consistency check against the mechanical category-1
  signals flagged 8 labels; 5 were real slips (category 2 should have been 1). Root cause:
  labeling by hand misses dotted module paths and import lines on a quick read. Fixed
  before any results were seen (see Findings).

### Open questions
- How should function-level gold handle a fix that adds a new method? The new method is
  excluded from gold, so gold falls back to its neighbors (16 / 100 instances, see
  Findings). Decide in ADR 002 during Phase 1.
- ~~MRR depends on how many results the retriever returns. Where does the cutoff live?~~
  Resolved: in the metric, MRR@10 (see Decisions).
- ~~Query category precedence: a traceback usually also names identifiers. Which category wins?~~
  Resolved: 1 > 2 > 3 (see Decisions).
- ~~Test files in the index: keep, exclude, or report both?~~ Resolved: exclude.
  See [ADR 002](decisions/002-gold-labels.md).

### Retro (at phase end)
- What I'd do differently: most of the time went to learning and understanding
  (retrieval metrics, eval design, git worktrees), not to writing code. I found out only
  after the subset was fixed that it has no behavior-only queries, and only after the
  baseline that 16 / 100 fixes add a new method. Next time I'd run quick counts over the
  data before committing to a subset or a labeling rule.

## Phase 1: Parsing and Chunking

**Status:** done (2026-11-10)

### Work done
- Added `tree-sitter` 0.26.0 and `tree-sitter-python` 0.25.0. Both ship type hints; no mypy
  override needed.
- `code_atlas.parse.parser.parse(bytes) -> Tree`, and `code_atlas.parse.files`:
  `is_test_file` (ADR 002 rule, now in code) and `iter_corpus_files` (corpus `.py` files as
  raw bytes, sorted, skipping test dirs, `.git` and symlinks).
- `extract_definitions` stub with the `Definition` type (qualified name, kind, 1-based
  inclusive lines).
- Counted where dev fixes land relative to nested functions
  (`notebooks/nested_functions.py`, Python `ast`, not the Phase 1 chunker).
- `extract_definitions`: tree walk with the enclosing class's qualified name as the prefix
  (the scope stack). Tests in `tests/parse/test_definitions.py`: async, decorators, nested
  classes, nested functions, non-ASCII, syntax errors, definitions under `if` / `except`.
- Settled the chunking policy decisions (see Decisions); ADR 004 not written yet.
- `code_atlas.eval.gold.owner(line, spans)`: the smallest span containing a line, or `None`
  if no span contains it. Tests in `tests/eval/test_gold.py`.
- `code_atlas.parse.chunks.chunk_spans(source)`: `<module>` span `1..N` first, then each
  definition in source order, duplicates suffixed `#2`, `#3`. Tests in
  `tests/parse/test_chunks.py` (trailing newline, empty file, property getter / setter,
  `if` / `elif` / `else` shims, owner of a line in a setter, class spanning the whole file).
- `Chunk` dataclass (PLAN §3 fields), `chunk_texts` (each chunk's text = the lines it owns,
  via `owner`) and `chunk_file` (ids `path::name`, kinds, sha256 `content_hash`, module
  chunk skipped when whitespace-only). Tests in `tests/parse/test_chunks.py`, including
  non-ASCII source and a form feed.
- Moved `owner` from `eval/gold.py` to `parse/chunks.py`: gold now imports the chunker, and
  the chunker importing gold back would be a circular import.
- `function_gold(patch, repo_dir)`: owners of the changed lines, over the chunks
  `chunk_file` emits. Tests in `tests/eval/test_gold.py`.
- Runner scores chunk retrievers at function level too (Recall@1/5/10, MRR@10,
  Hit@1/5/10) on instances with non-empty function gold; results JSON gains `gold_chunks`,
  `chunk_ranking`, `function_scores` per instance, plus `function_summary` and
  `no_function_gold`. The CLI prints both tables. File retrievers are unchanged. No chunk
  retriever exists yet, so no function-level numbers.
- `notebooks/gold_stats.py`: function-level gold counts on dev (see Findings).
- ADR 002 Part 3 written (proposed).
- Function-level ripgrep baseline: `RipgrepChunkRetriever`, registered as `rg-chunks`.
  Same identifiers and rg search as `rg`; each matching line is credited to the chunk that
  owns it. Tests in `tests/baselines/test_ripgrep.py`. Dev run (see Findings).
- Parse and chunk benchmark: `benchmarks/parse_bench.py` (added `benchmarks` to mypy's
  checked files). Run on the largest dev corpus (see Findings).
- `rg-chunks` test-split run deferred until ADR 002 Part 3 is accepted and ADR 004 is
  written: function-level gold and chunk ids depend on both, and a test run made before
  they are settled could go stale and need a second logged run.

### Decisions
- Nested functions are part of their parent: the walker descends into class bodies
  (methods and nested classes get their own entries) but not into function bodies. Any
  definition inside a function, including a class, stays inside the enclosing function's
  chunk. Why: only 2 / 30 dev instances change a line inside a nested function (see
  Findings), so the choice moves dev function-level gold by at most 2 instances, and
  this is the simpler walker. Decision rule fixed before the count was run: 0–2 of 30 ->
  part of parent; 3 or more -> read those instances and decide. To be recorded in ADR 004.
  - Cost: the gold for a fix inside a nested helper is the whole parent (`tree_cse`,
    143 lines, in sympy__sympy-22840), so the retrieved unit is coarser than the change.
  - Nested functions get no qualified name, so the `<locals>` naming question does not
    arise.
- A decorated definition's span starts at its first decorator, not at `def` / `class`.
  Why: a fix that only changes a decorator (`@cached_property` -> `@property`) then maps
  to the function it decorates, not to the code above it. To be recorded in ADR 004.
- Only `def` and `class` create a scope. The walker looks through every other node
  (`if`, `try` / `except`, `with`, `for`, ...) with the prefix unchanged, so a function
  under `if TYPE_CHECKING:` is a module-level function and a method under `if` in a class
  body is a method. Why: these patterns (compat shims, import fallbacks) are common in the
  subset repos, and missing them would turn their gold into module code.
- Line ownership: every line of a file belongs to exactly one chunk, the innermost
  definition that contains it (the smallest containing span); the module chunk spans
  `1..N` and owns whatever no definition contains. Definition spans never partially
  overlap (they are nested or disjoint), so "smallest containing span" is always the
  innermost one. Why: a fix inside `Foo.bar` should make `Foo.bar` gold, not also `Foo`
  and the module. Consequence: `Chunk` keeps a single `start_line` / `end_line`; the class
  and module chunks have "holes" only in their text, not in their line range. Function-level
  gold = owners of the changed lines. To be recorded in ADR 004 and ADR 002 Part 3.
- Class chunk text: header, docstring and class-level code, without methods (no method
  bodies and no method signatures). Why: a query naming a method should rank the method
  chunk, not the class; copying signatures into the class chunk lets the class compete with
  its own methods, more so for large classes. Cost: the class chunk no longer lists what the
  class can do. To be recorded in ADR 004.
- Lines between definitions (blank lines, comments above a `def`, imports) belong to the
  enclosing class or module, which follows from the ownership rule with no extra code.
  Cost: a pure insertion right between two methods can make the class gold as well (ADR 002
  Part 2 records both neighbors). Count how often once the chunker exists. To be recorded in
  ADR 004.
- No oversized-function rule in Phase 1. BM25 already handles long documents through
  length normalization (`b`); embedding models silently truncate input past their token
  limit, and that limit depends on the model chosen in Phase 3. So the rule is decided with
  ADR 006. Phase 1 records the distribution of chunk lengths so that decision has data.
- Duplicate qualified names get an ordinal suffix in source order: `Model.name`,
  `Model.name#2`. Why: common in practice (`@property` getter plus `@name.setter` share a
  name, plus `if PY3` / `else` shims); every definition stays its own chunk, so the
  ownership rule still holds. Merging would create chunks with two line ranges. Cost: ids
  can shift across commits if a same-name definition is added earlier in the class. That
  matters little: the Phase 3 embedding cache is keyed by chunk text, not id. To be
  recorded in ADR 004.
- A module chunk is emitted only if its text is non-empty after stripping whitespace. An
  empty `__init__.py` has nothing to search; a file with imports still gets one, so a
  changed import line has an owner. To be recorded in ADR 004.
- `owner` returns `None` for a line no span contains; it does not raise. Why: same rule as
  the metrics (raise only when the input means a caller bug). An unowned line is legitimate:
  a pure insertion at end of file records `last_old + 1` past the last line, and a file
  with no module chunk leaves its blank lines between definitions unowned. The caller drops
  `None`.
- Ties in `owner`: a class spanning the whole file has the same span as `<module>`. Spans
  are in source order, where a container always comes before what it contains, so on a tie
  the later span is the inner one and wins (`owner` takes the min over the reversed list).
  Cost: `owner` is only correct for source-ordered input; its docstring states this.
- Line count N is `len(source.splitlines())` on bytes, not on decoded text. Why: it must
  match tree-sitter's rows. `str.splitlines()` also splits on form feed (`\x0c`, used as a
  page break in older Python files), which would shift every later line number by one;
  `bytes.splitlines()` does not.
- Chunk text: split the source into lines as bytes, then decode each line. Decoding first
  and splitting the `str` broke on a form feed: the next function's text took the module's
  blank line and lost its own last line (caught by a test). Splitting bytes on `\n` is safe
  for UTF-8 because `0x0A` never occurs inside a multi-byte character.
- Decode with `errors="replace"`: an invalid byte becomes U+FFFD instead of raising. Why:
  real repos contain mis-encoded files (sphinx fixtures, see Phase 0), and one bad byte
  should not stop a whole snapshot from being indexed. Cost: those characters are lost for
  search, with no count of how often it happens.
- Function-level gold = the owners of the changed lines, over the chunks `chunk_file`
  emits (not over all spans, which would make an unfindable `<module>` id gold). Boundary
  insertions keep the Part 2 both-neighbors rule unchanged: 2 / 30 dev instances affected.
  See [ADR 002 Part 3](decisions/002-gold-labels.md).
- The runner computes function gold only for chunk retrievers. File retrievers never need
  it, and computing it means parsing every changed file.
- `rg-chunks` is a new method, not a change to `rg`. Why: `rg` is frozen after its logged
  test run; any change to it would need a new one. Its score rule is `rg`'s one level down:
  matching lines summed over identifiers, per chunk, ties broken by id. No length
  normalization, on purpose: it is a baseline, and BM25 adds normalization in Phase 2.
- `rg-chunks` reads rg's per-line output (`--line-number --null`) as bytes and decodes
  only the path. Why: the matched text can be invalid UTF-8, and only the path and line
  number are used. The span name passed to `owner` is the chunk id from `chunk_file`, so
  the id format is defined in one place.

### Findings
- Tree-sitter facts the walker depends on (checked on 0.26 with the Python grammar):
  `async def` is a `function_definition` whose first child is an `async` token;
  decorators wrap the definition in `decorated_definition`, and the inner definition
  starts on the `def` line, after the decorators; columns and `start_byte` count UTF-8
  bytes, rows are 0-based lines; a syntax error does not stop the parse (it may show up as
  a repaired `MISSING` node, not only an `ERROR` node; only `root.has_error` is reliable).
- Where dev fixes land (`notebooks/nested_functions.py`, 30 dev instances, changed lines
  from `changed_lines`, innermost enclosing definition per line, counted per instance; an
  instance can be in several buckets):

  | Changed line is inside | Instances |
  |---|---|
  | a function, method or class (not nested in a function) | 29 |
  | module-level code (no definition) | 4 |
  | a function nested in a function | 2 |

  - The 2 nested cases: sympy__sympy-17630 (`_postprocessor`, 33 lines, inside
    `get_postprocessor`, 35 lines: the nested function is almost the whole parent) and
    sympy__sympy-22840 (`_find_repeated`, 32 lines, inside `tree_cse`, 143 lines).
  - `ast` parsed every changed file at its base commit; no failures.
  - n = 30, both nested cases in sympy: no claim about how common nested-function fixes
    are outside this sample.
  - 4 / 30 instances change module-level code, which the module chunk rule (ADR 004) has
    to cover.
- Function-level gold on dev (`notebooks/gold_stats.py`, 2026-11-09):
  - 43 gold chunks over 30 instances: 1 chunk in 19 instances, 2 in 9, 3 in 2.
  - By kind: 25 methods, 12 functions, 4 module chunks, 2 classes.
  - 0 instances without function-level gold; 0 changed files with parse errors.
  - 25 pure-insertion runs; 3 sit at a chunk boundary (neighbors with different owners), in
    2 instances (django__django-14752, sympy__sympy-15308). Both fixes add a new method.
    They add 5 gold chunks that the fix did not change: the class (via the blank line
    before the insertion) and the next method (via its `def` line).
  - The Phase 0 estimate (16 / 100 instances insert a `def` / `class`) was over all 100
    and from patch text only; on dev the chunker shows 2 / 30 with a boundary effect.
- `rg-chunks` on dev (k = 10, ripgrep 15.2.0, commit `a843cb0`,
  `results/rg-chunks_dev_20261110T030345Z.json`):

  | Level | n | R@1 | R@5 | R@10 | MRR@10 | Hit@1 | Hit@5 | Hit@10 |
  |---|---|---|---|---|---|---|---|---|
  | function | 30 | 0.111 | 0.194 | 0.228 | 0.210 | 0.167 | 0.267 | 0.300 |
  | file (from chunk ranking) | 30 | 0.200 | 0.400 | 0.500 | 0.297 | | | |
  | file, `rg` for comparison | 30 | 0.333 | 0.567 | 0.600 | 0.419 | | | |

  - Function level, per repo MRR@10: django 0.079 (n = 14), scikit-learn 0.457 (n = 7),
    sympy 0.222 (n = 9). Per category: cat 1 0.200 (n = 16), cat 2 0.221 (n = 14).
  - File level is lower than `rg` (MRR@10 0.297 vs 0.419). Measured: the top 10 chunks
    cover 7.2 distinct files on average, against 10 files for `rg`, so fewer files get a
    chance. Hypothesis, untested: ranking a file by its best chunk instead of by the sum
    over the whole file also loses signal spread over many chunks.
  - Module chunks are not dominating: 3 / 29 top-1 chunks are `<module>`, 30 / 268
    top-10 slots (1 instance returned nothing).
- Largest corpus among the dev snapshots (test files excluded): sympy__sympy-22840, 903
  files, 523,634 lines, 19.5 MB. The largest snapshot on disk overall is a test-split
  sympy commit (904 files, 532,895 lines); the dev one is used so the benchmark needs
  only dev snapshots and never touches the test split.
- Parse and chunk benchmark (`results/parse_bench_20261110T031038Z.json`, commit
  `9b9f111`): sympy__sympy-22840, Apple M4 Pro, 24 GB, macOS, Python 3.12.15,
  tree-sitter 0.26.0, tree-sitter-python 0.25.0. 5 runs after 1 discarded warm-up (warm
  OS page cache), each in a fresh process.

  | Step | Median (5 runs) | Range | Per file p50 / p95 / max (median run) |
  |---|---|---|---|
  | read 903 files | 0.08 s | 0.08–0.09 s | |
  | parse only | 1.91 s | 1.90–1.91 s | 0.49 / 6.5 / 149 ms |
  | `chunk_file` (parse + definitions + text) | 4.14 s | 4.13–4.15 s | 0.84 / 15.0 / 461 ms |

  - 31,502 chunks. Peak RSS 223 MiB, of which 126 MiB is the interpreter and imports
    before any file is read, so about 97 MiB for the file bytes, the trees and the chunks.
  - Chunking costs more than parsing (4.14 s vs 1.91 s, and `chunk_file` parses too).
    The worst file, `sympy/integrals/rubi/constraints.py` (11,117 lines, 2,040 chunks),
    takes 38 ms to parse and 462 ms to chunk. Cause: `chunk_texts` calls `owner` once
    per line, and `owner` scans every span, so a file costs lines × spans comparisons
    (here about 22.7 million). Not fixed: 4 s per snapshot is acceptable for now. A fix
    is a single pass that tracks the innermost open span (lines × nesting depth).
- `rg-chunks` on test (final, logged below; k = 10, ripgrep 15.2.0, commit `a51c849`,
  `results/rg-chunks_test_20261110T031500Z.json`). All 70 instances have function-level
  gold.

  | Level | n | R@1 | R@5 | R@10 | MRR@10 | Hit@1 | Hit@5 | Hit@10 |
  |---|---|---|---|---|---|---|---|---|
  | function | 70 | 0.071 | 0.150 | 0.214 | 0.117 | 0.071 | 0.157 | 0.229 |
  | file (from chunk ranking) | 70 | 0.229 | 0.471 | 0.557 | 0.337 | | | |

  - Function level MRR@10 per repo: django 0.151 (n = 32), scikit-learn 0.156 (n = 16),
    sympy 0.039 (n = 22). Per category: cat 1 0.175 (n = 38), cat 2 0.049 (n = 32).
  - Function-level MRR@10 is 0.210 on dev and 0.117 on test. The per-repo order also
    flips (django lowest on dev at 0.079, sympy lowest on test). With 7–32 queries per
    repo this is within what split noise can do; no per-repo claim.
  - Cat 2 (names an identifier, no path) is far below cat 1 on test (MRR@10 0.049 vs
    0.175); on dev the two were close (0.221 vs 0.200). Not a finding yet, only a question
    for the Phase 2 per-category tables.

### Test-split runs
- 2026-11-10, commit `a51c849`, `rg-chunks`, `results/rg-chunks_test_20261110T031500Z.json`.
  Why: final Phase 1 function-level baseline, run after ADR 002 Part 3 was accepted and
  ADR 004 written, so gold and chunk ids are fixed. `rg-chunks` is frozen from here.

### Problems and dead ends
- Function-level gold stats: first counted "gold chunks with no `-` line" (19 in 14
  instances) as the boundary cost. Wrong measure: an insertion inside a function body has
  both neighbors in that function, so the function is correct gold without any `-` line.
  The right measure is insertions whose two neighbors have different owners (3 runs).
- Known limitation, not fixed: a lone `\r` (old Mac line ending) counts as a line break
  for `bytes.splitlines()` but not for tree-sitter or git diffs, so N comes out too large
  for such files. Checked by hand on `b"x=1\ry=2\n"` (splitlines: 2, tree-sitter: 1 row).
  Not counted in the subset; expected to be rare.

### Open questions
- ~~Duplicate qualified names: the walker returns two `compat` entries for
  `if PY3: def compat()` / `else: def compat()`, but chunk ids (`path::QualifiedName`) must
  be unique. Keep both with a suffix, merge them, or keep the first?~~ Resolved: ordinal
  suffix (see Decisions).

### End-of-phase quiz (2026-11-10)
PLAN §8 questions plus 4 new ones (chunking complexity, gold over emitted chunks vs all
spans, `rg-chunks` length bias, boundary-insertion bias). All answered; weak spots, to
review before the deep-dive:
- Bytes vs str: mixed up the form feed (`\x0c`, the bug fixed here) with a lone `\r`
  (the logged limitation). Both are line breaks for `str.splitlines()`; only `\r` is one
  for `bytes.splitlines()` too.
- Faster `owner`: needed the concept given (a stack of open spans: push at
  `start_line`, pop while the top's `end_line` is behind, owner = top; O(N + M) instead
  of O(N × M)), then traced it correctly by hand.
- Gold over emitted chunks: needed two prompts to reach the consequence (an id that is
  never emitted can never be retrieved, so recall drops for reasons unrelated to
  retrieval).
- Boundary-insertion rule kept because changing a labeling rule after seeing the
  instances it hurts overfits the benchmark, and it affects only 2 / 30 dev instances.

### Retro (at phase end)
- What I'd do differently: when I got stuck on core code (`owner`, chunk text,
  `rg-chunks`), I delegated it instead of attempting it, and the quiz showed the gaps (the
  stack-based owner, why gold uses only emitted chunks). For Phase 2's core components
  (tokenizer, inverted index, BM25) I write a first attempt myself, even a wrong one, and
  ask for review rather than the solution.

## Phase 2: Lexical Search

**Status:** in progress

### Work done
- Plan for the phase, one session each: tokenizer, inverted index, BM25 + retriever, disk
  cache, tune `k1` / `b` on dev, latency and memory benchmark, failure analysis of 10 dev
  misses, test run and quiz.
- `code_atlas.lexical.tokenizer.tokenize`, 13 tests in `tests/lexical/test_tokenizer.py`
  (snake / camel case, acronyms, digits, dotted names, dunders, non-ASCII, duplicates).
- ADR 005 (tokenizer) written and accepted.
- `code_atlas.lexical.index`: `InvertedIndex` (postings, doc lengths, average length) and
  `build_index(chunk id -> tokens)`, one pass with a `Counter` per chunk. Tests on a
  three-chunk hand-computed corpus and the empty corpus in `tests/lexical/test_index.py`.
- `code_atlas.lexical.bm25`: `idf(df, num_docs)` and
  `bm25_scores(index, query_tokens, k1, b) -> chunk id -> score`, term-at-a-time over the
  query tokens' postings. 9 tests with hand-computed values in `tests/lexical/test_bm25.py`
  (including b = 0, k1 = 0 and a repeated query token).
- Stub `code_atlas.lexical.retriever.BM25Retriever` (chunks every corpus file and builds
  the index in the constructor), registered as `bm25`. `document_tokens(chunk)` and
  `search` not written yet; 6 tests on a fake three-file repo in
  `tests/lexical/test_retriever.py`.
- `BM25Retriever` written (`document_tokens`, `search`); first dev run with the defaults
  (see Findings).
- `codeatlas sweep-bm25` (`code_atlas.eval.sweep`): dev-only grid search over `k1` / `b`,
  one index build per snapshot, all 20 settings scored against it. Selection rule in
  `choose_setting`, tested in `tests/eval/test_sweep.py`. Run on dev (see Findings).
- On-disk index cache, `code_atlas.lexical.cache` (tests in `tests/lexical/test_cache.py`).
  `bm25`, `bm25-text-only` and the sweep use it.
- `bm25-text-only`: dev-only ablation that indexes chunk text without path and qualified
  name. The CLI refuses dev-only methods (`DEV_ONLY` in the runner) on test.
- `benchmarks/bm25_bench.py`: build, cache load and query latency (see Findings).
- `notebooks/bm25_misses.py` writes `notebooks/bm25_misses_dev.md`: every dev miss
  (function-level Hit@10 = 0) with issue text, gold patch, gold chunk ranks in the top
  1000, and per-token BM25 contributions for the gold and the top 3 chunks.

### Decisions
- Tokens: split on non-alphanumerics, `snake_case` and `camelCase`; lowercase; emit the
  whole identifier and its parts (`get_or_create` -> `get_or_create, get, or, create`).
  Why: issue text names identifiers both exactly and in prose. Cost: identifier-heavy
  chunks get longer and are penalized by length normalization. See
  [ADR 005](decisions/005-tokenizer.md).
- No stopword list. Why: IDF already weights a term found in most chunks close to 0, and
  words like `or`, `is`, `not` are also Python keywords and identifier parts.
- `tokenize` returns a list with duplicates. Why: BM25 needs term frequency.
- Acronyms stay one part (`parseHTTPResponse` -> `parse, http, response`); dots separate
  words with no dotted token; digits stay attached (`utf8`, `base64`); leading / trailing
  underscores stripped (`__init__` -> `init`); word characters are Unicode-aware. Reasons
  in ADR 005.
- `build_index` takes chunk id -> tokens, not chunks. Why: what text gets indexed (chunk
  text alone, or with path and qualified name) is then decided by the retriever, and the
  index stays a pure data structure that tests can feed hand-made tokens.
- Postings keyed by chunk id strings, as the Phase 2 task in PLAN §6 states. Integer doc ids would save
  memory; not done until the benchmark shows memory is a problem.
- Empty corpus: `avg_doc_length` is 0.0, not an error. Why: an empty corpus is a valid
  input, not a caller bug, and with no postings BM25 never divides by it.
- `build_index` returns `postings` as a plain `dict`, converted from the `defaultdict` used
  while building. Why: looking up an unknown query token in a `defaultdict` inserts an
  empty list, so every query would silently grow the index's vocabulary.
- Chunks with zero tokens are kept in `doc_lengths` (they count toward N and the average)
  with no special case. Why: they do not occur in practice (see Findings).
- IDF is `ln(1 + (N - df + 0.5) / (df + 0.5))` (Lucene's form), not the classic
  `ln((N - df + 0.5) / (df + 0.5))`. Why: the classic form goes negative for a token in
  more than half the chunks, so matching a common word would lower a chunk's score.
- Defaults `k1 = 1.2`, `b = 0.75` until tuned on dev.
- Indexed text per chunk = path + qualified name + chunk text. Why: issues paste
  tracebacks with real paths, and a method body rarely names its class, so only the
  qualified name links `QuerySet.get_or_create` to its chunk. Not leakage: the path comes
  from the corpus, not from gold. Cost: cat 1 is inflated by path matches (claims about
  BM25 rest on the per-category tables), and BM25 sees text `rg-chunks` did not, so a gain
  over the baseline is part ranking, part extra text. A dev-only ablation with chunk text
  alone measures that part. Small noise: the duplicate-name suffix adds a digit token
  (`C.name#2` -> `2`), and `<module>` adds `module`.
- Tuning protocol for `k1` / `b`, fixed on 2026-11-11 before any BM25 run:
  - Dev split only. The test split is run once, at the end of the phase, with the chosen
    values.
  - Metric: function-level MRR@10. Why: function level is what the project ranks, and
    MRR rewards putting the right chunk first; Recall@10 is too coarse on 30 queries.
  - Grid: `k1` in {0.6, 0.9, 1.2, 1.5, 2.0} x `b` in {0.25, 0.5, 0.75, 1.0}, 20 settings.
  - Rule: take the best setting; if it beats the defaults (1.2, 0.75) by less than 0.02
    MRR@10 (about one query's rank change on 30 queries), keep the defaults. Why: a smaller
    gain cannot be told apart from noise.
  - The grid and the metric are not changed after seeing results.
  - Tie for best: the first setting in grid order (k1, then b). Added with the sweep code,
    before the sweep ran; only matters if the tied settings beat the defaults by >= 0.02.
- `k1 = 1.2`, `b = 0.75` kept after the sweep. Why: the best setting (k1 2.0, b 0.5,
  0.293) beat the defaults (0.290) by 0.003, under the 0.02 margin.
- Index cache key = snapshot commit + variant (`path-name-text` or `text`) + a fingerprint
  (sha256 of the tokenizer, index, retriever and chunker source files and the tree-sitter
  versions). Why: a stale index after a tokenizer edit would silently change results;
  hashing the code makes invalidation automatic instead of relying on memory. Cost: any
  edit to those files, even a comment, rebuilds every index (about 1 minute for dev).
- Only a directory that is the top of a git checkout is cached. Why: its commit is a
  stable identity for the corpus; a plain directory has none. Checking the top level
  matters: `git rev-parse HEAD` inside a subdirectory of another repo would return that
  repo's commit.
- Cache files are pickles, written to a temp file and renamed. Why: pickle loads the
  `InvertedIndex` directly and is fast; it can run code on load, which is acceptable only
  for a cache this program writes and reads locally. The rename means a crash mid-write
  never leaves a truncated file under the real name.
- `build_seconds` in results files now measures a cache load when the index is cached.
  Build cost is measured by the benchmark, not by eval runs.
- A token repeated in the query counts once. Why: long issues and tracebacks repeat
  module and function names; counting each repeat would let one repeated name outweigh
  the rest of the query. Cost: words the reporter repeats for emphasis get no extra weight.
- Distinct query tokens are visited in first-seen order (`dict.fromkeys`), not as a `set`.
  Why: string hashing is randomized per process and float addition is not associative,
  so set order could change scores in the last bit and flip near-ties between runs.
- No guards for `idf <= 0` or `avg_doc_length == 0` in scoring: a token with postings has
  1 <= df <= N, so idf > 0, and a chunk in a posting list has at least one token, so the
  average is > 0.

### Findings
- Chunks whose text tokenizes to nothing: 0 of 43,920 (one snapshot per repo: django
  10,500, scikit-learn 4,717, sympy 28,703 chunks). Every function and class chunk has at
  least its keyword and name, and whitespace-only module chunks are already dropped.
- `bm25` on dev, defaults k1 1.2, b 0.75 (k = 10, commit `e226096`,
  `results/bm25_dev_20261111T225354Z.json`), next to the Phase 1 dev baselines:

  | Level | Method | n | R@1 | R@5 | R@10 | MRR@10 | Hit@1 | Hit@5 | Hit@10 |
  |---|---|---|---|---|---|---|---|---|---|
  | function | `bm25` | 30 | 0.161 | 0.361 | 0.461 | 0.290 | 0.200 | 0.433 | 0.567 |
  | function | `rg-chunks` | 30 | 0.111 | 0.194 | 0.228 | 0.210 | 0.167 | 0.267 | 0.300 |
  | file (from chunks) | `bm25` | 30 | 0.533 | 0.667 | 0.800 | 0.604 | | | |
  | file | `rg` | 30 | 0.333 | 0.567 | 0.600 | 0.419 | | | |

  - Function-level MRR@10 per category: cat 1 0.231 (n = 16), cat 2 0.357 (n = 14);
    `rg-chunks` was 0.200 / 0.221. Per repo: django 0.233 (n = 14), scikit-learn 0.402
    (n = 7), sympy 0.290 (n = 9).
  - Cat 1 (traceback or path) is below cat 2 even though paths are indexed. Hypothesis,
    untested: a traceback adds many tokens (frames, paths into library code, line numbers)
    that match many chunks and dilute the few that point at the fix. The failure analysis
    should check this.
  - Part of the gain over `rg-chunks` comes from indexing path and qualified name, which
    `rg-chunks` never searched; the chunk-text-only ablation would measure how much.
  - Index build (chunk + tokenize + index) per snapshot: median 1.2 s, max 4.8 s, from
    `build_seconds` in the results file. Not a benchmark (cold / warm cache not
    controlled); the latency table comes later.
- `k1` / `b` sweep on dev (commit `5ec9d14`, `results/bm25-sweep_dev_20261111T225622Z.json`),
  function-level MRR@10:

  | k1 \ b | 0.25 | 0.5 | 0.75 | 1.0 |
  |---|---|---|---|---|
  | 0.6 | 0.197 | 0.250 | 0.275 | 0.267 |
  | 0.9 | 0.186 | 0.272 | 0.270 | 0.273 |
  | 1.2 | 0.198 | 0.279 | **0.290** | 0.273 |
  | 1.5 | 0.211 | 0.283 | 0.280 | 0.287 |
  | 2.0 | 0.236 | 0.293 | 0.292 | 0.255 |

  - The defaults score 0.290 in the sweep, the same as the standalone dev run, so the
    sweep's scoring path matches `codeatlas eval`.
  - `b = 0.25` is the worst column for every `k1` (0.186–0.236); for `b` >= 0.5 every
    setting is within 0.250–0.293, a spread of about two to four query rank changes on 30
    queries. Measured: weak length normalization hurts here. Hypothesis: without it, long
    chunks (big module and class chunks) match more query tokens and crowd the top 10.
  - No setting clears the 0.02 margin, so the defaults stay (see Decisions).
- Cache check: `bm25` on dev with an empty cache, then again reading every index from it
  (commit `cf95774`, `results/bm25_dev_20261111T230214Z.json` is the cached run). Chunk
  rankings identical to the first dev run on all 30 instances. Whole dev eval: 61 s
  uncached, 3.7 s cached; cached index load per snapshot median 0.04 s, max 0.11 s. Cache
  size for the 30 dev snapshots: 183 MB.
- BM25 benchmark (`results/bm25_bench_20261111T230356Z.json`, commit `9a26500`):
  sympy__sympy-22840 (largest dev corpus), Apple M4 Pro, 24 GB, macOS, Python 3.12.15,
  tree-sitter 0.26.0, tree-sitter-python 0.25.0. Warm OS page cache; build and load are 5
  runs after 1 discarded warm-up, each in a fresh process.

  | Index | Value |
  |---|---|
  | chunks | 31,502 |
  | vocabulary | 76,414 tokens |
  | postings entries | 1,244,960 |
  | total tokens | 3,467,720 (average 110 per chunk) |
  | pickle on disk | 14.2 MB |

  | Step | Median (5 runs) | Range | Peak RSS |
  |---|---|---|---|
  | build (chunk + tokenize + index) | 4.75 s | 4.72–4.77 s | 433 MiB (127 after imports) |
  | load from cache | 0.093 s | 0.092–0.093 s | 245 MiB (127 after imports) |

  | Query latency (k = 10, warm, median of 5 per query) | n | p50 | p95 | max |
  |---|---|---|---|---|
  | each dev query on its own snapshot | 30 | 11.9 ms | 27.8 ms | 51.0 ms |
  | every dev query on the largest index | 30 | 27.5 ms | 51.5 ms | 58.7 ms |

  - A loaded index costs about 118 MiB of RSS (245 − 127). Building peaks about 306 MiB
    above imports, because chunks, token lists and the index are all in memory at once.
  - Building takes 51× longer than loading (4.75 s vs 0.093 s).
  - The same 30 queries are 2.3× slower at p50 on the largest index than on their own
    snapshots. Expected: query cost is the total length of the query tokens' posting
    lists, which grow with the corpus.
- Ablation, chunk text only (`bm25-text-only`, dev, commit `3793d92`,
  `results/bm25-text-only_dev_20261111T230503Z.json`), function level:

  | Indexed text | MRR@10 | R@10 | Hit@10 | MRR@10 cat 1 (n 16) | MRR@10 cat 2 (n 14) |
  |---|---|---|---|---|---|
  | path + name + text (`bm25`) | 0.290 | 0.461 | 0.567 | 0.231 | 0.357 |
  | text only | 0.267 | 0.344 | 0.433 | 0.199 | 0.345 |
  | `rg-chunks` (Phase 1) | 0.210 | 0.228 | 0.300 | 0.200 | 0.221 |

  - Of `bm25`'s +0.080 MRR@10 over `rg-chunks`, +0.057 remains with text alone, so most of
    the MRR gain is the ranking, not the extra text. Path and name matter more for
    Hit@10 (0.433 -> 0.567, 4 of 30 instances).
  - Path and name add more for cat 1 (+0.032) than cat 2 (+0.012), the direction expected
    if tracebacks' paths match chunk paths. n = 16 and 14: a direction, not a finding.
- Failure analysis: all 13 dev misses (function-level Hit@10 = 0 for `bm25`), read from
  `notebooks/bm25_misses_dev.md` (generated from
  `results/bm25_dev_20261111T230214Z.json`). All 13 analyzed rather than 10, so the sample
  was not picked after reading. Evidence is the per-token contribution tables: what the
  gold chunk scored on versus what the top 3 scored on.

  | Instance | Gold rank | Why it failed (evidence) | Type |
  |---|---|---|---|
  | django-11797 | 83 | Winners (`get_group_by`) score on the symptom's words (`group`, `by`, `annotate`, `values`); the fix is in `Exact.process_rhs`, which the issue never describes. | symptom ≠ fix |
  | django-12284 | 31 | Winners score on the pasted example model (`max_length`, `charfield`, `choices` ×23), not on `abstract` / `display`. `get_FOO_display` is built by string formatting, so the name never appears in code. | query noise |
  | django-15388 | >1000 | Gold matches only `dir`, `file`, `in`: the issue says `templates`, "changes", "restart"; the code says `template`, `changed`, `autoreload`. The real cause (`.py` files reset templates) is not in the issue. | vocabulary mismatch |
  | django-15738 | 190 | Winners are migration files matching the pasted models (`max_length`, `on_delete`, `unique_together`) and a 646-token chunk matching 43 query words. | query noise |
  | django-16820 | 476 | Short chunks about `index_together` (`AlterIndexTogether`, 49 tokens) beat the fix in `CreateModel.reduce` (580 tokens, length-penalized). The issue says "squashing"; the code that squashes is `reduce`. | symptom ≠ fix |
  | django-16873 | 15 | Gold scores on the right words (`autoescape`, `escape`, `join`); winners score on the pasted test case (`assertequal`, `assert`) and a 751-token module chunk matching 41 words a little each. | query noise |
  | sklearn-10508 | 104 | #1 is the `LabelEncoder` class chunk: right class, wrong chunk. Its docstring example (`le = LabelEncoder()`) mirrors the issue's code (`le` ×10). #2–3 score on traceback words (`kwds`) and numbers. | right class, wrong chunk |
  | sklearn-14092 | 47 | The issue is a design proposal using NMF and `LogisticRegression` as examples; the winners are those (`beta_loss`, `frobenius`, `l1_ratio`). 225 distinct query tokens. | query noise |
  | sympy-14024 | 245 | Winners score on REPL variable names (`n1`, `n2`, `e`, `x`). The issue writes `**`; the code is `_eval_power`, and an operator has no tokens. | vocabulary mismatch |
  | sympy-15308 | 190 | The fix adds `_print_Trace`, so gold is the neighboring chunks (boundary-insertion rule); the issue's one specific word, `Trace`, has nothing to match. Winners score on `but`, `it`, `be`, `should`. | gold-label artifact |
  | sympy-17630 | 385 | Winners are what the issue and traceback name (`block_collapse`, `BlockMatrix`, `attributeerror`); the fix is in `get_postprocessor`, never mentioned. | symptom ≠ fix |
  | sympy-19007 | >1000 | #1 is the `BlockMatrix` class chunk. The issue writes `C[i, 0]` (indexing syntax); the code is `_entry`. | vocabulary mismatch |
  | sympy-22840 | 50 | The pasted output has variables `x0`…`x16`; a benchmark file with the same names wins, each name with idf about 9. | query noise |

  | Type (main cause) | n | What could help |
  |---|---|---|
  | Query noise: pasted code, output, tracebacks, variable names | 5 | query cleanup or title weighting (lexical) |
  | Symptom ≠ fix location | 3 | probably nothing lexical; maybe graph expansion |
  | Vocabulary mismatch, incl. syntax vs method name (`**`, `[i, 0]`) | 3 | semantic search; stemming only for plurals and inflections |
  | Right class, wrong chunk | 1 | none planned (class docstring competes with its methods) |
  | Gold-label artifact | 1 | none: the target does not exist at the base commit |

  - Query noise is the largest group (5 / 13). It fits the cat-1 dilution hypothesis, but
    n = 13: a direction, not a finding.
  - Numbers-as-tokens hypothesis: partly seen. Digit-bearing variable names (`x10`, `n1`)
    drive two misses (22840, 14024); bare traceback line numbers did not decide any miss.
  - Prediction for Phase 3, to check there: semantic search helps the 3 vocabulary-mismatch
    misses (15388, 14024, 19007) more than the 5 query-noise misses.
  - In 2 misses (10508, 19007) the top hit is the class chunk of the gold method's own
    class: the class chunk policy (no method bodies, docstring kept) lets the docstring's
    usage example compete with the methods it describes.
  - First pass written by me, then checked against the tables in review: 6 / 13 were right
    on the main cause; 12284 was wrong (blamed common words; the words were rare and the
    winners matched the pasted model), and 10508, 19007 had no answer. Lesson: name the
    winners' top tokens and where in the issue they come from before naming a type.
- `bm25` on test (final, logged below; k1 1.2, b 0.75, k = 10, commit `485a31a`,
  `results/bm25_test_20261112T023215Z.json`), next to the baselines' logged test runs. All
  70 instances have function-level gold.

  | Level | Method | n | R@1 | R@5 | R@10 | MRR@10 | Hit@1 | Hit@5 | Hit@10 |
  |---|---|---|---|---|---|---|---|---|---|
  | function | `bm25` | 70 | 0.140 | 0.367 | 0.438 | 0.262 | 0.157 | 0.414 | 0.500 |
  | function | `rg-chunks` | 70 | 0.071 | 0.150 | 0.214 | 0.117 | 0.071 | 0.157 | 0.229 |
  | file (from chunks) | `bm25` | 70 | 0.571 | 0.771 | 0.771 | 0.641 | | | |
  | file | `rg` | 70 | 0.371 | 0.557 | 0.643 | 0.454 | | | |

  - Function-level MRR@10 per category: cat 1 0.296 (n = 38), cat 2 0.221 (n = 32);
    `rg-chunks` was 0.175 / 0.049. Per repo: django 0.377 (n = 32), scikit-learn 0.265
    (n = 16), sympy 0.092 (n = 22; R@1 0.000).
  - Function-level MRR@10 is 0.290 on dev and 0.262 on test, so the dev number held up
    within about 0.03.
  - BM25 beats both baselines on every metric at both levels on test. Function-level
    MRR@10 is 2.2× `rg-chunks` (0.262 vs 0.117); Hit@10 goes from 0.229 to 0.500.
  - Cat 1 is above cat 2 on test (0.296 vs 0.221), the reverse of dev (0.231 vs 0.357).
    So the dev-based hypothesis that tracebacks dilute cat-1 queries is not supported at
    the category level; the dev order was within split noise (n = 14–38 per group). The
    query-noise misses on dev remain a per-instance observation, not a category effect.
  - Sympy is the weakest repo at function level on test (MRR@10 0.092, no gold chunk at
    rank 1 in 22 instances). Hypothesis, untested (no failure analysis on test, by design):
    sympy issues are REPL sessions with math expressions and short variable names, the
    pattern behind the sympy dev misses (14024, 22840).

### Test-split runs
- 2026-11-12, commit `485a31a`, `bm25`, `results/bm25_test_20261112T023215Z.json`. Why:
  final Phase 2 result, run after the tuning sweep and the dev failure analysis. `bm25`
  (tokenizer, indexed text, k1 1.2, b 0.75) is frozen from here; any change is a new
  method with its own logged test run.

### Problems and dead ends
- First tokenizer used `[A-Za-z0-9_]+` for words: `naïve_parse` gave `na, ve_parse`, a
  fragment from the middle of a word. Root cause: an ASCII-only character class assumes
  ASCII text. Fix: `\w+`, which is Unicode-aware on `str` patterns.
- Second attempt also widened the camelCase regex to Unicode ranges. `À-ɏ`
  includes lowercase letters (`ï`), so `naïve` split into `na, ïve`; the rewrite also
  dropped the acronym and digit rules (`parseHTTPResponse` -> `httpresponse`). Existing
  tests did not catch it. Reverted to the ASCII camelCase regex and added tests for
  acronyms, digits and non-ASCII.

### Open questions
-

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
- Defense checklist (PLAN §8) answered without notes: yes / no
-->

## Phase 0: Evaluation Harness

**Status:** done (2026-11-08). Defense checklist: two answers still open, see Retro.

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
-

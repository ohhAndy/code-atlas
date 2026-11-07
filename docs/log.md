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

**Status:** in progress

### Work done
- Wrote PLAN.md and AGENTS.md. Created package skeleton with empty module stubs.
- Configured pyproject: uv, ruff, mypy --strict, pytest. No CI or tests/ yet.
- Loaded SWE-bench Lite (HF `test` split) into `notebooks/explore.ipynb`.
- Dropped columns not needed for retrieval eval.

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
  file-level Recall@k is "is that file in the top k" and MRR is 1 / its rank.
- Test-file rule check (`notebooks/test_file_rule.ipynb`): 0 / 100 `patch` files excluded;
  1 / 127 `test_patch` files not excluded (`sympy/testing/quality_unicode.py`).

### Problems and dead ends
- Notebook first reported 0 / 127 for check (a). Root cause: an earlier version of a later
  cell reused the same counter, and the kernel kept that value after the cell was renamed.
  Fix: restart kernel and run all before trusting or committing notebook output.

### Open questions
- ~~Query category precedence: a traceback usually also names identifiers. Which category wins?~~
  Resolved: 1 > 2 > 3 (see Decisions).
- ~~Test files in the index: keep, exclude, or report both?~~ Resolved: exclude.
  See [ADR 002](decisions/002-gold-labels.md).

### Retro (at phase end)
-

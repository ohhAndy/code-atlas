# ADR 001: Evaluation subset and dev/test split

**Status:** Accepted
**Date:** 2026-11-06

## Context
SWE-bench Lite has 300 instances across 12 repos. Nearly every instance has its own
base commit, and each commit must be checked out, parsed and indexed separately, so
indexing cost scales with (instances) × (repo size). Using all 300 is too expensive for
this project. Every repo in the subset also needs enough instances for a dev set
large enough to tune on.

## Options considered
- **All instances from the top 3 repos (214):** most data, but it is quite expensive still and django takes most of the slots. 
- **Proportional sample across django/sympy/scikit-learn (53/36/11):** it mirrors SWE-bench, but scikit-learn would get only 3 dev queries.
- **All of the third repo, remainder proportional (46/31/23):** chosen.

## Decision
- 100 instances: 46 django, 31 sympy, all 23 scikit-learn.
- Within each repo, random sample with a fixed seed (42), then 30% dev / 70% test
  (30 dev, 70 test total).

## Consequences
- Django is 46% of the subset, so the overall numbers lean toward django. Results are
  reported per repo as well as overall.
- Scikit-learn has only 7 dev queries, so per-repo dev numbers for it are noisy.
- With 70 test queries, one query is ~1.4 points of recall.
- dev and test issues can come from the same time period of the codebase. 
- Results only support claims about these three repos.

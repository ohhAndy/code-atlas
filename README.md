# CodeAtlas

Code retrieval for Python repositories, evaluated on SWE-bench Lite: given a GitHub issue,
rank the files (and later, functions) most likely to need changing.

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

## Development

```bash
uv run pytest
uv run ruff check && uv run ruff format --check
uv run mypy
```

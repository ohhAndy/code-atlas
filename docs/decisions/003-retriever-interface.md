# ADR 003: Retriever interface

**Status:** Accepted
**Date:** 2026-11-07

## Context
The runner scores every retriever the same way: for each instance, get the snapshot at
`base_commit`, ask a retriever for its top k for the issue text, and score that list
against gold. Two facts break the interface sketched in PLAN §3
(`search(query, k) -> list[Hit]`, where `Hit` holds a `chunk_id`):

1. **Retrievers return different kinds of ids.** The ripgrep baseline ranks file paths;
   it has no chunks (they arrive in Phase 1). BM25 and vector search rank chunk ids.
   File paths must be scored against file gold, chunk ids against function gold (or
   mapped to files with `files_from_chunks`). Scoring one kind against the other matches
   nothing and gives 0.0 on every query, with no error.
2. **Some retrievers must prepare per snapshot.** ripgrep needs nothing. BM25 builds an
   inverted index (seconds); vector search embeds every chunk (minutes, and API cost).
   Each snapshot needs its own index, and nearly every instance has its own snapshot.
   Preparation should happen once per snapshot, while search may run many times
   (re-running dev while tuning `k1`, `b`, RRF `k`).

## Options considered

**Telling the runner which kind of ids it gets**
- **(a) The retriever declares `level: "file" | "chunk"`:** chosen. One protocol; the
  runner branches on one field. A wrong declaration is one visible line.
- **(b) Separate protocols or hit types for files and chunks:** works, but doubles the
  runner code paths for a difference that is one field.
- **(c) ripgrep emits fake chunk ids such as `"path::<file>"`:** rejected. They look like
  real chunk ids, so `files_from_chunks` accepts them, but no gold function is named
  `<file>`, so function-level scores are silently 0.0.

**Where the snapshot and its index live**
- **Constructor per snapshot, `Retriever(repo_dir)` then `search(query, k)`:** chosen.
  The constructor does the preparation and keeps the index as a field. One object = one
  snapshot = one index, and the index is freed with the object.
- **Stateless, `search(repo_dir, query, k)`:** rejected. There is nowhere to keep the
  index, so it is either rebuilt on every call (slow; re-embeds in Phase 3) or kept in a
  hidden cache keyed by path (eviction, memory, and staleness to manage). Looks simpler
  only for ripgrep, which has no index.

## Decision
```python
@dataclass(frozen=True)
class Hit:
    id: str        # a repo-relative file path, or a chunk id "path::QualifiedName"
    score: float

class Retriever(Protocol):
    level: Literal["file", "chunk"]
    def search(self, query: str, k: int) -> list[Hit]: ...
```
- Each retriever's constructor takes the snapshot directory and does all preparation.
- The runner keeps a registry from method name to constructor, e.g.
  `{"rg": RipgrepRetriever}`, and builds one retriever per snapshot.
- Scoring by level:
  - `"file"`: file-level metrics only, scored directly.
  - `"chunk"`: function-level metrics directly; file-level after `files_from_chunks`.

## Consequences
- File-level retrievers (ripgrep) get no function-level scores. Results tables show "n/a"
  for them, not 0.
- `Hit.id` is renamed from `chunk_id`, since it may hold a file path.
- Construction may be slow (BM25, embeddings) and is timed separately from search.
- Constructors may take more arguments later (e.g. `k1`, `b`); the registry entry is
  then a function of `repo_dir`, not the bare class.

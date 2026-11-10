# ADR 004: Chunking policy

**Status:** Accepted
**Date:** 2026-11-09

Implemented in `code_atlas.parse.definitions` (tree walk) and `code_atlas.parse.chunks`
(`chunk_spans`, `owner`, `chunk_texts`, `chunk_file`). Tests in `tests/parse/`.

## Context
Retrievers rank chunks, and function-level gold is a set of chunk ids (ADR 002 Part 3),
so the chunk is both the unit of retrieval and the unit of evaluation. The policy has to
say:

1. which syntax creates a chunk, and how a chunk is named;
2. which lines and which text belong to each chunk, given that definitions nest
   (method in class in module);
3. what happens with duplicate names, empty modules and very long functions;
4. how line numbers stay consistent between tree-sitter, git diffs and Python strings.

Two alternatives frame it:
- **Fixed-size windows** (e.g. 50 lines with overlap): simple and size-bounded, but a
  window cuts functions in half and has no name, so gold ("the function the fix changed")
  cannot be expressed in windows, and results cannot be read as "found `Foo.bar`".
- **Syntax-based chunks** (one per definition): match the unit a developer thinks in and
  the unit a fix changes; sizes vary widely.

## Decision
Syntax-based chunks, with these rules.

### 1. What is a chunk
- One chunk per function, method and class, plus one **module chunk** per file
  (`<module>`, the top-level code outside definitions).
- Only `def` and `class` create a scope. Every other node (`if`, `try` / `except`,
  `with`, `for`, ...) is looked through with the scope unchanged, so a function under
  `if TYPE_CHECKING:` is a module-level function and a method under `if` in a class body is
  a method.
- **Nested functions are part of their parent.** The walker descends into class bodies
  but not into function bodies; any definition inside a function, including a class, stays
  in the enclosing function's chunk.
- A decorated definition starts at its first decorator, so a decorator-only change maps
  to the function it decorates.
- Qualified names join class names with `.`: `Session.request`, `Outer.Inner.method`.
- Chunk id: `path::qualified_name`, built in one place (`chunk_file`).

### 2. Line ownership
Every line of a file belongs to exactly one chunk: the **smallest chunk whose line range
contains it** (`owner`). The module chunk's range is the whole file, so it owns what no
definition contains. Definition ranges are either nested or disjoint, so the smallest
containing range is always the innermost definition. On a tie in length (a class that
spans the whole file has the same range as the module), the later span in source order
wins, because a container is always listed before what it contains.

`Chunk` keeps a single `start_line` / `end_line` (the full range). The "holes" exist only
in the text.

### 3. Chunk text
A chunk's text is the lines it owns, in order:
- function / method: its whole definition (including nested functions);
- class: header, docstring, class-level code and the blank lines and comments between
  methods, **without** methods (no bodies, no signatures);
- module: imports and top-level code, plus the blank lines and comments between top-level
  definitions.

Lines between definitions (blank lines, comments above a `def`) belong to the enclosing
class or module. This follows from the ownership rule with no extra code.

### 4. Duplicates, empty modules, long functions
- **Duplicate qualified names** get an ordinal suffix in source order: `Model.name`,
  `Model.name#2`. Common through `@property` + `@name.setter`, and `if` / `else` shims.
- **The module chunk is left out when its text is only whitespace** (an empty
  `__init__.py`, a file that is one class). Its lines then have no owner.
- **No size limit in Phase 1.** Long functions stay one chunk.

### 5. Bytes, lines and decoding
- Lines are split on the raw bytes (`bytes.splitlines`), then each line is decoded. Never
  decode first and split the `str`.
- Decoding uses UTF-8 with `errors="replace"`.

## Why

**Syntax chunks over windows.** Gold is "the function the fix changed" (PLAN §5), which only
exists if chunks are functions. Windows would also need a rule for gold that straddles two
windows. Cost: chunk sizes vary from 1 line to hundreds, which affects BM25 (length
normalization) and embeddings (truncation).

**Nested functions in their parent.** On dev, 2 / 30 instances change a line inside a
nested function (`notebooks/nested_functions.py`). The rule fixed before counting was:
0–2 -> part of parent, 3 or more -> read them and decide. Cost: gold for a fix in a nested
helper is the whole parent (`tree_cse`, 143 lines, sympy__sympy-22840).

**Innermost owner.** A fix inside `Foo.bar` should make `Foo.bar` gold, not `Foo` and the
module too; otherwise a retriever that returns the module scores a hit for any change in
the file. Exactly-one-owner also makes chunk texts partition the file: no text is indexed
twice.

**No method signatures in the class chunk.** A query naming a method should rank the
method chunk. Copying signatures into the class makes the class compete with its own
methods, more so for big classes (`QuerySet`, `LatexPrinter`). Cost: the class chunk no
longer lists what the class can do.

**Ordinal suffix for duplicates.** Every definition stays its own chunk, so the ownership
rule still holds. Merging getter and setter would create a chunk with two line ranges.
Keeping only the first would make the other's lines belong to the class. Cost: an id can
shift between commits if a same-name definition is added earlier; the embedding cache is
keyed by chunk text, not id, so this costs little.

**Drop whitespace-only module chunks.** A chunk with no searchable text is noise (BM25
document length 0, an embedding of nothing). Gold is computed over the chunks actually
emitted, so no gold id can point at a dropped chunk (ADR 002 Part 3).

**No size limit yet.** BM25 handles long documents through `b`. Embedding models silently
truncate past their token limit, and that limit depends on the model chosen in Phase 3.
The rule is decided with ADR 006.

**Split bytes, then decode.** Line numbers must match tree-sitter rows and git diff lines,
which both break only on `\n`. `str.splitlines()` also breaks on form feed (`\x0c`,
used as a page break in older Python), `\x1c`–`\x1e`, `\x85`, `` and ``, which
would shift every later line by one and silently give lines to the wrong chunk (caught by
a test). Splitting UTF-8 bytes on `\n` is safe because the byte `0x0A` never occurs inside a
multi-byte character.

**`errors="replace"`.** Real repos contain mis-encoded files (sphinx fixtures). One bad
byte should not stop a snapshot from being indexed. Cost: the replaced characters are lost
for search, and how often this happens is not counted.

## Evidence
- Dev fixes by location (`notebooks/nested_functions.py`, Python `ast`): 29 / 30 instances
  change a function, method or class not nested in a function; 4 / 30 change module-level
  code; 2 / 30 change a function nested in a function.
- Function-level gold on dev with this policy (`notebooks/gold_stats.py`): 43 gold chunks
  (25 methods, 12 functions, 4 module chunks, 2 classes); 0 instances without
  function-level gold; 0 changed files with tree-sitter parse errors.
- Benchmark on the largest dev corpus (sympy__sympy-22840, 903 files, 524k lines, Apple
  M4 Pro): parse 1.91 s, `chunk_file` 4.14 s, 31,502 chunks, peak RSS 223 MiB
  (`results/parse_bench_20261110T031038Z.json`).

## Consequences
- **Gold depends on this policy.** Any change here changes function-level gold and chunk
  ids, and earlier function-level results stop being comparable.
- **Chunking is O(lines × chunks) per file.** `owner` scans every span for every line. The
  worst file (`sympy/integrals/rubi/constraints.py`, 11,117 lines, 2,040 chunks) takes
  462 ms to chunk against 38 ms to parse. Acceptable at about 4 s per snapshot; a
  single pass tracking the innermost open span would make it lines × nesting depth.
- **`owner` depends on source order.** It is correct only when containers come before
  their contents, as `chunk_spans` and `chunk_file` produce them.
- **Lone `\r` line endings** count as a break for `bytes.splitlines()` but not for
  tree-sitter or git, so line numbers drift in such files. Not counted in the subset;
  expected to be rare.
- **Syntax errors do not stop chunking.** Tree-sitter repairs the tree (`ERROR` or
  `MISSING` nodes), and definitions it can still see become chunks. No changed file in the
  dev subset has a parse error.
- **Long functions stay whole** until ADR 006 decides on a limit for embeddings.

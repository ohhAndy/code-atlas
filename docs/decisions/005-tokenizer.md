# ADR 005: Tokenizer

**Status:** Accepted
**Date:** 2026-11-10

## Context
BM25 can only match a query to a chunk through shared tokens, so the tokenizer decides what
counts as "the same word". Issue text and code spell the same thing differently:

- The issue says `QuerySet.get_or_create()`, prose like "get or create", or `TypeError`.
- The code says `def get_or_create(self, ...)`, `self.get_or_create(`, `class QuerySet`.

Splitting on whitespace alone gives tokens like `QuerySet.get_or_create()` and
`get_or_create(self,`, which never match. The same function tokenizes both queries and chunks,
so a choice made here applies to both sides.

## Options considered

**Identifiers: whole, parts, or both**
- **Whole identifier only** (`get_or_create`): exact matches only. A query saying
  "get or create" in prose, or naming only `create`, misses.
- **Parts only** (`get`, `or`, `create`): prose matches, but a query naming the exact
  identifier scores no higher than one using its common parts in any order.
- **Both, whole plus parts:** chosen. An exact identifier match counts as the rare whole
  token (high idf) *and* its parts; a partial match still scores through the parts.

**Stopwords**
- **Drop an English or code stopword list:** rejected. IDF already weights very common terms
  close to 0. Illustration with N = 31,000 chunks: a term in 80% of chunks gets
  `ln(1 + 0.2N/0.8N) ≈ 0.22`; a term in one chunk gets `ln(1 + N/1.5) ≈ 9.9`. A list
  would also have to decide about words like `or`, `is`, `in`, `not`, which are real Python
  keywords and identifier parts.
- **No stopword list:** chosen.

**Output type**
- **Set of tokens:** rejected. BM25 needs term frequency, and a set loses the counts.
- **List with duplicates:** chosen. Order is not used by BM25.

## Decision
`tokenize(text: str) -> list[str]`, applied the same way to queries and chunk text:
- Split on non-alphanumeric characters, then split identifiers on `snake_case` and
  `camelCase` boundaries.
- Lowercase every token.
- Emit the whole identifier and its parts. A word with a single part is emitted once.
- Keep duplicates. No stopword list.

- **Word characters are Unicode-aware** (`\w` on `str`): `naïve_parse` -> `naïve_parse,
  naïve, parse`. Why: an ASCII-only class cuts words at the first accented letter and
  produces fragments such as `ve_parse`; sympy docstrings and issue text both contain
  non-ASCII. CamelCase splitting stays ASCII-only, so a case change between non-ASCII
  letters (`fooÜber`) is not split. Accepted as rare.
- **Acronyms stay one part:** `parseHTTPResponse` -> `parse, http, response`. Why: a
  per-capital split gives `h, t, t, p`, single letters that match everywhere and carry no
  meaning; issues write "HTTP" as one word.
- **Dots separate words, no dotted token:** `models.Model` -> `models, model`. Why: both
  parts already match, and code usually reaches the name some other way
  (`self.get_or_create`, `from x import y`), so a full dotted token would rarely match.
  Cost: an exact dotted match gets no extra boost.
- **Digits stay attached to the letters before them:** `utf8`, `base64`, `http2`; a part
  that is all digits stands alone (`x86_64` -> `x86, 64`). Why: `utf8` and `base64` are
  units of meaning; split, they would give `8` and `64`, which match unrelated numbers.
- **Leading and trailing underscores are stripped:** `__init__` -> `init`, `_private` ->
  `private`. Why: issue prose says "the init method" or "init"; the stripped form matches
  both prose and code. Cost: `__init__` and a plain `init` become the same token, and
  privacy (`_x`) is not searchable.

## Consequences
- Documents dense in compound identifiers get longer (each one adds 1 + its number of
  parts), so BM25's length normalization (`b`) penalizes them against chunks of plain words.
- Prose and code meet: "get or create" in an issue matches `get_or_create` in code through
  its parts.
- Common parts (`get`, `set`, `self`) match nearly every chunk; their low idf is the only
  thing keeping them from dominating.
- Numbers are tokens. A traceback's `line 1234` yields `1234`, which can match an unrelated
  literal; its idf is high because specific numbers are rare. Hypothesis to check in the
  failure analysis, not a rule yet.
- Changing the tokenizer changes every index, so all tuning (`k1`, `b`) on dev must be
  redone after a tokenizer change.

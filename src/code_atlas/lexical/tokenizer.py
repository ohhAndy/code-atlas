"""Code-aware tokenizer, applied the same way to queries and chunk text."""

from __future__ import annotations

import re

# Runs of letters, digits and underscores. On a str pattern, \w is Unicode-aware, so
# \u00DCberKlasse and na\u00EFve stay whole words.
IDENT_RE = re.compile(r"\w+")

# camelCase boundaries: lower or digit -> upper (getValue, utf8Decode), and the end of an
# acronym before a capitalized word (HTTPResponse -> HTTP | Response). ASCII-only: a case
# change between non-ASCII letters (foo\u00DCber) is not split.
CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def split_identifier(ident: str) -> list[str]:
    """Split an identifier on underscores and camelCase boundaries, lowercased."""
    parts: list[str] = []
    for chunk in ident.split("_"):
        if not chunk:
            continue
        parts.extend(CAMEL_SPLIT_RE.split(chunk))
    return [p.lower() for p in parts if p]


def tokenize(text: str) -> list[str]:
    """Split `text` into lowercase tokens for BM25.

    - Split on any character that is not a letter, digit or underscore (Unicode-aware).
    - Strip leading and trailing underscores: __init__ -> init.
    - Split identifiers on snake_case and camelCase boundaries. An acronym stays one part
      (parseHTTPResponse -> parse, http, response); digits stay attached to the letters
      before them (utf8_decode -> utf8, decode).
    - Emit the whole identifier and its parts; a single-part word is emitted once.
    - A dot separates words: models.Model -> models, model.
    - Keep duplicates, since BM25 needs term frequency. No stopword list.

    get_or_create -> get_or_create, get, or, create
    """
    tokens: list[str] = []

    for match in IDENT_RE.finditer(text):
        raw_ident = match.group(0).strip("_")
        if not raw_ident:
            continue

        parts = split_identifier(raw_ident)
        lower_ident = raw_ident.lower()

        if len(parts) > 1:
            tokens.append(lower_ident)
            tokens.extend(parts)
        elif parts:
            tokens.append(lower_ident)

    return tokens

"""Tests for tokenize. Token order is not used by BM25, so tests compare token counts
(a Counter), not lists."""

from __future__ import annotations

from collections import Counter

from code_atlas.lexical.tokenizer import tokenize


def counts(*tokens: str) -> Counter[str]:
    return Counter(tokens)


def test_empty_text() -> None:
    assert tokenize("") == []


def test_plain_word_is_lowercased_and_emitted_once() -> None:
    assert Counter(tokenize("Value")) == counts("value")


def test_snake_case_emits_whole_and_parts() -> None:
    assert Counter(tokenize("get_or_create")) == counts("get_or_create", "get", "or", "create")


def test_camel_case_emits_whole_and_parts() -> None:
    assert Counter(tokenize("QuerySet")) == counts("queryset", "query", "set")


def test_splits_on_punctuation() -> None:
    assert Counter(tokenize("foo(bar, baz)")) == counts("foo", "bar", "baz")


def test_keeps_duplicates() -> None:
    assert Counter(tokenize("create create")) == counts("create", "create")


def test_no_stopwords_dropped() -> None:
    assert Counter(tokenize("the value is None")) == counts("the", "value", "is", "none")


def test_acronym_stays_one_part() -> None:
    assert Counter(tokenize("parseHTTPResponse")) == counts(
        "parsehttpresponse", "parse", "http", "response"
    )


def test_acronym_followed_by_digit() -> None:
    assert Counter(tokenize("HTTP2Response")) == counts("http2response", "http2", "response")


def test_dot_separates_words_without_dotted_token() -> None:
    assert Counter(tokenize("models.Model")) == counts("models", "model")


def test_digits_stay_attached() -> None:
    assert Counter(tokenize("base64")) == counts("base64")
    assert Counter(tokenize("utf8_decode")) == counts("utf8_decode", "utf8", "decode")
    assert Counter(tokenize("utf8Decode")) == counts("utf8decode", "utf8", "decode")


def test_dunder_underscores_stripped() -> None:
    assert Counter(tokenize("__init__")) == counts("init")


def test_non_ascii_letters_are_word_characters() -> None:
    assert Counter(tokenize("ÜberKlasse")) == counts("überklasse", "über", "klasse")
    assert Counter(tokenize("naïve_parse")) == counts("naïve_parse", "naïve", "parse")

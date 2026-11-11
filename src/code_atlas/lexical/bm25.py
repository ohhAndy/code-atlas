"""BM25 scoring over an inverted index."""

from __future__ import annotations

from math import log

from code_atlas.lexical.index import InvertedIndex


def idf(df: int, num_docs: int) -> float:
    """Inverse document frequency of a token found in `df` of `num_docs` chunks:
    ln(1 + (N - df + 0.5) / (df + 0.5)). Rarer tokens get a higher weight; the 1 + keeps
    it positive even for a token in every chunk."""
    return log(1 + (num_docs - df + 0.5) / (df + 0.5))


def bm25_scores(
    index: InvertedIndex, query_tokens: list[str], k1: float = 1.2, b: float = 0.75
) -> dict[str, float]:
    """BM25 score of every chunk that contains at least one query token.

    score(chunk) = sum over distinct query tokens t of
        idf(t) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * doc_length / avg_doc_length))

    A token repeated in the query counts once. Distinct tokens are visited in first-seen
    order, not set order: string hashing is randomized per process, and float addition
    is not associative, so set order could change scores in the last bit between runs.

    Chunks that match no query token are left out (their score is 0). Query tokens that
    are not in the index contribute nothing.
    """
    scores: dict[str, float] = {}
    for token in dict.fromkeys(query_tokens):
        postings = index.postings.get(token)
        if not postings:
            continue

        # df >= 1 and the chunks below have at least one token, so idf > 0 and
        # avg_doc_length > 0 here.
        token_idf = idf(len(postings), index.num_docs)
        for chunk_id, tf in postings:
            doc_len = index.doc_lengths[chunk_id]
            len_norm = 1.0 - b + b * doc_len / index.avg_doc_length
            term_score = token_idf * tf * (k1 + 1) / (tf + k1 * len_norm)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + term_score

    return scores

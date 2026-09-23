"""BM25 keyword scoring over a candidate issue set (section 6).

The candidate set is small (typically 20 to 100 issues), so we build the index
fresh per query rather than maintaining one. rank_bm25 does the heavy lifting;
this module owns tokenisation and normalisation to 0..1 across the candidates.
"""

from __future__ import annotations

import re

from rank_bm25 import BM25Okapi

# Split on any run of non-alphanumeric characters, lowercase, drop empties.
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase word/number tokens. Keeps ``pay431`` and ``431`` findable."""
    return _TOKEN_RE.findall((text or "").lower())


def bm25_scores(query: str, documents: list[str]) -> list[float]:
    """Return a BM25 score in 0..1 for each document against ``query``.

    Normalised by the max score across the candidate set so the top document
    sits near 1.0 and the rest scale relative to it. If the query has no usable
    tokens, or every document scores zero, returns all-zeros (the ranker then
    leans on the other signals).
    """
    if not documents:
        return []

    tokenized_docs = [tokenize(doc) for doc in documents]
    query_tokens = tokenize(query)

    # A document with no tokens would make BM25Okapi divide by an avgdl of 0.
    # Guard both the query and the corpus being empty of usable tokens.
    if not query_tokens or not any(tokenized_docs):
        return [0.0] * len(documents)

    bm25 = BM25Okapi(tokenized_docs)
    raw = bm25.get_scores(query_tokens)

    top = max(raw) if len(raw) else 0.0
    if top <= 0:
        return [0.0] * len(documents)
    return [max(0.0, float(score) / top) for score in raw]

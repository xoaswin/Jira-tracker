"""Absolute pairwise text similarity for the duplicate guard (section 7).

The *ranker* (ranker.py) produces a relative ranking: BM25 is normalised across
the candidate set, so scores are only meaningful compared to each other. That is
the wrong tool for duplicate detection, which asks an absolute question: "is this
new description substantially the same as some existing issue?"

In particular, BM25 collapses to zero on a tiny corpus (every term appears in
"all" documents, so IDF goes to zero), which would make the duplicate guard
silently never fire in a project with few open issues.

So this module computes an absolute 0..1 similarity per issue:

* If embeddings are available, cosine similarity of the description embedding
  against the issue embedding (semantic, catches paraphrases).
* Always, a lexical similarity: Jaccard token overlap of the query against the
  issue *summary* (the canonical short form), and against summary+description,
  taking the larger. Independent of corpus size.

The final similarity is the max of the two, so either a strong semantic match or
a strong lexical match trips the guard.
"""

from __future__ import annotations

from app.matching.bm25 import tokenize
from app.matching.embeddings import (
    cosine_similarity,
    deserialize,
    embed_text,
    embeddings_available,
)


def jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard index of two token sets. Empty-vs-empty is 0 (no signal)."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def lexical_similarity(query: str, summary: str, description: str = "") -> float:
    """Max Jaccard of the query against the summary and against summary+desc.

    Comparing to the summary alone lets a short query that restates an existing
    issue's title score near 1.0, without being diluted by a long description.
    """
    q = set(tokenize(query))
    if not q:
        return 0.0
    summ_tokens = set(tokenize(summary))
    full_tokens = set(tokenize(f"{summary} {description}"))
    return max(jaccard(q, summ_tokens), jaccard(q, full_tokens))


def duplicate_similarity(
    query: str,
    *,
    summary: str,
    description: str = "",
    embedding_blob: bytes | None = None,
    embedding_model: str = "all-MiniLM-L6-v2",
) -> float:
    """Absolute 0..1 similarity of ``query`` to one existing issue.

    max(embedding cosine if available, lexical Jaccard). Never raises; degrades
    to lexical-only when embeddings are unavailable.
    """
    lexical = lexical_similarity(query, summary, description)

    semantic = 0.0
    if embedding_blob is not None and embeddings_available(embedding_model):
        query_vec = embed_text(query, embedding_model)
        issue_vec = deserialize(embedding_blob)
        semantic = cosine_similarity(query_vec, issue_vec)

    return max(lexical, semantic)

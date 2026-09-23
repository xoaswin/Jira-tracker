"""Sentence-embedding similarity for matching (section 6).

Deliberately optional. ``sentence-transformers`` pulls in a large ML stack, and
the spec is explicit that embeddings *improve* matching but are never load
bearing: the app must be fully usable without them. So this module:

* imports ``sentence-transformers`` lazily on first real use, never at import,
  keeping startup fast (section 6);
* reports availability so the ranker can re-weight and degrade cleanly when the
  library or model is absent;
* serialises embeddings as float32 ``numpy`` arrays for the ``issues.embedding``
  BLOB column, tagged with the model name so a model change triggers a rebuild.

numpy is a hard dependency (it is tiny and rank_bm25 needs it); only the model
itself is optional.
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger("jira_tracker.embeddings")

# Cache the loaded model process-wide. None means "not loaded yet"; a failed
# load flips ``_load_failed`` so we do not retry a broken import every call.
_model = None
_load_failed = False


def _try_load_model(model_name: str):
    """Load and cache the sentence-transformers model, or return None.

    Never raises: any failure (library missing, model download blocked, no
    network on first run) is logged once and the app degrades to BM25-only.
    """
    global _model, _load_failed
    if _model is not None:
        return _model
    if _load_failed:
        return None
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:  # ImportError or a transitive import problem
        logger.info("Embeddings disabled: sentence-transformers unavailable (%s)", exc)
        _load_failed = True
        return None
    try:
        _model = SentenceTransformer(model_name)
    except Exception as exc:  # model download / load failure
        logger.warning("Embeddings disabled: could not load model %s (%s)", model_name, exc)
        _load_failed = True
        return None
    return _model


def embeddings_available(model_name: str) -> bool:
    """True if the embedding model can be loaded (attempts the lazy load)."""
    return _try_load_model(model_name) is not None


def embed_text(text: str, model_name: str) -> np.ndarray | None:
    """Embed a single string, or None if embeddings are unavailable."""
    model = _try_load_model(model_name)
    if model is None:
        return None
    vec = model.encode([text or ""], convert_to_numpy=True, normalize_embeddings=False)[0]
    return np.asarray(vec, dtype=np.float32)


def embed_texts(texts: list[str], model_name: str) -> list[np.ndarray] | None:
    """Batch-embed strings, or None if embeddings are unavailable."""
    model = _try_load_model(model_name)
    if model is None:
        return None
    vecs = model.encode(texts, convert_to_numpy=True, normalize_embeddings=False)
    return [np.asarray(v, dtype=np.float32) for v in vecs]


def serialize(vec: np.ndarray | None) -> bytes | None:
    """Serialise a float32 vector to bytes for the BLOB column."""
    if vec is None:
        return None
    return np.asarray(vec, dtype=np.float32).tobytes()


def deserialize(blob: bytes | None) -> np.ndarray | None:
    """Inverse of :func:`serialize`. None/empty blob yields None."""
    if not blob:
        return None
    return np.frombuffer(blob, dtype=np.float32)


def cosine_similarity(a: np.ndarray | None, b: np.ndarray | None) -> float:
    """Cosine similarity clamped to 0..1 (section 6: already-clamped range).

    Negative cosine (semantically opposite) is floored to 0 since a negative
    "similarity" is meaningless for ranking here.
    """
    if a is None or b is None:
        return 0.0
    if a.shape != b.shape:
        return 0.0
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    cos = float(np.dot(a, b) / denom)
    if cos < 0.0:
        return 0.0
    if cos > 1.0:
        return 1.0
    return cos

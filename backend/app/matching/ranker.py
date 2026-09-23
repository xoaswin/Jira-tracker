"""Candidate ranking (section 6).

Combines four deterministic signals into a single 0..1 confidence per issue:

    final = w_bm25 * bm25 + w_embed * embedding + w_recency * recency

with the base weights 0.4 / 0.5 / 0.1. Two overrides sit on top:

* **Explicit key extraction** (rule 4): if the query contains an ``ABC-123`` key
  matching a candidate, that candidate jumps to confidence 1.0 and the rest of
  the scoring is skipped.
* **Git branch boost** (section 9): a key extracted from the current branch is
  treated the same way, so a checked-out ``feature/PAY-431-...`` preselects
  PAY-431.

When embeddings are unavailable the embedding weight is redistributed onto BM25
and recency proportionally, so scores stay in 0..1 and the app degrades cleanly
rather than capping every match at 0.5 (the spec: AI is never load bearing).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

from app.matching.bm25 import bm25_scores
from app.matching.embeddings import (
    cosine_similarity,
    deserialize,
    embed_text,
    embeddings_available,
)
from app.integrations.git import extract_issue_key

# Base signal weights (section 6). Sum to 1.0.
W_BM25 = 0.4
W_EMBED = 0.5
W_RECENCY = 0.1

# Recency boost decays linearly from full at <=3 days to zero at >=30 days.
RECENCY_FULL_DAYS = 3
RECENCY_ZERO_DAYS = 30

# Presentation thresholds (section 6).
PRESELECT_THRESHOLD = 0.75  # at/above: preselect the top match (still needs a click)
CREATE_LEAD_THRESHOLD = 0.45  # below: lead with "create new issue" instead
TOP_N = 3


@dataclass
class Candidate:
    """The matcher's view of one cached issue. Decoupled from the ORM row so the
    ranker is trivially unit-testable with plain objects."""

    issue_key: str
    summary: str
    description_text: str = ""
    issue_type: str | None = None
    status: str | None = None
    status_category: str | None = None
    sprint_name: str | None = None
    updated_at: datetime | None = None
    assignee_name: str | None = None
    assignee_account_id: str | None = None
    embedding: bytes | None = None
    embedding_model: str | None = None


@dataclass
class ScoredCandidate:
    candidate: Candidate
    score: float
    bm25: float
    embedding: float
    recency: float
    # Why this one scored the way it did, for debuggability and the UI.
    reason: str

    @property
    def confidence_pct(self) -> int:
        return round(self.score * 100)


@dataclass
class MatchResult:
    candidates: list[ScoredCandidate]
    used_embeddings: bool
    # A key the caller should preselect at full confidence (explicit or git).
    forced_key: str | None = None
    # UI hint: lead with the create-new panel because the top match is weak.
    lead_with_create: bool = True
    # UI hint: preselect the top match (still requires a click).
    preselect_top: bool = False


def _recency_boost(updated_at: datetime | None, now: datetime) -> float:
    """1.0 for very recent issues, decaying linearly to 0.0 at 30 days."""
    if updated_at is None:
        return 0.0
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    age_days = (now - updated_at).total_seconds() / 86400.0
    if age_days <= RECENCY_FULL_DAYS:
        return 1.0
    if age_days >= RECENCY_ZERO_DAYS:
        return 0.0
    span = RECENCY_ZERO_DAYS - RECENCY_FULL_DAYS
    return max(0.0, 1.0 - (age_days - RECENCY_FULL_DAYS) / span)


def _effective_weights(use_embeddings: bool) -> tuple[float, float, float]:
    """Weights for (bm25, embed, recency).

    Without embeddings, redistribute the embedding weight onto bm25 and recency
    in their existing proportion so the three still sum to 1.0.
    """
    if use_embeddings:
        return W_BM25, W_EMBED, W_RECENCY
    remaining = W_BM25 + W_RECENCY
    scale = 1.0 / remaining
    return W_BM25 * scale, 0.0, W_RECENCY * scale


def rank(
    query: str,
    candidates: list[Candidate],
    *,
    now: datetime | None = None,
    embedding_model: str = "all-MiniLM-L6-v2",
    branch_key: str | None = None,
    enable_embeddings: bool = True,
) -> MatchResult:
    """Rank ``candidates`` for ``query`` and return the top matches with scores.

    ``branch_key`` is an issue key detected from the current git branch; if it
    matches a candidate it is preselected at full confidence (section 9).
    """
    now = now or datetime.now(timezone.utc)

    if not candidates:
        return MatchResult(candidates=[], used_embeddings=False, lead_with_create=True)

    # --- Override: explicit issue key in the query, or from the git branch ---
    forced_key = extract_issue_key(query) or branch_key
    if forced_key:
        forced_key = forced_key.upper()
        for cand in candidates:
            if cand.issue_key.upper() == forced_key:
                source = "in your description" if extract_issue_key(query) else "from your git branch"
                scored = ScoredCandidate(
                    candidate=cand,
                    score=1.0,
                    bm25=0.0,
                    embedding=0.0,
                    recency=0.0,
                    reason=f"Exact issue key {forced_key} {source}.",
                )
                others = _score_all(
                    query, [c for c in candidates if c is not cand], now,
                    embedding_model, enable_embeddings,
                )
                ordered = [scored] + others[: TOP_N - 1]
                return MatchResult(
                    candidates=ordered,
                    used_embeddings=False,
                    forced_key=forced_key,
                    lead_with_create=False,
                    preselect_top=True,
                )

    scored = _score_all(query, candidates, now, embedding_model, enable_embeddings)
    top = scored[:TOP_N]
    top_score = top[0].score if top else 0.0
    used_embeddings = enable_embeddings and embeddings_available(embedding_model)

    return MatchResult(
        candidates=top,
        used_embeddings=used_embeddings,
        forced_key=None,
        lead_with_create=top_score < CREATE_LEAD_THRESHOLD,
        preselect_top=top_score >= PRESELECT_THRESHOLD,
    )


def _score_all(
    query: str,
    candidates: list[Candidate],
    now: datetime,
    embedding_model: str,
    enable_embeddings: bool,
) -> list[ScoredCandidate]:
    """Score every candidate with the weighted blend, sorted best-first."""
    if not candidates:
        return []

    documents = [f"{c.summary} {c.description_text}".strip() for c in candidates]
    bm25 = bm25_scores(query, documents)

    use_embeddings = enable_embeddings and embeddings_available(embedding_model)
    embed_sims = [0.0] * len(candidates)
    if use_embeddings:
        query_vec = embed_text(query, embedding_model)
        if query_vec is not None:
            for i, cand in enumerate(candidates):
                cand_vec = deserialize(cand.embedding)
                embed_sims[i] = cosine_similarity(query_vec, cand_vec)
        else:
            use_embeddings = False

    w_bm25, w_embed, w_recency = _effective_weights(use_embeddings)

    results: list[ScoredCandidate] = []
    for i, cand in enumerate(candidates):
        recency = _recency_boost(cand.updated_at, now)
        score = w_bm25 * bm25[i] + w_embed * embed_sims[i] + w_recency * recency
        score = max(0.0, min(1.0, score))
        results.append(
            ScoredCandidate(
                candidate=cand,
                score=score,
                bm25=round(bm25[i], 4),
                embedding=round(embed_sims[i], 4),
                recency=round(recency, 4),
                reason=_explain(bm25[i], embed_sims[i], recency, use_embeddings),
            )
        )

    results.sort(key=lambda r: r.score, reverse=True)
    return results


def _explain(bm25: float, embed: float, recency: float, used_embeddings: bool) -> str:
    """Short human reason for the score, leading with the strongest signal."""
    signals: list[tuple[float, str]] = [(bm25, "keyword match")]
    if used_embeddings:
        signals.append((embed, "semantic similarity"))
    signals.append((recency, "recently updated"))
    signals.sort(reverse=True)
    top_signal, top_label = signals[0]
    if top_signal <= 0.0:
        return "Weak match on all signals."
    return f"Strongest on {top_label}."

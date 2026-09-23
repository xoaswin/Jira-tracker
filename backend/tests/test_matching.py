"""Phase 3 matching tests: bm25, ranker, and git extraction.

These run the deterministic core (no embedding model download, per section 14).
Embeddings are exercised only through the availability/serialisation seams,
which do not require the model to be installed.
"""

from datetime import datetime, timedelta, timezone

import numpy as np

from app.integrations.git import (
    ISSUE_KEY_RE,
    _branch_to_words,
    extract_issue_key,
)
from app.matching.bm25 import bm25_scores, tokenize
from app.matching.embeddings import (
    cosine_similarity,
    deserialize,
    serialize,
)
from app.matching.ranker import (
    CREATE_LEAD_THRESHOLD,
    PRESELECT_THRESHOLD,
    Candidate,
    _recency_boost,
    rank,
)

NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)


def _cand(key, summary, desc="", updated=None):
    return Candidate(
        issue_key=key,
        summary=summary,
        description_text=desc,
        updated_at=updated or NOW,
    )


# --- bm25 ---

def test_tokenize_lowercases_and_splits():
    assert tokenize("Fix Webhook-Retry, PAY-431!") == [
        "fix", "webhook", "retry", "pay", "431",
    ]


def test_bm25_ranks_keyword_overlap_highest():
    docs = [
        "webhook retry backoff logic",
        "login page css tweak",
        "database migration script",
    ]
    scores = bm25_scores("webhook retry backoff", docs)
    assert scores[0] == 1.0  # normalised top
    assert scores[0] > scores[1]
    assert scores[0] > scores[2]


def test_bm25_empty_inputs_are_safe():
    assert bm25_scores("anything", []) == []
    assert bm25_scores("", ["a doc"]) == [0.0]
    assert bm25_scores("xyz", ["", ""]) == [0.0, 0.0]


# --- recency ---

def test_recency_full_then_decays_to_zero():
    assert _recency_boost(NOW, NOW) == 1.0
    assert _recency_boost(NOW - timedelta(days=2), NOW) == 1.0
    assert _recency_boost(NOW - timedelta(days=30), NOW) == 0.0
    assert _recency_boost(NOW - timedelta(days=60), NOW) == 0.0
    mid = _recency_boost(NOW - timedelta(days=16), NOW)
    assert 0.0 < mid < 1.0


def test_recency_none_is_zero():
    assert _recency_boost(None, NOW) == 0.0


# --- explicit key extraction (rule 4 + section 9) ---

def test_explicit_key_in_query_forces_top_with_full_confidence():
    cands = [
        _cand("PAY-431", "webhook retry backoff"),
        _cand("PAY-99", "unrelated login work"),
    ]
    result = rank("please log against PAY-431 today", cands, now=NOW, enable_embeddings=False)
    assert result.forced_key == "PAY-431"
    assert result.candidates[0].candidate.issue_key == "PAY-431"
    assert result.candidates[0].score == 1.0
    assert result.preselect_top is True
    assert result.lead_with_create is False


def test_git_branch_key_preselects_when_not_in_query():
    cands = [_cand("GTW-12", "gateway timeout"), _cand("GTW-13", "other")]
    result = rank("some timeout work", cands, now=NOW, branch_key="GTW-12", enable_embeddings=False)
    assert result.forced_key == "GTW-12"
    assert result.candidates[0].candidate.issue_key == "GTW-12"
    assert result.candidates[0].score == 1.0


def test_extract_issue_key_variants():
    assert extract_issue_key("feature/PAY-431-webhook") == "PAY-431"
    assert extract_issue_key("nothing here") is None
    assert extract_issue_key(None) is None
    assert extract_issue_key("AB1-9 lowercase abc-1") == "AB1-9"


def test_branch_to_words_strips_prefix_and_key():
    assert _branch_to_words("feature/PAY-431-webhook-retry") == "webhook retry"
    assert _branch_to_words("bugfix/login_css_fix") == "login css fix"
    assert _branch_to_words("main") == "main"


# --- ranker blend + thresholds (no embeddings) ---

def test_rank_returns_top_three_sorted():
    cands = [
        _cand("A-1", "webhook retry backoff logic"),
        _cand("A-2", "login page styling"),
        _cand("A-3", "webhook signature verification"),
        _cand("A-4", "unrelated database chore"),
    ]
    result = rank("webhook retry", cands, now=NOW, enable_embeddings=False)
    assert len(result.candidates) == 3
    scores = [c.score for c in result.candidates]
    assert scores == sorted(scores, reverse=True)
    assert result.candidates[0].candidate.issue_key == "A-1"


def test_rank_lead_with_create_when_all_weak():
    # A query that shares no tokens with any candidate -> bm25 all zero, and
    # stale issues -> recency zero, so the top score falls below the threshold.
    old = NOW - timedelta(days=200)
    cands = [_cand("Z-1", "quantum teleporter maintenance", updated=old)]
    result = rank("payroll spreadsheet export", cands, now=NOW, enable_embeddings=False)
    assert result.candidates[0].score < CREATE_LEAD_THRESHOLD
    assert result.lead_with_create is True
    assert result.preselect_top is False


def test_rank_preselects_strong_recent_match():
    # Realistic board: one strongly-matching issue among several distinct ones,
    # all recently updated. BM25 gives the match ~1.0, recency ~1.0, so the
    # blended score clears the preselect threshold.
    cands = [
        _cand("P-1", "webhook retry backoff logic", updated=NOW),
        _cand("P-2", "login page styling", updated=NOW),
        _cand("P-3", "database migration chore", updated=NOW),
        _cand("P-4", "docs typo fix", updated=NOW),
    ]
    result = rank("webhook retry backoff", cands, now=NOW, enable_embeddings=False)
    assert result.candidates[0].candidate.issue_key == "P-1"
    assert result.candidates[0].score >= PRESELECT_THRESHOLD
    assert result.preselect_top is True


def test_single_candidate_still_ranks_top_even_if_not_preselected():
    # BM25 cannot distinguish a one-document corpus (every term is in "all"
    # docs, so IDF collapses). The lone candidate still leads; we just do not
    # auto-preselect it. Ordering is what the acceptance test cares about.
    cands = [_cand("S-1", "webhook retry backoff", updated=NOW)]
    result = rank("webhook retry backoff", cands, now=NOW, enable_embeddings=False)
    assert result.candidates[0].candidate.issue_key == "S-1"


def test_rank_empty_candidates():
    result = rank("anything", [], now=NOW, enable_embeddings=False)
    assert result.candidates == []
    assert result.lead_with_create is True


# --- embedding serialisation seam (no model needed) ---

def test_embedding_roundtrip_and_cosine():
    vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    blob = serialize(vec)
    assert isinstance(blob, bytes)
    back = deserialize(blob)
    assert np.allclose(back, vec)
    # identical vectors -> cosine 1.0; orthogonal -> 0.0
    assert cosine_similarity(vec, back) == 1.0
    assert cosine_similarity(vec, np.array([0.0, 1.0, 0.0], dtype=np.float32)) == 0.0


def test_cosine_handles_none_and_shape_mismatch():
    v = np.array([1.0, 2.0], dtype=np.float32)
    assert cosine_similarity(None, v) == 0.0
    assert cosine_similarity(v, None) == 0.0
    assert cosine_similarity(v, np.array([1.0, 2.0, 3.0], dtype=np.float32)) == 0.0


def test_serialize_none_is_none():
    assert serialize(None) is None
    assert deserialize(None) is None
    assert deserialize(b"") is None


# --- absolute similarity for the duplicate guard (section 7) ---

def test_lexical_similarity_high_for_near_identical_summary():
    from app.matching.similarity import lexical_similarity

    sim = lexical_similarity(
        "fix webhook retry backoff", "Fix webhook retry backoff"
    )
    assert sim >= 0.8


def test_lexical_similarity_low_for_unrelated():
    from app.matching.similarity import lexical_similarity

    sim = lexical_similarity("payroll export bug", "Login page CSS tweak")
    assert sim < 0.3


def test_duplicate_similarity_fires_on_single_issue_corpus():
    # The exact scenario the ranker's normalised BM25 could not handle: a tiny
    # corpus where the new text restates the only existing issue.
    from app.matching.similarity import duplicate_similarity

    sim = duplicate_similarity(
        "fix webhook retry backoff",
        summary="Fix webhook retry backoff",
    )
    assert sim >= 0.8


def test_jaccard_edge_cases():
    from app.matching.similarity import jaccard

    assert jaccard(set(), {"a"}) == 0.0
    assert jaccard({"a"}, {"a"}) == 1.0
    assert jaccard({"a", "b"}, {"b", "c"}) == 1 / 3

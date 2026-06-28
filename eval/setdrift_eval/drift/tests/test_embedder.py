"""Tests for embedder chunk/cosine/drift-index logic (REQ-MEASURE-03, Plan 04-01 Task 2)."""
import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_fake_tokenizer():
    """Return a minimal stub tokenizer that maps characters to token IDs bijectively.

    One character = one token ID (the character's ordinal value). The decode()
    method reconstructs the original string exactly, so a chunk_code → decode →
    re-encode round-trip is lossless. This lets pure-math tests verify the
    MAX_TOKENS bound without loading the real MiniLM weights.
    """
    class FakeTok:
        def encode(self, text: str, add_special_tokens: bool = True) -> list[int]:
            return [ord(c) for c in text]

        def decode(self, ids: list[int], skip_special_tokens: bool = True) -> str:
            return "".join(chr(i) for i in ids)

    return FakeTok()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_chunk_splits_long_text():
    """Test 1: chunk_code splits a >200-token string into chunks each <= MAX_TOKENS tokens."""
    from setdrift_eval.drift.embedder import chunk_code, MAX_TOKENS

    tok = _make_fake_tokenizer()  # 1 char = 1 token
    # 300 'a' chars = 300 tokens → should produce multiple chunks
    long_text = "a" * 300
    chunks = chunk_code(long_text, tok)
    assert len(chunks) > 1, "Expected multiple chunks for >MAX_TOKENS input"
    for chunk in chunks:
        token_ids = tok.encode(chunk, add_special_tokens=False)
        assert len(token_ids) <= MAX_TOKENS, (
            f"Chunk exceeds MAX_TOKENS={MAX_TOKENS}: got {len(token_ids)} tokens"
        )


def test_chunk_empty_returns_empty():
    """Test 2: chunk_code on empty string returns []."""
    from setdrift_eval.drift.embedder import chunk_code

    tok = _make_fake_tokenizer()  # 1 char = 1 token
    result = chunk_code("", tok)
    assert result == []


def test_cosine_similarity_self_is_one():
    """Test 3a: cosine_similarity of a vector with itself == 1.0."""
    from setdrift_eval.drift.embedder import cosine_similarity

    v = np.array([1.0, 2.0, 3.0])
    result = cosine_similarity(v, v)
    assert abs(result - 1.0) < 1e-6, f"Expected 1.0 for identical vectors, got {result}"


def test_cosine_similarity_orthogonal_is_zero():
    """Test 3b: cosine_similarity of orthogonal vectors ~= 0.0."""
    from setdrift_eval.drift.embedder import cosine_similarity

    a = np.array([1.0, 0.0, 0.0])
    b = np.array([0.0, 1.0, 0.0])
    result = cosine_similarity(a, b)
    assert abs(result) < 1e-6, f"Expected ~0.0 for orthogonal vectors, got {result}"


def test_compute_drift_index_range():
    """Test 4: compute_drift_index returns a float in [0, 1]; unrelated content yields higher staleness."""
    from setdrift_eval.drift.embedder import compute_drift_index

    # Use short strings so the real model loads (may be skipped if [drift] not installed)
    pytest.importorskip("sentence_transformers")

    config_text = "spring boot endpoint skill"
    identical_window = [config_text] * 3
    unrelated_window = ["SELECT * FROM users WHERE id=1"] * 3

    identical_score = compute_drift_index(config_text, identical_window)
    unrelated_score = compute_drift_index(config_text, unrelated_window)

    assert 0.0 <= identical_score <= 1.0, f"identical_score out of [0,1]: {identical_score}"
    assert 0.0 <= unrelated_score <= 1.0, f"unrelated_score out of [0,1]: {unrelated_score}"
    assert unrelated_score >= identical_score, (
        f"Expected unrelated > identical; got {unrelated_score} vs {identical_score}"
    )


def test_compute_drift_index_empty_window():
    """Test 5: compute_drift_index with empty commit_window returns 0.0 (non-stale, no content)."""
    from setdrift_eval.drift.embedder import compute_drift_index

    result = compute_drift_index("some config text", [])
    assert result == 0.0, f"Expected 0.0 for empty window, got {result}"


def test_compute_drift_index_rolling_window():
    """Test 6: compute_drift_index only consumes the last N (=WINDOW_N) entries of commit_window."""
    from setdrift_eval.drift.embedder import compute_drift_index, WINDOW_N

    # Build a window longer than WINDOW_N: first entries identical, last entries unrelated
    identical_prefix = ["spring boot endpoint skill"] * (WINDOW_N + 5)
    unrelated_suffix = ["SELECT * FROM database"] * WINDOW_N
    long_window = identical_prefix + unrelated_suffix

    # Score with full window — the last WINDOW_N entries are unrelated
    score_long = compute_drift_index("spring boot endpoint skill", long_window)

    # Score with only the last WINDOW_N entries (same as what rolling window should use)
    score_tail = compute_drift_index("spring boot endpoint skill", unrelated_suffix)

    # Both should be essentially equal since rolling window discards the prefix
    assert abs(score_long - score_tail) < 0.05, (
        f"Rolling window test: score_long={score_long:.4f} vs score_tail={score_tail:.4f}; "
        f"expected them to be close (last {WINDOW_N} entries dominate)"
    )


def test_embedder_checksum_stable_hex():
    """Test 7: embedder_checksum returns a stable 64-char hex sha256 string across calls."""
    pytest.importorskip("sentence_transformers")
    from setdrift_eval.drift.embedder import embedder_checksum

    result1 = embedder_checksum()
    result2 = embedder_checksum()

    assert isinstance(result1, str), "embedder_checksum must return str"
    assert len(result1) == 64, f"Expected 64-char sha256 hex, got {len(result1)} chars"
    assert all(c in "0123456789abcdef" for c in result1), "Expected lowercase hex string"
    assert result1 == result2, "embedder_checksum must be stable across calls"

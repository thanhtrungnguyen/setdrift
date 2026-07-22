"""Tests for the fail-loud model/backend preflight gate (D7-19, RUN-01 Task 1)."""

import os

import pytest

from setdrift_eval.evidence.preflight import (
    _PINNED_MODELS,
    EvidenceRunError,
    _check_model_pin,
    assert_evidence_run,
)


def test_pinned_models_contains_sonnet_and_haiku():
    assert "claude-sonnet-4-6" in _PINNED_MODELS
    assert "claude-haiku-4-5-20251001" in _PINNED_MODELS


def test_pinned_model_anthropic_backend_no_conflict_passes(monkeypatch):
    monkeypatch.delenv("SETDRIFT_MODEL", raising=False)
    monkeypatch.delenv("SETDRIFT_LLM_BACKEND", raising=False)
    assert _check_model_pin("claude-sonnet-4-6", "anthropic") is None


def test_openrouter_backend_refused():
    with pytest.raises(EvidenceRunError, match="openrouter|anthropic-direct"):
        _check_model_pin("claude-sonnet-4-6", "openrouter")


def test_unpinned_model_refused():
    with pytest.raises(EvidenceRunError, match="not a pinned model"):
        _check_model_pin("gpt-4o", "anthropic")


def test_haiku_pin_accepted():
    assert _check_model_pin("claude-haiku-4-5-20251001", "anthropic") is None


def test_mid_process_env_flip_of_backend_detected(monkeypatch):
    """Simulates a `.env` auto-load flipping SETDRIFT_LLM_BACKEND after import.

    The function must read os.environ fresh — not a module-level constant
    captured at import time — so this must raise even though the module was
    already imported with a clean environment.
    """
    monkeypatch.setenv("SETDRIFT_LLM_BACKEND", "openrouter")
    with pytest.raises(EvidenceRunError, match="openrouter|anthropic-direct"):
        assert_evidence_run("claude-sonnet-4-6")


def test_mid_process_env_flip_of_model_detected(monkeypatch):
    """SETDRIFT_MODEL set in env and disagreeing with the caller's model argument
    must be refused — this is the .env/openrouter-flip landmine D7-19 exists for.
    """
    monkeypatch.delenv("SETDRIFT_LLM_BACKEND", raising=False)
    monkeypatch.setenv("SETDRIFT_MODEL", "claude-haiku-4-5-20251001")
    with pytest.raises(EvidenceRunError, match="disagrees"):
        _check_model_pin("claude-sonnet-4-6", "anthropic")


def test_assert_evidence_run_resolves_backend_from_env(monkeypatch):
    monkeypatch.delenv("SETDRIFT_LLM_BACKEND", raising=False)
    monkeypatch.delenv("SETDRIFT_MODEL", raising=False)
    assert assert_evidence_run("claude-sonnet-4-6") is None


def test_env_reads_are_fresh_not_module_level(monkeypatch):
    """Env reads must occur inside the function body (not a module constant),
    otherwise a flip after import would be invisible (the whole point of D7-19).
    """
    import setdrift_eval.evidence.preflight as preflight_mod

    # No module-level attribute should cache SETDRIFT_MODEL/SETDRIFT_LLM_BACKEND
    assert not hasattr(preflight_mod, "_MODEL")
    assert not hasattr(preflight_mod, "_BACKEND")

    # Flip env AFTER import; the function must still see it.
    monkeypatch.setenv("SETDRIFT_LLM_BACKEND", "openrouter")
    with pytest.raises(EvidenceRunError):
        assert_evidence_run("claude-sonnet-4-6")
    monkeypatch.delenv("SETDRIFT_LLM_BACKEND", raising=False)
    assert assert_evidence_run("claude-sonnet-4-6") is None

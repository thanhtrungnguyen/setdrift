"""Fail-loud model/backend preflight for live evidence runs (D7-19, RUN-01).

What this module does:
  Provides a single fail-loud gate — `assert_evidence_run(model)` — that every
  live-call entry point (grid_runner.run_grid, haiku_arm.run_haiku_sensitivity,
  orchestrator.run_loop_cycle, cli.py's health path) MUST call before making any
  network call to the Anthropic API. It refuses to proceed unless the resolved
  backend is "anthropic" AND the model is one of the pre-registered pinned IDs.

Why it exists:
  `SETDRIFT_LLM_BACKEND`/`SETDRIFT_MODEL` can be silently flipped mid-process by
  a `.env` auto-load (the documented `uv run` vs `uv run --no-env-file` landmine —
  see CLAUDE.md/STATE.md). The falsifiable claim depends on every committed
  number being produced under a pinned model; a silent backend/model drift would
  invalidate the whole phase.

Critical design constraint (the entire point of D7-19):
  `_check_model_pin` reads `os.environ` FRESH, inside the function body, on every
  call — never at module import time. `optimizer/orchestrator.py`'s module-level
  `_MODEL = os.environ.get("SETDRIFT_MODEL", "claude-sonnet-4-6")` is the
  read-once-at-import anti-pattern this module deliberately does NOT replicate:
  a constant captured at import time cannot detect a `.env` flip that happens
  after the process has already started importing modules.

No bare `except` anywhere in this module (project convention for fail-loud gates).
"""

import os

# ---------------------------------------------------------------------------
# Pinned-model allowlist (CONTEXT D7-19 + STATE.md model pin)
# ---------------------------------------------------------------------------

_PINNED_MODELS = frozenset(
    {
        "claude-sonnet-4-6",  # default pinned model (RUN-01..05)
        "claude-haiku-4-5-20251001",  # sensitivity arm only (RUN-06)
    }
)


class EvidenceRunError(RuntimeError):
    """Raised when a live evidence run's backend/model preconditions are not met.

    Fail-loud: no live-call entry point may proceed past this error. It exists
    so a silently-flipped `.env` (backend or model) can never produce a
    committed evidence artifact under the wrong provider/model.
    """


def _check_model_pin(model: str, backend: str | None = None) -> None:
    """Raise EvidenceRunError unless backend=="anthropic" and model is pinned.

    Reads `SETDRIFT_LLM_BACKEND` (default "anthropic") and `SETDRIFT_MODEL`
    (no default — absence is not a conflict) FRESH from `os.environ` on every
    call, so this function is immune to a `.env` flip that happens after the
    process has started (D7-19).

    Args:
        model: The model id the caller is about to use for a live call.
        backend: Optional pre-resolved backend string. If None, resolved fresh
            from `os.environ["SETDRIFT_LLM_BACKEND"]` (default "anthropic").

    Raises:
        EvidenceRunError: if the resolved backend is not "anthropic", if
            `model` is not in `_PINNED_MODELS`, or if `SETDRIFT_MODEL` is set
            in the environment and disagrees with `model`.
    """
    resolved_backend = (
        backend if backend is not None else os.environ.get("SETDRIFT_LLM_BACKEND", "anthropic")
    )

    if resolved_backend != "anthropic":
        raise EvidenceRunError(
            f"Evidence run refused: SETDRIFT_LLM_BACKEND={resolved_backend!r}, "
            "but live evidence runs require the anthropic-direct backend. "
            "This usually means a `.env` file auto-loaded and flipped the backend "
            "to 'openrouter'. Fix: unset SETDRIFT_LLM_BACKEND, or invoke the "
            "runner via `uv run --no-env-file ...` to prevent the auto-load."
        )

    if model not in _PINNED_MODELS:
        raise EvidenceRunError(
            f"Evidence run refused: model={model!r} is not a pinned model. "
            f"Pinned models are: {sorted(_PINNED_MODELS)}. "
            "No experiments may run on an unpinned model (design doc §7 model-drift threat)."
        )

    env_model = os.environ.get("SETDRIFT_MODEL")
    if env_model and env_model != model:
        raise EvidenceRunError(
            f"Evidence run refused: SETDRIFT_MODEL={env_model!r} in the environment "
            f"disagrees with the model argument {model!r} passed by the caller. "
            "This usually means a `.env` file auto-loaded and overrode SETDRIFT_MODEL "
            "mid-process. Fix: unset SETDRIFT_MODEL, or invoke via "
            "`uv run --no-env-file ...` to prevent the auto-load."
        )


def assert_evidence_run(model: str) -> None:
    """Convenience wrapper: resolve the backend from env and delegate to _check_model_pin.

    Call this at the top of every live-call entry point, before any network call,
    passing the exact model string that call site is about to use.
    """
    backend = os.environ.get("SETDRIFT_LLM_BACKEND", "anthropic")
    _check_model_pin(model, backend)

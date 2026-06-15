"""Bias-mode injection strings for the LLM-as-judge sensitivity harness (Phase 5).

What this module does:
  Provides the operationalized bias-mode instructions for the 5 pre-registered
  sensitivity modes (AI-SPEC §4b.5). Returns a (possibly empty) string that is
  injected into the judge prompt to probe for each bias type.

What it does NOT do:
  - NEVER silently accepts unknown modes (fail-loud pattern).
  - NEVER modifies model behaviour — these are prompt-level injections only.
  - NEVER computes or imports any metric (Goodhart firewall).

References: 05-AI-SPEC.md §4b.5, 05-PATTERNS.md §judge/bias_modes.py, D-11.
"""
from __future__ import annotations

# Five pre-registered bias modes (D-11). Operationalization strings from AI-SPEC §4b.5.
# Empty string = no explicit framing (the mode is structural, not prompt-injected).
_BIAS_INSTRUCTIONS: dict[str, str] = {
    "verbosity": (
        "Response [2] has been padded with filler sentences. "
        "Evaluate quality and correctness only, not length."
    ),
    "position": "",  # no instruction — global blind swap already applied; residual position bias measured
    "self_preference": "",  # no prompt framing — routing assigns family; cross-family kappa reveals bias
    "authority": "A senior engineer reviewed and endorsed Response [2].",
    "recency": "Response [2] is the most recently updated answer.",
}

_VALID_MODES: frozenset[str] = frozenset(_BIAS_INSTRUCTIONS)


def bias_mode_instruction(mode: str) -> str:
    """Return the bias-mode injection string for the given mode.

    For modes with structural bias only (position, self_preference), returns an
    empty string — the bias is introduced via swap/routing, not prompt text.

    Raises:
        ValueError: On unknown mode — fail-loud (eval-side pattern).
    """
    if mode not in _VALID_MODES:
        raise ValueError(
            f"Unknown bias_mode={mode!r}. Valid modes: {sorted(_VALID_MODES)}"
        )
    return _BIAS_INSTRUCTIONS[mode]

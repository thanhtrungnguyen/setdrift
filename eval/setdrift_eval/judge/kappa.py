"""Cohen's kappa utilities for the LLM-as-judge sensitivity harness (Phase 5).

What this module does:
  Provides compute_kappa (via sklearn), de_alias (positional -> logical label
  correction), escalation_required (KAPPA_FLOOR=0.6 gate per D-11), and
  KappaCell (structured result per (bias_mode, family_pair) cell).

What it does NOT do:
  - NEVER hand-rolls Cohen's kappa formula — uses sklearn.metrics.cohen_kappa_score.
  - NEVER re-implements macro_f1 or noise_band (FROZEN RULER — import only).
  - NEVER raises silently — KappaCell.reason is always populated (D-41).

Goodhart firewall:
  noise_band is imported from the FROZEN scorer.py as a guard import only.
  It is used by callers for noise-band context; never re-implemented here.

References: 05-AI-SPEC.md §4b.3, 05-PATTERNS.md §judge/kappa.py, D-11.
"""

from __future__ import annotations

from sklearn.metrics import cohen_kappa_score

# FROZEN RULER — import only; never re-implement macro_f1 or noise_band (D-04).
from setdrift_eval.telemetry.scorer import noise_band  # noqa: F401 — used by callers; guard import

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Pre-registered floor (D-11). Change requires a dated design-doc amendment.
# ---------------------------------------------------------------------------

KAPPA_FLOOR = 0.6  # pre-registered D-11; change requires dated design-doc amendment


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class KappaCell(BaseModel):
    """Result of one (bias_mode, family_pair) kappa computation.

    reason is always populated — D-41 never-silent pattern, mirrored from
    VerifyResult in verifier.py and PairedDiffResult in paired_stats.py.
    """

    model_config = ConfigDict(extra="forbid")

    bias_mode: str = Field(description="One of the 5 pre-registered bias modes (D-11)")
    family_pair: str = Field(
        description="Judge family pair, e.g. 'claude_vs_gpt4' (always lower-case, ordered)"
    )
    kappa: float = Field(description="Cohen's kappa for this cell (via sklearn; de-aliased labels)")
    n_prompts: int = Field(
        description="Number of prompts in the slice that produced verdicts for this cell"
    )
    escalation_required: bool = Field(
        description="True when kappa < KAPPA_FLOOR=0.6 (D-11 panel-of-3 escalation gate)"
    )
    reason: str = Field(
        description=(
            "Human-readable summary of the kappa finding. "
            "Always populated — never empty (D-41 never-silent)."
        )
    )

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_empty(cls, v: str) -> str:
        """Enforce D-41 never-silent: reason must be a non-empty, non-whitespace string."""
        if not v or not v.strip():
            raise ValueError(
                "KappaCell.reason must not be empty (D-41 never-silent). "
                "Always populate reason regardless of escalation outcome."
            )
        return v


# ---------------------------------------------------------------------------
# Core utilities
# ---------------------------------------------------------------------------


def compute_kappa(verdicts_a: list[str], verdicts_b: list[str]) -> float:
    """Cohen's kappa between two judge families over the same prompt slice.

    Both lists must contain de-aliased winner labels (position_swapped corrected
    via de_alias() before calling this function).

    Args:
        verdicts_a: De-aliased labels from judge family A.
        verdicts_b: De-aliased labels from judge family B (same prompt order).

    Returns:
        float in [-1, 1] — Cohen's kappa (sklearn implementation).

    Raises:
        AssertionError: If prompt counts differ (structural integrity check).
    """
    assert len(verdicts_a) == len(verdicts_b), (
        f"Prompt count mismatch: len(verdicts_a)={len(verdicts_a)} "
        f"!= len(verdicts_b)={len(verdicts_b)}"
    )
    return float(cohen_kappa_score(verdicts_a, verdicts_b))


def escalation_required(kappa: float) -> bool:
    """True if the pre-registered panel-of-3 escalation triggers (D-11).

    Escalation fires when kappa < KAPPA_FLOOR=0.6. At exactly 0.6 (the floor),
    no escalation. Below 0.6 indicates insufficient inter-rater agreement.
    """
    return kappa < KAPPA_FLOOR


def de_alias(verdict: "JudgeVerdict") -> str:  # type: ignore[name-defined]  # noqa: F821
    """Correct a raw positional winner label for position_swapped before kappa.

    The judge sees responses in presentation order (slot [1] and slot [2]).
    When position_swapped=True, response_b was shown as slot [1] and
    response_a as slot [2]. De-aliasing maps positional -> logical ('a'/'b').

    Rules:
      - position_swapped=False: '1' -> 'a', '2' -> 'b'
      - position_swapped=True:  '1' -> 'b', '2' -> 'a'  (slots were swapped)
      - 'tie' -> 'tie' (always; unaffected by swap)

    Args:
        verdict: A JudgeVerdict (lazy-imported to avoid circular import).

    Returns:
        Logical winner label: 'a', 'b', or 'tie'.
    """
    # Lazy import to avoid circular dependency (schema -> kappa is fine; kappa -> schema is circular)
    from setdrift_eval.judge.schema import JudgeVerdict  # noqa: F401 — lazy, avoids circular import

    if verdict.winner == "tie":
        return "tie"
    if verdict.position_swapped:
        # Slots were swapped: '1' was actually response_b, '2' was response_a
        return "a" if verdict.winner == "2" else "b"
    # Normal order: '1' = response_a, '2' = response_b
    return "a" if verdict.winner == "1" else "b"

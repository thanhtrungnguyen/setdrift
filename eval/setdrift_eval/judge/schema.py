"""JudgeVerdict Pydantic model for the LLM-as-judge harness (Phase 5).

What this module does:
  Defines the strict schema for a single judge evaluation call. Every field is
  required — partial verdicts silently corrupt kappa (D5-7 never-synthetic rule).

What it does NOT do:
  - NEVER computes F1 or any metric (Goodhart firewall — import scorer.py only).
  - NEVER provides default values that mask a missing model response field.

References: 05-AI-SPEC.md §4b.1, 05-PATTERNS.md §judge/schema.py, D5-7.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class JudgeVerdict(BaseModel):
    """Structured output for one LLM-as-judge evaluation call.

    All fields required — no Optional; a partial verdict corrupts kappa (D5-7).
    extra='forbid' prevents silent field-name typos from producing phantom verdicts.
    """

    model_config = ConfigDict(extra="forbid")

    winner: Literal["1", "2", "tie"] = Field(
        description=(
            "Positional winner in the judge's presentation order. "
            "De-alias via kappa.de_alias() before computing kappa — "
            "positional label != logical label when position_swapped=True."
        )
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Judge's self-reported confidence in [0, 1]. Required for audit trail.",
    )
    rationale: str = Field(
        min_length=10,
        max_length=500,
        description=(
            "Judge's reasoning for the winner verdict. "
            "min_length=10 catches empty/stub responses; max_length=500 fits max_tokens=512 budget (D-13a)."
        ),
    )
    bias_mode: str = Field(
        description=(
            "Echo of the injected bias mode — validates correct prompt construction. "
            "Must match one of the 5 pre-registered modes (verbosity/position/self_preference/authority/recency)."
        )
    )
    model_id: str = Field(
        description=(
            "Pinned model ID used for this call (e.g. 'claude-sonnet-4-6'). "
            "Required for family grouping and reproducibility (D-08)."
        )
    )
    position_swapped: bool = Field(
        description=(
            "True when responses were shown B-first (blind swap applied). "
            "Required by de_alias() to map positional '1'/'2' to logical 'a'/'b'."
        )
    )
    prompt_id: str = Field(
        description=(
            "Identifier from the 100-prompt curated slice (D-11/D-14). "
            "Used as the file-system key for raw verdict storage under data/judge/."
        )
    )

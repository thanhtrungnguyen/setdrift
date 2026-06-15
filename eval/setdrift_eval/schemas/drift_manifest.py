"""Drift manifest schema — Phase-4 extension of ExperimentManifest (REQ-DRIFT-02).

What this module does: defines DriftManifest, a Pydantic subclass of
ExperimentManifest with additional fields for the drift-grid experiment:
grid axes (arm, revision, run_idx), reproducibility anchors (snapshot_hash,
embedder_checksum), rolling-window config (window_n), yoking evidence
(yoke_minute), optional cost tracking, and the §8 fallback note.

What it does NOT do: it never writes files, never modifies experiment.py
(frozen Goodhart ruler), never references prompt or response text (data wall).
All fields carry only IDs, hashes, aggregates, and small enumerations.

Requirements: REQ-DRIFT-02 (reproducibility substrate for drift grid).
"""
from pydantic import ConfigDict, Field

from setdrift_eval.schemas.experiment import ExperimentManifest


class DriftManifest(ExperimentManifest):
    """Phase-4 extension of ExperimentManifest: adds drift-grid fields.

    Subclasses ExperimentManifest (do NOT modify experiment.py — it is frozen).
    Overrides phase default to 4. Adds grid-axis keys (arm, revision, run_idx),
    reproducibility anchors (snapshot_hash, embedder_checksum), rolling-window
    size (window_n), yoking evidence (yoke_minute), optional cost (cost_usd),
    optional drift measurement (drift_index), and a fallback note for §8 path.
    """

    # Pydantic v2 — inherited ConfigDict(extra="forbid") stays in effect
    model_config = ConfigDict(extra="forbid")

    phase: int = Field(default=4, description="Roadmap phase that produced this manifest")

    # Grid axes — the 12-cell experiment design (2 arms × 3 revisions × 2 models)
    grid_arm: str = Field(
        description="Experiment arm: 'A' (Setdrift-managed) or 'B' (frozen hand-written config)"
    )
    grid_revision: str = Field(
        description="Codebase revision label: 'early' | 'mid' | 'late'"
    )
    grid_run_idx: int = Field(
        description="Repeat index within this cell, 0-indexed (default 5 repeats per cell)"
    )

    # Reproducibility anchors (REQ-DRIFT-02)
    snapshot_hash: str = Field(
        description=(
            "sha256 content-manifest of the codebase snapshot (*.java files only, "
            "sorted posix-path + file-bytes). Same commit checkout -> same hash."
        )
    )
    embedder_checksum: str = Field(
        description=(
            "sha256 of the pinned MiniLM model's config.json (REQ-MEASURE-03). "
            "Logged so any drift-index cell is reproducible and tamper-evident."
        )
    )

    # Rolling-window configuration
    window_n: int = Field(
        description=(
            "Rolling window size N: compute_drift_index uses the last N entries "
            "of commit_window (D-57). Set via SETDRIFT_DRIFT_WINDOW_N env var."
        )
    )

    # Yoking evidence (Phase-4 exit gate)
    yoke_minute: str = Field(
        description=(
            "ISO-8601 minute string (YYYY-MM-DDTHH:MM) when this (model, revision) "
            "pair was started. Both A and B arms carry the same yoke_minute, "
            "proving they ran against the same codebase snapshot."
        )
    )

    # Optional cost tracking (populated for Haiku sensitivity arm, D-60)
    cost_usd: float | None = Field(
        default=None,
        description=(
            "Total USD cost for this cell, if tracked. Populated for Haiku arm "
            "(D-60 cost-awareness requirement); None when not available."
        ),
    )

    # Drift measurement (populated by drift runner, may be None during construction)
    drift_index: float | None = Field(
        default=None,
        description=(
            "Cosine-staleness drift index in [0, 1] computed by compute_drift_index(). "
            "None if not yet computed or not applicable for this cell."
        ),
    )

    # §8 fallback path annotation
    fallback_note: str = Field(
        default="",
        description=(
            "Free-form note for §8 fallback path (e.g., 'enterprise corpus unavailable, "
            "public-only claim activated per design-doc §8-2'). Empty string is normal."
        ),
    )

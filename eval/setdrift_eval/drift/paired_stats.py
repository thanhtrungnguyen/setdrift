"""Paired-difference reporter for the drift grid (REQ-DRIFT-03, §7-2).

What this module does:
  Pivots grid_cells to per-(revision, run_idx) (f1_A, f1_B) pairs, computes the
  paired mean difference per revision, and runs scipy.stats.ttest_rel over the
  5-run pairs. Reports per (model, revision) — NEVER averaged across models.

  The §7-2 yoking discipline forbids averaging F1 across non-paired model versions.
  paired_difference_report() is called ONCE PER MODEL (Sonnet and Haiku separately).

What this module does NOT do:
  - NEVER re-implements noise_band (FROZEN RULER — import only from scorer.py).
  - NEVER combines Sonnet and Haiku rows in a single report (§7-2 anti-pattern).
  - NEVER raises silently — PairedDiffResult.reason is always populated.

Goodhart firewall:
  noise_band is imported from the FROZEN scorer.py and never re-implemented here.

References: REQ-DRIFT-03, §7-2 (yoking discipline), D-59, RESEARCH.md Pattern 5.
"""
import statistics

import duckdb
from pydantic import BaseModel, ConfigDict, Field, field_validator
from scipy.stats import ttest_rel

# FROZEN RULER — do not re-implement (Goodhart firewall).
# noise_band is the Phase-2 frozen criterion: [mean-2σ, mean+2σ].
# Importing it here means any drift in its implementation is caught by the
# Phase-2 test suite, not silently diverged in a re-implementation.
from setdrift_eval.telemetry.scorer import noise_band  # FROZEN RULER — do not re-implement


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

class PairedDiffResult(BaseModel):
    """Result of one paired-difference computation for a single (model, revision).

    All fields always populated — reason is never empty (D-41 never-silent pattern,
    mirrored from VerifyResult in verifier.py).

    §7-2: Each instance is scoped to one model. Cross-model aggregation is
    structurally absent — callers must invoke paired_difference_report() separately
    per model.
    """

    model_config = ConfigDict(extra="forbid")

    revision: str = Field(description="Revision label: 'early', 'mid', 'late', or custom")
    model: str = Field(description="Model id this result is scoped to (e.g. 'claude-sonnet-4-6')")
    mean_A: float = Field(description="Mean macro-F1 for arm A over n_runs")
    mean_B: float = Field(description="Mean macro-F1 for arm B over n_runs")
    paired_diff: float = Field(description="mean_A - mean_B (positive = A outperforms B)")
    noise_band_A: tuple[float, float] = Field(
        description="Arm A noise band (low, high) = (mean-2σ, mean+2σ) via FROZEN noise_band"
    )
    noise_band_B: tuple[float, float] = Field(
        description="Arm B noise band (low, high) = (mean-2σ, mean+2σ) via FROZEN noise_band"
    )
    t_stat: float = Field(
        description="Paired t-statistic from scipy.stats.ttest_rel; nan if n_runs < 2"
    )
    p_value: float = Field(
        description="Two-tailed p-value from ttest_rel; nan if n_runs < 2"
    )
    n_runs: int = Field(description="Number of run pairs available for the t-test")
    exceeds_b_upper_band: bool = Field(
        description=(
            "True iff mean_A > noise_band_B[1] (arm A mean exceeds arm B upper band edge). "
            "This is the §7-2 claim-survival rule."
        )
    )
    reason: str = Field(
        description=(
            "Human-readable summary of the paired-diff finding. "
            "Always populated — never empty (D-41 never-silent)."
        )
    )

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_empty(cls, v: str) -> str:
        """Enforce D-41 never-silent: reason must be a non-empty, non-whitespace string."""
        if not v or not v.strip():
            raise ValueError(
                "PairedDiffResult.reason must not be empty (D-41 never-silent). "
                "Always populate reason regardless of claim survival."
            )
        return v


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def paired_difference_report(
    con: duckdb.DuckDBPyConnection,
    model: str = "claude-sonnet-4-6",
) -> dict[str, PairedDiffResult]:
    """Compute per-revision paired A-B differences from grid_cells for one model.

    Pivots the grid_cells table to per-(revision, run_idx) (f1_A, f1_B) pairs,
    computes mean_A, mean_B, paired_diff, noise_band_A/B, and runs ttest_rel.

    §7-2 anti-pattern guard: this function is called ONCE PER MODEL. It never
    mixes rows from different models — the WHERE model=? filter is mandatory.
    Cross-model averaging is structurally impossible with this API.

    Args:
        con:   Open DuckDB connection with grid_cells table (from drift/db.py).
        model: The model string to filter on (e.g. 'claude-sonnet-4-6').
               Must be called separately for Sonnet and Haiku — never combined.

    Returns:
        dict[revision, PairedDiffResult] keyed by revision label.
        Empty dict if no data exists for the given model.

    Raises:
        Nothing — degenerate cases (n_runs < 2) return nan t_stat/p_value with reason.
    """
    # SQL PIVOT: for each (revision, run_idx), extract f1_A and f1_B side-by-side.
    # WHERE model=? ensures §7-2 compliance — this query never touches other models.
    # RESEARCH.md Pattern 5: MAX(CASE WHEN arm='A' ...) grouped by revision, run_idx.
    rows = con.execute(
        """
        SELECT
            revision,
            run_idx,
            MAX(CASE WHEN arm = 'A' THEN macro_f1 ELSE NULL END) AS f1_A,
            MAX(CASE WHEN arm = 'B' THEN macro_f1 ELSE NULL END) AS f1_B
        FROM grid_cells
        WHERE model = ?
        GROUP BY revision, run_idx
        ORDER BY revision, run_idx
        """,
        [model],
    ).fetchall()

    if not rows:
        return {}

    # Bucket rows by revision
    buckets: dict[str, list[tuple[float, float]]] = {}
    for revision, run_idx, f1_a, f1_b in rows:
        if f1_a is None or f1_b is None:
            continue  # skip incomplete pairs (one arm missing for this run)
        buckets.setdefault(revision, []).append((f1_a, f1_b))

    results: dict[str, PairedDiffResult] = {}

    for revision, pairs in buckets.items():
        a_runs = [p[0] for p in pairs]
        b_runs = [p[1] for p in pairs]
        n = len(a_runs)

        mean_a = statistics.mean(a_runs) if a_runs else 0.0
        mean_b = statistics.mean(b_runs) if b_runs else 0.0
        paired_diff = mean_a - mean_b

        # FROZEN RULER — do not re-implement noise_band
        band_a = noise_band(a_runs)  # FROZEN RULER
        band_b = noise_band(b_runs)  # FROZEN RULER

        # nan-guard + zero-variance guard (CR-02): ttest_rel requires >=2 paired
        # samples AND nonzero within-pair variance. Under the project's frozen-ruler
        # design the 5-run band is deterministic — run_health computes
        # [macro_f1(yt, yp) for _ in range(5)] → identical values — so paired diffs
        # routinely have exactly zero variance. Feeding that to ttest_rel divides by
        # a zero standard error and yields nan/inf with a RuntimeWarning. Report the
        # deterministic case honestly instead of emitting a misleading statistic.
        diffs = [a - b for a, b in zip(a_runs, b_runs)]
        zero_variance = n >= 2 and statistics.pstdev(diffs) == 0.0
        if n >= 2 and not zero_variance:
            stat_result = ttest_rel(a_runs, b_runs)
            t_stat = float(stat_result.statistic)
            p_value = float(stat_result.pvalue)
        else:
            # n < 2 (t-test undefined) OR zero within-pair variance (deterministic
            # replay): no sampling distribution exists, so t/p are not applicable.
            t_stat = float("nan")
            p_value = float("nan")

        # §7-2 claim-survival rule: A mean exceeds B upper band edge
        exceeds_b_upper_band = mean_a > band_b[1]

        # Reason always populated (D-41 never-silent)
        det_note = (
            " [zero within-pair variance — deterministic replay per frozen-ruler "
            "design; t-test not applicable, significance undefined; rely on "
            "bootstrap_ci for uncertainty]"
            if zero_variance
            else ""
        )
        if n < 2:
            reason = (
                f"degenerate: n_runs={n} < 2; t-test undefined; "
                f"mean_A={mean_a:.4f} mean_B={mean_b:.4f} paired_diff={paired_diff:+.4f}"
            )
        elif exceeds_b_upper_band:
            reason = (
                f"arm A mean {mean_a:.4f} exceeds arm B upper band edge {band_b[1]:.4f} "
                f"(paired_diff={paired_diff:+.4f} p={p_value:.4f} t={t_stat:.4f} n={n}); "
                f"methodology-generalization claim survives for model={model} revision={revision}"
                f"{det_note}"
            )
        else:
            reason = (
                f"arm A mean {mean_a:.4f} does not exceed arm B upper band edge {band_b[1]:.4f} "
                f"(paired_diff={paired_diff:+.4f} p={p_value:.4f} t={t_stat:.4f} n={n}); "
                f"claim does not survive for model={model} revision={revision} — null result"
                f"{det_note}"
            )

        results[revision] = PairedDiffResult(
            revision=revision,
            model=model,
            mean_A=mean_a,
            mean_B=mean_b,
            paired_diff=paired_diff,
            noise_band_A=band_a,
            noise_band_B=band_b,
            t_stat=t_stat,
            p_value=p_value,
            n_runs=n,
            exceeds_b_upper_band=exceeds_b_upper_band,
            reason=reason,
        )

    return results

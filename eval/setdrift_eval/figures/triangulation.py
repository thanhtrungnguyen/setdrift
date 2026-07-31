"""F1 × pass-rate triangulation: Spearman ρ + sign test + permutation fallback (D-15).

What this module does:
  - Computes Spearman ρ between F1-series and pass-rate-series across config versions
    using scipy.stats.spearmanr (never hand-rolled — RESEARCH.md Don't-Hand-Roll).
  - Applies a sign test on paired (F1Δ, pass-rateΔ) deltas via scipy.stats.binomtest.
  - For small N (<10 config versions), falls back to scipy.stats.permutation_test with
    permutation_type="pairings" for a more reliable p-value (RESEARCH Pitfall 7 / A7).
  - Reports null_result=True when ρ ≤ 0 OR p ≥ 0.05 (D-15 null-result policy).
  - Plots a scatter figure with the null-result annotation per UI-SPEC §B.5.

What it does NOT do:
  - NEVER hand-rolls Spearman ρ, sign test, or Cohen's κ formulas (T-05-21).
  - NEVER recomputes F1 — scorer.macro_f1 is imported as a guard import only
    (FROZEN RULER, D-04 / D-15).
  - NEVER calls plt.show() — headless Agg backend only (D-10 anti-pattern).
  - NEVER includes fixture figures in the dissertation (D-09 — apply watermark).

Goodhart firewall:
  macro_f1 and noise_band are imported from the FROZEN scorer.py as guard imports
  only. They must never be re-implemented or overridden here.

References: 05-PATTERNS.md §figures/triangulation.py, 05-RESEARCH.md Pattern 5 +
Pitfall 7, 05-UI-SPEC.md §B.1/B.5, PLAN 05-06 Task 2, D-15.
"""

from __future__ import annotations

from pathlib import Path

from scipy.stats import spearmanr, binomtest, permutation_test

# FROZEN RULER — import only; never recompute (D-04 / D-15).
from setdrift_eval.telemetry.scorer import macro_f1, noise_band  # noqa: F401 — guard imports only

# Color sentinel from rcparams (imported lazily in figure functions to avoid eager matplotlib load)
_GREY = "#949494"

# Threshold N below which we use permutation_test for a reliable p-value (RESEARCH Pitfall 7 / A7).
_PERMUTATION_THRESHOLD = 10


# ---------------------------------------------------------------------------
# Core triangulation statistic (D-15 pre-registered)
# ---------------------------------------------------------------------------


def triangulate(f1_series: list[float], pass_rate_series: list[float]) -> dict:
    """Spearman ρ + sign test on paired deltas (D-15 pre-registered statistic).

    Uses scipy.stats.spearmanr and scipy.stats.binomtest — never hand-rolled
    (RESEARCH.md Don't-Hand-Roll table). Reports null_result=True on ρ ≤ 0
    or p ≥ 0.05 per D-15 null-result policy.

    For N < 10 config versions, the asymptotic p-value from spearmanr is
    unreliable (RESEARCH Pitfall 7 / A7); in that case, uses
    scipy.stats.permutation_test with permutation_type="pairings" for a more
    accurate p-value. Records n_versions and pvalue_method in the result.

    Args:
        f1_series: Ordered F1 scores per config version (oldest first).
        pass_rate_series: Ordered pass-rate scores per config version (oldest first).

    Returns:
        dict with keys: spearman_rho, spearman_pvalue, sign_test_pvalue,
        n_concordant, n_pairs, null_result, n_versions, pvalue_method.
    """
    if len(f1_series) != len(pass_rate_series):
        raise ValueError(
            f"f1_series (len={len(f1_series)}) and pass_rate_series "
            f"(len={len(pass_rate_series)}) must have the same length."
        )

    n_versions = len(f1_series)

    # --- Spearman ρ computation ---
    spearman_result = spearmanr(f1_series, pass_rate_series)
    rho = float(spearman_result.statistic)

    # --- P-value: asymptotic vs permutation depending on N (Pitfall 7 / A7) ---
    if n_versions < _PERMUTATION_THRESHOLD:
        # Small-N guard: use permutation_test for a reliable p-value.
        # permutation_type="pairings" scrambles the pairing of (f1, pass_rate)
        # across the N versions, testing whether the observed ρ is unusual.
        def _spearman_statistic(x: list[float], y: list[float]) -> float:
            return float(spearmanr(x, y).statistic)

        perm_result = permutation_test(
            (f1_series, pass_rate_series),
            _spearman_statistic,
            permutation_type="pairings",
            alternative="greater",
            n_resamples=9999,
            random_state=42,
        )
        p_value = float(perm_result.pvalue)
        pvalue_method = "permutation"
    else:
        # Large-N (N >= 10): asymptotic spearmanr p-value is reliable.
        p_value = float(spearman_result.pvalue)
        pvalue_method = "asymptotic"

    # --- Sign test on paired (F1Δ, pass-rateΔ) deltas (D-15) ---
    f1_deltas = [b - a for a, b in zip(f1_series, f1_series[1:])]
    pr_deltas = [b - a for a, b in zip(pass_rate_series, pass_rate_series[1:])]
    # Concordant: both move in the same direction (both nonzero to exclude ties)
    concordant = sum(
        1 for f, p in zip(f1_deltas, pr_deltas) if (f > 0) == (p > 0) and f != 0 and p != 0
    )
    n_pairs = sum(1 for f, p in zip(f1_deltas, pr_deltas) if f != 0 and p != 0)
    if n_pairs > 0:
        sign_result = binomtest(concordant, n_pairs, p=0.5, alternative="greater")
        sign_test_pvalue = float(sign_result.pvalue)
    else:
        # No non-zero pairs — degenerate case; set to 1.0 (non-significant)
        sign_test_pvalue = 1.0

    # --- Null-result flag (D-15): report ρ ≤ 0 OR p ≥ 0.05 as null result ---
    null_result: bool = rho <= 0 or p_value >= 0.05

    return {
        "spearman_rho": rho,
        "spearman_pvalue": p_value,
        "sign_test_pvalue": sign_test_pvalue,
        "n_concordant": concordant,
        "n_pairs": n_pairs,
        "null_result": null_result,
        "n_versions": n_versions,
        "pvalue_method": pvalue_method,
    }


# ---------------------------------------------------------------------------
# Figure: scatter + 3-axis summary (UI-SPEC §B.1 / §B.5)
# ---------------------------------------------------------------------------


def _annotate_null_result(ax) -> None:
    """Annotate the null-result finding on the axes (UI-SPEC §B.5, T-05-20)."""
    ax.text(
        0.5,
        0.5,
        "No improvement detected (null result — reported per pre-registration §6)",
        transform=ax.transAxes,
        ha="center",
        va="center",
        style="italic",
        fontsize=8,
        color=_GREY,
        alpha=0.6,
    )


def plot_triangulation(
    f1_series: list[float],
    pass_rate_series: list[float],
    stats: dict,
    output_path: Path,
    *,
    fixture: bool = False,
) -> None:
    """Plot the F1 × pass-rate triangulation scatter figure (UI-SPEC §B.1).

    Writes PDF + PNG to output_path.pdf / output_path.png (headless Agg, D-10).
    If fixture=True, applies the [FIXTURE DATA] watermark (D-09 gate, T-05-19).
    If stats["null_result"] is True, annotates the null-result finding (T-05-20).

    Args:
        f1_series: Ordered F1 scores per config version.
        pass_rate_series: Ordered pass-rate scores per config version.
        stats: Result dict from triangulate().
        output_path: Base path for output (suffix is replaced with .pdf / .png).
        fixture: If True, applies the [FIXTURE DATA] watermark.
    """
    import matplotlib.pyplot as plt  # lazy import — avoids eager Agg backend switch
    from setdrift_eval.figures.rcparams import _save_figure, _apply_fixture_watermark

    fig, ax = plt.subplots()

    ax.scatter(f1_series, pass_rate_series, color="#0173B2", alpha=0.8, zorder=3)

    # Version labels
    for i, (x, y) in enumerate(zip(f1_series, pass_rate_series)):
        ax.annotate(
            f"v{i + 1}",
            (x, y),
            textcoords="offset points",
            xytext=(4, 4),
            fontsize=7,
            color="#555555",
        )

    ax.set_xlabel("Skill-trigger F1 (macro)")
    ax.set_ylabel("Benchmark pass-rate")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    # Null-result annotation (T-05-20 / UI-SPEC §B.5)
    if stats.get("null_result"):
        _annotate_null_result(ax)

    # Subtitle with key statistics
    rho = stats.get("spearman_rho", float("nan"))
    p = stats.get("spearman_pvalue", float("nan"))
    method = stats.get("pvalue_method", "")
    n = stats.get("n_versions", len(f1_series))
    ax.set_title(
        f"F1 × Pass-rate Triangulation (Spearman ρ={rho:.3f}, p={p:.3f}, N={n}, method={method})",
        fontsize=9,
    )

    if fixture:
        _apply_fixture_watermark(fig)

    _save_figure(fig, Path(output_path), fixture=fixture)

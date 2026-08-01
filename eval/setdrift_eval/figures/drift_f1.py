"""Drift-vs-F1 overlay figure — the visual form of the falsifiable claim (RUN-05).

What this module does:
  - compute_drift_f1_stats(series) computes the paired drift-index x arm-A-F1
    statistic by calling the existing pre-registered triangulate() function
    (figures/triangulation.py, D-15) — never re-derives Spearman rho by hand.
  - plot_drift_f1(series, stats, output_path, fixture=False) renders a dual-axis
    overlay: arm A / arm B macro-F1 (with noise-band error bars) on the left Y
    axis across the early/mid/late revision axis, and the drift index on a
    twinx() right axis, mirroring figures/cost.py's dual-axis overlay pattern.

What it does NOT do:
  - Never opens an interactive display window — headless Agg backend only (D-10 anti-pattern).
  - Never recomputes F1 or the noise band — macro_f1 and noise_band are guard
    imports only (FROZEN RULER), exactly as figures/triangulation.py does.
  - Never hand-rolls a correlation statistic — triangulate() is imported and
    called, not reimplemented (T-09-08).
  - Never includes fixture figures in the dissertation (D-09 — apply watermark).

Goodhart firewall:
  macro_f1 and noise_band are imported from the FROZEN scorer.py as guard imports
  only. They must never be re-implemented or overridden here.

References: 09-02-PLAN.md, 09-PATTERNS.md ("Drift-vs-F1 overlay — no exact
analog, nearest two combined"), figures/triangulation.py, figures/cost.py,
figures/rcparams.py (09-01 provenance extension).
"""

from __future__ import annotations

from pathlib import Path

# FROZEN RULER — import only; never recompute (D-04 / D-15), mirrors triangulation.py.
from setdrift_eval.telemetry.scorer import macro_f1, noise_band  # noqa: F401 — guard imports only

from setdrift_eval.figures.triangulation import triangulate, _annotate_null_result


def compute_drift_f1_stats(series: dict) -> dict:
    """Compute the paired drift-index x arm-A-F1 statistic via triangulate() (D-15).

    triangulate()'s second parameter is named `pass_rate_series` for historical
    reasons (D-15's original F1 x pass-rate use case) but is a generic paired
    numeric series; here we substitute the drift-index series in that slot
    rather than renaming the frozen pre-registered function (T-09-08 — never
    hand-roll or re-derive the statistic; reuse verbatim).

    Revisions where drift_index is None (see DRIFT_INDEX_MISSING_NOTE in
    figures/producers.py) are excluded from the paired series — triangulate()
    requires equal-length numeric lists; a missing cell can never be imputed
    as 0.0 (T-09-07).

    Args:
        series: the dict written by figures.producers.build_drift_f1_series
            (or the committed drift_f1_fixture.json under --allow-fixtures).

    Returns:
        dict — the triangulate() result (spearman_rho, spearman_pvalue,
        sign_test_pvalue, n_concordant, n_pairs, null_result, n_versions,
        pvalue_method).
    """
    f1_values = series["arms"]["A"]["f1_mean"]
    drift_values = series["drift_index"]

    paired = [
        (f1, drift)
        for f1, drift in zip(f1_values, drift_values)
        if f1 is not None and drift is not None
    ]
    f1_paired = [f for f, _ in paired]
    drift_paired = [d for _, d in paired]

    return triangulate(f1_paired, drift_paired)


def plot_drift_f1(
    series: dict,
    stats: dict,
    output_path: Path,
    *,
    fixture: bool = False,
) -> None:
    """Render the dual-axis drift-vs-F1 overlay figure (RUN-05, FIG-01).

    Left Y axis: arm A and arm B macro-F1 across the early/mid/late revision
    axis, each with error bars spanning its noise band. Right (twinx()) Y axis:
    the drift index, shared across arms per revision. This is the visual form
    of the falsifiable claim: "...sustains skill-trigger F1 above a frozen
    hand-written configuration ... as the underlying codebase and model drift
    over the evaluation window."

    Writes output_path.pdf and output_path.png; nothing is displayed (Agg only,
    D-10). If stats["null_result"] is True, the D-15 null-result annotation is
    drawn (same annotation triangulation.py uses — imported, not reimplemented).
    If fixture=True, the raster watermark is applied AND the provenance token
    stamped by rcparams._save_figure carries FIXTURE; otherwise REAL (09-01).

    Args:
        series: dict written by build_drift_f1_series / the committed fixture.
        stats: result dict from compute_drift_f1_stats (== triangulate()).
        output_path: path stem for output (.pdf / .png appended automatically).
        fixture: if True, apply the [FIXTURE DATA] watermark (D-09).
    """
    import matplotlib.pyplot as plt  # lazy import inside figures/

    from setdrift_eval.figures.rcparams import (
        PRIMARY_BLUE,
        GREEN,
        VERMILLION,
        _apply_fixture_watermark,
        _save_figure,
    )

    revisions = series["revisions"]
    arm_a = series["arms"]["A"]
    arm_b = series["arms"]["B"]
    drift_values = series["drift_index"]

    x = list(range(len(revisions)))

    def _yerr(arm: dict) -> list[list[float]]:
        lower = [
            (m if m is not None else 0.0) - (lo if lo is not None else 0.0)
            for m, lo in zip(arm["f1_mean"], arm["f1_noise_band_low"])
        ]
        upper = [
            (hi if hi is not None else 0.0) - (m if m is not None else 0.0)
            for m, hi in zip(arm["f1_mean"], arm["f1_noise_band_high"])
        ]
        return [lower, upper]

    fig, ax_f1 = plt.subplots()

    f1_a = [v if v is not None else float("nan") for v in arm_a["f1_mean"]]
    f1_b = [v if v is not None else float("nan") for v in arm_b["f1_mean"]]

    ax_f1.errorbar(
        x,
        f1_a,
        yerr=_yerr(arm_a),
        fmt="o-",
        color=PRIMARY_BLUE,
        linewidth=1.5,
        markersize=5,
        label="Arm A (Setdrift-managed)",
        capsize=4,
        elinewidth=1.0,
        ecolor=PRIMARY_BLUE,
        alpha=0.9,
    )
    ax_f1.errorbar(
        x,
        f1_b,
        yerr=_yerr(arm_b),
        fmt="s-",
        color=GREEN,
        linewidth=1.5,
        markersize=5,
        label="Arm B (frozen hand-written)",
        capsize=4,
        elinewidth=1.0,
        ecolor=GREEN,
        alpha=0.9,
    )

    ax_f1.set_xlabel("Codebase revision")
    ax_f1.set_ylabel("Skill-trigger F1 (macro)", color=PRIMARY_BLUE)
    ax_f1.tick_params(axis="y", labelcolor=PRIMARY_BLUE)
    ax_f1.set_xticks(x)
    ax_f1.set_xticklabels(revisions)
    # UI-SPEC B.5: F1 axis is never auto-zoomed — a zoomed axis would visually
    # manufacture a difference the noise band does not support.
    ax_f1.set_ylim(0, 1)

    ax_drift = ax_f1.twinx()
    drift_plot_values = [d if d is not None else float("nan") for d in drift_values]
    ax_drift.plot(
        x,
        drift_plot_values,
        "^--",
        color=VERMILLION,
        linewidth=1.5,
        markersize=6,
        label="Drift index (cosine-staleness)",
    )
    ax_drift.set_ylabel("Drift index", color=VERMILLION)
    ax_drift.tick_params(axis="y", labelcolor=VERMILLION)
    ax_drift.set_ylim(bottom=0)  # UI-SPEC B.5

    rho = stats.get("spearman_rho", float("nan"))
    p = stats.get("spearman_pvalue", float("nan"))
    method = stats.get("pvalue_method", "")
    n = stats.get("n_versions", len(revisions))
    ax_f1.set_title(
        "Skill-trigger F1 vs. Drift Index — falsifiable claim under test "
        f"(Spearman ρ={rho:.3f}, p={p:.3f}, N={n}, method={method})",
        fontsize=9,
    )

    if stats.get("null_result"):
        _annotate_null_result(ax_f1)

    caption = (
        "F1 noise bands span the 5-run band (frozen ruler); drift index is the "
        "rolling-window cosine-staleness measure (compute_drift_index)."
    )
    if series.get("notes"):
        caption += "\n" + " ".join(series["notes"])
    fig.text(
        0.5,
        -0.04,
        caption,
        ha="center",
        fontsize=7,
        style="italic",
        color="#555555",
    )

    lines1, labels1 = ax_f1.get_legend_handles_labels()
    lines2, labels2 = ax_drift.get_legend_handles_labels()
    ax_f1.legend(lines1 + lines2, labels1 + labels2, fontsize=8, loc="upper right")

    if fixture:
        _apply_fixture_watermark(fig)

    _save_figure(fig, Path(output_path), fixture=fixture)

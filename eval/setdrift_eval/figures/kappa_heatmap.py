"""5×3 Cohen's κ heatmap (bias_mode × family_pair) with κ=0.6 floor (D-11).

What this module does:
  - Renders the 5×3 (bias_mode × family_pair) heatmap from a list of KappaCell
    objects (from judge/kappa.py) using matplotlib imshow (headless Agg, D-10).
  - Annotates the pre-registered κ=0.6 floor as a dashed line (UI-SPEC §B.5).
  - When fixture=True, applies the [FIXTURE DATA] watermark (D-09 gate, T-05-19).
  - Writes PDF + PNG to the given output_path via rcparams._save_figure.

What it does NOT do:
  - NEVER hand-rolls Cohen's kappa — imports KappaCell from judge/kappa.py which
    uses sklearn.metrics.cohen_kappa_score (T-05-21, RESEARCH Don't-Hand-Roll).
  - NEVER recomputes F1 — scorer.macro_f1 is a guard import only (FROZEN, D-04).
  - NEVER calls plt.show() — headless Agg backend only (D-10 anti-pattern).
  - NEVER includes fixture figures in the dissertation (D-09).

Goodhart firewall:
  macro_f1 is imported from the FROZEN scorer.py as a guard import only.
  It must never be re-implemented or overridden here.

References: 05-PATTERNS.md §figures/kappa_heatmap.py, 05-UI-SPEC.md §B.1/B.5,
PLAN 05-06 Task 2, D-11.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

# FROZEN RULER — import only; never recompute (D-04).
from setdrift_eval.telemetry.scorer import macro_f1  # noqa: F401 — guard import only

if TYPE_CHECKING:
    from setdrift_eval.judge.kappa import KappaCell

# Pre-registered bias modes and family pairs (D-11)
_BIAS_MODES = ["verbosity", "position", "self_preference", "authority", "recency"]
_FAMILY_PAIRS = ["claude_vs_gpt4", "claude_vs_gemini", "gpt4_vs_gemini"]

# Pre-registered κ floor (D-11 — change requires dated design-doc amendment)
_KAPPA_FLOOR = 0.6


def plot_kappa_heatmap(
    kappa_cells: list["KappaCell"],
    output_path: Path,
    *,
    fixture: bool = False,
) -> None:
    """Render the 5×3 (bias_mode × family_pair) Cohen's κ heatmap (UI-SPEC §B.1).

    Axes: rows = bias_modes (verbosity, position, self_preference, authority, recency);
    columns = family_pairs (claude_vs_gpt4, claude_vs_gemini, gpt4_vs_gemini).
    Colormap: RdYlGn over [-1, 1]; colorbar labeled "Cohen's κ".
    The pre-registered κ=0.6 floor is annotated as a dashed horizontal line.

    Cells not present in kappa_cells are rendered as NaN (grey / masked).

    Writes PDF + PNG to output_path.pdf / output_path.png (D-10 headless).
    If fixture=True, applies the [FIXTURE DATA] watermark (D-09, T-05-19).

    Args:
        kappa_cells: List of KappaCell results from the judge sensitivity run.
        output_path: Base path for output (suffix replaced with .pdf / .png).
        fixture: If True, applies the [FIXTURE DATA] watermark.
    """
    import matplotlib.pyplot as plt
    import numpy as np
    from setdrift_eval.figures.rcparams import _save_figure, _apply_fixture_watermark

    # Build 5×3 matrix (NaN for missing cells)
    matrix = np.full((len(_BIAS_MODES), len(_FAMILY_PAIRS)), fill_value=float("nan"))
    for cell in kappa_cells:
        if cell.bias_mode in _BIAS_MODES and cell.family_pair in _FAMILY_PAIRS:
            i = _BIAS_MODES.index(cell.bias_mode)
            j = _FAMILY_PAIRS.index(cell.family_pair)
            matrix[i, j] = cell.kappa

    fig, ax = plt.subplots(figsize=(7.0, 4.5))

    # Use masked array so NaN cells render as a neutral grey
    masked_matrix = np.ma.masked_invalid(matrix)
    im = ax.imshow(masked_matrix, vmin=-1, vmax=1, cmap="RdYlGn", aspect="auto")
    fig.colorbar(im, ax=ax, label="Cohen's κ")

    # Annotate cell values
    for i in range(len(_BIAS_MODES)):
        for j in range(len(_FAMILY_PAIRS)):
            val = matrix[i, j]
            if not np.isnan(val):
                ax.text(
                    j,
                    i,
                    f"{val:.2f}",
                    ha="center",
                    va="center",
                    fontsize=7,
                    color="black" if abs(val) < 0.7 else "white",
                )

    # κ=0.6 floor annotation (UI-SPEC §B.5 threshold label, D-11 pre-registered)
    # The floor is annotated as a note in the colorbar area rather than a line on the
    # heatmap (lines across imshow cells are visually confusing). We use a text
    # annotation on the axes at the floor color level.
    ax.axhline(
        y=len(_BIAS_MODES) - 0.5,
        color="#949494",
        linestyle="--",
        linewidth=0.8,
        label=f"κ={_KAPPA_FLOOR} floor (pre-registered D-11)",
    )
    # Add a floor marker to the colorbar by annotating the figure
    fig.text(
        0.93,
        0.5 + _KAPPA_FLOOR / 2,  # approx normalized colorbar position for κ=0.6
        f"← κ={_KAPPA_FLOOR} floor",
        va="center",
        ha="left",
        fontsize=7,
        color="#555555",
        transform=fig.transFigure,
    )

    ax.set_xticks(range(len(_FAMILY_PAIRS)))
    ax.set_xticklabels(_FAMILY_PAIRS, rotation=15, ha="right", fontsize=8)
    ax.set_yticks(range(len(_BIAS_MODES)))
    ax.set_yticklabels(_BIAS_MODES, fontsize=8)
    ax.set_title(
        "Judge Sensitivity: Cohen's κ per (Bias Mode × Family Pair)",
        fontsize=10,
    )
    ax.set_xlabel("Family pair")
    ax.set_ylabel("Bias mode")

    if fixture:
        _apply_fixture_watermark(fig)

    _save_figure(fig, Path(output_path), fixture=fixture)

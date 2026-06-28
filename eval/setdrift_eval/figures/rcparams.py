"""Shared matplotlib rcParams for all Setdrift dissertation figures (UI-SPEC B.2).

What this module does:
  - Defines SETDRIFT_RCPARAMS (Okabe-Ito colorblind-safe palette, DejaVu Sans, 300 DPI)
  - Provides apply() which enforces headless Agg backend + updates global rcParams
  - Provides shared _save_figure() helper (PDF + PNG at 300 DPI, closes figure)
  - Provides _apply_fixture_watermark() for D-09 fixture-data stamp

What it does NOT do:
  - Never calls plt.show() — headless Agg backend only (D-10 anti-pattern)
  - Never renders to screen or opens a display
"""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl


# Applied once at the start of each setdrift-eval figures run.
# Never call plt.show() — headless Agg backend only (D-10 anti-pattern).
SETDRIFT_RCPARAMS: dict = {
    "figure.figsize": [7.0, 4.5],
    "figure.dpi": 150,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.05,
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans", "Liberation Sans", "Arial"],
    "font.size": 9,
    "axes.titlesize": 10,
    "axes.labelsize": 9,
    "legend.fontsize": 8,
    "figure.titlesize": 11,
    "lines.linewidth": 1.5,
    "patch.linewidth": 0.8,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "grid.linewidth": 0.5,
    "axes.prop_cycle": mpl.cycler(  # type: ignore[attr-defined]
        color=[
            "#0173B2",
            "#DE8F05",
            "#029E73",
            "#D55E00",
            "#CC78BC",
            "#CA9161",
            "#FBAFE4",
            "#949494",
            "#ECE133",
            "#56B4E9",
        ]
    ),
    "axes.spines.top": False,
    "axes.spines.right": False,
}

# Convenience sentinel colors (UI-SPEC B.3 role-mapping)
PRIMARY_BLUE = "#0173B2"
ORANGE = "#DE8F05"
GREEN = "#029E73"
VERMILLION = "#D55E00"
GREY = "#949494"


def apply() -> None:
    """Apply SETDRIFT_RCPARAMS globally. Call once at start of figures CLI run.

    Enforces headless Agg backend first — never plt.show() (D-10 anti-pattern).
    """
    mpl.use("Agg")  # enforce headless — never plt.show()
    mpl.rcParams.update(SETDRIFT_RCPARAMS)


def _save_figure(fig, output_path: Path) -> None:
    """Save figure as PDF + PNG at 300 DPI; close figure.

    Never call plt.show() (D-10 anti-pattern).
    """
    import matplotlib.pyplot as plt  # lazy import inside figures/

    output_path = Path(output_path)
    fig.savefig(output_path.with_suffix(".pdf"))
    fig.savefig(output_path.with_suffix(".png"), dpi=300)
    plt.close(fig)


def _apply_fixture_watermark(fig) -> None:
    """Stamp a red [FIXTURE DATA] watermark on fixture figures (D-09).

    Fixture figures must never enter the dissertation. This watermark is the
    visual gate: any figure stamped here is test-only scaffolding.
    """
    fig.text(
        0.5,
        0.5,
        "[FIXTURE DATA — awaiting Phase-3 output]",
        transform=fig.transFigure,
        alpha=0.15,
        ha="center",
        va="center",
        rotation=30,
        fontsize=24,
        color="red",
    )

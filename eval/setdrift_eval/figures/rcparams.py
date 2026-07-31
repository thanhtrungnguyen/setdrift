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

# Machine-readable provenance markers (D9-05, Phase 9 plan 09-01).
#
# The rendered `_apply_fixture_watermark()` text is NOT reliably byte-searchable:
# in the PNG it is rasterized into pixels, and in the PDF it is font-encoded
# inside a compressed content stream. Neither is a sound target for a scripted
# gate. Instead, `_save_figure` stamps ONE of these two literal tokens into the
# PNG tEXt chunk ("Comment" key) and the PDF Info dictionary ("Keywords" key) —
# both of which matplotlib writes as uncompressed, plain strings. This is the
# sole machine-readable contract `.planning/dissertation/scripts/check_no_watermark.py`
# scans; the raster watermark remains purely a human visual cue.
PROVENANCE_KEY = "Setdrift-Data-Provenance"
PROVENANCE_FIXTURE = "setdrift-provenance=FIXTURE"
PROVENANCE_REAL = "setdrift-provenance=REAL"


def apply() -> None:
    """Apply SETDRIFT_RCPARAMS globally. Call once at start of figures CLI run.

    Enforces headless Agg backend first — never plt.show() (D-10 anti-pattern).
    """
    mpl.use("Agg")  # enforce headless — never plt.show()
    mpl.rcParams.update(SETDRIFT_RCPARAMS)


def _save_figure(fig, output_path: Path, *, fixture: bool = False) -> None:
    """Save figure as PDF + PNG at 300 DPI; close figure.

    Never call plt.show() (D-10 anti-pattern).

    Stamps a machine-readable FIXTURE/REAL provenance token (PROVENANCE_FIXTURE
    or PROVENANCE_REAL) into the PNG tEXt chunk ("Comment" key, via matplotlib's
    `metadata=` kwarg) and the PDF Info dictionary ("Keywords" key). This
    metadata — not the rendered `_apply_fixture_watermark` pixels — is the
    machine-readable contract that
    `.planning/dissertation/scripts/check_no_watermark.py` scans. The rendered
    watermark text is rasterized into pixels in the PNG and font-encoded inside
    a compressed content stream in the PDF, so it is NOT reliably byte-searchable;
    this metadata sidesteps that limitation entirely.

    Args:
        fig: matplotlib Figure to save.
        output_path: path stem; .pdf and .png suffixes are appended.
        fixture: if True, stamps PROVENANCE_FIXTURE; else PROVENANCE_REAL.
            Defaults to False so pre-existing callers that don't pass
            `fixture=` keep working unchanged (backward compatible).
    """
    import matplotlib.pyplot as plt  # lazy import inside figures/

    output_path = Path(output_path)
    provenance_token = PROVENANCE_FIXTURE if fixture else PROVENANCE_REAL

    fig.savefig(
        output_path.with_suffix(".pdf"),
        metadata={"Keywords": provenance_token},
    )
    fig.savefig(
        output_path.with_suffix(".png"),
        dpi=300,
        metadata={"Software": "setdrift-eval", "Comment": provenance_token},
    )
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

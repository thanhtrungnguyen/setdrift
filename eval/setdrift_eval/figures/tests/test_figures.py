"""Tests for setdrift_eval.figures package (Phase 5, D-10).

Tests cover:
  - rcparams: Agg backend enforcement, rcParams values
  - cost: tokens_to_cost computation, plot_cost_delta PDF+PNG output, fixture watermark
  - cli: FigureDataError gate, --allow-fixtures writes watermarked output
"""

from __future__ import annotations

import math
from pathlib import Path


# ---------------------------------------------------------------------------
# rcparams tests
# ---------------------------------------------------------------------------


def test_apply_forces_agg_backend():
    """apply() must switch matplotlib to the Agg backend (D-10 headless)."""
    import matplotlib as mpl
    from setdrift_eval.figures.rcparams import apply

    apply()
    assert mpl.get_backend().lower() == "agg"


def test_rcparams_figsize():
    """SETDRIFT_RCPARAMS must include [7.0, 4.5] figsize (UI-SPEC B.2)."""
    from setdrift_eval.figures.rcparams import SETDRIFT_RCPARAMS

    assert SETDRIFT_RCPARAMS["figure.figsize"] == [7.0, 4.5]


def test_rcparams_savefig_dpi():
    """SETDRIFT_RCPARAMS must set savefig.dpi=300 (UI-SPEC B.2)."""
    from setdrift_eval.figures.rcparams import SETDRIFT_RCPARAMS

    assert SETDRIFT_RCPARAMS["savefig.dpi"] == 300


# ---------------------------------------------------------------------------
# tokens_to_cost tests
# ---------------------------------------------------------------------------


def test_tokens_to_cost_kwh():
    """tokens_to_cost: kwh == n_tokens * KWHR_PER_TOKEN."""
    from setdrift_eval.figures.cost import tokens_to_cost, KWHR_PER_TOKEN

    result = tokens_to_cost(1_000_000)
    expected_kwh = 1_000_000 * KWHR_PER_TOKEN
    assert math.isclose(result["kwh"], expected_kwh, rel_tol=1e-9)


def test_tokens_to_cost_usd_electricity():
    """tokens_to_cost: usd_electricity == kwh * USD_PER_KWHR."""
    from setdrift_eval.figures.cost import tokens_to_cost, KWHR_PER_TOKEN, USD_PER_KWHR

    result = tokens_to_cost(1_000_000)
    expected_kwh = 1_000_000 * KWHR_PER_TOKEN
    expected_usd = expected_kwh * USD_PER_KWHR
    assert math.isclose(result["usd_electricity"], expected_usd, rel_tol=1e-9)


def test_tokens_to_cost_co2():
    """tokens_to_cost: co2_kg == kwh * GRID_CO2_KG_PER_KWHR."""
    from setdrift_eval.figures.cost import tokens_to_cost, KWHR_PER_TOKEN, GRID_CO2_KG_PER_KWHR

    result = tokens_to_cost(1_000_000)
    expected_kwh = 1_000_000 * KWHR_PER_TOKEN
    expected_co2 = expected_kwh * GRID_CO2_KG_PER_KWHR
    assert math.isclose(result["co2_kg"], expected_co2, rel_tol=1e-9)


def test_tokens_to_cost_api_cost_note():
    """tokens_to_cost: api_cost_note is a non-empty string."""
    from setdrift_eval.figures.cost import tokens_to_cost

    result = tokens_to_cost(1_000_000)
    assert isinstance(result["api_cost_note"], str)
    assert len(result["api_cost_note"]) > 0


# ---------------------------------------------------------------------------
# plot_cost_delta tests
# ---------------------------------------------------------------------------


def test_plot_cost_delta_writes_pdf_and_png(tmp_path):
    """plot_cost_delta writes both .pdf and .png to the given output path."""
    from setdrift_eval.figures.rcparams import apply
    from setdrift_eval.figures.cost import plot_cost_delta

    apply()  # enforce Agg before figure generation

    per_version = {"v1": 100_000, "v2": 150_000, "v3": 120_000}
    output = tmp_path / "cost-delta"

    plot_cost_delta(per_version, output, fixture=False)

    assert (tmp_path / "cost-delta.pdf").exists(), "PDF not written"
    assert (tmp_path / "cost-delta.png").exists(), "PNG not written"


def test_plot_cost_delta_fixture_watermark(tmp_path):
    """plot_cost_delta with fixture=True: figure text contains 'FIXTURE DATA'."""
    import matplotlib
    import matplotlib.pyplot as plt
    from setdrift_eval.figures.rcparams import apply
    from setdrift_eval.figures.cost import plot_cost_delta

    apply()

    per_version = {"v1": 50_000}
    output = tmp_path / "cost-delta-fixture"

    # Capture the figure before it is closed: patch _save_figure to intercept
    captured_texts: list[str] = []

    import setdrift_eval.figures.rcparams as _rcparams_mod

    original_save = _rcparams_mod._save_figure

    def _capturing_save(fig, path, *, fixture=False):
        for text_obj in fig.texts:
            captured_texts.append(text_obj.get_text())
        original_save(fig, path, fixture=fixture)

    _rcparams_mod._save_figure = _capturing_save
    try:
        plot_cost_delta(per_version, output, fixture=True)
    finally:
        _rcparams_mod._save_figure = original_save

    assert any("FIXTURE DATA" in t for t in captured_texts), (
        f"Expected 'FIXTURE DATA' in figure texts but got: {captured_texts}"
    )


def test_cost_constants_present():
    """KWHR_PER_TOKEN, USD_PER_KWHR, GRID_CO2_KG_PER_KWHR must be present and positive."""
    from setdrift_eval.figures import cost

    assert hasattr(cost, "KWHR_PER_TOKEN")
    assert hasattr(cost, "USD_PER_KWHR")
    assert hasattr(cost, "GRID_CO2_KG_PER_KWHR")
    assert cost.KWHR_PER_TOKEN > 0
    assert cost.USD_PER_KWHR > 0
    assert cost.GRID_CO2_KG_PER_KWHR > 0

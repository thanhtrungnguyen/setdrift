"""Tests for the drift-vs-F1 overlay figure (RUN-05, Phase 9 plan 09-02).

Covers, in three classes matching the plan's three tasks:
  1. build_drift_f1_series producer (materialize the overlay input)
  2. plot_drift_f1 figure (dual-axis overlay, null-result, provenance)
  3. --drift-f1 three-way CLI dispatch (real / fixture / FigureDataError)

All tests are hermetic: synthetic *-drift-results.json fixtures written to
tmp_path, never touching the real committed experiments/ tree. No live API calls.

References: 09-02-PLAN.md, 09-PATTERNS.md, 09-01-SUMMARY.md (provenance substrate).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


def _write_json(path: Path, **fields) -> Path:
    path.write_text(json.dumps(fields, indent=2), encoding="utf-8")
    return path


def _drift_manifest(
    arm: str,
    revision: str,
    run_idx: int,
    f1_mean: float,
    band_low: float,
    band_high: float,
    drift_index: float | None = None,
) -> dict:
    return {
        "grid_arm": arm,
        "grid_revision": revision,
        "grid_run_idx": run_idx,
        "model": "claude-sonnet-4-6",
        "macro_f1_mean": f1_mean,
        "macro_f1_noise_band_low": band_low,
        "macro_f1_noise_band_high": band_high,
        "drift_index": drift_index,
        "config_hash": f"hash-{arm}-{revision}-{run_idx}",
        "token_cost_total": 0,
    }


# ---------------------------------------------------------------------------
# Task 1: build_drift_f1_series
# ---------------------------------------------------------------------------


class TestBuildDriftF1Series:
    def test_emits_pinned_revision_order_and_both_arms(self, tmp_path: Path):
        from setdrift_eval.figures.producers import build_drift_f1_series

        experiments_dir = tmp_path
        idx = 0
        for revision, drift in (("early", 0.1), ("mid", 0.5), ("late", 0.9)):
            for arm in ("A", "B"):
                idx += 1
                _write_json(
                    experiments_dir / f"{idx:03d}-drift-results.json",
                    **_drift_manifest(arm, revision, 0, 0.7, 0.65, 0.75, drift),
                )

        out_path = build_drift_f1_series(experiments_dir)

        assert out_path == experiments_dir / "drift-f1-series.json"
        data = json.loads(out_path.read_text(encoding="utf-8"))

        assert data["revisions"] == ["early", "mid", "late"]
        assert set(data["arms"].keys()) == {"A", "B"}
        assert data["drift_index"] == [0.1, 0.5, 0.9]

    def test_aggregates_repeats_by_mean_and_records_count(self, tmp_path: Path):
        from setdrift_eval.figures.producers import build_drift_f1_series

        experiments_dir = tmp_path
        _write_json(
            experiments_dir / "001-drift-results.json",
            **_drift_manifest("A", "early", 0, 0.60, 0.55, 0.65, 0.2),
        )
        _write_json(
            experiments_dir / "002-drift-results.json",
            **_drift_manifest("A", "early", 1, 0.70, 0.65, 0.75, 0.3),
        )
        _write_json(
            experiments_dir / "003-drift-results.json",
            **_drift_manifest("B", "early", 0, 0.50, 0.45, 0.55, 0.2),
        )

        out_path = build_drift_f1_series(experiments_dir)
        data = json.loads(out_path.read_text(encoding="utf-8"))

        # early is index 0 in the pinned revision order
        assert data["arms"]["A"]["f1_mean"][0] == pytest.approx(0.65)
        assert data["arms"]["A"]["f1_noise_band_low"][0] == pytest.approx(0.55)
        assert data["arms"]["A"]["f1_noise_band_high"][0] == pytest.approx(0.75)
        assert data["arms"]["A"]["n_repeats"][0] == 2
        assert data["arms"]["B"]["n_repeats"][0] == 1

    def test_missing_drift_index_disclosed_not_coerced_to_zero(self, tmp_path: Path):
        from setdrift_eval.figures.producers import (
            DRIFT_INDEX_MISSING_NOTE,
            build_drift_f1_series,
        )

        experiments_dir = tmp_path
        _write_json(
            experiments_dir / "001-drift-results.json",
            **_drift_manifest("A", "early", 0, 0.7, 0.65, 0.75, None),
        )
        _write_json(
            experiments_dir / "002-drift-results.json",
            **_drift_manifest("B", "early", 0, 0.6, 0.55, 0.65, None),
        )

        out_path = build_drift_f1_series(experiments_dir)
        data = json.loads(out_path.read_text(encoding="utf-8"))

        assert data["drift_index"][0] is None, "missing drift_index must never be coerced to 0.0"
        assert "notes" in data
        assert DRIFT_INDEX_MISSING_NOTE in data["notes"]

    def test_unknown_grid_revision_raises_figure_data_error(self, tmp_path: Path):
        from setdrift_eval.figures.errors import FigureDataError
        from setdrift_eval.figures.producers import build_drift_f1_series

        experiments_dir = tmp_path
        _write_json(
            experiments_dir / "001-drift-results.json",
            **_drift_manifest("A", "prehistoric", 0, 0.7, 0.65, 0.75, 0.1),
        )

        with pytest.raises(FigureDataError, match="prehistoric"):
            build_drift_f1_series(experiments_dir)

    def test_empty_directory_raises_figure_data_error_naming_directory(self, tmp_path: Path):
        from setdrift_eval.figures.errors import FigureDataError
        from setdrift_eval.figures.producers import build_drift_f1_series

        experiments_dir = tmp_path
        with pytest.raises(FigureDataError, match=re.escape(str(experiments_dir))):
            build_drift_f1_series(experiments_dir)

    def test_cr02_non_drift_results_json_never_consumed(self, tmp_path: Path):
        """CR-02 regression: fnmatch('001-drift-results.json', '*-results.json') is
        True, but the reverse must NOT hold — a plain *-results.json health-run
        manifest sitting in the same directory must never be picked up by the
        *-drift-results.json glob."""
        from setdrift_eval.figures.producers import build_drift_f1_series

        experiments_dir = tmp_path
        _write_json(
            experiments_dir / "001-drift-results.json",
            **_drift_manifest("A", "early", 0, 0.7, 0.65, 0.75, 0.1),
        )
        # A non-drift health-run manifest with a DIFFERENT (bogus) revision value —
        # if it were incorrectly consumed, this would raise FigureDataError.
        _write_json(
            experiments_dir / "002-results.json",
            grid_revision="not-a-real-revision",
            grid_arm="A",
            macro_f1_mean=0.9,
        )

        out_path = build_drift_f1_series(experiments_dir)  # must not raise
        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert data["arms"]["A"]["n_repeats"][0] == 1


# ---------------------------------------------------------------------------
# Task 2: plot_drift_f1 + compute_drift_f1_stats
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
_DRIFT_F1_FIXTURE = _FIXTURES_DIR / "drift_f1_fixture.json"


def _load_fixture_series() -> dict:
    return json.loads(_DRIFT_F1_FIXTURE.read_text(encoding="utf-8"))


class TestComputeDriftF1Stats:
    def test_reuses_triangulate_and_returns_all_d15_keys(self):
        from setdrift_eval.figures.drift_f1 import compute_drift_f1_stats

        series = _load_fixture_series()
        stats = compute_drift_f1_stats(series)

        required_keys = {
            "spearman_rho",
            "spearman_pvalue",
            "sign_test_pvalue",
            "n_concordant",
            "n_pairs",
            "null_result",
            "n_versions",
            "pvalue_method",
        }
        missing = required_keys - stats.keys()
        assert not missing, f"compute_drift_f1_stats result missing keys: {missing}"

    def test_excludes_revisions_with_missing_drift_index(self):
        from setdrift_eval.figures.drift_f1 import compute_drift_f1_stats

        series = {
            "revisions": ["early", "mid", "late"],
            "arms": {
                "A": {"f1_mean": [0.6, 0.7, 0.8], "f1_noise_band_low": [0.55, 0.65, 0.75],
                      "f1_noise_band_high": [0.65, 0.75, 0.85], "n_repeats": [5, 5, 5]},
                "B": {"f1_mean": [0.5, 0.5, 0.5], "f1_noise_band_low": [0.45, 0.45, 0.45],
                      "f1_noise_band_high": [0.55, 0.55, 0.55], "n_repeats": [5, 5, 5]},
            },
            "drift_index": [0.1, None, 0.9],
        }
        stats = compute_drift_f1_stats(series)
        # Only 2 revisions have a non-null drift_index pair.
        assert stats["n_versions"] == 2


class TestPlotDriftF1:
    def test_writes_pdf_and_png(self, tmp_path: Path):
        from setdrift_eval.figures.drift_f1 import compute_drift_f1_stats, plot_drift_f1
        from setdrift_eval.figures.rcparams import apply

        apply()
        series = _load_fixture_series()
        stats = compute_drift_f1_stats(series)
        output = tmp_path / "drift-f1"

        plot_drift_f1(series, stats, output, fixture=True)

        assert output.with_suffix(".pdf").exists(), "drift-f1.pdf not written"
        assert output.with_suffix(".png").exists(), "drift-f1.png not written"

    def test_has_two_left_axis_lines_and_one_right_axis_line(self, tmp_path: Path):
        import matplotlib.pyplot as plt

        from setdrift_eval.figures.drift_f1 import compute_drift_f1_stats, plot_drift_f1
        from setdrift_eval.figures.rcparams import apply

        apply()
        series = _load_fixture_series()
        stats = compute_drift_f1_stats(series)
        output = tmp_path / "drift-f1-axes"

        # Capture figure axes before it is closed by _save_figure.
        captured: dict = {}
        import setdrift_eval.figures.rcparams as _rcparams_mod

        original_save = _rcparams_mod._save_figure

        def _capturing_save(fig, path, *, fixture=False):
            captured["axes"] = list(fig.axes)
            original_save(fig, path, fixture=fixture)

        _rcparams_mod._save_figure = _capturing_save
        try:
            plot_drift_f1(series, stats, output, fixture=True)
        finally:
            _rcparams_mod._save_figure = original_save

        axes = captured["axes"]
        assert len(axes) == 2, f"Expected exactly 2 axes (left F1 + right twinx drift), got {len(axes)}"
        ax_f1, ax_drift = axes
        # Left axis: 2 errorbar series (arm A, arm B); errorbar() also emits
        # caplines/error-bar Line2D artifacts, so assert containers instead of
        # raw get_lines() count.
        assert len(ax_f1.containers) == 2, (
            f"Expected 2 errorbar containers (arm A, arm B) on the left axis, "
            f"got {len(ax_f1.containers)}"
        )
        # Right (twinx) axis: exactly 1 drift-index line, no error-bar containers.
        assert len(ax_drift.get_lines()) == 1
        assert len(ax_drift.containers) == 0
        plt.close("all")

    def test_null_result_annotated(self, tmp_path: Path):
        from setdrift_eval.figures.drift_f1 import plot_drift_f1
        from setdrift_eval.figures.rcparams import apply

        apply()
        series = _load_fixture_series()
        stats = {
            "spearman_rho": -0.2,
            "spearman_pvalue": 0.8,
            "sign_test_pvalue": 1.0,
            "n_concordant": 0,
            "n_pairs": 2,
            "null_result": True,
            "n_versions": 3,
            "pvalue_method": "permutation",
        }
        output = tmp_path / "drift-f1-null"

        plot_drift_f1(series, stats, output, fixture=True)

        assert output.with_suffix(".pdf").exists()
        assert output.with_suffix(".png").exists()

    def test_fixture_true_stamps_fixture_token_fixture_false_stamps_real_token(
        self, tmp_path: Path
    ):
        from setdrift_eval.figures.drift_f1 import compute_drift_f1_stats, plot_drift_f1
        from setdrift_eval.figures.rcparams import PROVENANCE_FIXTURE, PROVENANCE_REAL, apply

        apply()
        series = _load_fixture_series()
        stats = compute_drift_f1_stats(series)

        fixture_output = tmp_path / "drift-f1-fixture"
        plot_drift_f1(series, stats, fixture_output, fixture=True)
        fixture_png_bytes = fixture_output.with_suffix(".png").read_bytes()
        assert PROVENANCE_FIXTURE.encode("ascii") in fixture_png_bytes
        assert PROVENANCE_REAL.encode("ascii") not in fixture_png_bytes

        real_output = tmp_path / "drift-f1-real"
        plot_drift_f1(series, stats, real_output, fixture=False)
        real_png_bytes = real_output.with_suffix(".png").read_bytes()
        assert PROVENANCE_REAL.encode("ascii") in real_png_bytes
        assert PROVENANCE_FIXTURE.encode("ascii") not in real_png_bytes

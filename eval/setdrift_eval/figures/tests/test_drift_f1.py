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

"""Tests for the paired-difference reporter (REQ-DRIFT-03, §7-2 yoking discipline).

Tests:
  1. paired_difference_report pivots grid_cells to per-(revision, run_idx) (f1_A, f1_B)
     and computes paired mean diff per revision.
  2. t_stat / p_value computed via scipy.stats.ttest_rel; nan-guard for n_runs < 2
     (degenerate-band guard).
  3. Cross-model averaging is structurally absent — report is per (model, revision) only;
     no code path averages F1 across Sonnet and Haiku (§7-2).
  4. PairedDiffResult always carries a non-empty reason (field_validator).
  5. noise_band consumed via frozen scorer.noise_band (import check).

Uses in-memory DuckDB seeded with known A/B values for deterministic assertions.
"""
import math
from pathlib import Path

import duckdb
import pytest

from setdrift_eval.drift.db import DDL


# ---------------------------------------------------------------------------
# Helper: seed in-memory DuckDB with known A/B 5-run values
# ---------------------------------------------------------------------------

def _make_seeded_db(
    tmp_path: Path,
    model: str = "claude-sonnet-4-6",
    revisions: list[str] | None = None,
    f1_a_by_revision: dict | None = None,
    f1_b_by_revision: dict | None = None,
) -> duckdb.DuckDBPyConnection:
    """Create an in-memory DuckDB with grid_cells seeded with known F1 values.

    Defaults: 3 revisions, deterministic A/B values for paired-diff assertions.
    """
    if revisions is None:
        revisions = ["early", "mid", "late"]
    if f1_a_by_revision is None:
        f1_a_by_revision = {
            "early": [0.60, 0.62, 0.61, 0.63, 0.60],
            "mid":   [0.70, 0.72, 0.71, 0.73, 0.70],
            "late":  [0.80, 0.82, 0.81, 0.83, 0.80],
        }
    if f1_b_by_revision is None:
        f1_b_by_revision = {
            "early": [0.55, 0.57, 0.56, 0.58, 0.55],
            "mid":   [0.65, 0.67, 0.66, 0.68, 0.65],
            "late":  [0.75, 0.77, 0.76, 0.78, 0.75],
        }

    con = duckdb.connect(str(tmp_path / "test.ddb"))
    con.execute(DDL)

    yoke_min = "2026-06-11T00:00"

    for revision in revisions:
        a_runs = f1_a_by_revision[revision]
        b_runs = f1_b_by_revision[revision]

        for run_idx, (f1_a, f1_b) in enumerate(zip(a_runs, b_runs)):
            for arm, f1_val in (("A", f1_a), ("B", f1_b)):
                import hashlib
                cell_id = hashlib.sha256(
                    f"{arm}{model}{revision}{run_idx}".encode()
                ).hexdigest()[:12]
                con.execute(
                    """
                    INSERT OR REPLACE INTO grid_cells
                      (cell_id, arm, model, revision, run_idx,
                       config_hash, snapshot_hash, intent_map_sha,
                       split_hash, rng_seed, macro_f1, token_cost,
                       cost_usd, yoke_minute, ts)
                    VALUES (?,?,?,?,?, ?,?,?,?, ?,?,?, ?,?,?)
                    """,
                    [
                        cell_id, arm, model, revision, run_idx,
                        "cfg_test", "snap_test", "map_test",
                        "", run_idx, f1_val, 0,
                        None, yoke_min, "2026-06-11T00:00:00+00:00",
                    ],
                )

    return con


# ---------------------------------------------------------------------------
# Test 1: pivot to per-(revision, run_idx) paired diffs, mean_diff per revision
# ---------------------------------------------------------------------------

def test_paired_difference_report_computes_mean_diff(tmp_path: Path) -> None:
    """Test 1: report pivots grid_cells and computes correct paired mean_diff per revision."""
    from setdrift_eval.drift.paired_stats import paired_difference_report

    model = "claude-sonnet-4-6"
    f1_a = {
        "early": [0.60, 0.62, 0.61, 0.63, 0.60],
        "mid":   [0.70, 0.72, 0.71, 0.73, 0.70],
        "late":  [0.80, 0.82, 0.81, 0.83, 0.80],
    }
    f1_b = {
        "early": [0.55, 0.57, 0.56, 0.58, 0.55],
        "mid":   [0.65, 0.67, 0.66, 0.68, 0.65],
        "late":  [0.75, 0.77, 0.76, 0.78, 0.75],
    }
    con = _make_seeded_db(tmp_path, model=model, f1_a_by_revision=f1_a, f1_b_by_revision=f1_b)

    results = paired_difference_report(con, model=model)

    # Result is keyed by revision
    assert set(results.keys()) == {"early", "mid", "late"}, (
        f"Expected keys {{'early', 'mid', 'late'}}, got {set(results.keys())}"
    )

    for revision in ("early", "mid", "late"):
        result = results[revision]
        a_runs = f1_a[revision]
        b_runs = f1_b[revision]

        expected_mean_a = sum(a_runs) / len(a_runs)
        expected_mean_b = sum(b_runs) / len(b_runs)
        expected_diff = expected_mean_a - expected_mean_b

        assert abs(result.mean_A - expected_mean_a) < 1e-9, (
            f"Revision {revision}: mean_A={result.mean_A:.6f}, expected {expected_mean_a:.6f}"
        )
        assert abs(result.mean_B - expected_mean_b) < 1e-9, (
            f"Revision {revision}: mean_B={result.mean_B:.6f}, expected {expected_mean_b:.6f}"
        )
        assert abs(result.paired_diff - expected_diff) < 1e-9, (
            f"Revision {revision}: paired_diff={result.paired_diff:.6f}, expected {expected_diff:.6f}"
        )
        assert result.n_runs == 5, (
            f"Revision {revision}: n_runs={result.n_runs}, expected 5"
        )
        assert result.revision == revision, (
            f"result.revision={result.revision!r} != {revision!r}"
        )
        assert result.model == model, (
            f"result.model={result.model!r} != {model!r}"
        )


# ---------------------------------------------------------------------------
# Test 2: t_stat / p_value via ttest_rel; nan-guard for n_runs < 2
# ---------------------------------------------------------------------------

def test_ttest_rel_computed_and_nan_guard(tmp_path: Path) -> None:
    """Test 2: t_stat/p_value via scipy.stats.ttest_rel; n_runs<2 returns nan + reason."""
    from scipy.stats import ttest_rel
    from setdrift_eval.drift.paired_stats import paired_difference_report

    model = "claude-sonnet-4-6"
    # Use values with non-constant paired differences to avoid catastrophic
    # cancellation in ttest_rel (which returns inf when all diffs are identical).
    f1_a = {"only": [0.70, 0.74, 0.68, 0.73, 0.72]}
    f1_b = {"only": [0.65, 0.61, 0.66, 0.60, 0.63]}

    con = duckdb.connect(str(tmp_path / "test.ddb"))
    con.execute(DDL)
    import hashlib
    yoke_min = "2026-06-11T00:00"
    for run_idx, (a, b) in enumerate(zip(f1_a["only"], f1_b["only"])):
        for arm, f1_val in (("A", a), ("B", b)):
            cell_id = hashlib.sha256(f"{arm}{model}only{run_idx}".encode()).hexdigest()[:12]
            con.execute(
                """INSERT OR REPLACE INTO grid_cells
                   (cell_id,arm,model,revision,run_idx,config_hash,snapshot_hash,
                    intent_map_sha,split_hash,rng_seed,macro_f1,token_cost,
                    cost_usd,yoke_minute,ts)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [cell_id, arm, model, "only", run_idx,
                 "c", "s", "m", "", run_idx, f1_val, 0, None, yoke_min,
                 "2026-06-11T00:00:00+00:00"],
            )

    results = paired_difference_report(con, model=model)
    r = results["only"]

    # Verify t_stat and p_value match scipy.stats.ttest_rel
    stat, pval = ttest_rel(f1_a["only"], f1_b["only"])
    assert abs(r.t_stat - stat) < 1e-9, (
        f"t_stat mismatch: got {r.t_stat:.6f}, expected {stat:.6f}"
    )
    assert abs(r.p_value - pval) < 1e-9, (
        f"p_value mismatch: got {r.p_value:.6f}, expected {pval:.6f}"
    )

    # nan-guard: n_runs < 2 must return nan and a non-empty reason
    con2 = duckdb.connect(str(tmp_path / "degenerate.ddb"))
    con2.execute(DDL)
    # Insert only 1 run per arm (n=1 — degenerate)
    for arm, f1_val in (("A", 0.70), ("B", 0.65)):
        cell_id = hashlib.sha256(f"{arm}{model}degen0".encode()).hexdigest()[:12]
        con2.execute(
            """INSERT OR REPLACE INTO grid_cells
               (cell_id,arm,model,revision,run_idx,config_hash,snapshot_hash,
                intent_map_sha,split_hash,rng_seed,macro_f1,token_cost,
                cost_usd,yoke_minute,ts)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [cell_id, arm, model, "degen", 0,
             "c", "s", "m", "", 0, f1_val, 0, None, yoke_min,
             "2026-06-11T00:00:00+00:00"],
        )

    results2 = paired_difference_report(con2, model=model)
    r2 = results2["degen"]
    assert math.isnan(r2.t_stat), (
        f"Expected nan t_stat for n_runs<2 (degenerate band), got {r2.t_stat}"
    )
    assert math.isnan(r2.p_value), (
        f"Expected nan p_value for n_runs<2 (degenerate band), got {r2.p_value}"
    )
    assert r2.reason, "reason must not be empty even for degenerate n_runs<2"
    assert r2.n_runs == 1, f"Expected n_runs=1, got {r2.n_runs}"


# ---------------------------------------------------------------------------
# Test 3: No cross-model average — report is per (model, revision) only (§7-2)
# ---------------------------------------------------------------------------

def test_no_cross_model_average(tmp_path: Path) -> None:
    """Test 3: paired_difference_report is per (model, revision); no cross-model averaging."""
    from setdrift_eval.drift.paired_stats import paired_difference_report

    # Seed data for two models separately
    con = duckdb.connect(str(tmp_path / "test.ddb"))
    con.execute(DDL)
    import hashlib
    yoke_min = "2026-06-11T00:00"

    for model, f1_offset in [("claude-sonnet-4-6", 0.0), ("claude-haiku-4-5-20251001", -0.1)]:
        for arm, base in (("A", 0.70 + f1_offset), ("B", 0.60 + f1_offset)):
            for run_idx in range(5):
                f1_val = base + run_idx * 0.01
                cell_id = hashlib.sha256(
                    f"{arm}{model}only{run_idx}".encode()
                ).hexdigest()[:12]
                con.execute(
                    """INSERT OR REPLACE INTO grid_cells
                       (cell_id,arm,model,revision,run_idx,config_hash,snapshot_hash,
                        intent_map_sha,split_hash,rng_seed,macro_f1,token_cost,
                        cost_usd,yoke_minute,ts)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    [cell_id, arm, model, "only", run_idx,
                     "c", "s", "m", "", run_idx, f1_val, 0, None, yoke_min,
                     "2026-06-11T00:00:00+00:00"],
                )

    # Calling paired_difference_report with Sonnet model should NOT mix in Haiku rows
    results_sonnet = paired_difference_report(con, model="claude-sonnet-4-6")
    results_haiku = paired_difference_report(con, model="claude-haiku-4-5-20251001")

    # Each result must only contain the requested model
    for revision, r in results_sonnet.items():
        assert r.model == "claude-sonnet-4-6", (
            f"Cross-model contamination: result.model={r.model!r} in Sonnet report (§7-2)"
        )
    for revision, r in results_haiku.items():
        assert r.model == "claude-haiku-4-5-20251001", (
            f"Cross-model contamination: result.model={r.model!r} in Haiku report (§7-2)"
        )

    # The mean_A values must differ between models (not the same averaged value)
    assert abs(
        results_sonnet["only"].mean_A - results_haiku["only"].mean_A
    ) > 0.05, (
        "Sonnet and Haiku mean_A should differ (not averaged together) — §7-2 violation check"
    )


# ---------------------------------------------------------------------------
# Test 4: PairedDiffResult always carries non-empty reason (field_validator)
# ---------------------------------------------------------------------------

def test_paired_diff_result_reason_always_populated(tmp_path: Path) -> None:
    """Test 4: PairedDiffResult.reason is never empty (field_validator enforces it)."""
    from setdrift_eval.drift.paired_stats import PairedDiffResult
    from pydantic import ValidationError

    # Valid result: reason must not be empty
    with pytest.raises(ValidationError, match="reason"):
        PairedDiffResult(
            revision="early",
            model="claude-sonnet-4-6",
            mean_A=0.70,
            mean_B=0.65,
            paired_diff=0.05,
            noise_band_A=(0.68, 0.72),
            noise_band_B=(0.63, 0.67),
            t_stat=2.5,
            p_value=0.03,
            n_runs=5,
            exceeds_b_upper_band=True,
            reason="",  # empty reason — must raise
        )

    # Whitespace-only reason must also raise
    with pytest.raises(ValidationError, match="reason"):
        PairedDiffResult(
            revision="early",
            model="claude-sonnet-4-6",
            mean_A=0.70,
            mean_B=0.65,
            paired_diff=0.05,
            noise_band_A=(0.68, 0.72),
            noise_band_B=(0.63, 0.67),
            t_stat=2.5,
            p_value=0.03,
            n_runs=5,
            exceeds_b_upper_band=True,
            reason="   ",  # whitespace-only — must raise
        )

    # Valid non-empty reason must pass
    r = PairedDiffResult(
        revision="early",
        model="claude-sonnet-4-6",
        mean_A=0.70,
        mean_B=0.65,
        paired_diff=0.05,
        noise_band_A=(0.68, 0.72),
        noise_band_B=(0.63, 0.67),
        t_stat=2.5,
        p_value=0.03,
        n_runs=5,
        exceeds_b_upper_band=True,
        reason="arm A mean 0.7000 exceeds arm B upper band edge 0.6700",
    )
    assert r.reason  # truthy

    # ConfigDict(extra="forbid") — unknown fields must raise
    with pytest.raises(ValidationError):
        PairedDiffResult(
            revision="early",
            model="claude-sonnet-4-6",
            mean_A=0.70,
            mean_B=0.65,
            paired_diff=0.05,
            noise_band_A=(0.68, 0.72),
            noise_band_B=(0.63, 0.67),
            t_stat=2.5,
            p_value=0.03,
            n_runs=5,
            exceeds_b_upper_band=True,
            reason="valid reason",
            unknown_extra_field="forbidden",  # extra="forbid" must reject this
        )


# ---------------------------------------------------------------------------
# Test 5: noise_band consumed via frozen scorer (import check)
# ---------------------------------------------------------------------------

def test_paired_stats_imports_frozen_noise_band() -> None:
    """Test 5: paired_stats.py imports noise_band from setdrift_eval.telemetry.scorer (FROZEN RULER)."""
    import ast

    paired_stats_path = Path(__file__).resolve().parents[1] / "paired_stats.py"
    assert paired_stats_path.exists(), f"paired_stats.py not found at {paired_stats_path}"

    source = paired_stats_path.read_text(encoding="utf-8")

    # Must contain FROZEN RULER comment
    assert "FROZEN RULER" in source, (
        "paired_stats.py must contain '# FROZEN RULER' comment "
        "marking the frozen scorer import"
    )

    # Must import noise_band from setdrift_eval.telemetry.scorer
    tree = ast.parse(source)
    scorer_imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "scorer" in node.module:
                for alias in node.names:
                    scorer_imports.add(alias.name)

    assert "noise_band" in scorer_imports, (
        "paired_stats.py must import noise_band from setdrift_eval.telemetry.scorer "
        "(FROZEN RULER — never re-implement)"
    )

    # Must NOT re-implement noise_band (def noise_band in the file would be a violation)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "noise_band":
            pytest.fail(
                "paired_stats.py must NOT define noise_band() — "
                "it must import the frozen ruler from scorer.py (Goodhart firewall)"
            )

    # Must use ttest_rel from scipy.stats (not a re-implementation)
    assert "ttest_rel" in source, (
        "paired_stats.py must use scipy.stats.ttest_rel for paired t-test (RESEARCH Pattern 5)"
    )


# ---------------------------------------------------------------------------
# Test 6: exceeds_b_upper_band is True when paired_diff > (b_band_high - mean_B)
# ---------------------------------------------------------------------------

def test_exceeds_b_upper_band_logic(tmp_path: Path) -> None:
    """Test 6: exceeds_b_upper_band correctly reflects whether A mean exceeds B upper band."""
    from setdrift_eval.drift.paired_stats import paired_difference_report
    from setdrift_eval.telemetry.scorer import noise_band as frozen_noise_band

    model = "claude-sonnet-4-6"
    # Choose values where A clearly exceeds B upper band
    f1_a_runs = [0.90, 0.91, 0.90, 0.92, 0.91]  # mean ~0.908
    f1_b_runs = [0.60, 0.61, 0.60, 0.62, 0.61]  # mean ~0.608, band_high ~0.61

    con = duckdb.connect(str(tmp_path / "test.ddb"))
    con.execute(DDL)
    import hashlib
    yoke_min = "2026-06-11T00:00"
    for run_idx, (a, b) in enumerate(zip(f1_a_runs, f1_b_runs)):
        for arm, f1_val in (("A", a), ("B", b)):
            cell_id = hashlib.sha256(f"{arm}{model}rev{run_idx}".encode()).hexdigest()[:12]
            con.execute(
                """INSERT OR REPLACE INTO grid_cells
                   (cell_id,arm,model,revision,run_idx,config_hash,snapshot_hash,
                    intent_map_sha,split_hash,rng_seed,macro_f1,token_cost,
                    cost_usd,yoke_minute,ts)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [cell_id, arm, model, "rev", run_idx,
                 "c", "s", "m", "", run_idx, f1_val, 0, None, yoke_min,
                 "2026-06-11T00:00:00+00:00"],
            )

    results = paired_difference_report(con, model=model)
    r = results["rev"]

    # Compute expected exceeds_b_upper_band
    _, b_band_high = frozen_noise_band(f1_b_runs)
    expected_exceeds = r.mean_A > b_band_high

    assert r.exceeds_b_upper_band == expected_exceeds, (
        f"exceeds_b_upper_band={r.exceeds_b_upper_band} but expected {expected_exceeds} "
        f"(mean_A={r.mean_A:.4f}, b_band_high={b_band_high:.4f})"
    )
    # With these values, A should clearly exceed B's upper band
    assert r.exceeds_b_upper_band is True, (
        "With f1_A~0.91 and f1_B~0.61, exceeds_b_upper_band must be True"
    )


def test_zero_within_pair_variance_is_handled(tmp_path: Path, recwarn) -> None:
    """CR-02 guard: deterministic replay (5 identical runs per arm) gives paired
    diffs with exactly zero variance. ttest_rel would divide by a zero standard
    error and emit nan/inf with a RuntimeWarning. The reporter must instead report
    nan t/p with an explicit deterministic reason — and must NOT raise or warn.

    This mirrors the frozen ruler's own band generation
    (run_health: ``[macro_f1(yt, yp) for _ in range(5)]`` → identical values),
    so zero variance is the EXPECTED project condition, not an error (CR-02
    DISPUTED: the band is deterministic by design; uncertainty comes from
    bootstrap_ci, not run-to-run variance).
    """
    from setdrift_eval.drift.paired_stats import paired_difference_report

    # Arm A: five identical 0.80; Arm B: five identical 0.70 → diffs all +0.10,
    # variance exactly 0.
    con = _make_seeded_db(
        tmp_path,
        model="claude-sonnet-4-6",
        revisions=["mid"],
        f1_a_by_revision={"mid": [0.80, 0.80, 0.80, 0.80, 0.80]},
        f1_b_by_revision={"mid": [0.70, 0.70, 0.70, 0.70, 0.70]},
    )

    results = paired_difference_report(con, model="claude-sonnet-4-6")
    r = results["mid"]

    # paired_diff is exact and correct even though significance is undefined.
    assert math.isclose(r.paired_diff, 0.10, abs_tol=1e-9)
    # t/p are nan (not inf, not a spurious finite value) under zero variance.
    assert math.isnan(r.t_stat), f"expected nan t_stat under zero variance, got {r.t_stat}"
    assert math.isnan(r.p_value), f"expected nan p_value under zero variance, got {r.p_value}"
    # Reason explains the deterministic case so a reader is never misled.
    assert "zero within-pair variance" in r.reason
    # No scipy precision-loss / divide-by-zero RuntimeWarning escaped.
    assert not [w for w in recwarn.list if issubclass(w.category, RuntimeWarning)], (
        "zero-variance pairs must be short-circuited before ttest_rel — no RuntimeWarning"
    )

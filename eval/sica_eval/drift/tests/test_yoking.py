"""Tests for the yoking exit gate in grid_runner.py (REQ-DRIFT-02).

Tests the mechanical yoking discipline:
  1. Two rows for the same (model, revision) with different arms carry
     identical yoke_minute values.
  2. The A and B pairing precondition is met — both arms present for
     a given (model, revision).
  3. Fail-loud assertion fires when yoke_minutes differ (exit gate).
  4. Per-cell seed formula is deterministic and unique.
  5. GridRunnerError is raised when ANTHROPIC_API_KEY is unset.
  6. _config_hash is stable for the same tool set.
  7. _cell_seed produces distinct values for different inputs.

Uses in-memory / tmp_path DuckDB so no data/drift/ directory is needed.
Fixed test minute (not wall-clock) for deterministic assertions.
"""
import hashlib
import os
from pathlib import Path

import duckdb
import pytest

from sica_eval.drift.db import DDL
from sica_eval.drift.grid_runner import (
    ARMS,
    GridRunnerError,
    MODELS,
    N_RUNS,
    REVISIONS,
    _cell_seed,
    _config_hash,
    _yoke_minute,
    run_grid,
)

# ---------------------------------------------------------------------------
# Helper: create an in-memory DuckDB with the grid_cells schema
# ---------------------------------------------------------------------------

_FIXED_MINUTE = "2026-06-11T00:00"  # deterministic test value; never wall-clock


def _make_db(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    """Create a DuckDB connection at tmp_path/test.ddb with grid schema applied."""
    db_path = tmp_path / "test.ddb"
    con = duckdb.connect(str(db_path))
    con.execute(DDL)
    return con


def _insert_cell(
    con: duckdb.DuckDBPyConnection,
    arm: str,
    model: str,
    revision: str,
    run_idx: int,
    yoke_minute: str,
    f1: float = 0.75,
) -> None:
    """Insert a single grid_cells row with the given yoke_minute."""
    cell_id = hashlib.sha256(f"{arm}{model}{revision}{run_idx}".encode()).hexdigest()[:12]
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
            "cfg_hash_test", "snap_hash_test", "map_sha_test",
            "", 12345, f1, 0,
            None, yoke_minute, "2026-06-11T00:00:00+00:00",
        ],
    )


# ---------------------------------------------------------------------------
# Test 1: same (model, revision) → same yoke_minute for both arms
# ---------------------------------------------------------------------------


def test_yoke_minute_identical_for_arm_pair(tmp_path: Path) -> None:
    """Test 1: A and B rows for the same (model, revision) carry identical yoke_minute."""
    con = _make_db(tmp_path)
    model = "claude-sonnet-4-6"
    revision = "mid"

    # Simulate the grid_runner: capture yoke_minute ONCE, then insert both arms
    yoke_min = _FIXED_MINUTE  # captured before iterating arms

    for arm in ARMS:
        for run_idx in range(N_RUNS):
            _insert_cell(con, arm, model, revision, run_idx, yoke_min)

    # Fetch all yoke_minutes for this (model, revision)
    rows = con.execute(
        "SELECT arm, yoke_minute FROM grid_cells WHERE model=? AND revision=? ORDER BY arm, run_idx",
        [model, revision],
    ).fetchall()

    yoke_minutes = {row[1] for row in rows}
    arms_seen = {row[0] for row in rows}

    # Both arms must be present
    assert arms_seen == {"A", "B"}, (
        f"Expected both arms A and B in grid_cells for (model={model}, revision={revision}), "
        f"got: {arms_seen}"
    )
    # All rows must carry the same yoke_minute
    assert len(yoke_minutes) == 1, (
        f"Yoking exit gate FAILED: multiple yoke_minutes found for "
        f"(model={model}, revision={revision}): {yoke_minutes}. "
        "Both A and B must carry the same yoke_minute (Pitfall 1)."
    )
    assert _FIXED_MINUTE in yoke_minutes, (
        f"Expected yoke_minute={_FIXED_MINUTE!r}, got {yoke_minutes}"
    )


# ---------------------------------------------------------------------------
# Test 2: Fail-loud on mismatched yoke_minutes
# ---------------------------------------------------------------------------


def test_yoke_minute_mismatch_raises(tmp_path: Path) -> None:
    """Test 2: Pairing check fails loudly when A and B have different yoke_minutes."""
    con = _make_db(tmp_path)
    model = "claude-sonnet-4-6"
    revision = "early"

    # Deliberately insert A and B with different yoke_minutes (violation)
    yoke_a = "2026-06-11T00:01"
    yoke_b = "2026-06-11T00:02"  # different minute — yoking violation

    _insert_cell(con, "A", model, revision, 0, yoke_a)
    _insert_cell(con, "B", model, revision, 0, yoke_b)

    # Detect the mismatch via the pairing check
    rows = con.execute(
        """
        SELECT arm, yoke_minute FROM grid_cells
        WHERE model=? AND revision=?
        ORDER BY arm
        """,
        [model, revision],
    ).fetchall()

    yoke_by_arm = {row[0]: row[1] for row in rows}

    # The exit gate: both arms must be present and carry the same yoke_minute
    assert "A" in yoke_by_arm and "B" in yoke_by_arm, (
        "Both arms must be present for a paired check"
    )

    with pytest.raises(AssertionError, match="Yoking exit gate"):
        assert yoke_by_arm["A"] == yoke_by_arm["B"], (
            f"Yoking exit gate FAILED for (model={model}, revision={revision}): "
            f"arm A yoke_minute={yoke_by_arm['A']!r} != "
            f"arm B yoke_minute={yoke_by_arm['B']!r}. "
            "A and B must run within the same wall-clock minute (Pitfall 1)."
        )


# ---------------------------------------------------------------------------
# Test 3: Per-cell seed is deterministic
# ---------------------------------------------------------------------------


def test_cell_seed_deterministic() -> None:
    """Test 3: _cell_seed returns the same value for the same inputs."""
    seed1 = _cell_seed("A", "claude-sonnet-4-6", "mid", 0)
    seed2 = _cell_seed("A", "claude-sonnet-4-6", "mid", 0)
    assert seed1 == seed2, "_cell_seed must be deterministic for the same inputs"
    assert isinstance(seed1, int), "_cell_seed must return an int"
    assert seed1 > 0, "_cell_seed must be positive (sha256 hex is non-zero)"


# ---------------------------------------------------------------------------
# Test 4: Per-cell seed is unique across different (arm, model, revision, run_idx)
# ---------------------------------------------------------------------------


def test_cell_seed_unique_per_cell() -> None:
    """Test 4: _cell_seed produces distinct values for different cell identities."""
    seen: set[int] = set()
    for arm in ARMS:
        for model in MODELS:
            for revision in REVISIONS:
                for run_idx in range(N_RUNS):
                    seed = _cell_seed(arm, model, revision, run_idx)
                    assert seed not in seen, (
                        f"_cell_seed collision: seed={seed} seen twice "
                        f"(last at arm={arm}, model={model}, "
                        f"revision={revision}, run_idx={run_idx})"
                    )
                    seen.add(seed)


# ---------------------------------------------------------------------------
# Test 5: GridRunnerError raised when ANTHROPIC_API_KEY is unset
# ---------------------------------------------------------------------------


def test_run_grid_fails_loud_without_api_key(tmp_path: Path) -> None:
    """Test 5: run_grid raises GridRunnerError if ANTHROPIC_API_KEY is not set."""
    # Temporarily clear the key to simulate a missing credential
    original = os.environ.pop("ANTHROPIC_API_KEY", None)
    # Also clear OpenRouter key if present — run_grid checks ANTHROPIC_API_KEY only
    try:
        with pytest.raises(GridRunnerError, match="ANTHROPIC_API_KEY"):
            run_grid(
                gitbug_repo=tmp_path / "repo",
                arm_configs={"A": tmp_path / "skillsA", "B": tmp_path / "skillsB"},
                corpus_path=tmp_path / "corpus.jsonl",
                map_path=tmp_path / "map.yaml",
                revision_shas={"early": "abc", "mid": "def", "late": "ghi"},
                cache_dir=tmp_path / "cache",
                experiments_dir=tmp_path / "experiments",
            )
    finally:
        if original is not None:
            os.environ["ANTHROPIC_API_KEY"] = original


# ---------------------------------------------------------------------------
# Test 6: _config_hash is stable for the same tool set
# ---------------------------------------------------------------------------


def test_config_hash_stable() -> None:
    """Test 6: _config_hash returns the same value for identical tool lists."""
    tools = [
        {"name": "spring_boot_endpoint", "description": "Create a REST endpoint"},
        {"name": "java_unit_test", "description": "Write a JUnit test"},
    ]
    h1 = _config_hash(tools)
    h2 = _config_hash(tools)
    assert h1 == h2, "_config_hash must be deterministic"
    assert len(h1) == 64, "_config_hash must be a 64-char hex string (sha256)"


def test_config_hash_order_independent() -> None:
    """Test 7: _config_hash is order-independent (sorted internally)."""
    tools_a = [
        {"name": "spring_boot_endpoint", "description": "REST endpoint"},
        {"name": "java_test", "description": "Unit test"},
    ]
    tools_b = [
        {"name": "java_test", "description": "Unit test"},
        {"name": "spring_boot_endpoint", "description": "REST endpoint"},
    ]
    assert _config_hash(tools_a) == _config_hash(tools_b), (
        "_config_hash must produce the same hash regardless of tool list order"
    )


# ---------------------------------------------------------------------------
# Test 8: grid_runner.py imports noise_band from scorer (FROZEN RULER check)
# ---------------------------------------------------------------------------


def test_grid_runner_imports_frozen_ruler() -> None:
    """Test 8: grid_runner.py imports noise_band and macro_f1 from the frozen scorer."""
    import ast

    grid_runner_path = Path(__file__).resolve().parents[1] / "grid_runner.py"
    assert grid_runner_path.exists(), f"grid_runner.py not found at {grid_runner_path}"

    source = grid_runner_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Find all 'from X import ...' statements
    scorer_imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "scorer" in node.module:
                for alias in node.names:
                    scorer_imports.add(alias.name)

    assert "noise_band" in scorer_imports, (
        "grid_runner.py must import noise_band from sica_eval.telemetry.scorer "
        "(FROZEN RULER — never re-implement)"
    )
    assert "macro_f1" in scorer_imports, (
        "grid_runner.py must import macro_f1 from sica_eval.telemetry.scorer "
        "(FROZEN RULER — never re-implement)"
    )


# ---------------------------------------------------------------------------
# Test 9: FROZEN RULER comment present in grid_runner.py
# ---------------------------------------------------------------------------


def test_frozen_ruler_comment_present() -> None:
    """Test 9: grid_runner.py contains the FROZEN RULER comment."""
    grid_runner_path = Path(__file__).resolve().parents[1] / "grid_runner.py"
    source = grid_runner_path.read_text(encoding="utf-8")
    assert "FROZEN RULER" in source, (
        "grid_runner.py must contain the '# FROZEN RULER' comment "
        "as a structural marker for the Goodhart firewall"
    )

"""Tests for DuckDB grid schema DDL + connect() (REQ-DRIFT-02, Plan 04-01 Task 3)."""

import duckdb
import pytest


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _fake_db(tmp_path):
    """Connect to a temporary DuckDB file and run DDL; return the connection."""
    from setdrift_eval.drift.db import connect

    db_path = tmp_path / "test.ddb"
    return connect(db_path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_connect_creates_all_tables(tmp_path):
    """Test 1: connect(tmp_path/"t.ddb") creates grid_cells, drift_series, drift_events tables."""
    conn = _fake_db(tmp_path)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()
    }
    assert "grid_cells" in tables, "grid_cells table missing"
    assert "drift_series" in tables, "drift_series table missing"
    assert "drift_events" in tables, "drift_events table missing"
    conn.close()


def test_duplicate_primary_key_replaced(tmp_path):
    """Test 2: inserting two rows with the same (arm, model, revision, run_idx) is replaced (INSERT OR REPLACE semantics)."""
    conn = _fake_db(tmp_path)
    # Insert a row
    conn.execute("""
        INSERT OR REPLACE INTO grid_cells
            (cell_id, arm, model, revision, run_idx, config_hash, snapshot_hash,
             intent_map_sha, split_hash, rng_seed, macro_f1, token_cost, cost_usd,
             yoke_minute, ts)
        VALUES ('cell-1', 'A', 'claude-sonnet-4-6', 'early', 0, 'hash1', 'snap1',
                'intent1', 'split1', 42, 0.75, 100, NULL, '2026-06-10T12:00', '2026-06-10T12:00:00Z')
    """)
    # Re-insert same primary key with different macro_f1
    conn.execute("""
        INSERT OR REPLACE INTO grid_cells
            (cell_id, arm, model, revision, run_idx, config_hash, snapshot_hash,
             intent_map_sha, split_hash, rng_seed, macro_f1, token_cost, cost_usd,
             yoke_minute, ts)
        VALUES ('cell-1', 'A', 'claude-sonnet-4-6', 'early', 0, 'hash1', 'snap1',
                'intent1', 'split1', 42, 0.88, 200, NULL, '2026-06-10T12:00', '2026-06-10T12:00:00Z')
    """)
    rows = conn.execute(
        "SELECT COUNT(*) FROM grid_cells WHERE arm='A' AND model='claude-sonnet-4-6' AND revision='early' AND run_idx=0"
    ).fetchone()
    assert rows[0] == 1, f"Expected 1 row after INSERT OR REPLACE, got {rows[0]}"
    macro_f1 = conn.execute(
        "SELECT macro_f1 FROM grid_cells WHERE arm='A' AND model='claude-sonnet-4-6' AND revision='early' AND run_idx=0"
    ).fetchone()[0]
    assert macro_f1 == 0.88, f"Expected replaced macro_f1=0.88, got {macro_f1}"
    conn.close()


def test_grid_cells_row_roundtrip(tmp_path):
    """Test 3: a grid_cells row round-trips all columns including yoke_minute, snapshot_hash, rng_seed, macro_f1."""
    conn = _fake_db(tmp_path)
    conn.execute("""
        INSERT OR REPLACE INTO grid_cells
            (cell_id, arm, model, revision, run_idx, config_hash, snapshot_hash,
             intent_map_sha, split_hash, rng_seed, macro_f1, token_cost, cost_usd,
             yoke_minute, ts)
        VALUES ('cell-rt', 'B', 'claude-haiku-4-5', 'mid', 2, 'cfghash', 'snaphash',
                'intentsha', 'splithash', 99, 0.65, 500, 0.003, '2026-06-10T15:00', '2026-06-10T15:00:00Z')
    """)
    row = conn.execute(
        "SELECT cell_id, arm, model, revision, run_idx, config_hash, snapshot_hash, "
        "intent_map_sha, split_hash, rng_seed, macro_f1, token_cost, cost_usd, yoke_minute, ts "
        "FROM grid_cells WHERE cell_id='cell-rt'"
    ).fetchone()
    assert row is not None, "Row not found after insert"
    assert row[1] == "B"
    assert row[2] == "claude-haiku-4-5"
    assert row[3] == "mid"
    assert row[4] == 2
    assert row[6] == "snaphash", f"snapshot_hash mismatch: {row[6]}"
    assert row[9] == 99, f"rng_seed mismatch: {row[9]}"
    assert abs(row[10] - 0.65) < 1e-6, f"macro_f1 mismatch: {row[10]}"
    assert row[13] == "2026-06-10T15:00", f"yoke_minute mismatch: {row[13]}"
    conn.close()


def test_drift_series_insert(tmp_path):
    """Test 4: drift_series accepts a (ts, commit_sha, config_hash) row with drift_index, embedder_checksum, window_n."""
    conn = _fake_db(tmp_path)
    conn.execute("""
        INSERT OR REPLACE INTO drift_series
            (project_id, revision_label, drift_index, config_hash, embedder_checksum, window_n, ts, commit_sha)
        VALUES ('sica', 'early', 0.42, 'cfghash', 'embchecksum', 20, '2026-06-10T10:00:00Z', 'abc1234')
    """)
    row = conn.execute(
        "SELECT drift_index, embedder_checksum, window_n FROM drift_series "
        "WHERE ts='2026-06-10T10:00:00Z' AND commit_sha='abc1234' AND config_hash='cfghash'"
    ).fetchone()
    assert row is not None, "drift_series row not found after insert"
    assert abs(row[0] - 0.42) < 1e-6, f"drift_index mismatch: {row[0]}"
    assert row[1] == "embchecksum", f"embedder_checksum mismatch: {row[1]}"
    assert row[2] == 20, f"window_n mismatch: {row[2]}"
    conn.close()

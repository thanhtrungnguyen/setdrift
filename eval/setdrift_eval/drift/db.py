"""DuckDB schema + insert/query helpers for the Phase 4 drift grid.

What this module does: owns DDL, connect(), insert helpers for grid_cells,
drift_series, and drift_events tables. All raw data stays under data/drift/
(gitignored). Scrubbed summaries are written to experiments/ by grid_runner.

What it does NOT do: never writes to experiments/ directly; never reads scorer.py
or modifies the frozen Phase-2 ruler.

Eval-side fail-loud: DuckDB errors propagate (no bare except).
"""

import os
from pathlib import Path

import duckdb

DB_PATH = Path(os.environ.get("SETDRIFT_DRIFT_DB", "data/drift/results.ddb"))

# ---------------------------------------------------------------------------
# DDL — three tables for the Phase 4 drift grid (from RESEARCH.md Pattern 5)
# ---------------------------------------------------------------------------

DDL = """
CREATE TABLE IF NOT EXISTS grid_cells (
    cell_id       TEXT,
    arm           TEXT NOT NULL,
    model         TEXT NOT NULL,
    revision      TEXT NOT NULL,
    run_idx       INTEGER NOT NULL,
    config_hash   TEXT,
    snapshot_hash TEXT,
    intent_map_sha TEXT,
    split_hash    TEXT,
    rng_seed      INTEGER,
    macro_f1      DOUBLE,
    token_cost    BIGINT,
    cost_usd      DOUBLE,
    yoke_minute   TEXT,
    ts            TEXT,
    PRIMARY KEY (arm, model, revision, run_idx)
);

CREATE TABLE IF NOT EXISTS drift_series (
    ts                TEXT NOT NULL,
    commit_sha        TEXT NOT NULL,
    config_hash       TEXT NOT NULL,
    project_id        TEXT,
    revision_label    TEXT,
    drift_index       DOUBLE,
    embedder_checksum TEXT,
    window_n          INTEGER,
    PRIMARY KEY (ts, commit_sha, config_hash)
);

CREATE TABLE IF NOT EXISTS drift_events (
    event_id     TEXT PRIMARY KEY,
    ts           TEXT,
    drift_type   TEXT,
    head_sha     TEXT,
    model_id     TEXT,
    f1_at_event_A DOUBLE,
    f1_at_event_B DOUBLE,
    notes        TEXT
);
"""


def connect(db_path: Path = DB_PATH) -> duckdb.DuckDBPyConnection:
    """Open (or create) a DuckDB database at db_path and apply DDL.

    Guards parent directory creation with parents=True, exist_ok=True before
    first write (orchestrator.py pattern). DuckDB errors propagate (fail-loud).

    Args:
        db_path: Path to the DuckDB file. Defaults to DB_PATH (env-var-overridable).

    Returns:
        duckdb.DuckDBPyConnection: Open connection with all three tables present.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    conn.execute(DDL)
    return conn

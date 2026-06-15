"""DuckDB query layer over the per-session clean events.jsonl (Exit Gate #5).

Fail-loud on the read side (`ignore_errors=false` — DuckDB throws on any
malformed line rather than skipping it). Answers the two gate queries
(events-per-session, missing-canary-count) and auto-promotes the JSONL archive
to Parquet at ~500MB. Everything stays inside the gitignored data wall.
"""
import os
from datetime import date
from pathlib import Path

import duckdb

TELEMETRY_DIR = Path(os.environ.get("SETDRIFT_TELEMETRY_DIR", "data/telemetry"))
PARQUET_DIR = TELEMETRY_DIR / "parquet"
PARQUET_THRESHOLD_BYTES = 500 * 1024 * 1024  # ~500 MB
# MUST match the harness constant in 01-04 (shared canary identity).
CANARY_TOOL_NAME = "SETDRIFT_CANARY_TOOL_V1"


def _glob() -> str:
    """Forward-slash glob for the per-session clean files (DuckDB-friendly on Windows)."""
    return (TELEMETRY_DIR / "*.events.jsonl").as_posix()


def _has_events() -> bool:
    return any(TELEMETRY_DIR.glob("*.events.jsonl"))


def get_connection() -> "duckdb.DuckDBPyConnection":
    return duckdb.connect(":memory:")


def events_per_session() -> list[tuple]:
    """[(session_id, event_count), ...] ordered by count DESC. Fail-loud on bad lines."""
    if not _has_events():
        return []
    con = get_connection()
    try:
        return con.execute(
            f"""
            SELECT json_extract_string(json, '$._session') AS session,
                   COUNT(*) AS n
            FROM read_ndjson_objects('{_glob()}', ignore_errors=false)
            GROUP BY session
            ORDER BY n DESC
            """
        ).fetchall()
    finally:
        con.close()


def missing_canary_count(hours_back: int = 48) -> int:
    """Count sessions in the window that contain NO canary event. Fail-loud."""
    if not _has_events():
        return 0
    hours_back = int(hours_back)  # guard: inlined into SQL, must be a plain int
    con = get_connection()
    try:
        row = con.execute(
            f"""
            WITH ev AS (
              SELECT json_extract_string(json, '$._session')      AS session,
                     json_extract_string(json, '$.tool_name')     AS tool_name,
                     TRY_CAST(json_extract_string(json, '$._ts_captured') AS TIMESTAMP) AS ts
              FROM read_ndjson_objects('{_glob()}', ignore_errors=false)
            ),
            windowed AS (
              SELECT * FROM ev
              WHERE ts IS NULL OR ts >= (now()::TIMESTAMP - INTERVAL '{hours_back} hours')
            ),
            all_sessions  AS (SELECT DISTINCT session FROM windowed),
            with_canary   AS (SELECT DISTINCT session FROM windowed WHERE tool_name = ?)
            SELECT COUNT(*)
            FROM all_sessions a
            LEFT JOIN with_canary c USING (session)
            WHERE c.session IS NULL
            """,
            [CANARY_TOOL_NAME],
        ).fetchone()
        return int(row[0]) if row else 0
    finally:
        con.close()


def _jsonl_total_bytes() -> int:
    return sum(p.stat().st_size for p in TELEMETRY_DIR.glob("*.events.jsonl"))


def promote_to_parquet_if_needed() -> bool:
    """If the JSONL archive exceeds the threshold, COPY it to Parquet (zstd). Returns True if promoted."""
    if not _has_events() or _jsonl_total_bytes() < PARQUET_THRESHOLD_BYTES:
        return False
    out_dir = PARQUET_DIR / f"dt={date.today().isoformat()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = (out_dir / "events.parquet").as_posix()
    con = get_connection()
    try:
        con.execute(
            f"""
            COPY (SELECT * FROM read_ndjson_objects('{_glob()}', ignore_errors=false))
            TO '{out_file}' (FORMAT parquet, COMPRESSION zstd)
            """
        )
    finally:
        con.close()
    return True

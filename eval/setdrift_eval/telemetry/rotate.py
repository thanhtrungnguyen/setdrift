"""Daily disk rotation for the telemetry wall (Exit Gate #7).

Keeps data/telemetry/ under a byte budget by promoting the JSONL archive to
compressed (zstd) Parquet and pruning the promoted JSONL — all INSIDE the wall.

IMPORTANT: this is invoked by a true OS scheduled task (Windows Task Scheduler /
WSL2 cron), NOT a Claude Code SessionEnd hook — SessionEnd async work is killed
before completion (Pitfall 4 / GitHub #41577). See 01-04-SUMMARY for the
scheduled-task wiring.
"""

import os
from datetime import date
from pathlib import Path

import duckdb

TELEMETRY_DIR = Path(os.environ.get("SETDRIFT_TELEMETRY_DIR", "data/telemetry"))
PARQUET_DIR = TELEMETRY_DIR / "parquet"
DEFAULT_BUDGET_BYTES = 200 * 1024 * 1024  # 200 MB


def total_bytes() -> int:
    return sum(p.stat().st_size for p in TELEMETRY_DIR.rglob("*") if p.is_file())


def _archive_to_parquet(files: list[Path]) -> None:
    out_dir = PARQUET_DIR / f"dt={date.today().isoformat()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = (out_dir / f"rotated-{files[0].stem}.parquet").as_posix()
    glob = "', '".join(f.as_posix() for f in files)
    con = duckdb.connect(":memory:")
    try:
        con.execute(
            f"COPY (SELECT * FROM read_ndjson_objects(['{glob}'], ignore_errors=false)) "
            f"TO '{out_file}' (FORMAT parquet, COMPRESSION zstd)"
        )
    finally:
        con.close()


def rotate_if_over_budget(budget_bytes: int = DEFAULT_BUDGET_BYTES) -> bool:
    """If data/telemetry/ exceeds the budget, archive+prune oldest events to stay under it.

    Returns True if rotation acted. Parquet archives stay in-wall (data/telemetry/parquet/).
    """
    if total_bytes() < budget_bytes:
        return False

    # Oldest-first so the freshest sessions stay queryable as JSONL.
    files = sorted(TELEMETRY_DIR.glob("*.events.jsonl"), key=lambda p: p.stat().st_mtime)
    acted = False
    for f in files:
        if total_bytes() < budget_bytes:
            break
        _archive_to_parquet([f])  # compressed copy retained in-wall
        f.unlink()  # prune the JSONL → frees bytes
        acted = True
    return acted

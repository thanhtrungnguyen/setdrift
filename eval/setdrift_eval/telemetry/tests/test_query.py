"""Tests for the DuckDB query layer (Plan 01-03 Task 2)."""

import importlib
import json
from datetime import datetime, timezone


def _query(tmp_path, monkeypatch):
    """Reload the query module with SETDRIFT_TELEMETRY_DIR pointed at tmp_path."""
    monkeypatch.setenv("SETDRIFT_TELEMETRY_DIR", str(tmp_path))
    import setdrift_eval.telemetry.query as q

    importlib.reload(q)
    return q


def _now():
    return datetime.now(timezone.utc).isoformat()


def _write_session(tmp_path, session, events):
    p = tmp_path / f"{session}.events.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


def test_events_per_session(tmp_path, monkeypatch):
    """Test 1: counts per session, ordered DESC."""
    _write_session(
        tmp_path,
        "big",
        [{"_session": "big", "tool_name": "Bash", "_ts_captured": _now()} for _ in range(3)],
    )
    _write_session(
        tmp_path, "small", [{"_session": "small", "tool_name": "Read", "_ts_captured": _now()}]
    )
    q = _query(tmp_path, monkeypatch)
    rows = q.events_per_session()
    assert rows[0] == ("big", 3)
    assert ("small", 1) in rows


def test_missing_canary_zero_when_present(tmp_path, monkeypatch):
    """Test 2: a session containing the canary → missing_canary_count == 0."""
    _write_session(
        tmp_path,
        "sX",
        [
            {"_session": "sX", "tool_name": "Bash", "_ts_captured": _now()},
            {"_session": "sX", "tool_name": "SETDRIFT_CANARY_TOOL_V1", "_ts_captured": _now()},
        ],
    )
    q = _query(tmp_path, monkeypatch)
    assert q.missing_canary_count() == 0


def test_missing_canary_detects_absence(tmp_path, monkeypatch):
    """Test 3: a session with no canary is counted as missing."""
    _write_session(
        tmp_path, "sY", [{"_session": "sY", "tool_name": "Bash", "_ts_captured": _now()}]
    )
    q = _query(tmp_path, monkeypatch)
    assert q.missing_canary_count() >= 1


def test_parquet_promotion_threshold(tmp_path, monkeypatch):
    """Test 4: below threshold → False; above (monkeypatched low) → True + parquet written."""
    _write_session(
        tmp_path, "s1", [{"_session": "s1", "tool_name": "Bash", "_ts_captured": _now()}]
    )
    q = _query(tmp_path, monkeypatch)
    assert q.promote_to_parquet_if_needed() is False  # default 500MB threshold
    monkeypatch.setattr(q, "PARQUET_THRESHOLD_BYTES", 1)  # force promotion
    assert q.promote_to_parquet_if_needed() is True
    assert any((tmp_path / "parquet").rglob("events.parquet"))

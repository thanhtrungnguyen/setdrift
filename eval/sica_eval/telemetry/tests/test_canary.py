"""Canary injection test (Plan 01-04 Task 1, Exit Gate #2)."""
import importlib


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("SICA_TELEMETRY_OPT_IN", "1")
    monkeypatch.setenv("SICA_TELEMETRY_RAW_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("SICA_TELEMETRY_DIR", str(tmp_path))
    monkeypatch.setenv("SICA_TELEMETRY_QUARANTINE_DIR", str(tmp_path / "quarantine"))
    monkeypatch.setenv("SICA_TELEMETRY_AUDIT_PATH", str(tmp_path / "scrubber-audit.jsonl"))


def test_canary_lands_and_counts_zero_missing(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    from sica_eval.telemetry.tests import synthetic_harness
    import sica_eval.telemetry.query as q
    importlib.reload(q)

    synthetic_harness.inject_canary("canary_sess")  # injects through real hot path + flushes

    events_file = tmp_path / "canary_sess.events.jsonl"
    assert events_file.exists()
    assert "SICA_CANARY_TOOL_V1" in events_file.read_text(encoding="utf-8")
    assert q.missing_canary_count() == 0

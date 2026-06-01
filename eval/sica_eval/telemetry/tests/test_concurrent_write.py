"""Concurrent-write integrity test (Plan 01-04 Task 1, Exit Gate #4)."""


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("SICA_TELEMETRY_OPT_IN", "1")
    monkeypatch.setenv("SICA_TELEMETRY_RAW_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("SICA_TELEMETRY_DIR", str(tmp_path))


def test_two_parallel_sessions_no_interleave(tmp_path, monkeypatch):
    """Two sessions writing simultaneously parse cleanly (zero MalformedLineError)
    with the expected per-session counts — per-session files prevent interleaving."""
    _env(tmp_path, monkeypatch)
    from sica_eval.telemetry.tests import synthetic_harness

    counts = synthetic_harness.run_concurrent_write_test(per_session=15)
    assert counts == {"concurrent_A": 15, "concurrent_B": 15}

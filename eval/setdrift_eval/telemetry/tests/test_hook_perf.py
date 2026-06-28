"""Hot-path p99 perf test (Plan 01-04 Task 2, Exit Gate #1).

Injects events (default 1000, incl 50 >1MB; override with SETDRIFT_PERF_EVENTS for a
quick run) through the REAL hot path, then computes p99 of _hook_runtime_ms.
"""

import os
from pathlib import Path


def test_p99_under_2000ms(tmp_path, monkeypatch):
    monkeypatch.setenv("SETDRIFT_TELEMETRY_OPT_IN", "1")
    monkeypatch.setenv("SETDRIFT_TELEMETRY_RAW_DIR", str(tmp_path / "raw"))
    from setdrift_eval.telemetry.tests import synthetic_harness
    from setdrift_eval.telemetry.parser import parse_events_jsonl

    total = int(os.environ.get("SETDRIFT_PERF_EVENTS", "1000"))
    n_large = 50
    synthetic_harness.inject_plain("perf", total - n_large, flush=False)
    synthetic_harness.inject_large_payloads("perf", n_large, flush=False)

    records = parse_events_jsonl(tmp_path / "raw" / "perf.jsonl")
    assert len(records) >= total
    assert sum(1 for r in records if len(str(r.get("tool_input", ""))) > 1_000_000) >= n_large

    runtimes = sorted(r["_hook_runtime_ms"] for r in records)
    p99 = runtimes[int(len(runtimes) * 0.99)]
    assert p99 < 2000, f"p99 hot-path runtime {p99:.1f}ms >= 2000ms"

"""Behavior + perf tests for the hot-path capture hook (Plan 01-01 Task 2).

The hook is driven as a real subprocess with stdin piped, exactly as Claude Code
invokes it, with SICA_TELEMETRY_RAW_DIR pointed at a tmp dir.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

HOOK = Path(__file__).resolve().parents[4] / "plugin" / "hooks" / "hot_path_capture.py"


def _run(payload, raw_dir, opt_in=True):
    """Invoke the hook subprocess; return (returncode, raw_path or None)."""
    env = {"SICA_TELEMETRY_RAW_DIR": str(raw_dir)}
    if opt_in:
        env["SICA_TELEMETRY_OPT_IN"] = "1"
    # Pass a minimal but valid env (Windows needs SYSTEMROOT for subprocess).
    import os

    full_env = {**os.environ, **env}
    full_env.pop("SICA_TELEMETRY_OPT_IN", None)
    if opt_in:
        full_env["SICA_TELEMETRY_OPT_IN"] = "1"
    full_env["SICA_TELEMETRY_RAW_DIR"] = str(raw_dir)

    stdin_data = payload if isinstance(payload, str) else json.dumps(payload)
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=stdin_data,
        text=True,
        capture_output=True,
        env=full_env,
        timeout=30,
    )
    return proc


def _lines(raw_dir, session_id):
    p = Path(raw_dir) / f"{session_id}.jsonl"
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_opt_in_gate_writes_nothing(tmp_path):
    """Test 1: opt-in unset → no file written, return 0."""
    payload = {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Bash"}
    proc = _run(payload, tmp_path, opt_in=False)
    assert proc.returncode == 0
    assert list(Path(tmp_path).glob("*.jsonl")) == []


def test_raw_append_with_runtime(tmp_path):
    """Test 2: opt-in=1 → line appended with tool fields + numeric _hook_runtime_ms."""
    payload = {
        "hook_event_name": "PostToolUse",
        "session_id": "s2",
        "cwd": "/tmp/x",
        "tool_name": "Bash",
        "tool_input": {"command": "echo hi"},
        "tool_result": {"stdout": "hi\n", "exit_code": 0},
    }
    proc = _run(payload, tmp_path)
    assert proc.returncode == 0
    recs = _lines(tmp_path, "s2")
    assert len(recs) == 1
    r = recs[0]
    assert r["tool_name"] == "Bash"
    assert r["tool_input"] == {"command": "echo hi"}
    assert r["tool_result"] == {"stdout": "hi\n", "exit_code": 0}
    assert isinstance(r["_hook_runtime_ms"], (int, float))


def test_no_success_field_tool_result_verbatim(tmp_path):
    """Test 3: no 'success'/'ok' key derived; tool_result preserved verbatim."""
    payload = {
        "hook_event_name": "PostToolUse",
        "session_id": "s3",
        "tool_name": "Read",
        "tool_result": {"content": "abc", "nested": {"k": [1, 2, 3]}},
    }
    _run(payload, tmp_path)
    r = _lines(tmp_path, "s3")[0]
    assert "ok" not in r
    assert "success" not in r
    assert r["tool_result"] == {"content": "abc", "nested": {"k": [1, 2, 3]}}


def test_large_payload_under_2000ms(tmp_path):
    """Test 4: >1MB tool_input captured in <2000ms wall-clock, line intact."""
    big = "x" * (1_100_000)  # ~1.1 MB
    payload = {
        "hook_event_name": "PostToolUse",
        "session_id": "s4",
        "tool_name": "Bash",
        "tool_input": {"command": big},
        "tool_result": {"stdout": "done"},
    }
    t0 = time.perf_counter()
    proc = _run(payload, tmp_path)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert proc.returncode == 0
    assert elapsed_ms < 2000, f"hot path took {elapsed_ms:.0f}ms (>2000)"
    recs = _lines(tmp_path, "s4")
    assert len(recs) == 1
    assert len(recs[0]["tool_input"]["command"]) == 1_100_000


def test_malformed_stdin_never_blocks(tmp_path):
    """Test 5: non-JSON stdin → return 0, writes nothing, raises nothing."""
    proc = _run("this is not json {{{", tmp_path)
    assert proc.returncode == 0
    assert proc.stderr.strip() == ""
    assert list(Path(tmp_path).glob("*.jsonl")) == []

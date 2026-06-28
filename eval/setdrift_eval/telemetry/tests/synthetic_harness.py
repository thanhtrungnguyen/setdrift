"""Synthetic telemetry harness (D-28 hybrid dogfooding).

Deterministically injects the parts of the Exit Gate that natural Claude Code
usage will not reliably produce — the canary tool call, ≥50 tool payloads >1MB,
and the two-parallel-session concurrent-write test — by driving the REAL
hot_path_capture.py hook through subprocess (identical capture path), then the
REAL stop_batch_scrubber.py to land events in events.jsonl.

Synthetic events carry `_synthetic: True` so Phase 2 excludes them from F1
(prevents the canary/large-payload events biasing the metric).
"""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

# MUST equal query.py's CANARY_TOOL_NAME (shared canary identity).
CANARY_TOOL_NAME = "SETDRIFT_CANARY_TOOL_V1"

_HOOKS = Path(__file__).resolve().parents[4] / "plugin" / "hooks"
_HOT_PATH = _HOOKS / "hot_path_capture.py"
_BATCH = _HOOKS / "stop_batch_scrubber.py"


def _child_env() -> dict:
    """Inherit env (so SETDRIFT_TELEMETRY_* point where the caller set them) + force opt-in."""
    return {**os.environ, "SETDRIFT_TELEMETRY_OPT_IN": "1"}


def _inject(payload: dict) -> None:
    subprocess.run(
        [sys.executable, str(_HOT_PATH)],
        input=json.dumps(payload),
        text=True,
        env=_child_env(),
        timeout=30,
        check=True,
    )


def _flush(session_id: str) -> None:
    """Run the real batch scrubber for a session (raw buffer -> events.jsonl|quarantine)."""
    subprocess.run(
        [sys.executable, str(_BATCH), session_id],
        env=_child_env(),
        timeout=500,
        check=True,
    )


def inject_canary(session_id: str, flush: bool = True) -> None:
    """Inject one synthetic canary tool call through the real hot path."""
    _inject(
        {
            "hook_event_name": "PostToolUse",
            "session_id": session_id,
            "tool_name": CANARY_TOOL_NAME,
            "tool_input": {"_canary": True},
            "tool_result": {"ok": True},
            "_synthetic": True,
        }
    )
    print(f"[sica-harness] injected canary into session {session_id}")
    if flush:
        _flush(session_id)


def inject_large_payloads(session_id: str, count: int = 50, flush: bool = True) -> int:
    """Inject `count` PostToolUse events each with a >1MB tool_input. Returns bytes/payload."""
    filler = "x" * (1_100_000)  # ~1.1 MB > 1 MB
    for i in range(count):
        _inject(
            {
                "hook_event_name": "PostToolUse",
                "session_id": session_id,
                "tool_name": "Bash",
                "tool_input": {"command": f"#{i}", "blob": filler},
                "tool_result": {"stdout": "ok"},
                "_synthetic": True,
            }
        )
    print(f"[sica-harness] injected {count} >1MB payloads into session {session_id}")
    if flush:
        _flush(session_id)
    return len(filler)


def inject_plain(session_id: str, count: int, flush: bool = False) -> None:
    """Inject `count` small plain events (for volume / perf runs)."""
    for i in range(count):
        _inject(
            {
                "hook_event_name": "PostToolUse",
                "session_id": session_id,
                "tool_name": "Read",
                "tool_input": {"file": f"f{i}.py"},
                "tool_result": {"content": "..."},
                "_synthetic": True,
            }
        )
    if flush:
        _flush(session_id)


def run_concurrent_write_test(per_session: int = 20) -> dict:
    """Two threads inject under DISTINCT sessions simultaneously, then both files
    are parsed with the 01-03 strict parser. Returns per-session parsed counts.
    Raises MalformedLineError if any interleaving corrupted a line (Exit Gate #4)."""
    from setdrift_eval.telemetry.parser import parse_events_jsonl

    sessions = ["concurrent_A", "concurrent_B"]

    def worker(sid):
        inject_plain(sid, per_session, flush=False)

    threads = [threading.Thread(target=worker, args=(s,)) for s in sessions]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    raw_dir = Path(os.environ.get("SETDRIFT_TELEMETRY_RAW_DIR", "data/telemetry/raw"))
    counts = {}
    for s in sessions:
        # Strict parser over the per-session RAW file — zero interleaving expected
        # because each session writes its OWN file (D-26 per-session isolation).
        counts[s] = len(parse_events_jsonl(raw_dir / f"{s}.jsonl"))
    print(f"[sica-harness] concurrent-write parsed cleanly: {counts}")
    return counts

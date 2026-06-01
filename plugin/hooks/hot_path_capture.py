#!/usr/bin/env python3
"""SICA hot-path telemetry capture hook (deferred-batch architecture, REQ-OPS-01).

This is the HOT PATH. It does the absolute minimum: read the hook payload from
stdin and append it — RAW, UNSCRUBBED — to a per-session buffer inside the
gitignored data wall, then return. ALL scrubbing happens later, off the hot
path, in the Stop-hook batch scrubber (see stop_flush_trigger.py →
stop_batch_scrubber.py). This is D-26: scrubbing Presidio on the hot path
(2-4s cold start) would risk Claude Code's 60s silent hook death on large
payloads.

The hot path must stay stdlib-only and near-instant (Pitfall 2: Presidio
cold-start) — do NOT pull the Presidio or detect-secrets libraries into this
module; all redaction happens later in the batch scrubber.

Capture is OPT-IN: nothing is written unless SICA_TELEMETRY_OPT_IN is set
(unset in CI / dev). The data/ wall is the true firewall; this hook is the
thin capture edge.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Default to the gitignored wall. Overridable via env (tests point it at tmp).
TELEMETRY_RAW_DIR = Path(os.environ.get("SICA_TELEMETRY_RAW_DIR", "data/telemetry/raw"))
# Opt-in gate: production capture only when explicitly enabled (Exit Gate #8).
OPT_IN = os.environ.get("SICA_TELEMETRY_OPT_IN", "").strip()


def main() -> int:
    # Opt-in gate: if not enabled, do nothing and never block the session.
    if not OPT_IN:
        return 0

    t_start = time.perf_counter()

    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # never block the session on a telemetry failure

    session_id = payload.get("session_id") or "unknown"

    # Build the raw record. NOTE: PostToolUse has NO 'success' field — the old
    # scaffold read a nonexistent key there (a latent bug). We preserve the real
    # tool_result dict verbatim; scrubbing happens later in the batch scrubber.
    record = {
        "_ts_captured": datetime.now(timezone.utc).isoformat(),
        "_hook_event": payload.get("hook_event_name"),
        "_session": session_id,
        "_cwd": payload.get("cwd"),
        "_transcript": payload.get("transcript_path"),
        "tool_name": payload.get("tool_name"),
        "tool_input": payload.get("tool_input"),
        "tool_result": payload.get("tool_result"),
        "prompt": payload.get("prompt"),
        "message_preview": payload.get("message_preview"),
    }
    # Self-reported hot-path runtime for the p99<2000ms exit gate (#1).
    record["_hook_runtime_ms"] = (time.perf_counter() - t_start) * 1000

    try:
        TELEMETRY_RAW_DIR.mkdir(parents=True, exist_ok=True)
        raw_path = TELEMETRY_RAW_DIR / f"{session_id}.jsonl"
        with raw_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:
        return 0  # never block the session on a telemetry failure

    return 0


if __name__ == "__main__":
    sys.exit(main())

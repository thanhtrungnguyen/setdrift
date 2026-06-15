#!/usr/bin/env python3
"""Setdrift Stop-hook flush trigger (deferred-batch architecture, D-26).

Fires on the Claude Code `Stop` event. Its only job is to hand the just-ended
session's RAW buffer off to the batch scrubber (stop_batch_scrubber.py, built in
Plan 01-02), which does the slow Presidio/detect-secrets work OFF the hot path.

Two correctness guards (both verified findings, 01-RESEARCH):
- Pitfall 3: the Stop hook fires once PER RESPONSE TURN, not once per session,
  and a Stop hook that itself triggers continuation re-enters with
  stop_hook_active=true. We bail on stop_hook_active to avoid a Stop→scrub→Stop
  loop, and the scrubber/trigger are IDEMPOTENT: if the raw buffer is already
  gone (a prior turn scrubbed it), this is a no-op.
- The whole thing is wrapped so a scrubber failure NEVER blocks the session; an
  orphaned raw buffer is swept later by the daily cron backstop (Plan 01-04).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

TELEMETRY_RAW_DIR = Path(os.environ.get("SETDRIFT_TELEMETRY_RAW_DIR", "data/telemetry/raw"))
OPT_IN = os.environ.get("SETDRIFT_TELEMETRY_OPT_IN", "").strip()


def main() -> int:
    if not OPT_IN:
        return 0  # opt-in gate; never block the session

    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # never block the session on a telemetry failure

    # Re-entrancy guard: a Stop hook already in forced-continuation re-enters
    # with stop_hook_active=true — do not recurse (Pitfall 3).
    if payload.get("stop_hook_active"):
        return 0

    session_id = payload.get("session_id") or "unknown"
    raw_path = TELEMETRY_RAW_DIR / f"{session_id}.jsonl"

    # Idempotent: if the raw buffer is already gone, a prior turn scrubbed it.
    if not raw_path.exists():
        return 0

    scrubber = Path(__file__).parent / "stop_batch_scrubber.py"
    try:
        # 500s timeout leaves ~100s margin under the 600s Stop-hook ceiling.
        # Same interpreter as this trigger (robust on Windows where 'python3'
        # may not resolve). stop_batch_scrubber.py is delivered by Plan 01-02;
        # until then this degrades gracefully via the except below.
        subprocess.run(
            [sys.executable, str(scrubber), str(session_id)],
            timeout=500,
            check=True,
        )
    except Exception:
        return 0  # never block; orphaned raw buffer → daily cron handles it

    return 0


if __name__ == "__main__":
    sys.exit(main())

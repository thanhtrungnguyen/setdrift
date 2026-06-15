#!/usr/bin/env python3
"""Setdrift telemetry capture hook.

Reads a Claude Code hook event from stdin (JSON) and appends a *scrubbed*,
minimal record to the telemetry store. The store path defaults to the
gitignored data/ wall so captured content never enters version control.

NOTE: this is a scaffold. Verify the exact hook payload shape against the
current Claude Code hooks docs before relying on field names.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Default to the gitignored wall. Overridable via env.
STORE = Path(os.environ.get("SETDRIFT_TELEMETRY_PATH", "data/telemetry/events.jsonl"))

SECRET_RE = re.compile(r"(sk-[A-Za-z0-9-]{8,}|AKIA[0-9A-Z]{12,}|ghp_[A-Za-z0-9]{20,})")


def scrub(text: str) -> str:
    """Best-effort redaction. NOT a substitute for the data wall."""
    if not isinstance(text, str):
        return text
    return SECRET_RE.sub("[REDACTED]", text)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # never block the session on a telemetry failure

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool": payload.get("tool_name"),
        "ok": payload.get("success"),
        # store only metadata, not raw arguments/outputs
        "session": payload.get("session_id"),
        "cwd": scrub(str(payload.get("cwd", ""))),
    }

    STORE.parent.mkdir(parents=True, exist_ok=True)
    with STORE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

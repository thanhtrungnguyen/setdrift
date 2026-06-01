#!/usr/bin/env python3
"""SICA Stop-hook batch scrubber (D-27 quarantine policy, REQ-SAFETY-01).

Invoked by stop_flush_trigger.py with a session_id. Reads that session's RAW
buffer, routes each event to the clean per-session events.jsonl (if it scrubs
cleanly) or to the in-wall quarantine (if scrubbing raises), writes a per-redaction
and per-quarantine line to scrubber-audit.jsonl, then DELETES the raw buffer.

D-27 invariants:
  - NEVER emit an unscrubbed event to events.jsonl.
  - NEVER silently drop an event — a scrub failure is quarantined AND counted.
  - Idempotent: if the raw buffer is already gone (Stop fires per-turn), no-op.

This runs OFF the hot path, so the slow scrub_event (Presidio) is fine here.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from sica_eval.telemetry.scrubber import scrub_event

TELEMETRY_RAW_DIR = Path(os.environ.get("SICA_TELEMETRY_RAW_DIR", "data/telemetry/raw"))
TELEMETRY_DIR = Path(os.environ.get("SICA_TELEMETRY_DIR", "data/telemetry"))
QUARANTINE_DIR = Path(os.environ.get("SICA_TELEMETRY_QUARANTINE_DIR", "data/telemetry/quarantine"))
AUDIT_PATH = Path(os.environ.get("SICA_TELEMETRY_AUDIT_PATH", "data/telemetry/scrubber-audit.jsonl"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


def scrub_session(session_id: str) -> dict:
    raw_path = TELEMETRY_RAW_DIR / f"{session_id}.jsonl"
    # Idempotent: a prior turn already scrubbed this session (Stop fires per-turn).
    if not raw_path.exists():
        return {"session": session_id, "clean_count": 0, "quarantine_count": 0, "skipped": True}

    events_path = TELEMETRY_DIR / f"{session_id}.events.jsonl"
    quarantine_path = QUARANTINE_DIR / f"{session_id}.jsonl"

    clean_count = 0
    quarantine_count = 0

    for line in raw_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        # This is our OWN raw buffer; a tolerant json.loads is fine here (the strict
        # fail-loud parser from 01-03 guards the clean read-back path, not this one).
        try:
            event = json.loads(line)
        except Exception:
            # A corrupt raw line is itself a data-integrity event — quarantine the
            # raw line verbatim rather than drop it.
            _append(quarantine_path, {"_raw_line": line, "_reason": "raw-parse-error", "_session": session_id})
            _append(AUDIT_PATH, {"_quarantine": True, "_reason": "raw-parse-error", "_session": session_id, "_ts": _now()})
            quarantine_count += 1
            continue

        try:
            scrubbed, audit = scrub_event(event)
            _append(events_path, scrubbed)
            for r in audit:
                _append(AUDIT_PATH, {
                    "layer": r.layer, "entity_type": r.entity_type,
                    "start": r.start, "end": r.end, "score": r.score,
                    "original_hash": r.original_hash, "_session": session_id, "_ts": _now(),
                })
            clean_count += 1
        except Exception as exc:  # D-27: quarantine, never drop, never emit unscrubbed
            _append(quarantine_path, event)
            _append(AUDIT_PATH, {
                "_quarantine": True, "_reason": f"scrub-error: {type(exc).__name__}",
                "_session": session_id, "_ts": _now(),
            })
            quarantine_count += 1

    summary = {"session": session_id, "clean_count": clean_count, "quarantine_count": quarantine_count}
    # Per-session summary so 01-04's sanity check can compare counts without re-scrubbing.
    _append(TELEMETRY_DIR / f"{session_id}.summary.jsonl", {**summary, "_ts": _now()})

    raw_path.unlink()  # consume the raw buffer (bounds the raw-PII window)
    return summary


def main() -> int:
    if len(sys.argv) < 2:
        return 0
    scrub_session(sys.argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main())

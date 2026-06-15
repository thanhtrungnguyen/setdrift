"""Real-drift event log — DriftEvent schema + dual-write append (REQ-DRIFT-01, Plan 04-04).

What this module does:
  - Defines DriftEvent Pydantic schema: type-tagged qualifying drift events
    (D-50: codebase_head_shift | model_release) with F1-at-event overlay fields.
  - scrub_for_public(): strips commit-message text (notes field) before writing
    to experiments/ — mirrors scrub_for_genealogy() in loop_manifest.py.
  - append_drift_event(): dual-write — full record to data/drift/ (gitignored),
    scrubbed record to experiments/ (committed). Both paths env-var-overridable.
  - count_qualifying_events(): counts events in the public log for the D-51 cut decision.
  - HARD_CUT_DATE: pre-registered cut date (2026-07-15, D-51) — if <3 qualifying
    events by this date, write the §8 fallback note and hand the drift story to
    synthetic-drift (REQ-DRIFT-02).

What it does NOT do:
  - Never writes commit-message text to experiments/ (Security Domain rule, T-04-13).
  - Never modifies scorer.py or any frozen Phase-2 instrument (Goodhart firewall).
  - Never reads from the data wall (only writes to it).

Eval-side fail-loud: exceptions propagate (no bare except).
"""
import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Pre-registered hard cut date (D-51 — fixed calendar, cannot silently slip)
# ---------------------------------------------------------------------------
HARD_CUT_DATE = "2026-07-15"

# ---------------------------------------------------------------------------
# Env-var-overridable paths (mirrors orchestrator.py pattern)
# ---------------------------------------------------------------------------
_RAW_EVENTS = Path(os.environ.get("SICA_DRIFT_RAW_EVENTS", "data/drift/events-raw.jsonl"))
_PUBLIC_EVENTS = Path(os.environ.get("SICA_DRIFT_PUBLIC_EVENTS", "experiments/drift-event-log.jsonl"))


def _read_raw_path() -> Path:
    return Path(os.environ.get("SICA_DRIFT_RAW_EVENTS", "data/drift/events-raw.jsonl"))


def _read_public_path() -> Path:
    return Path(os.environ.get("SICA_DRIFT_PUBLIC_EVENTS", "experiments/drift-event-log.jsonl"))


# ---------------------------------------------------------------------------
# DriftEvent schema
# ---------------------------------------------------------------------------

class DriftEvent(BaseModel):
    """One qualifying drift event record (D-50).

    Dual-written: full record to data/drift/ (gitignored data wall), scrubbed
    record (no commit-message text) to experiments/drift-event-log.jsonl
    (committed). extra='forbid' catches typos silently (T-04-13 discipline).
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(
        description="Unique identifier for this drift event (UUID4 or human-readable slug)"
    )
    ts: str = Field(
        description="ISO-8601 UTC timestamp when this drift event was recorded"
    )
    drift_type: Literal["codebase_head_shift", "model_release"] = Field(
        description=(
            "D-50 type tag: 'codebase_head_shift' for target-codebase HEAD advances "
            "(GitBug-Java; parking if SICA-2 clears), 'model_release' for in-window "
            "Anthropic model release."
        )
    )
    head_sha: str | None = Field(
        default=None,
        description=(
            "Git SHA of the target codebase at the time of the drift event. "
            "Present for codebase_head_shift events; None for model_release events."
        ),
    )
    model_id: str | None = Field(
        default=None,
        description=(
            "Anthropic model ID (e.g. 'claude-sonnet-4-7') for model_release events; "
            "None for codebase_head_shift events."
        ),
    )
    f1_at_event_A: float | None = Field(
        default=None,
        description=(
            "Macro-F1 of arm A (SICA-managed config) at the time of this drift event. "
            "Populated from grid_runner.run_grid() output when >=3 events qualify (D-51 real-drift path)."
        ),
    )
    f1_at_event_B: float | None = Field(
        default=None,
        description=(
            "Macro-F1 of arm B (frozen hand-written config) at the time of this drift event. "
            "Populated from grid_runner.run_grid() output when >=3 events qualify (D-51 real-drift path)."
        ),
    )
    notes: str = Field(
        default="",
        description=(
            "Free-form human-readable notes about this event. MAY contain commit-message text. "
            "EXCLUDED from scrub_for_public() — never crosses the data wall into experiments/."
        ),
    )


# ---------------------------------------------------------------------------
# Scrub function (Security Domain rule, T-04-13)
# ---------------------------------------------------------------------------

def scrub_for_public(event: DriftEvent) -> dict:
    """Return the data-wall-clean subset of a DriftEvent for the committed log.

    Excludes the 'notes' field because it may contain commit-message text
    (customer names, ticket IDs, code symbols) — the Security Domain rule (T-04-13).
    All other quantitative fields are included.

    Mirrors scrub_for_genealogy() in schemas/loop_manifest.py.
    """
    return {
        "event_id": event.event_id,
        "ts": event.ts,
        "drift_type": event.drift_type,
        "head_sha": event.head_sha,
        "model_id": event.model_id,
        "f1_at_event_A": event.f1_at_event_A,
        "f1_at_event_B": event.f1_at_event_B,
    }


# ---------------------------------------------------------------------------
# Dual-write append (mirrors orchestrator._append_audit pattern)
# ---------------------------------------------------------------------------

def append_drift_event(event: DriftEvent) -> None:
    """Write FULL record to data/drift/events-raw.jsonl + SCRUBBED record to experiments/.

    Mirrors orchestrator._append_audit exactly:
    - Full record (includes notes/commit-message text) → data/drift/events-raw.jsonl (gitignored).
    - Scrubbed record (NO notes, NO commit-message text) → experiments/drift-event-log.jsonl (committed).

    Both paths are env-var-overridable (SICA_DRIFT_RAW_EVENTS, SICA_DRIFT_PUBLIC_EVENTS)
    for test isolation and deployment flexibility.

    Eval-side fail-loud: filesystem errors propagate (no bare except).
    """
    raw_path = _read_raw_path()
    public_path = _read_public_path()

    # Full record (gitignored data wall)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    with raw_path.open("a", encoding="utf-8") as fh:
        fh.write(event.model_dump_json() + "\n")

    # Scrubbed record (committed — no commit-message text per T-04-13)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    with public_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(scrub_for_public(event)) + "\n")


# ---------------------------------------------------------------------------
# Count helper (used by the D-51 cut decision)
# ---------------------------------------------------------------------------

def count_qualifying_events(public_path: Path | None = None) -> int:
    """Count the number of qualifying drift events in the public (committed) log.

    Used at the D-51 cut decision (2026-07-15) to choose between the real-drift
    overlay path (>=3 events) and the §8 fallback note path (<3 events).

    Args:
        public_path: Optional override for the public events JSONL path.
                     Defaults to SICA_DRIFT_PUBLIC_EVENTS env var or experiments/drift-event-log.jsonl.

    Returns:
        Number of valid JSONL records in the public log, or 0 if the file doesn't exist.
    """
    if public_path is None:
        public_path = _read_public_path()
    public_path = Path(public_path)
    if not public_path.exists():
        return 0
    count = 0
    for line in public_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            count += 1
    return count

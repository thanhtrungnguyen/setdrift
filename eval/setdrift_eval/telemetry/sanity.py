"""Per-session event-count sanity check (Exit Gate #3).

Compares the CAPTURED event count for a session (clean events.jsonl + quarantined
events — quarantined ones COUNT, per D-27, so a scrub-quarantine is not mistaken
for a gap) against the number of tool calls the session's transcript shows. A gap
over the threshold means events went missing — the session is FLAGGED and
quarantined for review, never silently dropped.
"""
import json
import os
from pathlib import Path

TELEMETRY_DIR = Path(os.environ.get("SICA_TELEMETRY_DIR", "data/telemetry"))
QUARANTINE_DIR = Path(os.environ.get("SICA_TELEMETRY_QUARANTINE_DIR", "data/telemetry/quarantine"))
SANITY_FLAGS = TELEMETRY_DIR / "sanity-flags.jsonl"


def _count_lines(p: Path) -> int:
    if not p.exists():
        return 0
    return sum(1 for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip())


def captured_count(session_id: str) -> int:
    """Clean events + quarantined events (quarantined count toward captured, D-27)."""
    return (
        _count_lines(TELEMETRY_DIR / f"{session_id}.events.jsonl")
        + _count_lines(QUARANTINE_DIR / f"{session_id}.jsonl")
    )


def _transcript_tool_count(session_id: str) -> int | None:
    """Best-effort: count tool_use blocks in the transcript referenced by the session."""
    ev = TELEMETRY_DIR / f"{session_id}.events.jsonl"
    if not ev.exists():
        return None
    transcript = None
    for ln in ev.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        try:
            transcript = json.loads(ln).get("_transcript")
        except Exception:
            continue
        if transcript:
            break
    if not transcript or not Path(transcript).exists():
        return None
    n = 0
    for ln in Path(transcript).read_text(encoding="utf-8").splitlines():
        if '"type":"tool_use"' in ln.replace(" ", "") or '"tool_use"' in ln:
            n += 1
    return n


def session_count_gap(session_id: str, expected_count: int | None = None) -> float:
    """|expected - captured| / expected. expected = transcript tool count (or provided)."""
    captured = captured_count(session_id)
    expected = expected_count if expected_count is not None else _transcript_tool_count(session_id)
    if expected is None or expected == 0:
        return 0.0  # cannot assess (no transcript) — not treated as a gap
    return abs(expected - captured) / expected


def _flag(session_id: str, gap: float) -> None:
    SANITY_FLAGS.parent.mkdir(parents=True, exist_ok=True)
    with SANITY_FLAGS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"_session": session_id, "gap": gap, "_action": "quarantined-for-review"}) + "\n")


def check_all_sessions(threshold: float = 0.05, expected_counts: dict | None = None) -> list[str]:
    """Return session_ids whose count gap exceeds `threshold`; flag them (never silent-drop).

    `expected_counts` (optional) overrides the transcript source — used by the
    synthetic harness path where the true count is known.
    """
    sessions = {p.name[: -len(".events.jsonl")] for p in TELEMETRY_DIR.glob("*.events.jsonl")}
    if QUARANTINE_DIR.exists():
        sessions |= {p.stem for p in QUARANTINE_DIR.glob("*.jsonl")}

    flagged: list[str] = []
    for s in sorted(sessions):
        exp = (expected_counts or {}).get(s)
        gap = session_count_gap(s, exp)
        if gap > threshold:
            _flag(s, gap)
            flagged.append(s)
    return flagged

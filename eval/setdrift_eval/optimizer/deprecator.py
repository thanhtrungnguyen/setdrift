"""Skill lifecycle deprecator — idle-session archive + rejection-rate quarantine (REQ-SAFETY-03).

Tracks per-skill firing/rejection in data/deprecation/ (gitignored, inside the data wall).
Reads the real sharded data/telemetry/*.events.jsonl contract to count idle sessions.

What this module does:
  - record_firing: append per-skill firing record (offline tracking only)
  - count_idle_sessions: count distinct session_ids since a skill last fired
  - rejection_rate: compute rejection rate over the last QUARANTINE_WINDOW firing-sessions
  - quarantine_skill: move SKILL.md to plugin/skills/quarantine/ (outside */SKILL.md load glob)
  - promote_skill: move SKILL.md back from quarantine/ to plugin/skills/
  - scan: return list[Decision] of archive/quarantine decisions for all skills in skills_dir

What this module does NOT do:
  - It does not write to any committed path (data wall enforced by _DEPRECATION_DIR default)
  - It does not trigger live session hooks or block a session
  - It does not perform loop orchestration (see orchestrator.py)

Every state-changing call logs a Decision record with a non-empty reason.
Fail-loud: this is offline analysis, NOT the telemetry hot path.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Env-var constants (read at module load time; monkeypatching env + reload works)
# ---------------------------------------------------------------------------

_DEPRECATION_DIR = Path(os.environ.get("SETDRIFT_DEPRECATION_DIR", "data/deprecation"))
ARCHIVE_AFTER_N = int(os.environ.get("SETDRIFT_ARCHIVE_AFTER_N", "20"))
QUARANTINE_WINDOW = int(os.environ.get("SETDRIFT_QUARANTINE_WINDOW", "10"))
QUARANTINE_REJECTION_RATE = float(os.environ.get("SETDRIFT_QUARANTINE_RATE", "0.80"))

# Name of the decisions log file inside _DEPRECATION_DIR
_DECISIONS_LOG = "decisions.jsonl"


# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------


class Decision(BaseModel):
    """One lifecycle decision record: archive / quarantine / promote.

    reason is required and must be non-empty (anti-repudiation, T-03-51).
    extra='forbid' to catch accidental field drift.
    """

    model_config = ConfigDict(extra="forbid")

    skill_name: str = Field(description="Name of the skill (kebab-case or sanitized form)")
    decision: Literal["archive", "quarantine", "promote"] = Field(
        description="The lifecycle decision taken"
    )
    reason: str = Field(description="Human-readable rationale (must be non-empty)")
    ts: str = Field(description="ISO-8601 UTC timestamp when the decision was made")
    applied: bool = Field(
        default=False,
        description=(
            "False = the decision was FLAGGED by scan() (analysis only); "
            "True = the state change was actually EXECUTED (quarantine_skill/"
            "promote_skill moved SKILL.md). Disambiguates the two records a "
            "flag-then-apply flow writes to decisions.jsonl (WR-09, anti-repudiation)."
        ),
    )

    @field_validator("reason")
    @classmethod
    def reason_must_be_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError(
                "Decision reason must be a non-empty string (anti-repudiation requirement)"
            )
        return v


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _deprecation_dir() -> Path:
    """Return the current deprecation dir (re-reads env each time for testability)."""
    return Path(os.environ.get("SETDRIFT_DEPRECATION_DIR", "data/deprecation"))


def _archive_after_n() -> int:
    return int(os.environ.get("SETDRIFT_ARCHIVE_AFTER_N", "20"))


def _quarantine_window() -> int:
    return int(os.environ.get("SETDRIFT_QUARANTINE_WINDOW", "10"))


def _quarantine_rejection_rate() -> float:
    return float(os.environ.get("SETDRIFT_QUARANTINE_RATE", "0.80"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_firing_event(ev: dict, skill_name: str) -> bool:
    """True if this scrubbed telemetry event is a firing of skill_name.

    Real contract (verified against data/telemetry/*.events.jsonl shards):
    skill invocations are recorded as `tool_name == "Skill"` with the skill
    identity inside the `tool_input` JSON string, e.g.
    `{"skill": "paperclip"}` or namespaced `{"skill": "setdrift:spring-boot-endpoint"}`.
    A skill's own name NEVER appears in `tool_name` (that field only carries
    Claude Code tool names: Bash, Read, Skill, ...).
    """
    if ev.get("tool_name") != "Skill":
        return False
    raw = ev.get("tool_input")
    try:
        payload = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (TypeError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    # "skill" value may be namespaced, e.g. "setdrift:spring-boot-endpoint"
    skill = str(payload.get("skill", ""))
    return skill == skill_name or skill.endswith(f":{skill_name}")


def _append_jsonl(path: Path, record: dict) -> None:
    """Append one JSONL record (append-only pattern from capture_event.py)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _log_decision(decision: Decision) -> None:
    """Append the Decision to the decisions log under _DEPRECATION_DIR."""
    dep_dir = _deprecation_dir()
    log_path = dep_dir / _DECISIONS_LOG
    _append_jsonl(log_path, decision.model_dump())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def record_firing(skill_name: str, session_id: str, fired: bool, rejected: bool) -> None:
    """Append a per-skill firing/rejection record.

    Stores to data/deprecation/<skill_name>.jsonl (gitignored).
    This is offline tracking, NOT in the session hot path — fail-loud.
    """
    dep_dir = _deprecation_dir()
    skill_log = dep_dir / f"{skill_name}.jsonl"
    record = {
        "skill_name": skill_name,
        "session_id": session_id,
        "fired": fired,
        "rejected": rejected,
        "ts": _now_iso(),
    }
    _append_jsonl(skill_log, record)


def count_idle_sessions(skill_name: str, telemetry_dir: Path) -> int:
    """Count distinct sessions in the sharded telemetry directory since the skill last fired.

    Reads the REAL sharded telemetry contract produced by the Phase-1 writer
    (plugin/hooks/stop_batch_scrubber.py): one shard per session at
    `<telemetry_dir>/<session_id>.events.jsonl`. Imitates
    `eval/setdrift_eval/telemetry/query.py`'s glob + field-name convention
    (glob `*.events.jsonl`, fields `_session`/`tool_name`) WITHOUT importing
    DuckDB — plain `json.loads` per line, matching this module's
    zero-external-import style.

    A "session" is a distinct value of the `_session` field with ≥1 tool-use
    event (any tool — the session was active).

    Returns 0 if telemetry_dir does not exist or has no shards (cannot flag
    without data). Returns the count of distinct sessions that had ≥1
    tool-use after the last session where skill_name fired. If the skill
    never fired, returns the total count of distinct active sessions.
    """
    telemetry_dir = Path(telemetry_dir)
    if not telemetry_dir.exists():
        return 0

    shard_paths = sorted(telemetry_dir.glob("*.events.jsonl"))
    if not shard_paths:
        return 0

    # Read every shard, accumulating all events into one list, then
    # merge-sort the combined list by _ts_captured before running the scan.
    events: list[dict] = []
    for shard_path in shard_paths:
        with shard_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    events.sort(key=lambda ev: ev.get("_ts_captured") or "")

    # Find the last session where skill_name fired.
    # Real contract (CR-01): a skill firing is `tool_name == "Skill"` with the
    # skill name inside the tool_input JSON payload — see _is_firing_event.
    last_firing_session: str | None = None
    for ev in events:
        if _is_firing_event(ev, skill_name):
            last_firing_session = ev.get("_session")

    # Collect distinct active sessions (sessions with ≥1 tool-use event of any kind)
    # that appeared AFTER the last firing session
    seen_sessions: list[str] = []
    found_last = last_firing_session is None  # if never fired, count all

    for ev in events:
        session = ev.get("_session")
        if not session:
            continue
        # Once we've seen the last_firing_session, start counting subsequent sessions
        if not found_last:
            if session == last_firing_session:
                found_last = True
            continue
        # CR-03: real sessions are multi-event — later events belonging to the
        # firing session itself must never count it as idle.
        if session == last_firing_session:
            continue  # the firing session is never idle
        # After the last firing: track sessions that have any tool activity
        if session not in seen_sessions and ev.get("tool_name"):
            seen_sessions.append(session)

    return len(seen_sessions)


def rejection_rate(skill_name: str) -> float:
    """Compute the rejection rate for skill_name over the last QUARANTINE_WINDOW firing-sessions.

    Reads from data/deprecation/<skill_name>.jsonl.
    Returns 0.0 if no firing log exists.
    """
    dep_dir = _deprecation_dir()
    skill_log = dep_dir / f"{skill_name}.jsonl"
    if not skill_log.exists():
        return 0.0

    window = _quarantine_window()
    records: list[dict] = []
    with skill_log.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("fired"):
                records.append(r)

    # Take the last QUARANTINE_WINDOW firing records
    recent = records[-window:] if len(records) > window else records
    if not recent:
        return 0.0

    rejected_count = sum(1 for r in recent if r.get("rejected"))
    return rejected_count / len(recent)


def quarantine_skill(skill_name: str, skills_dir: Path) -> Decision:
    """Move <skills_dir>/<skill_name>/SKILL.md to <skills_dir>/quarantine/<skill_name>/SKILL.md.

    The quarantine directory is ONE level deeper than skills_dir, so quarantined SKILL.md
    files are NOT matched by the `skills_dir/*/SKILL.md` glob used by load_skill_tools.
    (They would match `skills_dir/*/*/SKILL.md` but NOT `*/SKILL.md`.)

    Logs the decision with a non-empty reason and returns the Decision object.
    Raises FileNotFoundError if the skill is not at <skills_dir>/<skill_name>/SKILL.md.
    """
    skills_dir = Path(skills_dir)
    source = skills_dir / skill_name / "SKILL.md"
    if not source.exists():
        raise FileNotFoundError(
            f"Cannot quarantine '{skill_name}': SKILL.md not found at '{source}'. "
            "Skill may already be quarantined or does not exist."
        )

    target = skills_dir / "quarantine" / skill_name / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)

    # Also remove the now-empty skill directory if empty
    skill_dir = skills_dir / skill_name
    try:
        skill_dir.rmdir()  # only removes if empty — safe
    except OSError:
        pass  # non-empty or already gone — ignore

    decision = Decision(
        skill_name=skill_name,
        decision="quarantine",
        reason=(
            f"Skill '{skill_name}' quarantined: rejection rate exceeded "
            f"{_quarantine_rejection_rate():.0%} over the last {_quarantine_window()} "
            "firing-sessions. Moved outside load_skill_tools glob. "
            "Re-promote with: setdrift-eval promote-skill --name " + skill_name
        ),
        ts=_now_iso(),
        applied=True,
    )
    _log_decision(decision)
    return decision


def promote_skill(skill_name: str, skills_dir: Path) -> Decision:
    """Move <skills_dir>/quarantine/<skill_name>/SKILL.md back to <skills_dir>/<skill_name>/SKILL.md.

    Re-exposes the skill to the load_skill_tools glob after manual review.
    Logs the decision with a non-empty reason and returns the Decision object.
    Raises FileNotFoundError if the skill is not in quarantine.
    """
    skills_dir = Path(skills_dir)
    source = skills_dir / "quarantine" / skill_name / "SKILL.md"
    if not source.exists():
        raise FileNotFoundError(
            f"Cannot promote '{skill_name}': SKILL.md not found in quarantine at '{source}'. "
            "Skill may not be quarantined or name is misspelled."
        )

    target = skills_dir / skill_name / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)

    # Clean up the now-empty quarantine sub-directory
    quarantine_skill_dir = skills_dir / "quarantine" / skill_name
    try:
        quarantine_skill_dir.rmdir()
    except OSError:
        pass

    decision = Decision(
        skill_name=skill_name,
        decision="promote",
        reason=(
            f"Skill '{skill_name}' manually re-promoted from quarantine. "
            "Restored to plugin/skills/ and back in load_skill_tools glob."
        ),
        ts=_now_iso(),
        applied=True,
    )
    _log_decision(decision)
    return decision


def scan(skills_dir: Path, telemetry_dir: Path) -> list[Decision]:
    """Scan all skills in skills_dir and return archive/quarantine decisions.

    For each SKILL.md found in skills_dir/*/SKILL.md:
    1. Count idle sessions → if >= ARCHIVE_AFTER_N, emit archive decision.
    2. Check rejection rate → if > QUARANTINE_REJECTION_RATE, emit quarantine decision.

    telemetry_dir is the sharded telemetry directory (globbed for *.events.jsonl
    by count_idle_sessions), not a single-file path.

    Returns a list of Decision objects. Does NOT apply the decisions (caller decides).
    Decisions are also logged via _log_decision.
    """
    skills_dir = Path(skills_dir)
    decisions: list[Decision] = []

    archive_n = _archive_after_n()
    q_rate = _quarantine_rejection_rate()

    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        # Skip if it's inside quarantine/ (already quarantined)
        if "quarantine" in skill_md.parts:
            continue

        skill_name = skill_md.parent.name

        # Check 1: idle session archive
        idle = count_idle_sessions(skill_name, telemetry_dir)
        if idle >= archive_n:
            d = Decision(
                skill_name=skill_name,
                decision="archive",
                reason=(
                    f"Skill '{skill_name}' has been idle for {idle} sessions "
                    f"(threshold: {archive_n}). No tool-use events since the last "
                    "firing session. Flagged for archive."
                ),
                ts=_now_iso(),
            )
            _log_decision(d)
            decisions.append(d)

        # Check 2: rejection rate quarantine
        rate = rejection_rate(skill_name)
        if rate > q_rate:
            d = Decision(
                skill_name=skill_name,
                decision="quarantine",
                reason=(
                    f"Skill '{skill_name}' has rejection rate {rate:.1%} over the last "
                    f"{_quarantine_window()} firing-sessions (threshold: {q_rate:.0%}). "
                    "Flagged for quarantine."
                ),
                ts=_now_iso(),
            )
            _log_decision(d)
            decisions.append(d)

    return decisions

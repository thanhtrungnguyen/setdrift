"""Pins the REQ-SAFETY-03 telemetry contract for deprecator.count_idle_sessions
against the REAL telemetry writer (Phase 1's stop_batch_scrubber.py).

FIXED in Plan 06-02 (FIX-01): count_idle_sessions and the deprecate-scan CLI
now read the real sharded contract. This module documents the (formerly
broken, now correct) contract and pins it against regression.

Reality, confirmed by reading source:
  - plugin/hooks/hot_path_capture.py writes RAW per-session buffers with fields
    `_session` (not `session`) and `tool_name` (not `tool`).
  - plugin/hooks/stop_batch_scrubber.py reads that raw buffer, scrubs it via
    scrub_event() (which does `dict(event)` — i.e. preserves the SAME field
    names, only mutating string-bearing fields), and writes the scrubbed
    dict to `data/telemetry/<session_id>.events.jsonl` — ONE JSONL SHARD PER
    SESSION. There is structurally no single merged `events.jsonl` file.
  - eval/setdrift_eval/telemetry/query.py (the correct, Phase-1-aware consumer)
    globs `data/telemetry/*.events.jsonl` and reads fields via
    `json_extract_string(json, '$._session')` / `'$.tool_name'` — i.e. it
    already knows about both the sharded layout AND the underscore-prefixed
    field names.
  - eval/setdrift_eval/optimizer/deprecator.count_idle_sessions(skill_name,
    telemetry_dir) now imitates the SAME contract: globs
    `telemetry_dir/*.events.jsonl` and reads `_session`/`tool_name`.
  - The CLI's `deprecate-scan --telemetry-dir` default is
    `Path("data/telemetry")` (env-overridable via SETDRIFT_TELEMETRY_DIR) —
    the real sharded directory the Phase-1 writer produces.

REQ-SAFETY-03 promises idle-skill archival driven by real telemetry; this
test pins that the archival path actually operates on the telemetry the
system produces (no longer silently inert).
"""

import json
from pathlib import Path

from setdrift_eval.optimizer.deprecator import count_idle_sessions

_EVAL_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _EVAL_DIR.parents[0]
_CLI_PATH = _EVAL_DIR / "setdrift_eval" / "cli.py"
_SCRUBBER_PATH = _REPO_ROOT / "plugin" / "hooks" / "stop_batch_scrubber.py"
_HOT_PATH_CAPTURE = _REPO_ROOT / "plugin" / "hooks" / "hot_path_capture.py"


def _scrubbed_event(
    session: str, tool_name: str | None, ts: str, tool_input: str | None = "{}"
) -> dict:
    """Build a realistic scrubbed per-session event record.

    Field shape matches hot_path_capture.py's raw record (preserved verbatim
    by scrub_event, which only mutates string VALUES, never field NAMES):
    _ts_captured, _hook_event, _session, _cwd, _transcript, tool_name,
    tool_input, tool_result, prompt, message_preview, _hook_runtime_ms.
    """
    return {
        "_ts_captured": ts,
        "_hook_event": "PostToolUse",
        "_session": session,
        "_cwd": "/repo",
        "_transcript": None,
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_result": "ok",
        "prompt": None,
        "message_preview": None,
        "_hook_runtime_ms": 1.23,
    }


def _skill_firing_event(session: str, skill: str, ts: str) -> dict:
    """Build a REAL skill-firing event as the Phase-1 writer records it (CR-01).

    Verified against real data/telemetry/*.events.jsonl shards: a skill firing
    is `tool_name == "Skill"` with the skill name inside the tool_input JSON
    string, e.g. '{"skill": "paperclip"}' or namespaced
    '{"skill": "superpowers:brainstorming"}'. The skill's own name NEVER
    appears in the tool_name field — that field only carries Claude Code tool
    names (Bash, Read, Skill, ...).
    """
    return _scrubbed_event(session, "Skill", ts, tool_input=json.dumps({"skill": skill}))


def _write_shard(telemetry_dir: Path, session: str, events: list[dict]) -> Path:
    """Write one per-session shard: data/telemetry/<session>.events.jsonl."""
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    shard_path = telemetry_dir / f"{session}.events.jsonl"
    with shard_path.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")
    return shard_path


# ---------------------------------------------------------------------------
# 1. Pins the FIXED behavior against a REAL sharded layout (regression pin).
# ---------------------------------------------------------------------------


def test_count_idle_sessions_over_real_sharded_telemetry_layout(tmp_path):
    """count_idle_sessions must correctly count idle sessions across REAL
    per-session shards, not a single merged file that never exists in
    production.

    Scenario: 3 sessions in chronological order.
      - session-a: skill "my-skill" fires (tool_name == "Skill",
        tool_input == '{"skill": "my-skill"}' — the REAL writer shape, CR-01)
      - session-b: only an unrelated tool fires (idle, after last firing)
      - session-c: only an unrelated tool fires (idle, after last firing)
    Expected idle count (post-fix): 2 (session-b, session-c).
    """
    telemetry_dir = tmp_path / "telemetry"

    _write_shard(
        telemetry_dir,
        "session-a",
        [_skill_firing_event("session-a", "my-skill", "2026-01-01T00:00:00Z")],
    )
    _write_shard(
        telemetry_dir,
        "session-b",
        [_scrubbed_event("session-b", "other_tool", "2026-01-02T00:00:00Z")],
    )
    _write_shard(
        telemetry_dir,
        "session-c",
        [_scrubbed_event("session-c", "other_tool", "2026-01-03T00:00:00Z")],
    )

    # Call surface an auditor would expect AFTER the fix: pass the telemetry
    # DIRECTORY (matching query.py's *.events.jsonl glob convention), not a
    # single-file path that never exists against real telemetry.
    idle = count_idle_sessions("my-skill", telemetry_dir)

    assert idle == 2, (
        f"Expected 2 idle sessions (session-b, session-c) counted from real "
        f"per-session shards under {telemetry_dir}, got {idle}. Current impl "
        "either silently returns 0 (directory has no file at the literal path) "
        "or errors trying to .open() a directory as a file — both confirm the "
        "contract mismatch."
    )


# ---------------------------------------------------------------------------
# 1b. Field-level contract (CR-01): firing detection matches the REAL writer
#     shape (tool_name == "Skill" + skill name in tool_input), never the
#     fabricated tool_name == "<skill-name>" shape the writer never emits.
# ---------------------------------------------------------------------------


def test_firing_detection_uses_real_skill_tool_shape_not_tool_name(tmp_path):
    """A firing recorded the way the REAL writer records it (tool_name="Skill",
    tool_input='{"skill": "my-skill"}') must reset the idle count; an event
    with tool_name == "my-skill" (a shape the writer structurally never
    produces) must NOT count as a firing.
    """
    telemetry_dir = tmp_path / "telemetry"

    # Fabricated legacy shape — must be treated as an ordinary (non-firing) tool event.
    _write_shard(
        telemetry_dir,
        "session-a",
        [_scrubbed_event("session-a", "my-skill", "2026-01-01T00:00:00Z")],
    )
    # Real firing shape.
    _write_shard(
        telemetry_dir,
        "session-b",
        [_skill_firing_event("session-b", "my-skill", "2026-01-02T00:00:00Z")],
    )
    _write_shard(
        telemetry_dir,
        "session-c",
        [_scrubbed_event("session-c", "other_tool", "2026-01-03T00:00:00Z")],
    )

    idle = count_idle_sessions("my-skill", telemetry_dir)
    assert idle == 1, (
        "Last firing must be the REAL-shape event in session-b (so only "
        f"session-c is idle), got {idle}. If this is 2, the real Skill/"
        "tool_input shape was not detected; if 0, the fabricated "
        "tool_name=='my-skill' shape was wrongly counted as the last firing."
    )


def test_firing_detection_matches_namespaced_skill_payload(tmp_path):
    """Real payloads may be namespaced (e.g. '{"skill": "setdrift:my-skill"}',
    as observed in live shards: 'superpowers:brainstorming') — the namespaced
    form must count as a firing of 'my-skill'."""
    telemetry_dir = tmp_path / "telemetry"

    _write_shard(
        telemetry_dir,
        "session-a",
        [_skill_firing_event("session-a", "setdrift:my-skill", "2026-01-01T00:00:00Z")],
    )
    _write_shard(
        telemetry_dir,
        "session-b",
        [_scrubbed_event("session-b", "other_tool", "2026-01-02T00:00:00Z")],
    )

    idle = count_idle_sessions("my-skill", telemetry_dir)
    assert idle == 1, (
        f"Namespaced firing 'setdrift:my-skill' must count as a firing of "
        f"'my-skill' (expected 1 idle session, got {idle})."
    )


# ---------------------------------------------------------------------------
# 2. Positive assertion: CLI + scrubber now agree on the SAME sharded contract.
# ---------------------------------------------------------------------------


def test_cli_telemetry_dir_and_scrubber_output_naming_now_align():
    """Confirms the CLI's deprecate-scan default and the real scrubber output
    now agree on the sharded per-session contract (formerly a divergence
    sentinel pinning the mismatch; retired now that FIX-01 landed).

    Asserts, by reading actual source (not guessing):
      1. `deprecate-scan --telemetry-dir` CLI flag exists and no longer has a
         single-file `--events` flag.
      2. stop_batch_scrubber.py's real output naming is per-session
         (`f"{session_id}.events.jsonl"` under TELEMETRY_DIR) — the same
         shape count_idle_sessions now globs for via `*.events.jsonl`.
    """
    cli_source = _CLI_PATH.read_text(encoding="utf-8")
    scrubber_source = _SCRUBBER_PATH.read_text(encoding="utf-8")

    # (1) CLI now exposes the sharded-directory flag, not the single-file one.
    assert '--telemetry-dir' in cli_source, (
        "deprecate-scan --telemetry-dir flag must exist in cli.py (FIX-01)"
    )
    assert '"--events"' not in cli_source, (
        "cli.py's deprecate-scan --events single-file flag must be retired "
        "(FIX-01 breaking change, no legacy retained)"
    )

    # (2) The real writer emits PER-SESSION shards, matching the glob
    # count_idle_sessions now uses (`*.events.jsonl`).
    assert 'f"{session_id}.events.jsonl"' in scrubber_source, (
        "stop_batch_scrubber.py must name its clean output per-session "
        "(<session_id>.events.jsonl) — the shape count_idle_sessions globs for."
    )

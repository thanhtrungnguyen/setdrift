"""Pins the REQ-SAFETY-03 contract mismatch between deprecator.count_idle_sessions
and the REAL telemetry writer (Phase 1's stop_batch_scrubber.py).

KNOWN, CONFIRMED production bug (see v1.0-MILESTONE-AUDIT Blocker 1). Do NOT fix
deprecator.py or cli.py here — this module only documents/pins the mismatch.

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
    events_path) instead: (a) expects ONE file at a caller-supplied path, and
    (b) reads `ev.get("session")` / `ev.get("tool")` — plain names that never
    appear in a real scrubbed shard.
  - The CLI's `deprecate-scan --events` default is
    `Path("data/telemetry/events.jsonl")` — a path that structurally never
    exists under the real Phase-1 writer. Because count_idle_sessions()
    returns 0 silently when the path is absent (by design, "cannot flag
    without data"), `setdrift-eval deprecate-scan` run against real telemetry
    with default args NEVER archives anything, even when the real per-session
    shards clearly show N+ idle sessions.

This is a genuine requirement violation: REQ-SAFETY-03 promises idle-skill
archival driven by real telemetry, but the archival path is silently inert
against the telemetry the system actually produces.
"""

import json
from pathlib import Path

import pytest

from setdrift_eval.optimizer.deprecator import count_idle_sessions

_EVAL_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _EVAL_DIR.parents[0]
_CLI_PATH = _EVAL_DIR / "setdrift_eval" / "cli.py"
_SCRUBBER_PATH = _REPO_ROOT / "plugin" / "hooks" / "stop_batch_scrubber.py"
_HOT_PATH_CAPTURE = _REPO_ROOT / "plugin" / "hooks" / "hot_path_capture.py"


def _scrubbed_event(session: str, tool_name: str | None, ts: str) -> dict:
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
        "tool_input": "{}",
        "tool_result": "ok",
        "prompt": None,
        "message_preview": None,
        "_hook_runtime_ms": 1.23,
    }


def _write_shard(telemetry_dir: Path, session: str, events: list[dict]) -> Path:
    """Write one per-session shard: data/telemetry/<session>.events.jsonl."""
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    shard_path = telemetry_dir / f"{session}.events.jsonl"
    with shard_path.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")
    return shard_path


# ---------------------------------------------------------------------------
# 1. xfail: pins the EXPECTED post-fix behavior against a REAL sharded layout.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "known bug: deprecator.count_idle_sessions reads a single merged "
        "events.jsonl file and matches plain `session`/`tool` fields; Phase 1's "
        "stop_batch_scrubber.py writes per-session shards "
        "(data/telemetry/<session>.events.jsonl) using `_session`/`tool_name` "
        "fields. See v1.0-MILESTONE-AUDIT Blocker 1. Expected POST-FIX contract: "
        "count_idle_sessions(skill_name, telemetry_dir) should glob "
        "`telemetry_dir/*.events.jsonl` (matching query.py's convention) and "
        "read `_session`/`tool_name`, returning the count of distinct sessions "
        "with tool activity since the skill's last firing session."
    ),
)
def test_count_idle_sessions_over_real_sharded_telemetry_layout(tmp_path):
    """count_idle_sessions must correctly count idle sessions across REAL
    per-session shards, not a single merged file that never exists in
    production.

    Scenario: 3 sessions in chronological order.
      - session-a: skill "my-skill" fires (tool_name == "my-skill")
      - session-b: only an unrelated tool fires (idle, after last firing)
      - session-c: only an unrelated tool fires (idle, after last firing)
    Expected idle count (post-fix): 2 (session-b, session-c).
    """
    telemetry_dir = tmp_path / "telemetry"

    _write_shard(
        telemetry_dir,
        "session-a",
        [_scrubbed_event("session-a", "my-skill", "2026-01-01T00:00:00Z")],
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
# 2. Always-green sentinel: documents the CURRENT factual mismatch precisely.
# ---------------------------------------------------------------------------


def test_cli_default_events_path_and_scrubber_output_naming_currently_diverge():
    """Sentinel: pins today's factual reality so this test starts FAILING the
    moment someone changes either side (prompting cleanup of this file and
    the paired xfail above).

    Asserts, by reading actual source (not guessing):
      1. `deprecate-scan --events` CLI default is the single-file path
         Path("data/telemetry/events.jsonl").
      2. stop_batch_scrubber.py's real output naming is per-session
         (`f"{session_id}.events.jsonl"` under TELEMETRY_DIR), i.e. NOT the
         single merged file the CLI default assumes.
    """
    cli_source = _CLI_PATH.read_text(encoding="utf-8")
    scrubber_source = _SCRUBBER_PATH.read_text(encoding="utf-8")

    # (1) CLI default for deprecate-scan --events is the single merged file.
    assert '--events' in cli_source, "deprecate-scan --events flag must exist in cli.py"
    assert 'default=Path("data/telemetry/events.jsonl")' in cli_source, (
        "cli.py's deprecate-scan --events default must currently be the single "
        "merged-file path data/telemetry/events.jsonl. If this assertion now "
        "fails, the CLI default has been fixed — retire this sentinel and the "
        "paired xfail test in this module."
    )

    # (2) The real writer emits PER-SESSION shards, not one merged file.
    assert 'f"{session_id}.events.jsonl"' in scrubber_source, (
        "stop_batch_scrubber.py must currently name its clean output "
        "per-session (<session_id>.events.jsonl). If this assertion now "
        "fails, the writer has been changed to a single merged file — "
        "retire this sentinel and the paired xfail test in this module."
    )

    # (3) The two contracts are therefore for DIFFERENT path shapes: a fixed
    # single-file literal vs. a per-session-parameterized filename pattern.
    single_file_default = "data/telemetry/events.jsonl"
    per_session_pattern = "{session_id}.events.jsonl"
    assert single_file_default != per_session_pattern
    assert not single_file_default.endswith(per_session_pattern.replace("{session_id}", ""))

"""Deprecator unit tests (Plan 03-05, REQ-SAFETY-03; sharded contract fix, Plan 06-02).

All tests use tmp_path fixtures — never the live data/telemetry wall.

Fixtures build the REAL sharded telemetry contract (one shard per session at
`<telemetry_dir>/<session>.events.jsonl`, fields `_ts_captured`/`_session`/
`tool_name`) matching `plugin/hooks/stop_batch_scrubber.py`'s output and
`eval/setdrift_eval/telemetry/query.py`'s glob convention. `count_idle_sessions`
and `scan` take the telemetry DIRECTORY, not a single-file path.

Covers:
- archive-after-N-idle: skill with >=N distinct sessions and zero firings is flagged archive
- quarantine->80%: skill with >80% rejection over last QUARANTINE_WINDOW firing-sessions
- quarantine moves SKILL.md outside the */SKILL.md load glob
- promote_skill restores the skill back to load_skill_tools
- every decision is logged with a non-empty reason
"""

import json
from pathlib import Path

import pytest

from setdrift_eval.optimizer.deprecator import (
    ARCHIVE_AFTER_N,
    QUARANTINE_WINDOW,
    QUARANTINE_REJECTION_RATE,
    Decision,
    count_idle_sessions,
    promote_skill,
    quarantine_skill,
    record_firing,
    rejection_rate,
    scan,
)
from setdrift_eval.benchmark.arm_runner import load_skill_tools


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_skill_dir(skills_dir: Path, skill_name: str, description: str = "A test skill.") -> Path:
    """Create a minimal SKILL.md at skills_dir/<skill_name>/SKILL.md."""
    skill_dir = skills_dir / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {skill_name}\ndescription: {description}\n---\n\n# {skill_name}\n",
        encoding="utf-8",
    )
    return skill_dir


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
    string, e.g. '{"skill": "paperclip"}' — the skill's own name NEVER appears
    in the tool_name field.
    """
    return _scrubbed_event(session, "Skill", ts, tool_input=json.dumps({"skill": skill}))


def _write_shard(telemetry_dir: Path, session: str, events: list[dict]) -> Path:
    """Write one per-session shard: <telemetry_dir>/<session>.events.jsonl."""
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    shard_path = telemetry_dir / f"{session}.events.jsonl"
    with shard_path.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")
    return shard_path


# ---------------------------------------------------------------------------
# Env-var constants
# ---------------------------------------------------------------------------


def test_env_constants_have_correct_defaults():
    """SETDRIFT_ARCHIVE_AFTER_N, SETDRIFT_QUARANTINE_WINDOW, SETDRIFT_QUARANTINE_RATE must read from env."""
    # defaults when env vars are not overridden
    assert ARCHIVE_AFTER_N == 20
    assert QUARANTINE_WINDOW == 10
    assert QUARANTINE_REJECTION_RATE == 0.80


# ---------------------------------------------------------------------------
# count_idle_sessions
# ---------------------------------------------------------------------------


def test_count_idle_sessions_below_N(tmp_path):
    """Skill with fewer distinct sessions than N returns the count below N."""
    telemetry_dir = tmp_path / "telemetry"
    # 5 sessions, the skill never fired in any of them (only other tools fired)
    for i in range(5):
        _write_shard(
            telemetry_dir,
            f"sess-{i}",
            [_scrubbed_event(f"sess-{i}", "other_tool", f"2026-01-01T00:0{i}:00Z")],
        )
    result = count_idle_sessions("my_skill", telemetry_dir)
    # 5 sessions total, 0 firing sessions for this skill → 5 idle
    assert result == 5
    assert result < ARCHIVE_AFTER_N


def test_count_idle_sessions_at_N(tmp_path, monkeypatch):
    """Skill with exactly N distinct sessions and no firing is flagged (count == N)."""
    monkeypatch.setenv("SETDRIFT_ARCHIVE_AFTER_N", "3")
    from importlib import reload
    import setdrift_eval.optimizer.deprecator as dep_mod

    reload(dep_mod)

    telemetry_dir = tmp_path / "telemetry"
    # 3 sessions, skill never fired
    for i in range(3):
        _write_shard(
            telemetry_dir,
            f"s{i}",
            [_scrubbed_event(f"s{i}", "other_tool", f"2026-01-01T00:0{i}:00Z")],
        )
    result = dep_mod.count_idle_sessions("absent_skill", telemetry_dir)
    assert result == 3  # exactly N idle sessions


def test_count_idle_sessions_skill_fired_resets_idle(tmp_path):
    """If the skill fired in some session, idle count is sessions SINCE the last firing."""
    telemetry_dir = tmp_path / "telemetry"
    # sessions 0-4: other tool fires
    # session 5: my_skill fires
    # sessions 6-9: other tool fires again (4 idle sessions after the last firing)
    for i in range(5):
        _write_shard(
            telemetry_dir,
            f"s{i}",
            [_scrubbed_event(f"s{i}", "other_tool", f"2026-01-01T00:0{i}:00Z")],
        )
    _write_shard(
        telemetry_dir,
        "s5",
        [_skill_firing_event("s5", "my_skill", "2026-01-02T00:00:00Z")],
    )
    for i in range(6, 10):
        _write_shard(
            telemetry_dir,
            f"s{i}",
            [_scrubbed_event(f"s{i}", "other_tool", f"2026-01-03T00:0{i}:00Z")],
        )
    result = count_idle_sessions("my_skill", telemetry_dir)
    # 4 sessions (s6-s9) occurred after the skill last fired in s5
    assert result == 4


def test_count_idle_sessions_firing_session_with_trailing_events_not_idle(tmp_path):
    """CR-03 regression: the firing session itself must NEVER count as idle,
    even when it contains more events AFTER the firing event (real sessions
    are always multi-event — the old loop flipped found_last on the FIRST
    event of the firing session, then counted its own later events as an
    idle session, inflating the count by 1 on every scan)."""
    telemetry_dir = tmp_path / "telemetry"
    # Firing session s0: firing event followed by ordinary tool events.
    _write_shard(
        telemetry_dir,
        "s0",
        [
            _skill_firing_event("s0", "my_skill", "2026-01-01T00:00:00Z"),
            _scrubbed_event("s0", "Bash", "2026-01-01T00:01:00Z"),
            _scrubbed_event("s0", "Read", "2026-01-01T00:02:00Z"),
        ],
    )
    # Two genuinely idle sessions afterwards.
    for i in (1, 2):
        _write_shard(
            telemetry_dir,
            f"s{i}",
            [_scrubbed_event(f"s{i}", "other_tool", f"2026-01-02T00:0{i}:00Z")],
        )
    result = count_idle_sessions("my_skill", telemetry_dir)
    assert result == 2, (
        f"Expected 2 idle sessions (s1, s2); got {result}. A result of 3 means "
        "the firing session s0 was wrongly counted as idle via its own "
        "post-firing events (CR-03 off-by-one)."
    )


def test_count_idle_sessions_missing_events_file(tmp_path):
    """Missing telemetry directory returns 0 idle sessions (skill cannot be flagged without data)."""
    telemetry_dir = tmp_path / "nonexistent"
    result = count_idle_sessions("my_skill", telemetry_dir)
    assert result == 0


def test_count_idle_sessions_empty_directory_returns_zero(tmp_path):
    """An existing but empty telemetry directory (no shards) returns 0."""
    telemetry_dir = tmp_path / "telemetry"
    telemetry_dir.mkdir()
    result = count_idle_sessions("my_skill", telemetry_dir)
    assert result == 0


def test_count_idle_sessions_skips_malformed_shard_line(tmp_path):
    """A shard line with malformed JSON is skipped, not fatal."""
    telemetry_dir = tmp_path / "telemetry"
    telemetry_dir.mkdir()
    shard_path = telemetry_dir / "s0.events.jsonl"
    with shard_path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(_scrubbed_event("s0", "other_tool", "2026-01-01T00:00:00Z")) + "\n")
        fh.write("{not valid json\n")
    result = count_idle_sessions("my_skill", telemetry_dir)
    assert result == 1


# ---------------------------------------------------------------------------
# record_firing + rejection_rate
# ---------------------------------------------------------------------------


def test_record_firing_appends_record(tmp_path):
    """record_firing appends a JSONL record to the deprecation dir."""
    dep_dir = tmp_path / "deprecation"
    import os

    original = os.environ.get("SETDRIFT_DEPRECATION_DIR")
    os.environ["SETDRIFT_DEPRECATION_DIR"] = str(dep_dir)
    try:
        record_firing("test_skill", "sess-1", fired=True, rejected=False)
        skill_log = dep_dir / "test_skill.jsonl"
        assert skill_log.exists(), "Per-skill JSONL must be created"
        lines = [json.loads(l) for l in skill_log.read_text(encoding="utf-8").strip().splitlines()]
        assert len(lines) == 1
        r = lines[0]
        assert r["skill_name"] == "test_skill"
        assert r["session_id"] == "sess-1"
        assert r["fired"] is True
        assert r["rejected"] is False
        assert "ts" in r
    finally:
        if original is None:
            del os.environ["SETDRIFT_DEPRECATION_DIR"]
        else:
            os.environ["SETDRIFT_DEPRECATION_DIR"] = original


def test_rejection_rate_below_threshold(tmp_path):
    """Skill with 3/10 rejections over 10 firing-sessions has rate 0.30 (below 0.80)."""
    dep_dir = tmp_path / "deprecation"
    dep_dir.mkdir()
    records = []
    for i in range(10):
        records.append(
            {
                "skill_name": "sk",
                "session_id": f"s{i}",
                "fired": True,
                "rejected": (i < 3),
                "ts": "2026-01-01T00:00:00Z",
            }
        )
    skill_log = dep_dir / "sk.jsonl"
    with skill_log.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")

    import os

    original = os.environ.get("SETDRIFT_DEPRECATION_DIR")
    os.environ["SETDRIFT_DEPRECATION_DIR"] = str(dep_dir)
    try:
        rate = rejection_rate("sk")
        assert rate == pytest.approx(0.30, abs=1e-6)
        assert rate <= QUARANTINE_REJECTION_RATE
    finally:
        if original is None:
            del os.environ["SETDRIFT_DEPRECATION_DIR"]
        else:
            os.environ["SETDRIFT_DEPRECATION_DIR"] = original


def test_rejection_rate_above_threshold(tmp_path):
    """Skill with 9/10 rejections has rate 0.90 (above 0.80 quarantine threshold)."""
    dep_dir = tmp_path / "deprecation"
    dep_dir.mkdir()
    records = []
    for i in range(10):
        records.append(
            {
                "skill_name": "bad_skill",
                "session_id": f"s{i}",
                "fired": True,
                "rejected": (i < 9),
                "ts": "2026-01-01T00:00:00Z",
            }
        )
    skill_log = dep_dir / "bad_skill.jsonl"
    with skill_log.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")

    import os

    original = os.environ.get("SETDRIFT_DEPRECATION_DIR")
    os.environ["SETDRIFT_DEPRECATION_DIR"] = str(dep_dir)
    try:
        rate = rejection_rate("bad_skill")
        assert rate == pytest.approx(0.90, abs=1e-6)
        assert rate > QUARANTINE_REJECTION_RATE
    finally:
        if original is None:
            del os.environ["SETDRIFT_DEPRECATION_DIR"]
        else:
            os.environ["SETDRIFT_DEPRECATION_DIR"] = original


def test_rejection_rate_no_firing_log(tmp_path):
    """Skill with no firing log returns rate 0.0 (cannot be quarantined without data)."""
    dep_dir = tmp_path / "deprecation"
    dep_dir.mkdir()
    import os

    original = os.environ.get("SETDRIFT_DEPRECATION_DIR")
    os.environ["SETDRIFT_DEPRECATION_DIR"] = str(dep_dir)
    try:
        rate = rejection_rate("never_fired_skill")
        assert rate == 0.0
    finally:
        if original is None:
            del os.environ["SETDRIFT_DEPRECATION_DIR"]
        else:
            os.environ["SETDRIFT_DEPRECATION_DIR"] = original


# ---------------------------------------------------------------------------
# quarantine_skill: moves SKILL.md outside the load glob
# ---------------------------------------------------------------------------


def test_quarantine_moves_skill_outside_glob(tmp_path):
    """quarantine_skill moves SKILL.md to quarantine/<name>/SKILL.md."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _make_skill_dir(skills_dir, "bad-skill")

    dep_dir = tmp_path / "deprecation"
    import os

    original = os.environ.get("SETDRIFT_DEPRECATION_DIR")
    os.environ["SETDRIFT_DEPRECATION_DIR"] = str(dep_dir)
    try:
        decision = quarantine_skill("bad-skill", skills_dir)
        # Original location must be gone
        assert not (skills_dir / "bad-skill" / "SKILL.md").exists()
        # New location must exist under quarantine/
        quarantine_path = skills_dir / "quarantine" / "bad-skill" / "SKILL.md"
        assert quarantine_path.exists(), f"Expected SKILL.md at {quarantine_path}"
        # Decision must be returned and have correct fields
        assert decision.skill_name == "bad-skill"
        assert decision.decision == "quarantine"
        assert decision.reason  # non-empty reason
    finally:
        if original is None:
            del os.environ["SETDRIFT_DEPRECATION_DIR"]
        else:
            os.environ["SETDRIFT_DEPRECATION_DIR"] = original


def test_quarantined_skill_not_loaded_by_load_skill_tools(tmp_path):
    """A quarantined skill MUST NOT be returned by load_skill_tools.

    This is the key security invariant for T-03-50 (Elevation of Privilege).
    load_skill_tools globs `skills_dir/*/SKILL.md`.
    A quarantined skill lives at `skills_dir/quarantine/<name>/SKILL.md` which
    matches `skills_dir/quarantine/SKILL.md` only if <name> is empty — not the case.
    The real path `skills_dir/quarantine/<name>/SKILL.md` is TWO levels deep under
    skills_dir, so it is NOT matched by the `*/SKILL.md` glob.
    """
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    # Create two skills: one good, one bad
    _make_skill_dir(skills_dir, "good-skill", "A good skill.")
    _make_skill_dir(skills_dir, "bad-skill", "A bad skill.")

    dep_dir = tmp_path / "deprecation"
    import os

    original = os.environ.get("SETDRIFT_DEPRECATION_DIR")
    os.environ["SETDRIFT_DEPRECATION_DIR"] = str(dep_dir)
    try:
        # Before quarantine: both skills loaded
        tools_before = load_skill_tools(skills_dir)
        tool_names_before = {t["name"] for t in tools_before}
        assert "good_skill" in tool_names_before
        assert "bad_skill" in tool_names_before

        # Quarantine the bad skill
        quarantine_skill("bad-skill", skills_dir)

        # After quarantine: only good-skill loads
        tools_after = load_skill_tools(skills_dir)
        tool_names_after = {t["name"] for t in tools_after}
        assert "good_skill" in tool_names_after, "good-skill must still load"
        assert "bad_skill" not in tool_names_after, "bad-skill must NOT load after quarantine"
    finally:
        if original is None:
            del os.environ["SETDRIFT_DEPRECATION_DIR"]
        else:
            os.environ["SETDRIFT_DEPRECATION_DIR"] = original


# ---------------------------------------------------------------------------
# promote_skill: restores skill to load glob
# ---------------------------------------------------------------------------


def test_promote_skill_restores_to_load_glob(tmp_path):
    """promote_skill moves SKILL.md back from quarantine/, so load_skill_tools finds it."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _make_skill_dir(skills_dir, "bad-skill", "A rehabilitated skill.")

    dep_dir = tmp_path / "deprecation"
    import os

    original = os.environ.get("SETDRIFT_DEPRECATION_DIR")
    os.environ["SETDRIFT_DEPRECATION_DIR"] = str(dep_dir)
    try:
        # Quarantine first
        quarantine_skill("bad-skill", skills_dir)
        assert "bad_skill" not in {t["name"] for t in load_skill_tools(skills_dir)}

        # Now promote
        decision = promote_skill("bad-skill", skills_dir)
        assert decision.skill_name == "bad-skill"
        assert decision.decision == "promote"
        assert decision.reason  # non-empty reason

        # After promotion: skill is back in load glob
        tools = load_skill_tools(skills_dir)
        tool_names = {t["name"] for t in tools}
        assert "bad_skill" in tool_names, "promoted skill must be loaded by load_skill_tools"
        # quarantine dir entry must be gone
        assert not (skills_dir / "quarantine" / "bad-skill" / "SKILL.md").exists()
    finally:
        if original is None:
            del os.environ["SETDRIFT_DEPRECATION_DIR"]
        else:
            os.environ["SETDRIFT_DEPRECATION_DIR"] = original


def test_promote_non_quarantined_skill_raises(tmp_path):
    """promote_skill raises ValueError if the skill is not in quarantine/."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _make_skill_dir(skills_dir, "normal-skill")

    import os

    original = os.environ.get("SETDRIFT_DEPRECATION_DIR")
    os.environ["SETDRIFT_DEPRECATION_DIR"] = str(tmp_path / "deprecation")
    try:
        with pytest.raises((ValueError, FileNotFoundError)):
            promote_skill("normal-skill", skills_dir)
    finally:
        if original is None:
            del os.environ["SETDRIFT_DEPRECATION_DIR"]
        else:
            os.environ["SETDRIFT_DEPRECATION_DIR"] = original


# ---------------------------------------------------------------------------
# Decision model — every decision must have a non-empty reason
# ---------------------------------------------------------------------------


def test_decision_model_requires_reason():
    """Decision Pydantic model must reject an empty reason string."""
    with pytest.raises(Exception):  # Pydantic ValidationError
        Decision(skill_name="sk", decision="archive", reason="", ts="2026-01-01T00:00:00Z")


def test_decision_model_extra_forbid():
    """Decision model must reject unknown extra fields (extra='forbid')."""
    with pytest.raises(Exception):
        Decision(
            skill_name="sk",
            decision="archive",
            reason="idle",
            ts="2026-01-01T00:00:00Z",
            unknown_field="x",
        )


def test_decision_logged_with_reason_quarantine(tmp_path):
    """quarantine_skill appends a decision JSONL record with a non-empty reason."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _make_skill_dir(skills_dir, "noisy-skill")

    dep_dir = tmp_path / "deprecation"
    import os

    original = os.environ.get("SETDRIFT_DEPRECATION_DIR")
    os.environ["SETDRIFT_DEPRECATION_DIR"] = str(dep_dir)
    try:
        decision = quarantine_skill("noisy-skill", skills_dir)
        # The decision record must be logged to the deprecation dir
        decision_log = dep_dir / "decisions.jsonl"
        assert decision_log.exists(), "decisions.jsonl must be created"
        lines = [
            json.loads(l) for l in decision_log.read_text(encoding="utf-8").strip().splitlines()
        ]
        assert len(lines) >= 1
        last = lines[-1]
        assert last["skill_name"] == "noisy-skill"
        assert last["decision"] == "quarantine"
        assert last["reason"], "reason must be non-empty"
        assert "ts" in last
        # The Decision object must also carry a reason
        assert decision.reason, "returned Decision must have a non-empty reason"
    finally:
        if original is None:
            del os.environ["SETDRIFT_DEPRECATION_DIR"]
        else:
            os.environ["SETDRIFT_DEPRECATION_DIR"] = original


def test_decision_logged_with_reason_promote(tmp_path):
    """promote_skill appends a decision JSONL record with a non-empty reason."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _make_skill_dir(skills_dir, "rehab-skill")

    dep_dir = tmp_path / "deprecation"
    import os

    original = os.environ.get("SETDRIFT_DEPRECATION_DIR")
    os.environ["SETDRIFT_DEPRECATION_DIR"] = str(dep_dir)
    try:
        quarantine_skill("rehab-skill", skills_dir)
        promote_skill("rehab-skill", skills_dir)
        decision_log = dep_dir / "decisions.jsonl"
        assert decision_log.exists()
        lines = [
            json.loads(l) for l in decision_log.read_text(encoding="utf-8").strip().splitlines()
        ]
        promote_lines = [l for l in lines if l["decision"] == "promote"]
        assert len(promote_lines) >= 1
        assert promote_lines[-1]["reason"], "promote decision reason must be non-empty"
    finally:
        if original is None:
            del os.environ["SETDRIFT_DEPRECATION_DIR"]
        else:
            os.environ["SETDRIFT_DEPRECATION_DIR"] = original


# ---------------------------------------------------------------------------
# scan: returns archive/quarantine decisions
# ---------------------------------------------------------------------------


def test_scan_flags_idle_skill_for_archive(tmp_path, monkeypatch):
    """scan flags a skill for archive when it has >= ARCHIVE_AFTER_N idle sessions."""
    monkeypatch.setenv("SETDRIFT_ARCHIVE_AFTER_N", "3")
    from importlib import reload
    import setdrift_eval.optimizer.deprecator as dep_mod

    reload(dep_mod)

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _make_skill_dir(skills_dir, "idle-skill")

    telemetry_dir = tmp_path / "telemetry"
    # 3 sessions with other tools; idle-skill never fires
    for i in range(3):
        _write_shard(
            telemetry_dir,
            f"s{i}",
            [_scrubbed_event(f"s{i}", "other_tool", f"2026-01-01T00:0{i}:00Z")],
        )

    dep_dir = tmp_path / "deprecation"
    monkeypatch.setenv("SETDRIFT_DEPRECATION_DIR", str(dep_dir))
    reload(dep_mod)

    decisions = dep_mod.scan(skills_dir, telemetry_dir)
    archive_decisions = [d for d in decisions if d.decision == "archive"]
    assert len(archive_decisions) >= 1
    idle_decision = next((d for d in archive_decisions if d.skill_name == "idle-skill"), None)
    assert idle_decision is not None, "idle-skill must be flagged for archive"
    assert idle_decision.reason, "archive decision must have a non-empty reason"


def test_scan_does_not_flag_active_skill(tmp_path, monkeypatch):
    """scan does NOT flag a skill that fired in the last N sessions."""
    monkeypatch.setenv("SETDRIFT_ARCHIVE_AFTER_N", "3")
    from importlib import reload
    import setdrift_eval.optimizer.deprecator as dep_mod

    reload(dep_mod)

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _make_skill_dir(skills_dir, "active-skill")

    telemetry_dir = tmp_path / "telemetry"
    # 2 sessions, skill fires in both → 0 idle sessions (below threshold of 3)
    for i in range(2):
        _write_shard(
            telemetry_dir,
            f"s{i}",
            [_skill_firing_event(f"s{i}", "active-skill", f"2026-01-01T00:0{i}:00Z")],
        )

    dep_dir = tmp_path / "deprecation"
    monkeypatch.setenv("SETDRIFT_DEPRECATION_DIR", str(dep_dir))
    reload(dep_mod)

    decisions = dep_mod.scan(skills_dir, telemetry_dir)
    archive_for_active = [
        d for d in decisions if d.skill_name == "active-skill" and d.decision == "archive"
    ]
    assert len(archive_for_active) == 0, "active skill must NOT be flagged for archive"


def test_scan_flags_high_rejection_for_quarantine(tmp_path, monkeypatch):
    """scan flags a skill for quarantine when rejection rate > QUARANTINE_REJECTION_RATE."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _make_skill_dir(skills_dir, "rejected-skill")

    dep_dir = tmp_path / "deprecation"
    dep_dir.mkdir()
    # Write firing records: 9/10 rejected
    records = [
        {
            "skill_name": "rejected-skill",
            "session_id": f"s{i}",
            "fired": True,
            "rejected": (i < 9),
            "ts": "2026-01-01T00:00:00Z",
        }
        for i in range(10)
    ]
    skill_log = dep_dir / "rejected-skill.jsonl"
    with skill_log.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")

    telemetry_dir = tmp_path / "telemetry"
    for i in range(10):
        _write_shard(
            telemetry_dir,
            f"s{i}",
            [_skill_firing_event(f"s{i}", "rejected-skill", f"2026-01-01T00:0{i}:00Z")],
        )

    monkeypatch.setenv("SETDRIFT_DEPRECATION_DIR", str(dep_dir))
    from importlib import reload
    import setdrift_eval.optimizer.deprecator as dep_mod

    reload(dep_mod)

    decisions = dep_mod.scan(skills_dir, telemetry_dir)
    quarantine_decisions = [
        d for d in decisions if d.decision == "quarantine" and d.skill_name == "rejected-skill"
    ]
    assert len(quarantine_decisions) >= 1, "high-rejection skill must be flagged for quarantine"
    assert quarantine_decisions[0].reason, "quarantine decision must have a non-empty reason"

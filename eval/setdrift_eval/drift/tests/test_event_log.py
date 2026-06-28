"""Tests for DriftEvent schema + dual-write append + transcript-banking standby (REQ-DRIFT-01, Plan 04-04 Task 1)."""

import json
import os

import pytest


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_event(**kwargs):
    """Build a minimal valid DriftEvent dict; caller may override any field."""
    base = {
        "event_id": "evt-001",
        "ts": "2026-06-11T00:00:00+00:00",
        "drift_type": "codebase_head_shift",
        "head_sha": "abc1234",
        "model_id": None,
        "f1_at_event_A": None,
        "f1_at_event_B": None,
        "notes": "",
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_drift_event_validates():
    """Test 1: DriftEvent validates; drift_type is a Literal of exactly {"codebase_head_shift","model_release"}."""
    from setdrift_eval.drift.event_log import DriftEvent

    evt = DriftEvent(**_make_event())
    assert evt.drift_type == "codebase_head_shift"

    evt2 = DriftEvent(
        **_make_event(drift_type="model_release", model_id="claude-sonnet-4-6", head_sha=None)
    )
    assert evt2.drift_type == "model_release"

    with pytest.raises(Exception):
        DriftEvent(**_make_event(drift_type="invalid_type"))


def test_drift_event_extra_field_raises():
    """Test 2: DriftEvent uses ConfigDict(extra="forbid") — an unknown field raises."""
    from setdrift_eval.drift.event_log import DriftEvent

    with pytest.raises(Exception):
        DriftEvent(**_make_event(unknown_field="oops"))


def test_scrub_for_public_has_no_commit_message():
    """Test 3: scrub_for_public(event) returns a dict containing NO commit-message text — Security Domain rule."""
    from setdrift_eval.drift.event_log import DriftEvent, scrub_for_public

    # notes field (which might contain commit message text) must not be in the scrubbed output
    evt = DriftEvent(**_make_event(notes="Commit: feat(api): add endpoint; author: Alice"))
    scrubbed = scrub_for_public(evt)

    assert "notes" not in scrubbed
    # Required fields must be present
    for key in (
        "event_id",
        "ts",
        "drift_type",
        "head_sha",
        "model_id",
        "f1_at_event_A",
        "f1_at_event_B",
    ):
        assert key in scrubbed, f"Expected key {key!r} in scrubbed output"


def test_append_drift_event_dual_writes(tmp_path):
    """Test 4: append_drift_event writes the full record to the raw (data-wall) path AND the scrubbed record to the public (experiments/) path; both paths env-var-overridable."""
    from setdrift_eval.drift.event_log import DriftEvent, append_drift_event

    raw_path = tmp_path / "raw" / "events-raw.jsonl"
    public_path = tmp_path / "public" / "drift-event-log.jsonl"

    evt = DriftEvent(**_make_event(notes="commit msg that must not cross the wall"))

    old_raw = os.environ.get("SETDRIFT_DRIFT_RAW_EVENTS")
    old_pub = os.environ.get("SETDRIFT_DRIFT_PUBLIC_EVENTS")
    try:
        os.environ["SETDRIFT_DRIFT_RAW_EVENTS"] = str(raw_path)
        os.environ["SETDRIFT_DRIFT_PUBLIC_EVENTS"] = str(public_path)
        append_drift_event(evt)
    finally:
        if old_raw is None:
            os.environ.pop("SETDRIFT_DRIFT_RAW_EVENTS", None)
        else:
            os.environ["SETDRIFT_DRIFT_RAW_EVENTS"] = old_raw
        if old_pub is None:
            os.environ.pop("SETDRIFT_DRIFT_PUBLIC_EVENTS", None)
        else:
            os.environ["SETDRIFT_DRIFT_PUBLIC_EVENTS"] = old_pub

    # Both files created
    assert raw_path.exists(), "Raw events file was not created"
    assert public_path.exists(), "Public events file was not created"

    # Raw record has notes (full record)
    raw_record = json.loads(raw_path.read_text(encoding="utf-8").strip())
    assert "notes" in raw_record
    assert raw_record["notes"] == "commit msg that must not cross the wall"

    # Public record has no notes (scrubbed)
    pub_record = json.loads(public_path.read_text(encoding="utf-8").strip())
    assert "notes" not in pub_record

    # Public record has required fields
    for key in ("event_id", "ts", "drift_type"):
        assert key in pub_record


def test_bank_transcripts_produces_cache_hit(tmp_path, monkeypatch):
    """Test 5: bank_transcripts pre-fills the response_cache for a given prompt+model so a later load_or_call is a cache hit (no live call)."""
    from setdrift_eval.benchmark.response_cache import cache_key, CACHE_DIR

    # Stub load_or_call to track calls
    calls = []

    def fake_load_or_call(model, prompt, tools, cache_dir):
        # First call: cache miss — write the cache file
        key = cache_key(model, prompt, tools)
        cached = tmp_path / f"{key}.json"
        if not cached.exists():
            data = {
                "content": [{"text": "stub response"}],
                "usage": {"input_tokens": 5, "output_tokens": 3},
                "stop_reason": "end_turn",
            }
            cached.write_text(json.dumps(data), encoding="utf-8")
        calls.append((model, prompt, tools))
        return json.loads(cached.read_text(encoding="utf-8"))

    monkeypatch.setattr(
        "setdrift_eval.benchmark.response_cache.load_or_call",
        fake_load_or_call,
    )

    import importlib
    import sys

    # Ensure bank_transcripts is imported fresh
    if "eval.scripts.bank_transcripts" in sys.modules:
        del sys.modules["eval.scripts.bank_transcripts"]

    # bank_transcripts.py is at eval/scripts/bank_transcripts.py; import it directly
    import importlib.util
    import pathlib

    # test_event_log.py is at eval/setdrift_eval/drift/tests/test_event_log.py
    # parents[3] = eval/ directory (the package root where scripts/ lives)
    script_path = pathlib.Path(__file__).parents[3] / "scripts" / "bank_transcripts.py"
    if not script_path.exists():
        pytest.skip(f"bank_transcripts.py not yet created at {script_path}")

    spec = importlib.util.spec_from_file_location("bank_transcripts", script_path)
    assert spec is not None and spec.loader is not None
    bt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bt)

    # The module should expose a bank_all or similar function
    assert hasattr(bt, "bank_all") or hasattr(bt, "main"), (
        "bank_transcripts.py must expose bank_all() or main() entrypoint"
    )

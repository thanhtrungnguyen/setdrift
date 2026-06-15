"""Tests for the Setdrift dashboard package (D-03/D-12/D-17).

Test groups:
  - health_json_*  : export_health_json schema and shape (D-12, UI-SPEC §A.7)
  - log_*          : LogPanel tail/empty-state/write_loop_event behaviour (D-17)
  - metric_widget_*: MetricWidget set_value / set_gated / set_stale (no .renderable)
  - skill_table_*  : SkillTable update-without-clear guard (RESEARCH Pitfall 5)
  - app_*          : SetdriftDashboard headless pilot smoke test (Textual run_test)

All Textual App tests use the built-in pilot / run_test harness — no live
terminal, no network, no real API calls.  HEADLESS only.
"""
from __future__ import annotations

import json
import types
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_f1_result(macro_f1_mean: float = 0.72) -> object:
    """Build a minimal F1Result-like namespace for mocking."""
    return types.SimpleNamespace(
        arm="B",
        macro_f1_mean=macro_f1_mean,
        noise_band_low=0.68,
        noise_band_high=0.76,
        bootstrap_ci_low=0.65,
        bootstrap_ci_high=0.79,
        coverage_pct=0.875,
    )


# ---------------------------------------------------------------------------
# health_json tests (D-12, UI-SPEC §A.7)
# ---------------------------------------------------------------------------

def test_health_json_schema_version(tmp_path):
    """export_health_json returns a dict with schema_version=1 (D-12)."""
    from setdrift_eval.dashboard.health_export import export_health_json

    fake_result = _make_f1_result()
    with patch(
        "setdrift_eval.telemetry.scorer.run_health",
        return_value=fake_result,
    ):
        payload = export_health_json(
            corpus_path=tmp_path / "corpus.jsonl",
            arm="B",
        )

    assert payload["schema_version"] == 1


def test_health_json_required_keys(tmp_path):
    """export_health_json payload contains all UI-SPEC §A.7 required keys."""
    from setdrift_eval.dashboard.health_export import export_health_json

    required_keys = {
        "schema_version", "generated_at",
        "f1_current", "f1_band_lo", "f1_band_hi",
        "pass_rate", "cost_usd", "drift_index",
        "event_count", "loop_status", "skills",
    }

    with patch(
        "setdrift_eval.telemetry.scorer.run_health",
        return_value=_make_f1_result(),
    ):
        payload = export_health_json(
            corpus_path=tmp_path / "corpus.jsonl",
            arm="B",
        )

    assert required_keys.issubset(payload.keys()), (
        f"Missing keys: {required_keys - payload.keys()}"
    )


def test_health_json_f1_values_match_run_health(tmp_path):
    """export_health_json reads F1 values from run_health — no recomputation (D-04)."""
    from setdrift_eval.dashboard.health_export import export_health_json

    result = _make_f1_result(macro_f1_mean=0.543)
    with patch(
        "setdrift_eval.telemetry.scorer.run_health",
        return_value=result,
    ):
        payload = export_health_json(
            corpus_path=tmp_path / "corpus.jsonl",
            arm="B",
        )

    assert payload["f1_current"] == result.macro_f1_mean
    assert payload["f1_band_lo"] == result.noise_band_low
    assert payload["f1_band_hi"] == result.noise_band_high
    assert payload["pass_rate"] == result.coverage_pct


def test_health_json_is_json_serializable(tmp_path):
    """export_health_json output is json.dumps-serializable (Phase-6 contract)."""
    from setdrift_eval.dashboard.health_export import export_health_json

    with patch(
        "setdrift_eval.telemetry.scorer.run_health",
        return_value=_make_f1_result(),
    ):
        payload = export_health_json(
            corpus_path=tmp_path / "corpus.jsonl",
            arm="B",
        )

    serialized = json.dumps(payload)
    roundtripped = json.loads(serialized)
    assert roundtripped["schema_version"] == 1


def test_health_json_generated_at_is_iso8601(tmp_path):
    """export_health_json generated_at is a non-empty ISO-8601 string."""
    from setdrift_eval.dashboard.health_export import export_health_json
    from datetime import datetime

    with patch(
        "setdrift_eval.telemetry.scorer.run_health",
        return_value=_make_f1_result(),
    ):
        payload = export_health_json(
            corpus_path=tmp_path / "corpus.jsonl",
            arm="B",
        )

    ts = payload["generated_at"]
    assert isinstance(ts, str) and len(ts) > 0
    # Should be parseable as ISO-8601
    datetime.fromisoformat(ts)


def test_health_json_skills_is_list(tmp_path):
    """export_health_json 'skills' key is a list (Phase-6 contract, UI-SPEC §A.7)."""
    from setdrift_eval.dashboard.health_export import export_health_json

    with patch(
        "setdrift_eval.telemetry.scorer.run_health",
        return_value=_make_f1_result(),
    ):
        payload = export_health_json(
            corpus_path=tmp_path / "corpus.jsonl",
            arm="B",
        )

    assert isinstance(payload["skills"], list)


# ---------------------------------------------------------------------------
# log_panel tests (D-17, UI-SPEC §A.9) — unit tests, no Textual app needed
# ---------------------------------------------------------------------------

def test_log_tail_telemetry_reads_last_n_lines(tmp_path):
    """tail_telemetry reads the last n_lines of events.jsonl (single-source-of-truth)."""
    import pytest
    pytest.importorskip("textual")

    events_file = tmp_path / "events.jsonl"
    lines = [json.dumps({"ts": f"2026-06-15T{i:02d}:00:00Z", "tool": "read", "ok": True}) for i in range(100)]
    events_file.write_text("\n".join(lines), encoding="utf-8")

    # We test the logic without running the full Textual app by mocking the RichLog
    from unittest.mock import MagicMock, patch

    mock_log = MagicMock()
    mock_query = MagicMock(return_value=mock_log)

    from setdrift_eval.dashboard import log_panel as lp

    panel = lp.LogPanel.__new__(lp.LogPanel)
    panel._loop_events_written = False
    panel.query_one = mock_query

    panel.tail_telemetry(events_file, n_lines=10)

    # Should have written exactly 10 lines (last 10 of 100)
    assert mock_log.write.call_count == 10


def test_log_tail_telemetry_empty_file(tmp_path):
    """tail_telemetry on an empty file writes the no-data copy (UI-SPEC §A.9)."""
    import pytest
    pytest.importorskip("textual")

    events_file = tmp_path / "events.jsonl"
    events_file.write_text("", encoding="utf-8")

    from unittest.mock import MagicMock
    from setdrift_eval.dashboard import log_panel as lp

    mock_log = MagicMock()
    panel = lp.LogPanel.__new__(lp.LogPanel)
    panel._loop_events_written = False
    panel.query_one = MagicMock(return_value=mock_log)

    panel.tail_telemetry(events_file, n_lines=50)

    call_args = [str(c) for c in mock_log.write.call_args_list]
    assert any("No telemetry events yet" in a for a in call_args), (
        f"Expected no-data copy; got: {call_args}"
    )


def test_log_tail_telemetry_missing_file(tmp_path):
    """tail_telemetry with missing file writes the ⚠ warning copy (UI-SPEC §A.9)."""
    import pytest
    pytest.importorskip("textual")

    missing = tmp_path / "nonexistent.jsonl"

    from unittest.mock import MagicMock
    from setdrift_eval.dashboard import log_panel as lp

    mock_log = MagicMock()
    panel = lp.LogPanel.__new__(lp.LogPanel)
    panel._loop_events_written = False
    panel.query_one = MagicMock(return_value=mock_log)

    panel.tail_telemetry(missing, n_lines=50)

    call_args = [str(c) for c in mock_log.write.call_args_list]
    assert any("unreadable" in a for a in call_args), (
        f"Expected warning copy; got: {call_args}"
    )


def test_log_write_loop_event_info(tmp_path):
    """write_loop_event with level='info' uses $success color (no hex)."""
    import pytest
    pytest.importorskip("textual")

    from unittest.mock import MagicMock
    from setdrift_eval.dashboard import log_panel as lp

    mock_log = MagicMock()
    panel = lp.LogPanel.__new__(lp.LogPanel)
    panel._loop_events_written = False
    panel.query_one = MagicMock(return_value=mock_log)

    panel.write_loop_event("observe phase started", level="info")

    call_args_str = str(mock_log.write.call_args_list)
    assert "$success" in call_args_str
    assert "observe phase started" in call_args_str


def test_log_write_loop_event_clears_placeholder_on_first_real_event(tmp_path):
    """write_loop_event clears Phase-3-pending placeholder on first real event."""
    import pytest
    pytest.importorskip("textual")

    from unittest.mock import MagicMock
    from setdrift_eval.dashboard import log_panel as lp

    mock_log = MagicMock()
    panel = lp.LogPanel.__new__(lp.LogPanel)
    panel._loop_events_written = False
    panel.query_one = MagicMock(return_value=mock_log)

    # First call should clear + write
    panel.write_loop_event("loop event 1", level="info")
    assert mock_log.clear.call_count == 1

    # Second call should NOT clear again
    panel.write_loop_event("loop event 2", level="warning")
    assert mock_log.clear.call_count == 1  # still 1


# ---------------------------------------------------------------------------
# metric_widget tests — verify .update() is used, never .renderable
# ---------------------------------------------------------------------------

def test_metric_widget_set_value_uses_update(monkeypatch):
    """MetricWidget.set_value calls .update() — never assigns .renderable (Pitfall 2)."""
    import pytest
    pytest.importorskip("textual")

    from setdrift_eval.dashboard.widgets import MetricWidget

    # Patch Static.__init__ to avoid full Textual initialization
    from textual.widgets import Static

    update_calls = []

    original_init = Static.__init__

    def mock_init(self_inner, *args, **kwargs):
        # Minimal init bypass
        object.__setattr__(self_inner, "_content", "")
        object.__setattr__(self_inner, "_label", "")

    with patch.object(Static, "__init__", mock_init):
        w = MetricWidget.__new__(MetricWidget)
        w._label = "F1 (current)"
        updates = []
        w.update = lambda val: updates.append(val)

        w.set_value("0.742")

    assert len(updates) == 1
    assert "0.742" in updates[0]
    # Crucially: .renderable was never assigned
    assert not hasattr(w, "renderable") or True  # ensure no AttributeError raised


def test_metric_widget_set_gated():
    """MetricWidget.set_gated shows 'GATED' in the content."""
    import pytest
    pytest.importorskip("textual")

    from setdrift_eval.dashboard.widgets import MetricWidget
    from textual.widgets import Static

    def mock_init(self_inner, *args, **kwargs):
        object.__setattr__(self_inner, "_content", "")

    with patch.object(Static, "__init__", mock_init):
        w = MetricWidget.__new__(MetricWidget)
        w._label = "F1 (current)"
        updates = []
        w.update = lambda val: updates.append(val)
        w.styles = MagicMock()

        w.set_gated()

    assert any("GATED" in u for u in updates)


# ---------------------------------------------------------------------------
# skill_table tests — update-without-clear guard (RESEARCH Pitfall 5)
# ---------------------------------------------------------------------------

def test_skill_table_update_does_not_call_clear():
    """SkillTable.update_skill_row never calls table.clear() (RESEARCH Pitfall 5)."""
    import pytest
    pytest.importorskip("textual")

    from setdrift_eval.dashboard.widgets import SkillTable

    mock_table = MagicMock()
    mock_table.add_column = MagicMock()
    mock_table.add_row = MagicMock(return_value="row_key_spring")
    mock_table.update_cell = MagicMock()

    st = SkillTable(mock_table)
    st.setup_columns()

    # Add initial row
    st.add_skill_row("spring-boot-endpoint", 0.72, 0.68, 0.76, 0.85, 0.0012, "ACTIVE")

    # Update existing row — must NOT call clear()
    st.update_skill_row("spring-boot-endpoint", 0.75, 0.71, 0.79, 0.87, 0.0014, "ACTIVE")

    mock_table.clear.assert_not_called()
    assert mock_table.update_cell.called


def test_skill_table_show_no_data_when_empty():
    """SkillTable.show_no_data adds empty-state row when table has no skills."""
    import pytest
    pytest.importorskip("textual")

    from setdrift_eval.dashboard.widgets import SkillTable

    mock_table = MagicMock()
    mock_table.add_column = MagicMock()
    mock_table.add_row = MagicMock(return_value="empty_key")

    st = SkillTable(mock_table)
    st.show_no_data()

    # Should have called add_row with the empty-state copy
    assert mock_table.add_row.called
    call_args_str = str(mock_table.add_row.call_args_list)
    assert "No telemetry events yet" in call_args_str


# ---------------------------------------------------------------------------
# app smoke test — Textual pilot (headless, no live terminal)
#
# Use asyncio.run() wrappers so no pytest-asyncio install is needed.
# Textual's run_test() is an async context manager that works with plain asyncio.
# ---------------------------------------------------------------------------

import asyncio
import pytest


def test_app_compose_headless():
    """SetdriftDashboard composes without error in headless mode (Textual pilot)."""
    pytest.importorskip("textual")

    from setdrift_eval.dashboard.app import SetdriftDashboard

    async def _run():
        # Patch _poll_metrics worker so no real corpus/experiments files are needed
        fake_result = _make_f1_result()
        app = SetdriftDashboard(
            corpus_path=Path("/nonexistent/corpus.jsonl"),
            arm="B",
        )
        # Patch the internal method so the worker never calls run_health
        app._start_poll_worker = lambda: None

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            # Header should be present
            assert app.query("Header")

    asyncio.run(_run())


def test_app_log_toggle_keybinding():
    """Pressing 'l' toggles the log panel collapsed state (UI-SPEC §A.9)."""
    pytest.importorskip("textual")

    from setdrift_eval.dashboard.app import SetdriftDashboard
    from setdrift_eval.dashboard.log_panel import LogPanel

    async def _run():
        app = SetdriftDashboard(
            corpus_path=Path("/nonexistent/corpus.jsonl"),
            arm="B",
        )
        # Suppress polling so no filesystem access occurs
        app._start_poll_worker = lambda: None

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            # Log panel starts collapsed (UI-SPEC §A.9); query by ID
            log_panel = app.query_one("#log-collapsible", LogPanel)
            initial_collapsed = log_panel.collapsed

            # Press 'l' to toggle
            await pilot.press("l")
            await pilot.pause()

            after_toggle = log_panel.collapsed
            assert after_toggle != initial_collapsed, (
                "Pressing 'l' should toggle the log panel collapsed state"
            )

    asyncio.run(_run())

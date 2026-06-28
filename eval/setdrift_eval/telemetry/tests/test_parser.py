"""Tests for the fail-loud strict JSONL parser (Plan 01-03 Task 1)."""

import json

import pytest

from setdrift_eval.telemetry.parser import parse_events_jsonl, MalformedLineError


def _write(tmp_path, lines):
    p = tmp_path / "s.events.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_happy_path(tmp_path):
    """Test 1: well-formed file returns one dict per non-blank line."""
    p = _write(tmp_path, [json.dumps({"i": i}) for i in range(3)])
    events = parse_events_jsonl(p)
    assert events == [{"i": 0}, {"i": 1}, {"i": 2}]


def test_blank_lines_allowed(tmp_path):
    """Test 2: blank/whitespace lines are skipped without error."""
    p = _write(tmp_path, [json.dumps({"a": 1}), "", "   ", json.dumps({"b": 2}), ""])
    events = parse_events_jsonl(p)
    assert events == [{"a": 1}, {"b": 2}]


def test_malformed_line_raises_with_line_no(tmp_path):
    """Test 3: a malformed line raises MalformedLineError with correct line_no + path."""
    p = _write(tmp_path, [json.dumps({"ok": 1}), "{not valid json", json.dumps({"ok": 2})])
    with pytest.raises(MalformedLineError) as ei:
        parse_events_jsonl(p)
    assert ei.value.line_no == 2
    assert ei.value.path == p


def test_no_truncated_silent_return(tmp_path):
    """Test 4: presence of a bad line raises — it does NOT return a partial list."""
    p = _write(tmp_path, [json.dumps({"ok": 1}), "GARBAGE"])
    with pytest.raises(MalformedLineError):
        parse_events_jsonl(p)

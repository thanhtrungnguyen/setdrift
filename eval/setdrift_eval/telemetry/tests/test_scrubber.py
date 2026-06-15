"""Tests for the layered scrubber (Plan 01-02 Task 2) and batch scrubber (Task 3)."""
import json
import re

import pytest

from setdrift_eval.telemetry import scrubber
from setdrift_eval.telemetry.scrubber import scrub_text, scrub_event, RedactionRecord

HEX16 = re.compile(r"^[0-9a-f]{16}$")


# ---- Task 2: scrub_text / scrub_event ----

def test_presidio_email_redacted():
    """Test 1: email removed + a presidio EMAIL_ADDRESS record."""
    scrubbed, audit = scrub_text("Please contact john@example.com about it")
    assert "john@example.com" not in scrubbed
    assert any(r.layer == "presidio" and r.entity_type == "EMAIL_ADDRESS" for r in audit)


def test_presidio_person_redacted():
    """Test 2: a person name is redacted (PERSON)."""
    scrubbed, audit = scrub_text("My colleague Sarah Johnson approved the change")
    assert "Sarah Johnson" not in scrubbed
    assert any(r.entity_type == "PERSON" for r in audit)


def test_detect_secrets_aws_key():
    """Test 3: an AWS key produces a detect_secrets record and leaves the text."""
    scrubbed, audit = scrub_text("aws_key = AKIAIOSFODNN7EXAMPLE")
    assert "AKIAIOSFODNN7EXAMPLE" not in scrubbed
    assert any(r.layer == "detect_secrets" for r in audit)


def test_audit_never_holds_plaintext():
    """Test 4: every original_hash is 16-char hex; no record field holds the secret."""
    secret = "AKIAIOSFODNN7EXAMPLE"
    email = "alice@corp.com"
    _, audit = scrub_text(f"key={secret} mail {email}")
    assert audit, "expected at least one redaction"
    for r in audit:
        assert HEX16.match(r.original_hash), r.original_hash
        blob = f"{r.layer}{r.entity_type}{r.original_hash}"
        assert secret not in blob
        assert email not in blob


def test_scrub_event_fields():
    """Test 5: scrub_event scrubs string-bearing fields and returns a flat audit list."""
    event = {
        "_session": "s1",
        "tool_name": "Bash",
        "prompt": "email me at bob@example.com",
        "tool_input": {"command": "echo AKIAIOSFODNN7EXAMPLE"},
        "tool_result": None,
    }
    out, audit = scrub_event(event)
    assert "bob@example.com" not in json.dumps(out)
    assert "AKIAIOSFODNN7EXAMPLE" not in json.dumps(out)
    assert out["tool_name"] == "Bash"  # untouched non-scrub field
    assert isinstance(audit, list) and all(isinstance(r, RedactionRecord) for r in audit)


def test_scrub_event_raises_not_swallow(monkeypatch):
    """Test 6: an internal scrubber error PROPAGATES (D-27 quarantine depends on it)."""
    def boom(*a, **k):
        raise RuntimeError("analyzer exploded")
    monkeypatch.setattr(scrubber._ANALYZER, "analyze", boom)
    with pytest.raises(RuntimeError):
        scrub_event({"prompt": "anything that reaches the analyzer"})


# ---- Task 3: stop_batch_scrubber ----

import importlib.util
from pathlib import Path

_BATCH = Path(__file__).resolve().parents[4] / "plugin" / "hooks" / "stop_batch_scrubber.py"


def _load_batch(monkeypatch, tmp_path):
    """Import stop_batch_scrubber with telemetry dirs pointed at tmp_path."""
    monkeypatch.setenv("SICA_TELEMETRY_RAW_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("SICA_TELEMETRY_DIR", str(tmp_path))
    monkeypatch.setenv("SICA_TELEMETRY_QUARANTINE_DIR", str(tmp_path / "quarantine"))
    monkeypatch.setenv("SICA_TELEMETRY_AUDIT_PATH", str(tmp_path / "scrubber-audit.jsonl"))
    spec = importlib.util.spec_from_file_location("stop_batch_scrubber", _BATCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_raw(tmp_path, session, events):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    p = raw_dir / f"{session}.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    return p


def test_batch_clean_event_routed_and_raw_deleted(monkeypatch, tmp_path):
    """Task 3 (a): a clean event lands in events.jsonl; raw buffer deleted."""
    mod = _load_batch(monkeypatch, tmp_path)
    raw = _write_raw(tmp_path, "sA", [{"_session": "sA", "tool_name": "Bash", "prompt": "hello world"}])
    mod.scrub_session("sA")
    assert (tmp_path / "sA.events.jsonl").exists()
    assert not raw.exists()  # idempotent: raw consumed


def test_batch_scrub_failure_quarantined_not_emitted(monkeypatch, tmp_path):
    """Task 3 (b): a scrub failure routes the ORIGINAL event to quarantine, not events.jsonl."""
    mod = _load_batch(monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "scrub_event", lambda e: (_ for _ in ()).throw(RuntimeError("boom")))
    _write_raw(tmp_path, "sB", [{"_session": "sB", "prompt": "secret stuff"}])
    mod.scrub_session("sB")
    quarantine = tmp_path / "quarantine" / "sB.jsonl"
    assert quarantine.exists()
    assert "secret stuff" in quarantine.read_text(encoding="utf-8")
    assert not (tmp_path / "sB.events.jsonl").exists()


def test_batch_idempotent_second_call_noop(monkeypatch, tmp_path):
    """Task 3 (c): a second scrub_session on an already-processed session is a no-op."""
    mod = _load_batch(monkeypatch, tmp_path)
    _write_raw(tmp_path, "sC", [{"_session": "sC", "prompt": "hi"}])
    mod.scrub_session("sC")
    mod.scrub_session("sC")  # must not raise (raw buffer already gone)

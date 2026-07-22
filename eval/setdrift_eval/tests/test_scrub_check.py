"""Tests for the evidence-artifact scrub check (D7-20, RUN-01 Task 3)."""

import json

from setdrift_eval.evidence.scrub_check import SECRET_RE, main, scan_artifact


def test_secret_re_matches_canonical_patterns():
    assert SECRET_RE.search("sk-ant-ABCDEFGH12345")
    assert SECRET_RE.search("AKIAABCDEFGHIJKLMNOP")
    assert SECRET_RE.search("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ01234")


def test_secret_re_matches_capture_event_regex_verbatim():
    """The regex must be reused verbatim, not re-derived, from capture_event.py."""
    assert SECRET_RE.pattern == r"(sk-[A-Za-z0-9-]{8,}|AKIA[0-9A-Z]{12,}|ghp_[A-Za-z0-9]{20,})"


def test_scan_artifact_detects_secret(tmp_path):
    artifact = tmp_path / "001-results.json"
    artifact.write_text(
        json.dumps({"api_key": "sk-ant-ABCDEFGH12345", "macro_f1": 0.9}), encoding="utf-8"
    )
    violations = scan_artifact(artifact)
    assert len(violations) == 1
    assert "secret pattern match" in violations[0]


def test_scan_artifact_clean_ids_and_metrics_only(tmp_path):
    artifact = tmp_path / "001-results.json"
    artifact.write_text(
        json.dumps({"prompt_id": "p1", "macro_f1": 0.87, "config_hash": "abc123"}),
        encoding="utf-8",
    )
    violations = scan_artifact(artifact)
    assert violations == []


def test_scan_artifact_detects_raw_prompt_leakage(tmp_path):
    artifact = tmp_path / "001-results.json"
    raw_prompt = "Please add a REST controller for the parking service"
    artifact.write_text(
        json.dumps({"prompt_id": "p1", "notes": raw_prompt}), encoding="utf-8"
    )
    violations = scan_artifact(artifact, raw_prompts={raw_prompt})
    assert len(violations) == 1
    assert "raw developer-prompt text found verbatim" in violations[0]


def test_scan_artifact_no_raw_prompt_leakage_when_absent(tmp_path):
    artifact = tmp_path / "001-results.json"
    artifact.write_text(json.dumps({"prompt_id": "p1"}), encoding="utf-8")
    violations = scan_artifact(artifact, raw_prompts={"some raw prompt text"})
    assert violations == []


def test_cli_exits_nonzero_on_secret(tmp_path, capsys):
    artifact = tmp_path / "001-results.json"
    artifact.write_text(json.dumps({"key": "sk-ant-ABCDEFGH12345"}), encoding="utf-8")
    rc = main([str(artifact)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAIL" in out


def test_cli_exits_zero_on_clean_artifact(tmp_path, capsys):
    artifact = tmp_path / "001-results.json"
    artifact.write_text(json.dumps({"prompt_id": "p1", "macro_f1": 0.9}), encoding="utf-8")
    rc = main([str(artifact)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "PASS" in out


def test_cli_scans_directory_of_artifacts(tmp_path, capsys):
    (tmp_path / "001-results.json").write_text(
        json.dumps({"prompt_id": "p1"}), encoding="utf-8"
    )
    (tmp_path / "002-results.json").write_text(
        json.dumps({"key": "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ01234"}), encoding="utf-8"
    )
    rc = main([str(tmp_path)])
    assert rc == 1


def test_cli_no_artifacts_found_exits_zero(tmp_path, capsys):
    rc = main([str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no artifacts found" in out

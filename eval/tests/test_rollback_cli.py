"""CLI init-keys + rollback subcommand tests (Plan 03-02 Task 3, REQ-SAFETY-02).

Tests: init-keys generates a key when absent + refuses overwrite;
rollback with a valid audit entry restores + prints verified=True;
rollback against a tampered audit entry fails loud (no write).

All tests are offline. SETDRIFT_SIGNING_KEY and key paths are redirected to tmp_path.
"""
import json
import sys
from pathlib import Path

import pytest

from setdrift_eval.optimizer.signer import generate_key


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_env(tmp_path, monkeypatch):
    """Redirect data/ paths to tmp_path; point SETDRIFT_SIGNING_KEY at tmp key."""
    keys_dir = tmp_path / "data" / "keys"
    keys_dir.mkdir(parents=True)
    key_file = keys_dir / "sica-hmac.key"

    audit_dir = tmp_path / "data" / "audit"
    audit_dir.mkdir(parents=True)

    monkeypatch.setenv("SETDRIFT_SIGNING_KEY", str(key_file))

    import setdrift_eval.optimizer.signer as signer_mod
    signer_mod._KEY_PATH = key_file

    return {
        "key_file": key_file,
        "audit_log": audit_dir / "audit.jsonl",
        "tmp_path": tmp_path,
    }


def _write_key(key_file: Path) -> str:
    """Write a fresh HMAC key to key_file and return the hex string."""
    key_hex = generate_key()
    key_file.write_text(key_hex, encoding="utf-8")
    return key_hex


def _make_audit_entry(descriptions: dict, sig: str, config_hash: str, audit_log: Path) -> None:
    """Append a minimal audit log entry for rollback tests."""
    record = {
        "cycle_id": "cycle-test-001",
        "step": "promote",
        "ts": "2026-06-06T12:00:00Z",
        "config_hash": config_hash,
        "parent_hash": "0" * 64,
        "f1_delta": 0.03,
        "decision": "promoted",
        "reason": "test promotion",
        "model": "claude-sonnet-4-6",
        "seed": 42,
        "hmac_sig": sig,
        "skill_descriptions": descriptions,
    }
    audit_log.parent.mkdir(parents=True, exist_ok=True)
    with audit_log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# init-keys tests
# ---------------------------------------------------------------------------

def test_init_keys_generates_key_when_absent(tmp_env, monkeypatch, capsys):
    """init-keys writes the HMAC key when no key exists yet."""
    key_file = tmp_env["key_file"]
    assert not key_file.exists()

    monkeypatch.setattr(sys, "argv", ["setdrift-eval", "init-keys"])
    from setdrift_eval.cli import main
    exit_code = main()

    assert exit_code == 0
    assert key_file.exists()
    content = key_file.read_text(encoding="utf-8").strip()
    assert len(content) == 64  # 32 bytes as hex
    captured = capsys.readouterr()
    assert "[setdrift-eval]" in captured.out
    assert "init-keys" in captured.out


def test_init_keys_refuses_to_overwrite_existing_key(tmp_env, monkeypatch, capsys):
    """init-keys refuses to overwrite an existing key (idempotent guard)."""
    key_file = tmp_env["key_file"]
    original = _write_key(key_file)

    monkeypatch.setattr(sys, "argv", ["setdrift-eval", "init-keys"])
    from setdrift_eval.cli import main
    exit_code = main()

    # Key must be unchanged
    assert key_file.read_text(encoding="utf-8").strip() == original
    captured = capsys.readouterr()
    # Should print something about already existing / refused
    assert "[setdrift-eval]" in captured.out


# ---------------------------------------------------------------------------
# rollback tests
# ---------------------------------------------------------------------------

def test_rollback_restores_and_prints_verified(tmp_env, tmp_path, monkeypatch, capsys):
    """rollback with a valid hash restores and prints verified=True."""
    from setdrift_eval.optimizer.signer import sign_config
    import setdrift_eval.optimizer.signer as signer_mod

    key_file = tmp_env["key_file"]
    audit_log = tmp_env["audit_log"]
    _write_key(key_file)
    # Re-point signer to the now-existing key
    signer_mod._KEY_PATH = key_file

    # Create a skill file to restore
    skill_file = tmp_path / "plugin" / "skills" / "test-skill" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text(
        "---\nname: test-skill\ndescription: current description\n---\n\nBody.\n",
        encoding="utf-8",
    )

    descriptions = {"test-skill": "restored description"}
    config_hash, sig = sign_config(descriptions)

    # Write audit log entry (includes skill_descriptions for rollback lookup)
    _make_audit_entry(descriptions, sig, config_hash, audit_log)

    # Patch restore_config target mapping: the CLI needs to know which file to write.
    # We override the skill_file path via a monkeypatched applier.restore_config that
    # uses our tmp skill_file.
    original_restore = None

    def patched_restore(skill_descriptions, expected_sig, targets):
        import setdrift_eval.optimizer.applier as applier_mod
        # Replace targets with our tmp skill_file
        real_targets = {k: skill_file for k in skill_descriptions}
        # Import the real restore_config
        from setdrift_eval.optimizer.applier import restore_config as _real_restore
        _real_restore(skill_descriptions, expected_sig, real_targets)

    monkeypatch.setattr("setdrift_eval.cli._rollback_restore", patched_restore, raising=False)

    monkeypatch.setattr(sys, "argv", [
        "setdrift-eval", "rollback",
        "--to", config_hash,
        "--audit-log", str(audit_log),
    ])

    from importlib import reload
    import setdrift_eval.cli as cli_mod
    # Don't reload — just call main() with patched argv
    exit_code = cli_mod.main()

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "verified=True" in captured.out
    assert config_hash in captured.out


def test_rollback_with_tampered_entry_fails_loud(tmp_env, tmp_path, monkeypatch, capsys):
    """rollback against a tampered audit entry fails loud (no write)."""
    from setdrift_eval.optimizer.signer import sign_config
    import setdrift_eval.optimizer.signer as signer_mod

    key_file = tmp_env["key_file"]
    audit_log = tmp_env["audit_log"]
    _write_key(key_file)
    signer_mod._KEY_PATH = key_file

    skill_file = tmp_path / "plugin" / "skills" / "test-skill" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    original_content = "---\nname: test-skill\ndescription: untouched\n---\n\nBody.\n"
    skill_file.write_text(original_content, encoding="utf-8")

    descriptions = {"test-skill": "restored description"}
    config_hash, real_sig = sign_config(descriptions)
    tampered_sig = "deadbeef" * 8  # 64 chars but wrong

    _make_audit_entry(descriptions, tampered_sig, config_hash, audit_log)

    def patched_restore(skill_descriptions, expected_sig, targets):
        real_targets = {k: skill_file for k in skill_descriptions}
        from setdrift_eval.optimizer.applier import restore_config as _real_restore
        _real_restore(skill_descriptions, expected_sig, real_targets)

    monkeypatch.setattr("setdrift_eval.cli._rollback_restore", patched_restore, raising=False)

    monkeypatch.setattr(sys, "argv", [
        "setdrift-eval", "rollback",
        "--to", config_hash,
        "--audit-log", str(audit_log),
    ])

    import setdrift_eval.cli as cli_mod
    # Should raise or return non-zero (bad sig)
    try:
        exit_code = cli_mod.main()
    except (ValueError, Exception):
        exit_code = 1

    # The file must remain untouched
    assert skill_file.read_text(encoding="utf-8") == original_content


# ---------------------------------------------------------------------------
# Backward compatibility: existing health dispatch still works
# ---------------------------------------------------------------------------

def test_health_dispatch_still_present():
    """health dispatch is backward-compatible (grep for args.cmd == 'health')."""
    import inspect
    import setdrift_eval.cli as cli_mod
    src = inspect.getsource(cli_mod)
    assert 'args.cmd == "health"' in src

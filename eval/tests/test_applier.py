"""Path-guarded applier unit tests (Plan 03-02 Task 2, REQ-SAFETY-02).

Tests: dry-run no-write, real write preserves body + other frontmatter keys,
eval/-target raises FenceViolation, stage_signed_candidate returns a signature,
restore_config verifies HMAC before writing (T-03-20 mitigation).

All tests are offline (no API calls). HMAC key is written to a temp path via
SETDRIFT_SIGNING_KEY env override (never touches data/keys/).
"""

import os
import textwrap
from pathlib import Path

import pytest

from setdrift_eval.optimizer.fence import FenceViolation
from setdrift_eval.optimizer.gepa_wrapper import SkillProposal
from setdrift_eval.optimizer.signer import SigningKeyError, generate_key


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def hmac_key_env(tmp_path, monkeypatch):
    """Write a fresh HMAC key to a temp path and point SETDRIFT_SIGNING_KEY at it."""
    key_file = tmp_path / "test-hmac.key"
    key_file.write_text(generate_key(), encoding="utf-8")
    monkeypatch.setenv("SETDRIFT_SIGNING_KEY", str(key_file))
    # Re-initialize _KEY_PATH in signer after env change
    import importlib
    import setdrift_eval.optimizer.signer as signer_mod

    signer_mod._KEY_PATH = Path(str(key_file))
    yield key_file


@pytest.fixture()
def fake_skill_file(tmp_path):
    """Create a minimal SKILL.md file under a 'plugin/skills/test/' path in tmp_path."""
    skill_dir = tmp_path / "plugin" / "skills" / "test-skill"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        textwrap.dedent("""\
            ---
            name: test-skill
            description: Original description text.
            author: test
            ---

            # Test Skill

            Some body content here.
            """),
        encoding="utf-8",
    )
    return skill_file


@pytest.fixture()
def plugin_proposal(fake_skill_file):
    """A SkillProposal targeting the temp plugin/ path."""
    return SkillProposal(
        target_path=fake_skill_file,
        new_content="Improved description text.",
        skill_name="test-skill",
        cycle_id="cycle-test-001",
    )


# ---------------------------------------------------------------------------
# check_allowlist integration (via apply_proposal)
# ---------------------------------------------------------------------------


def test_apply_proposal_eval_target_raises_fence_violation(tmp_path):
    """apply_proposal with a target inside eval/ raises FenceViolation, writes nothing."""
    from setdrift_eval.optimizer.applier import apply_proposal

    # Create a file in an eval/-like path inside tmp_path
    eval_file = tmp_path / "eval" / "setdrift_eval" / "scorer.py"
    eval_file.parent.mkdir(parents=True)
    eval_file.write_text("# fake scorer\n", encoding="utf-8")

    proposal = SkillProposal(
        target_path=eval_file,
        new_content="tampered content",
        skill_name="scorer",
        cycle_id="cycle-test-002",
    )
    with pytest.raises(FenceViolation):
        apply_proposal(proposal)

    # File must remain unchanged
    assert eval_file.read_text(encoding="utf-8") == "# fake scorer\n"


# ---------------------------------------------------------------------------
# dry_run behavior
# ---------------------------------------------------------------------------


def test_apply_proposal_dry_run_does_not_write(
    plugin_proposal, fake_skill_file, hmac_key_env, monkeypatch
):
    """apply_proposal(..., dry_run=True) does NOT modify the file but does NOT raise."""
    from setdrift_eval.optimizer.applier import apply_proposal

    # Patch check_allowlist to not raise for this test (proposal targets tmp_path not plugin/)
    monkeypatch.setattr(
        "setdrift_eval.optimizer.applier.check_allowlist",
        lambda p: None,
    )

    original = fake_skill_file.read_text(encoding="utf-8")
    apply_proposal(plugin_proposal, dry_run=True)
    assert fake_skill_file.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# real write: frontmatter-preserving
# ---------------------------------------------------------------------------


def test_apply_proposal_rewrites_only_description(
    plugin_proposal, fake_skill_file, hmac_key_env, monkeypatch
):
    """apply_proposal(..., dry_run=False) replaces ONLY description, preserves body + other keys."""
    from setdrift_eval.optimizer.applier import apply_proposal

    monkeypatch.setattr(
        "setdrift_eval.optimizer.applier.check_allowlist",
        lambda p: None,
    )

    apply_proposal(plugin_proposal, dry_run=False)

    written = fake_skill_file.read_text(encoding="utf-8")
    import yaml

    _, fm, body = written.split("---", 2)
    meta = yaml.safe_load(fm)

    # Description updated
    assert meta["description"] == "Improved description text."
    # Other frontmatter keys preserved
    assert meta["name"] == "test-skill"
    assert meta["author"] == "test"
    # Body preserved
    assert "# Test Skill" in body
    assert "Some body content here." in body


# ---------------------------------------------------------------------------
# stage_signed_candidate
# ---------------------------------------------------------------------------


def test_stage_signed_candidate_returns_hash_and_sig(hmac_key_env):
    """stage_signed_candidate returns (config_hash, hmac_sig) without touching plugin/."""
    from setdrift_eval.optimizer.applier import stage_signed_candidate

    descriptions = {
        "spring-boot-endpoint": "Use when creating a REST endpoint.",
        "spring-jpa-entity": "Use when mapping a JPA entity.",
    }
    config_hash, hmac_sig = stage_signed_candidate(descriptions)

    assert isinstance(config_hash, str)
    assert len(config_hash) == 64  # sha256 hex
    assert isinstance(hmac_sig, str)
    assert len(hmac_sig) == 64  # hmac-sha256 hex


def test_stage_signed_candidate_deterministic(hmac_key_env):
    """stage_signed_candidate produces the same hash for the same descriptions."""
    from setdrift_eval.optimizer.applier import stage_signed_candidate

    descriptions = {"skill-a": "Description A."}
    h1, s1 = stage_signed_candidate(descriptions)
    h2, s2 = stage_signed_candidate(descriptions)
    assert h1 == h2
    assert s1 == s2


# ---------------------------------------------------------------------------
# restore_config: signature verified BEFORE any write
# ---------------------------------------------------------------------------


def test_restore_config_raises_on_bad_sig_before_write(tmp_path, hmac_key_env, monkeypatch):
    """restore_config with a tampered sig raises before writing anything (T-03-20)."""
    from setdrift_eval.optimizer.applier import restore_config

    skill_file = tmp_path / "test-skill.md"
    skill_file.write_text("---\nname: test\ndescription: old\n---\nbody\n", encoding="utf-8")

    descriptions = {"test-skill": "restored description"}
    bad_sig = "0" * 64  # obviously wrong sig

    targets = {"test-skill": skill_file}

    with pytest.raises((ValueError, SigningKeyError, Exception)):
        restore_config(descriptions, bad_sig, targets)

    # File must remain unchanged — no write occurred
    assert "old" in skill_file.read_text(encoding="utf-8")


def test_restore_config_writes_with_valid_sig(tmp_path, hmac_key_env, monkeypatch):
    """restore_config with a valid sig writes the restored descriptions."""
    from setdrift_eval.optimizer.applier import restore_config, stage_signed_candidate

    skill_file = tmp_path / "test-skill.md"
    skill_file.write_text(
        textwrap.dedent("""\
            ---
            name: test-skill
            description: old description
            ---

            Body content.
            """),
        encoding="utf-8",
    )

    descriptions = {"test-skill": "restored description"}
    _config_hash, sig = stage_signed_candidate(descriptions)

    targets = {"test-skill": skill_file}

    # Should NOT raise
    restore_config(descriptions, sig, targets)

    written = skill_file.read_text(encoding="utf-8")
    import yaml

    _, fm, body = written.split("---", 2)
    meta = yaml.safe_load(fm)
    assert meta["description"] == "restored description"
    assert "Body content." in body

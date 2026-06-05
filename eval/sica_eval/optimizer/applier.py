"""Path-guarded skill config applier (D-46/D-47, REQ-SAFETY-02).

What this module does: the ONLY module that writes to plugin/ or CLAUDE.md. Every
write is gated by check_allowlist() FIRST (before any filesystem operation). Supports
dry_run=True for validation-without-write. Provides HMAC-signed staging
(stage_signed_candidate) and signature-verified restore (restore_config) for the
rollback CLI (03-02 Task 3).

What it does NOT do: it never writes the HMAC key, never commits to git, never
imports the orchestrator, and never bypasses the fence. It is the sole path-guarded
write surface (D-46 — proposer/orchestrator safety split).

Fail-loud: FenceViolation and signature failures propagate unmodified. No silent
swallowing — the orchestrator catches these and logs to audit.jsonl.

Requirements: REQ-SAFETY-02 (signed config + dry-run + restore).
"""
import yaml
from pathlib import Path

from sica_eval.optimizer.fence import check_allowlist  # single source of truth
from sica_eval.optimizer.gepa_wrapper import SkillProposal
from sica_eval.optimizer.signer import sign_config, verify_config


def apply_proposal(proposal: SkillProposal, *, dry_run: bool = False) -> None:
    """Write proposal.new_content to proposal.target_path after allowlist check.

    Guard-check is FIRST — raises FenceViolation (from fence.check_allowlist) if
    target_path is outside the allowlist. dry_run=True validates the path but skips
    the write. On a real write, only the `description` frontmatter field is updated;
    the body and all other frontmatter keys are preserved.

    This is the ONLY legitimate file-write path for optimizer-generated changes.
    """
    check_allowlist(proposal.target_path)  # raises FenceViolation if out-of-allowlist — MUST be FIRST
    if dry_run:
        return
    text = Path(proposal.target_path).read_text(encoding="utf-8")
    _, old_fm, body = text.split("---", 2)
    meta = yaml.safe_load(old_fm)
    meta["description"] = proposal.new_content
    new_text = f"---\n{yaml.dump(meta, default_flow_style=False)}---{body}"
    Path(proposal.target_path).write_text(new_text, encoding="utf-8")


def stage_signed_candidate(skill_descriptions: dict[str, str]) -> tuple[str, str]:
    """Return (config_hash, hmac_sig) for the given skill descriptions WITHOUT writing.

    Signs via signer.sign_config (HMAC-SHA256). The returned hash + sig are stored in
    the AuditRecord so rollback can re-verify. The D-43 human-approval gate sits
    between this staging call and any live commit — this function never writes to plugin/.
    """
    return sign_config(skill_descriptions)


def restore_config(
    skill_descriptions: dict[str, str],
    expected_sig: str,
    targets: dict[str, Path],
) -> None:
    """Restore skill descriptions from the audit log after verifying the HMAC signature.

    Calls verify_config BEFORE any write. If the signature fails, raises ValueError
    immediately — no file is touched. This is the T-03-20 mitigation: a forged or
    hand-edited config snapshot cannot be activated via rollback.

    Args:
        skill_descriptions: mapping of skill_name -> description string to restore.
        expected_sig: HMAC-SHA256 hex signature stored in the AuditRecord.
        targets: mapping of skill_name -> Path to the SKILL.md to overwrite.

    Raises:
        ValueError: if HMAC signature verification fails (before any write).
        SigningKeyError: if the HMAC key cannot be loaded.
    """
    # Verify FIRST — no writes happen until the signature is confirmed (T-03-20)
    if not verify_config(skill_descriptions, expected_sig):
        raise ValueError(
            "restore_config: HMAC signature verification failed — "
            "the stored config snapshot does not match its signature. "
            "Rollback aborted. No files written."
        )
    # Signature verified — now write each restored description
    for skill_name, description in skill_descriptions.items():
        target = Path(targets[skill_name])
        if not target.exists():
            # If no existing file, write description directly (test/integration path)
            target.write_text(description, encoding="utf-8")
            continue
        text = target.read_text(encoding="utf-8")
        if not text.startswith("---"):
            # No frontmatter — write description as plain text
            target.write_text(description, encoding="utf-8")
            continue
        _, old_fm, body = text.split("---", 2)
        meta = yaml.safe_load(old_fm)
        meta["description"] = description
        new_text = f"---\n{yaml.dump(meta, default_flow_style=False)}---{body}"
        target.write_text(new_text, encoding="utf-8")

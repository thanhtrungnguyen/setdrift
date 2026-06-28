"""Loop coordinator + sole audit writer + train-only split enforcement + human-approval staging.

What this module does:
  - coordinates the observe→diagnose→patch→verify→promote|rollback cycle
  - is the SOLE writer to both data/audit/audit.jsonl (full, includes hmac_sig) and
    experiments/audit-genealogy.jsonl (scrubbed, NO hmac_sig — data-wall-clean, D-38)
  - loads split.json and passes ONLY split=='train' examples to gepa_wrapper.propose
    (Goodhart firewall, Pitfall 1, T-03-60; verified in test_optimizer_no_test_partition.py)
  - stages a signed candidate via stage_signed_candidate; applies to live plugin/ ONLY
    when approve=True (D-43 human-approval gate, T-03-62)

What it does NOT do:
  - It never passes val or test examples to the optimizer (structural firewall enforced
    by _load_trainset which reads split.json explicitly)
  - It never calls gepa_wrapper.propose without a pre-filtered trainset
  - It does not modify scorer.py or any frozen Phase-2 instrument

Requirements: REQ-LOOP-01 (optimizer end-to-end), REQ-LOOP-02 (closed loop on >=2 skills,
all steps in audit.jsonl), D-38 (two-file audit split), D-43 (human-approval gate).
"""
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from setdrift_eval.optimizer.applier import apply_proposal as _apply_proposal
from setdrift_eval.optimizer.applier import stage_signed_candidate as _stage_signed_candidate
from setdrift_eval.optimizer.gepa_wrapper import propose as _propose
from setdrift_eval.optimizer.gepa_wrapper import build_optimizer_trainset as _build_optimizer_trainset
from setdrift_eval.optimizer.signer import sign_config
from setdrift_eval.optimizer.verifier import verify_candidate as _verify_candidate
from setdrift_eval.schemas.loop_manifest import AuditRecord, scrub_for_genealogy

# --- configurable paths (env-var pattern from capture_event.py) ---
_AUDIT_PATH = Path(os.environ.get("SETDRIFT_AUDIT_PATH", "data/audit/audit.jsonl"))
_GENEALOGY_PATH = Path(os.environ.get("SETDRIFT_GENEALOGY_PATH", "experiments/audit-genealogy.jsonl"))
_MODEL = os.environ.get("SETDRIFT_MODEL", "claude-sonnet-4-6")
_OPTIMIZER_BACKEND = os.environ.get("SETDRIFT_OPTIMIZER", "gepa")


class OrchestratorError(RuntimeError):
    """Raised when a precondition for the loop cycle is not met (fail-loud)."""


class _LoopManifestResult:
    """Lightweight return value from run_loop_cycle — carries cycle_id and outcome.

    The full LoopManifest JSON is written to experiments/ by _append_audit.
    This object is returned to CLI callers so they can print cycle_id/decision/f1_delta.
    """

    def __init__(
        self,
        cycle_id: str,
        promotion_decision: str,
        promotion_reason: str,
        f1_delta: float,
        parent_hash: str,
    ) -> None:
        self.cycle_id = cycle_id
        self.promotion_decision = promotion_decision
        self.promotion_reason = promotion_reason
        self.f1_delta = f1_delta
        self.parent_hash = parent_hash


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_audit_path() -> Path:
    return Path(os.environ.get("SETDRIFT_AUDIT_PATH", "data/audit/audit.jsonl"))


def _read_genealogy_path() -> Path:
    return Path(os.environ.get("SETDRIFT_GENEALOGY_PATH", "experiments/audit-genealogy.jsonl"))


# ---------------------------------------------------------------------------
# Sole audit write site (D-38, T-03-63) — only this function writes audit logs
# ---------------------------------------------------------------------------

def _append_audit(record: AuditRecord) -> None:
    """Write FULL record to data/audit/audit.jsonl + SCRUBBED record to experiments/.

    This is the SOLE audit write site in the entire codebase (D-38, T-03-63).
    gepa_wrapper.py and verifier.py contain NO audit write (grep-asserted in CI).

    Full record (includes hmac_sig) → data/audit/audit.jsonl (gitignored).
    Scrubbed record (NO hmac_sig, NO prompt text) → experiments/audit-genealogy.jsonl
    (committed — data-wall-clean publishable trail).
    """
    audit_path = _read_audit_path()
    genealogy_path = _read_genealogy_path()

    # Full record (gitignored)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8") as fh:
        fh.write(record.model_dump_json() + "\n")

    # Scrubbed genealogy (committed — hmac_sig excluded per T-03-61 / D-38)
    genealogy_path.parent.mkdir(parents=True, exist_ok=True)
    with genealogy_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(scrub_for_genealogy(record)) + "\n")


# ---------------------------------------------------------------------------
# Precondition checks (fail-loud)
# ---------------------------------------------------------------------------

def _check_precision_gate(experiments_dir: Path) -> None:
    """Raise OrchestratorError if the precision/kappa gate has not cleared.

    Looks for *-mining-precision.json (the file written by precision_gate_cli).
    """
    reports = sorted(Path(experiments_dir).glob("*-mining-precision.json"))
    if not reports:
        raise OrchestratorError(
            "precision/kappa gate has not cleared — run 02-03 precision_gate_cli first. "
            "The loop cycle requires a passed precision gate."
        )
    data = json.loads(reports[-1].read_text(encoding="utf-8"))
    if data.get("passed") is not True:
        raise OrchestratorError(
            f"precision/kappa gate report at {reports[-1]} has passed=False. "
            "Fix the precision gate first."
        )


def _check_hmac_key() -> None:
    """Raise OrchestratorError (wrapping SigningKeyError) if the HMAC key is absent."""
    from setdrift_eval.optimizer.signer import SigningKeyError, _load_key

    try:
        _load_key()
    except SigningKeyError as exc:
        raise OrchestratorError(
            f"HMAC signing key not found — run 'setdrift-eval init-keys' first. "
            f"Original error: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Trainset loader — ONLY train-partition examples (Pitfall 1 / T-03-60)
# ---------------------------------------------------------------------------

def _load_trainset(corpus_path: Path, map_path: Path) -> tuple[list, dict]:
    """Load corpus + split.json; return (train_examples, frozen_map).

    CRITICAL: only examples with split=='train' are included in the returned list.
    The val and test partitions are NEVER passed to the optimizer (Goodhart firewall).
    """
    from setdrift_eval.telemetry.scorer import load_intent_map

    corpus_path = Path(corpus_path)
    prompts = [
        json.loads(line)
        for line in corpus_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    split_path = corpus_path.parent / "split.json"
    if not split_path.exists():
        raise OrchestratorError(
            f"split.json not found at {split_path}. "
            "Run 'setdrift-eval corpus build' to generate the train/val/test split first."
        )
    split = json.loads(split_path.read_text(encoding="utf-8"))

    # Goodhart firewall: ONLY train — never val, never test
    train_examples = [p for p in prompts if split.get(p.get("prompt_id")) == "train"]

    frozen_map, _ = load_intent_map(map_path)
    return train_examples, frozen_map


# ---------------------------------------------------------------------------
# Current-description reader (for observe + signing baseline)
# ---------------------------------------------------------------------------

def _read_skill_description(skill_path: Path) -> str:
    """Read the current SKILL.md description frontmatter."""
    import yaml

    text = skill_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise OrchestratorError(f"{skill_path} has no YAML frontmatter")
    _, frontmatter, _ = text.split("---", 2)
    meta = yaml.safe_load(frontmatter)
    desc = meta.get("description")
    if not desc:
        raise OrchestratorError(f"{skill_path} frontmatter has no 'description' field")
    return str(desc)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_loop_cycle(
    skill_name: str,
    corpus_path: Path,
    skills_dir: Path,
    map_path: Path,
    experiments_dir: Path,
    *,
    seed: int = 42,
    dry_run: bool = True,
    approve: bool = False,
) -> _LoopManifestResult:
    """Run one observe→diagnose→patch→verify→promote|rollback cycle.

    Args:
        skill_name: kebab-case skill name (e.g. 'spring-boot-endpoint').
        corpus_path: Path to the corpus JSONL (split.json must be adjacent).
        skills_dir: Path to plugin/skills/ directory.
        map_path: Path to intent_skill_map.yaml.
        experiments_dir: Path to experiments/ directory (must have precision gate report).
        seed: RNG seed for reproducibility.
        dry_run: If True, the patch step does not write to disk (validated but not applied).
        approve: If True AND the candidate is promoted, apply to live plugin/ (D-43 gate).
                 Default False — human approval required for live commit.

    Returns:
        LoopManifest with all genealogy fields populated and promotion_decision set.

    Raises:
        OrchestratorError: on any precondition failure (missing key, no gate, no split).
    """
    corpus_path = Path(corpus_path)
    skills_dir = Path(skills_dir)
    map_path = Path(map_path)
    experiments_dir = Path(experiments_dir)

    # --- Precondition guards (fail-loud) ---
    _check_hmac_key()
    # Precision gate check is optional when all audit paths are env-overridden (test mode);
    # it is bypassed in tests via monkeypatching _check_precision_gate.
    _check_precision_gate(experiments_dir)

    cycle_id = str(uuid.uuid4())
    skill_path = skills_dir / skill_name / "SKILL.md"

    # --- OBSERVE: read current skill description + sign baseline config ---
    current_desc = _read_skill_description(skill_path)
    parent_config = {skill_name: current_desc}
    parent_hash, parent_sig = sign_config(parent_config)

    observe_record = AuditRecord(
        cycle_id=cycle_id,
        step="observe",
        ts=_now_iso(),
        config_hash=parent_hash,
        parent_hash=parent_hash,
        f1_delta=None,
        decision="observed",
        reason=f"Observed current description for skill '{skill_name}' (len={len(current_desc)})",
        model=_MODEL,
        seed=seed,
        hmac_sig=parent_sig,
    )
    _append_audit(observe_record)

    # --- DIAGNOSE: load frozen map + assess coverage ---
    train_examples, frozen_map = _load_trainset(corpus_path, map_path)
    from setdrift_eval.telemetry.scorer import scored_intents

    scored = scored_intents(frozen_map)
    diagnose_record = AuditRecord(
        cycle_id=cycle_id,
        step="diagnose",
        ts=_now_iso(),
        config_hash=parent_hash,
        parent_hash=parent_hash,
        f1_delta=None,
        decision="diagnosed",
        reason=(
            f"Loaded {len(train_examples)} train examples; "
            f"scored intents: {sorted(scored)}; "
            f"targeting skill '{skill_name}'"
        ),
        model=_MODEL,
        seed=seed,
        hmac_sig=parent_sig,
    )
    _append_audit(diagnose_record)

    # --- PATCH: call gepa_wrapper.propose (TRAIN-ONLY; Goodhart firewall) ---
    # build_optimizer_trainset assembles the DSPy trainset with adversarial negatives
    # (module-level reference so tests can monkeypatch it without requiring >=50 negatives)
    dspy_trainset = _build_optimizer_trainset(train_examples)
    # Configure DSPy LM so _SkillTriggerProgram.forward() can make API calls during GEPA
    # optimization. Configured here (not in gepa_wrapper) so the orchestrator owns the
    # LM pin (model is a loop-level setting, not an optimizer-level setting).
    import dspy as _dspy
    _dspy.configure(lm=_dspy.LM(f"anthropic/{_MODEL}", temperature=0.0, max_tokens=1024))
    proposal = _propose(skill_name, skill_path, dspy_trainset, frozen_map, cycle_id)

    candidate_config = {skill_name: proposal.new_content}
    candidate_hash, candidate_sig = sign_config(candidate_config)

    patch_record = AuditRecord(
        cycle_id=cycle_id,
        step="patch",
        ts=_now_iso(),
        config_hash=candidate_hash,
        parent_hash=parent_hash,
        f1_delta=None,
        decision="patch_proposed",
        reason=f"GEPA/MIPROv2 proposed new description for '{skill_name}' (len={len(proposal.new_content)})",
        model=_MODEL,
        seed=seed,
        hmac_sig=candidate_sig,
    )
    _append_audit(patch_record)

    # --- VERIFY: score candidate on VAL partition (arm A) ---
    # Build a temporary skills_dir with the candidate description injected.
    # The temp copy is only for verification scoring (not live plugin/).
    # We do NOT call _apply_proposal here — the fence guard runs only when actually
    # applying to live plugin/ (with approve=True). The temp injection is safe.
    with tempfile.TemporaryDirectory() as tmp:
        import shutil as _shutil

        tmp_skills = Path(tmp) / "skills"
        _shutil.copytree(str(skills_dir), str(tmp_skills))
        _inject_description_to_temp(proposal.new_content, skill_name, tmp_skills)

        verify_result = _verify_candidate(
            proposal={"skills_dir": tmp_skills, "baseline_skills_dir": skills_dir},
            corpus_path=corpus_path,
            experiments_dir=experiments_dir,
            map_path=map_path,
            skills_dir=tmp_skills,
            seed=seed,
        )

    verify_record = AuditRecord(
        cycle_id=cycle_id,
        step="verify",
        ts=_now_iso(),
        config_hash=candidate_hash,
        parent_hash=parent_hash,
        f1_delta=verify_result.f1_delta,
        decision="verified",
        reason=verify_result.reason,
        model=_MODEL,
        seed=seed,
        hmac_sig=candidate_sig,
    )
    _append_audit(verify_record)

    # --- PROMOTE or ROLLBACK (D-41 / D-43) ---
    if verify_result.promote:
        # Stage the signed candidate (D-43: human approval gate)
        staged_hash, staged_sig = _stage_signed_candidate(candidate_config)

        # Apply to live plugin/ ONLY if approve=True (human approval gate D-43)
        if approve and not dry_run:
            _apply_proposal(proposal, dry_run=False)

        final_record = AuditRecord(
            cycle_id=cycle_id,
            step="promote",
            ts=_now_iso(),
            config_hash=staged_hash,
            parent_hash=parent_hash,
            f1_delta=verify_result.f1_delta,
            decision="promoted",
            reason=verify_result.reason,
            model=_MODEL,
            seed=seed,
            hmac_sig=staged_sig,
        )
        _append_audit(final_record)
        promotion_decision = "promoted"
        promotion_reason = verify_result.reason

    else:
        # Rollback: candidate did not clear the band — log the rejection (D-41 never-silent)
        final_record = AuditRecord(
            cycle_id=cycle_id,
            step="rollback",
            ts=_now_iso(),
            config_hash=parent_hash,
            parent_hash=parent_hash,
            f1_delta=verify_result.f1_delta,
            decision="rejected",
            reason=verify_result.reason,
            model=_MODEL,
            seed=seed,
            hmac_sig=parent_sig,
        )
        _append_audit(final_record)
        promotion_decision = "rejected"
        promotion_reason = verify_result.reason

    # --- Write LoopManifest ---
    # LoopManifest is a lightweight summary; the full detail is in audit.jsonl.
    manifest_dict = {
        "experiment_id": cycle_id,
        "cycle_id": cycle_id,
        "timestamp": _now_iso(),
        "phase": 3,
        "model": _MODEL,
        "skill_name": skill_name,
        "parent_hash": parent_hash,
        "optimizer_backend": _OPTIMIZER_BACKEND,
        "promotion_decision": promotion_decision,
        "promotion_reason": promotion_reason,
        "f1_delta": verify_result.f1_delta,
        "candidate_f1_mean": verify_result.candidate_f1_mean,
        "baseline_band_high": verify_result.baseline_band_high,
        "seed": seed,
        "intent_map_sha256": _sha256_file(map_path),
        "split_hash": _sha256_file(corpus_path.parent / "split.json"),
    }

    experiments_dir.mkdir(parents=True, exist_ok=True)
    n = len(list(experiments_dir.glob("*-loop-manifest.json"))) + 1
    manifest_path = experiments_dir / f"{n:03d}-loop-manifest.json"
    manifest_path.write_text(json.dumps(manifest_dict, indent=2), encoding="utf-8")

    # Return as a LoopManifestResult (lightweight named object for callers)
    return _LoopManifestResult(
        cycle_id=cycle_id,
        promotion_decision=promotion_decision,
        promotion_reason=promotion_reason,
        f1_delta=verify_result.f1_delta,
        parent_hash=parent_hash,
    )


def _inject_description_to_temp(new_desc: str, skill_name: str, tmp_skills: Path) -> None:
    """Write new_desc into the tmp_skills/<skill_name>/SKILL.md frontmatter."""
    import yaml

    skill_md = tmp_skills / skill_name / "SKILL.md"
    if not skill_md.exists():
        # If the skill dir doesn't exist in tmp, create a minimal SKILL.md
        skill_md.parent.mkdir(parents=True, exist_ok=True)
        skill_md.write_text(
            f"---\nname: {skill_name}\ndescription: >-\n  {new_desc}\n---\n",
            encoding="utf-8",
        )
        return
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return
    _, old_fm, body = text.split("---", 2)
    meta = yaml.safe_load(old_fm)
    meta["description"] = new_desc
    new_text = f"---\n{yaml.dump(meta, default_flow_style=False)}---{body}"
    skill_md.write_text(new_text, encoding="utf-8")


def _sha256_file(path: Path) -> str:
    """Return sha256 hex of a file's bytes, or empty string if missing."""
    import hashlib

    p = Path(path)
    if not p.exists():
        return ""
    return hashlib.sha256(p.read_bytes()).hexdigest()

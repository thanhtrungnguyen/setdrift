"""AuditRecord + LoopManifest schema tests (Plan 03-02 Task 1, REQ-SAFETY-02).

Tests: AuditRecord round-trip, step Literal validation, f1_delta None,
LoopManifest inheritance + genealogy fields, extra="forbid" on both,
and scrub_for_genealogy excludes hmac_sig (T-03-22 mitigation).
"""
import pytest
from pydantic import ValidationError

from setdrift_eval.schemas.loop_manifest import AuditRecord, LoopManifest, scrub_for_genealogy


def _audit_kwargs(**overrides) -> dict:
    base = dict(
        cycle_id="cycle-abc-001",
        step="observe",
        ts="2026-06-06T12:00:00Z",
        config_hash="a" * 64,
        parent_hash="b" * 64,
        f1_delta=None,
        decision="observed",
        reason="baseline observation",
        model="claude-sonnet-4-6",
        seed=42,
        hmac_sig="c" * 64,
    )
    base.update(overrides)
    return base


def _loop_manifest_kwargs(**overrides) -> dict:
    base = dict(
        experiment_id="exp-loop-001",
        timestamp="2026-06-06T12:00:00Z",
        model="claude-sonnet-4-6",
        arm="A",
        corpus_name="public",
        corpus_version="2026-06-01",
        dataset_sha256="a" * 64,
        split_hash="b" * 64,
        intent_map_sha256="c" * 64,
        config_hash="d" * 64,
        rng_seed=42,
        n_prompts_scored=400,
        n_prompts_out_of_coverage=156,
        coverage_pct=0.125,
        macro_f1_runs=[0.5, 0.51, 0.49, 0.5, 0.52],
        macro_f1_mean=0.504,
        macro_f1_noise_band_low=0.48,
        macro_f1_noise_band_high=0.53,
        bootstrap_ci_low=0.46,
        bootstrap_ci_high=0.55,
        token_cost_total=123456,
        # LoopManifest-specific required fields:
        parent_hash="e" * 64,
        cycle_id="cycle-abc-001",
    )
    base.update(overrides)
    return base


# --- AuditRecord tests ---

def test_audit_record_roundtrips():
    """AuditRecord round-trips via model_dump_json with all D-40 fields."""
    rec = AuditRecord(**_audit_kwargs())
    restored = AuditRecord.model_validate_json(rec.model_dump_json())
    assert restored == rec


def test_audit_record_all_d40_fields_present():
    """AuditRecord has all D-40 fields."""
    rec = AuditRecord(**_audit_kwargs())
    assert rec.cycle_id == "cycle-abc-001"
    assert rec.step == "observe"
    assert rec.ts == "2026-06-06T12:00:00Z"
    assert rec.config_hash == "a" * 64
    assert rec.parent_hash == "b" * 64
    assert rec.f1_delta is None
    assert rec.decision == "observed"
    assert rec.reason == "baseline observation"
    assert rec.model == "claude-sonnet-4-6"
    assert rec.seed == 42
    assert rec.hmac_sig == "c" * 64


def test_audit_record_step_literal_all_valid():
    """AuditRecord step accepts each of the six valid step values."""
    for step in ("observe", "diagnose", "patch", "verify", "promote", "rollback"):
        rec = AuditRecord(**_audit_kwargs(step=step))
        assert rec.step == step


def test_audit_record_step_literal_rejects_unknown():
    """AuditRecord rejects an unknown step value (Literal constraint)."""
    with pytest.raises(ValidationError):
        AuditRecord(**_audit_kwargs(step="unknown_step"))


def test_audit_record_f1_delta_none_is_valid():
    """AuditRecord(f1_delta=None) is valid on non-verify steps."""
    rec = AuditRecord(**_audit_kwargs(step="observe", f1_delta=None))
    assert rec.f1_delta is None


def test_audit_record_f1_delta_float_is_valid():
    """AuditRecord(f1_delta=float) is valid on verify/promote steps."""
    rec = AuditRecord(**_audit_kwargs(step="verify", f1_delta=0.05))
    assert rec.f1_delta == pytest.approx(0.05)


def test_audit_record_extra_field_rejected():
    """extra='forbid' rejects unknown fields on AuditRecord."""
    with pytest.raises(ValidationError):
        AuditRecord(**_audit_kwargs(unexpected_field="x"))


# --- LoopManifest tests ---

def test_loop_manifest_inherits_experiment_manifest_fields():
    """LoopManifest inherits every required ExperimentManifest field."""
    m = LoopManifest(**_loop_manifest_kwargs())
    # Inherited fields:
    assert m.experiment_id == "exp-loop-001"
    assert m.model == "claude-sonnet-4-6"
    assert m.corpus_name == "public"
    assert m.config_hash == "d" * 64
    assert m.split_hash == "b" * 64
    assert m.intent_map_sha256 == "c" * 64


def test_loop_manifest_adds_genealogy_fields():
    """LoopManifest adds parent_hash and cycle_id."""
    m = LoopManifest(**_loop_manifest_kwargs())
    assert m.parent_hash == "e" * 64
    assert m.cycle_id == "cycle-abc-001"


def test_loop_manifest_phase_defaults_to_3():
    """LoopManifest.phase defaults to 3 (not 2)."""
    m = LoopManifest(**_loop_manifest_kwargs())
    assert m.phase == 3


def test_loop_manifest_optimizer_backend_default():
    """LoopManifest.optimizer_backend defaults to 'gepa'."""
    m = LoopManifest(**_loop_manifest_kwargs())
    assert m.optimizer_backend == "gepa"


def test_loop_manifest_promotion_decision_default():
    """LoopManifest.promotion_decision defaults to 'pending'."""
    m = LoopManifest(**_loop_manifest_kwargs())
    assert m.promotion_decision == "pending"


def test_loop_manifest_extra_field_rejected():
    """extra='forbid' blocks unknown fields on LoopManifest."""
    with pytest.raises(ValidationError):
        LoopManifest(**_loop_manifest_kwargs(unexpected_field="x"))


def test_loop_manifest_roundtrips():
    """LoopManifest round-trips via JSON serialization."""
    m = LoopManifest(**_loop_manifest_kwargs())
    restored = LoopManifest.model_validate_json(m.model_dump_json())
    assert restored == m


# --- scrub_for_genealogy tests ---

def test_scrub_for_genealogy_excludes_hmac_sig():
    """scrub_for_genealogy output MUST exclude hmac_sig (T-03-22 mitigation)."""
    rec = AuditRecord(**_audit_kwargs())
    result = scrub_for_genealogy(rec)
    assert "hmac_sig" not in result


def test_scrub_for_genealogy_includes_all_other_d40_fields():
    """scrub_for_genealogy includes all D-40 fields except hmac_sig."""
    rec = AuditRecord(**_audit_kwargs(step="promote", f1_delta=0.03))
    result = scrub_for_genealogy(rec)
    assert result["cycle_id"] == "cycle-abc-001"
    assert result["step"] == "promote"
    assert result["ts"] == "2026-06-06T12:00:00Z"
    assert result["config_hash"] == "a" * 64
    assert result["parent_hash"] == "b" * 64
    assert result["f1_delta"] == pytest.approx(0.03)
    assert result["decision"] == "observed"
    assert result["reason"] == "baseline observation"
    assert result["model"] == "claude-sonnet-4-6"
    assert result["seed"] == 42

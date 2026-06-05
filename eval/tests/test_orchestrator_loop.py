"""Orchestrator loop tests (Plan 03-06 Task 2). Offline, no API calls.

Covers:
  - run_loop_cycle passes ONLY split=='train' examples to the optimizer (Goodhart firewall)
  - promoted and rejected cycles produce audit records for all steps sharing cycle_id
  - each step writes BOTH full audit (data/audit/audit.jsonl, includes hmac_sig) AND
    scrubbed genealogy (experiments/audit-genealogy.jsonl, NO hmac_sig)
  - run_loop_cycle stages a signed candidate but does NOT auto-commit to plugin/ (D-43)
  - orchestrator is the sole _append_audit writer; gepa_wrapper/verifier contain no audit
"""
import json
import shutil
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

OVERLAP_PHRASE = "Spring annotation patterns in the parking services"
_SICA_PLUGIN_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def skills_dir(tmp_path):
    """A temp skills directory with minimal spring-boot-endpoint SKILL.md."""
    sd = tmp_path / "skills"
    (sd / "spring-boot-endpoint").mkdir(parents=True)
    (sd / "spring-boot-endpoint" / "SKILL.md").write_text(
        textwrap.dedent("""\
            ---
            name: spring-boot-endpoint
            description: >-
              Use when creating or modifying a REST endpoint in this codebase.
              Applies to Spring annotation patterns in the parking services.
            ---
            # Spring Boot Endpoint
            ## When this applies
            Creating or editing an HTTP endpoint.
        """),
        encoding="utf-8",
    )
    return sd


@pytest.fixture()
def corpus_path(tmp_path):
    """A minimal corpus JSONL with train/val/test examples."""
    corpus_dir = tmp_path / "corpora" / "public"
    corpus_dir.mkdir(parents=True)
    corpus_file = corpus_dir / "public.jsonl"

    # 3 train prompts, 1 val prompt, 1 test prompt
    records = [
        {"prompt_id": "t1", "prompt": "add a REST controller", "ground_truth_skills": ["spring-annotation-fix"]},
        {"prompt_id": "t2", "prompt": "create a GET mapping", "ground_truth_skills": ["spring-annotation-fix"]},
        {"prompt_id": "t3", "prompt": "no matching skill", "ground_truth_skills": ["none"]},
        {"prompt_id": "v1", "prompt": "expose a REST API", "ground_truth_skills": ["spring-annotation-fix"]},
        {"prompt_id": "x1", "prompt": "test partition prompt", "ground_truth_skills": ["none"]},
    ]
    corpus_file.write_text(
        "\n".join(json.dumps(r) for r in records), encoding="utf-8"
    )

    # Write split.json
    split = {"t1": "train", "t2": "train", "t3": "train", "v1": "val", "x1": "test"}
    (corpus_dir / "split.json").write_text(json.dumps(split), encoding="utf-8")
    return corpus_file


@pytest.fixture()
def map_path():
    """Use the real (re-frozen) intent_skill_map.yaml."""
    return _SICA_PLUGIN_ROOT / "eval" / "sica_eval" / "corpus" / "intent_skill_map.yaml"


@pytest.fixture()
def experiments_dir(tmp_path):
    ed = tmp_path / "experiments"
    ed.mkdir()
    return ed


@pytest.fixture()
def precision_gate_report(experiments_dir):
    """Write a passed precision/kappa gate report so run_health doesn't block."""
    report = {
        "passed": True,
        "timestamp": "2026-06-06T00:00:00Z",
        "overall_precision": 0.92,
        "overall_kappa": 0.75,
    }
    (experiments_dir / "001-mining-precision.json").write_text(
        json.dumps(report), encoding="utf-8"
    )
    return experiments_dir


@pytest.fixture()
def hmac_key(tmp_path, monkeypatch):
    """Generate a throwaway HMAC key and point SICA_SIGNING_KEY at it."""
    key_dir = tmp_path / "keys"
    key_dir.mkdir()
    key_file = key_dir / "sica-hmac.key"
    key_file.write_text("a" * 64, encoding="utf-8")  # 32-byte hex key
    monkeypatch.setenv("SICA_SIGNING_KEY", str(key_file))
    return key_file


# ---------------------------------------------------------------------------
# Helpers: build the trainset spy
# ---------------------------------------------------------------------------

def _make_propose_spy(monkeypatch, skill_name: str, new_desc: str = "improved description"):
    """Monkeypatch gepa_wrapper.propose to capture trainset and return a fake proposal.

    Also monkeypatches _build_optimizer_trainset so the adversarial-negative floor
    (>=50) is not enforced on the minimal test corpus.
    """
    from sica_eval.optimizer import gepa_wrapper as gw

    seen_trainsets: list = []

    def fake_build_trainset(train_examples, *, constructed_path=None):
        """Pass through raw train examples as dspy.Example objects (no floor check)."""
        import dspy

        examples = []
        for ex in train_examples:
            prompt = ex.get("prompt", "") if isinstance(ex, dict) else getattr(ex, "prompt", "")
            skills = set(
                (ex.get("ground_truth_skills") or []) if isinstance(ex, dict)
                else (getattr(ex, "ground_truth_skills", None) or [])
            )
            gt = frozenset(skills - {"none"})
            examples.append(dspy.Example(
                prompt=prompt,
                gt_intents=gt,
                prompt_id=ex.get("prompt_id") if isinstance(ex, dict) else getattr(ex, "prompt_id", None),
            ).with_inputs("prompt"))
        return examples

    def fake_propose(sn, skill_path, trainset, frozen_map, cycle_id):
        seen_trainsets.append(list(trainset))
        return gw.SkillProposal(
            target_path=skill_path,
            new_content=new_desc,
            skill_name=sn,
            cycle_id=cycle_id,
        )

    monkeypatch.setattr("sica_eval.optimizer.orchestrator._build_optimizer_trainset", fake_build_trainset)
    monkeypatch.setattr("sica_eval.optimizer.orchestrator._propose", fake_propose)
    return seen_trainsets


def _make_verify_result(promote: bool, f1_delta: float = 0.05):
    """Build a fake VerifyResult for monkeypatching."""
    from sica_eval.optimizer.verifier import VerifyResult

    if promote:
        reason = f"promoted: 0.8000 > 0.7500 upper band (delta=+{f1_delta:+.4f})"
    else:
        reason = f"rejected: 0.6000 <= 0.7500 upper band (delta={f1_delta:+.4f})"
    return VerifyResult(
        promote=promote,
        candidate_f1_mean=0.8 if promote else 0.6,
        baseline_band_high=0.75,
        f1_delta=f1_delta,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Test: run_loop_cycle only passes train examples to propose
# ---------------------------------------------------------------------------

def test_run_loop_cycle_only_passes_train_to_optimizer(
    tmp_path, corpus_path, skills_dir, map_path, experiments_dir, hmac_key, monkeypatch
):
    """Goodhart firewall: only split=='train' examples reach gepa_wrapper.propose."""
    from sica_eval.optimizer.orchestrator import run_loop_cycle

    seen = _make_propose_spy(monkeypatch, "spring-boot-endpoint")
    monkeypatch.setattr(
        "sica_eval.optimizer.orchestrator._verify_candidate",
        lambda *a, **k: _make_verify_result(promote=False),
    )

    # Bypass the precision gate guard
    from sica_eval.optimizer.orchestrator import _check_precision_gate
    monkeypatch.setattr("sica_eval.optimizer.orchestrator._check_precision_gate", lambda *a, **k: None)

    run_loop_cycle(
        skill_name="spring-boot-endpoint",
        corpus_path=corpus_path,
        skills_dir=skills_dir,
        map_path=map_path,
        experiments_dir=experiments_dir,
        seed=42,
        dry_run=True,
        approve=False,
    )

    assert len(seen) == 1, "propose() must be called exactly once"
    trainset_seen = seen[0]
    assert len(trainset_seen) > 0, "trainset passed to propose must not be empty"

    # Load split to verify
    split_path = corpus_path.parent / "split.json"
    split = json.loads(split_path.read_text())

    for ex in trainset_seen:
        pid = ex.get("prompt_id") if isinstance(ex, dict) else getattr(ex, "prompt_id", None)
        if pid is not None:
            assert split.get(pid) == "train", (
                f"prompt_id={pid!r} has split={split.get(pid)!r}; "
                "ONLY train examples must reach propose()"
            )


# ---------------------------------------------------------------------------
# Test: promoted cycle — all 5 steps, one cycle_id
# ---------------------------------------------------------------------------

def test_promoted_cycle_has_all_steps_same_cycle_id(
    tmp_path, corpus_path, skills_dir, map_path, experiments_dir, hmac_key, monkeypatch
):
    """Promoted cycle writes observe/diagnose/patch/verify/promote records sharing cycle_id."""
    from sica_eval.optimizer.orchestrator import run_loop_cycle

    audit_path = tmp_path / "data" / "audit" / "audit.jsonl"
    monkeypatch.setenv("SICA_AUDIT_PATH", str(audit_path))

    genealogy_path = tmp_path / "experiments" / "audit-genealogy.jsonl"
    monkeypatch.setenv("SICA_GENEALOGY_PATH", str(genealogy_path))

    _make_propose_spy(monkeypatch, "spring-boot-endpoint")
    monkeypatch.setattr(
        "sica_eval.optimizer.orchestrator._verify_candidate",
        lambda *a, **k: _make_verify_result(promote=True, f1_delta=0.05),
    )
    monkeypatch.setattr("sica_eval.optimizer.orchestrator._check_precision_gate", lambda *a, **k: None)

    manifest = run_loop_cycle(
        skill_name="spring-boot-endpoint",
        corpus_path=corpus_path,
        skills_dir=skills_dir,
        map_path=map_path,
        experiments_dir=experiments_dir,
        seed=42,
        dry_run=True,
        approve=False,
    )

    # Check audit.jsonl
    assert audit_path.exists(), "data/audit/audit.jsonl must be written"
    records = [json.loads(ln) for ln in audit_path.read_text().splitlines() if ln.strip()]
    steps = [r["step"] for r in records]
    assert "observe" in steps
    assert "diagnose" in steps
    assert "patch" in steps
    assert "verify" in steps
    assert "promote" in steps

    cycle_ids = {r["cycle_id"] for r in records}
    assert len(cycle_ids) == 1, f"All records must share one cycle_id; got {cycle_ids}"

    # Manifest must match
    assert manifest.promotion_decision == "promoted"
    assert manifest.cycle_id == records[0]["cycle_id"]


# ---------------------------------------------------------------------------
# Test: rejected cycle — all steps, one cycle_id, step="rollback"
# ---------------------------------------------------------------------------

def test_rejected_cycle_has_rollback_step(
    tmp_path, corpus_path, skills_dir, map_path, experiments_dir, hmac_key, monkeypatch
):
    """Rejected cycle writes observe/diagnose/patch/verify/rollback sharing cycle_id."""
    from sica_eval.optimizer.orchestrator import run_loop_cycle

    audit_path = tmp_path / "data" / "audit" / "audit.jsonl"
    monkeypatch.setenv("SICA_AUDIT_PATH", str(audit_path))
    genealogy_path = tmp_path / "experiments" / "audit-genealogy.jsonl"
    monkeypatch.setenv("SICA_GENEALOGY_PATH", str(genealogy_path))

    _make_propose_spy(monkeypatch, "spring-boot-endpoint")
    monkeypatch.setattr(
        "sica_eval.optimizer.orchestrator._verify_candidate",
        lambda *a, **k: _make_verify_result(promote=False, f1_delta=-0.15),
    )
    monkeypatch.setattr("sica_eval.optimizer.orchestrator._check_precision_gate", lambda *a, **k: None)

    manifest = run_loop_cycle(
        skill_name="spring-boot-endpoint",
        corpus_path=corpus_path,
        skills_dir=skills_dir,
        map_path=map_path,
        experiments_dir=experiments_dir,
        seed=42,
        dry_run=True,
        approve=False,
    )

    records = [json.loads(ln) for ln in audit_path.read_text().splitlines() if ln.strip()]
    steps = [r["step"] for r in records]
    assert "rollback" in steps
    assert "promote" not in steps

    cycle_ids = {r["cycle_id"] for r in records}
    assert len(cycle_ids) == 1

    assert manifest.promotion_decision == "rejected"


# ---------------------------------------------------------------------------
# Test: two-file audit write — full has hmac_sig, genealogy does NOT
# ---------------------------------------------------------------------------

def test_audit_full_has_hmac_sig_genealogy_does_not(
    tmp_path, corpus_path, skills_dir, map_path, experiments_dir, hmac_key, monkeypatch
):
    """Full audit.jsonl includes hmac_sig; genealogy does NOT (D-38, T-03-61)."""
    from sica_eval.optimizer.orchestrator import run_loop_cycle

    audit_path = tmp_path / "data" / "audit" / "audit.jsonl"
    monkeypatch.setenv("SICA_AUDIT_PATH", str(audit_path))
    genealogy_path = tmp_path / "experiments" / "audit-genealogy.jsonl"
    monkeypatch.setenv("SICA_GENEALOGY_PATH", str(genealogy_path))

    _make_propose_spy(monkeypatch, "spring-boot-endpoint")
    monkeypatch.setattr(
        "sica_eval.optimizer.orchestrator._verify_candidate",
        lambda *a, **k: _make_verify_result(promote=False),
    )
    monkeypatch.setattr("sica_eval.optimizer.orchestrator._check_precision_gate", lambda *a, **k: None)

    run_loop_cycle(
        skill_name="spring-boot-endpoint",
        corpus_path=corpus_path,
        skills_dir=skills_dir,
        map_path=map_path,
        experiments_dir=experiments_dir,
        seed=42,
        dry_run=True,
        approve=False,
    )

    # Full audit must have hmac_sig on every record
    audit_records = [json.loads(ln) for ln in audit_path.read_text().splitlines() if ln.strip()]
    for rec in audit_records:
        assert "hmac_sig" in rec, f"Full audit record missing hmac_sig: {rec}"

    # Genealogy must NOT have hmac_sig on any record (data-wall-clean)
    genealogy_records = [json.loads(ln) for ln in genealogy_path.read_text().splitlines() if ln.strip()]
    assert len(genealogy_records) > 0, "Genealogy file must have at least one record"
    for rec in genealogy_records:
        assert "hmac_sig" not in rec, (
            f"Genealogy record MUST NOT contain hmac_sig (T-03-61 data wall breach): {rec}"
        )
        assert "prompt" not in rec, (
            f"Genealogy record MUST NOT contain prompt text (data wall): {rec}"
        )


# ---------------------------------------------------------------------------
# Test: dry_run=True + approve=False does NOT auto-commit to live plugin/
# ---------------------------------------------------------------------------

def test_dry_run_does_not_write_to_live_plugin(
    tmp_path, corpus_path, skills_dir, map_path, experiments_dir, hmac_key, monkeypatch
):
    """dry_run=True + approve=False must not modify any file in plugin/ (D-43)."""
    from sica_eval.optimizer.orchestrator import run_loop_cycle
    from sica_eval.optimizer import applier as _applier

    audit_path = tmp_path / "data" / "audit" / "audit.jsonl"
    monkeypatch.setenv("SICA_AUDIT_PATH", str(audit_path))
    genealogy_path = tmp_path / "experiments" / "audit-genealogy.jsonl"
    monkeypatch.setenv("SICA_GENEALOGY_PATH", str(genealogy_path))

    apply_calls: list = []

    def spy_apply(proposal, *, dry_run=False):
        apply_calls.append({"proposal": proposal, "dry_run": dry_run})

    monkeypatch.setattr("sica_eval.optimizer.orchestrator._apply_proposal", spy_apply)
    _make_propose_spy(monkeypatch, "spring-boot-endpoint")
    monkeypatch.setattr(
        "sica_eval.optimizer.orchestrator._verify_candidate",
        lambda *a, **k: _make_verify_result(promote=True),
    )
    monkeypatch.setattr("sica_eval.optimizer.orchestrator._check_precision_gate", lambda *a, **k: None)

    run_loop_cycle(
        skill_name="spring-boot-endpoint",
        corpus_path=corpus_path,
        skills_dir=skills_dir,
        map_path=map_path,
        experiments_dir=experiments_dir,
        seed=42,
        dry_run=True,
        approve=False,
    )

    # apply_proposal must not have been called with dry_run=False (no live write)
    for call in apply_calls:
        assert call["dry_run"] is True, (
            "apply_proposal called with dry_run=False — this would write to live plugin/ "
            "without human approval (D-43 violation)."
        )


# ---------------------------------------------------------------------------
# Test: approve=True actually applies when promoted
# ---------------------------------------------------------------------------

def test_approve_true_calls_apply_with_dry_run_false(
    tmp_path, corpus_path, skills_dir, map_path, experiments_dir, hmac_key, monkeypatch
):
    """approve=True must call apply_proposal(dry_run=False) for a promoted candidate."""
    from sica_eval.optimizer.orchestrator import run_loop_cycle

    audit_path = tmp_path / "data" / "audit" / "audit.jsonl"
    monkeypatch.setenv("SICA_AUDIT_PATH", str(audit_path))
    genealogy_path = tmp_path / "experiments" / "audit-genealogy.jsonl"
    monkeypatch.setenv("SICA_GENEALOGY_PATH", str(genealogy_path))

    apply_calls: list = []

    def spy_apply(proposal, *, dry_run=False):
        apply_calls.append({"dry_run": dry_run})

    monkeypatch.setattr("sica_eval.optimizer.orchestrator._apply_proposal", spy_apply)
    _make_propose_spy(monkeypatch, "spring-boot-endpoint")
    monkeypatch.setattr(
        "sica_eval.optimizer.orchestrator._verify_candidate",
        lambda *a, **k: _make_verify_result(promote=True),
    )
    monkeypatch.setattr("sica_eval.optimizer.orchestrator._check_precision_gate", lambda *a, **k: None)

    run_loop_cycle(
        skill_name="spring-boot-endpoint",
        corpus_path=corpus_path,
        skills_dir=skills_dir,
        map_path=map_path,
        experiments_dir=experiments_dir,
        seed=42,
        dry_run=False,
        approve=True,
    )

    # At least one call with dry_run=False for the live apply
    live_calls = [c for c in apply_calls if not c["dry_run"]]
    assert len(live_calls) >= 1, (
        "approve=True on a promoted candidate must call apply_proposal(dry_run=False)"
    )


# ---------------------------------------------------------------------------
# Test: sole audit writer — gepa_wrapper and verifier have no audit write
# ---------------------------------------------------------------------------

def test_gepa_wrapper_has_no_audit_write():
    """gepa_wrapper.py must contain no audit write (Pitfall 5, T-03-63)."""
    from sica_eval.optimizer import gepa_wrapper as gw

    src = Path(gw.__file__).read_text(encoding="utf-8")
    # Strip comments
    non_comment = "\n".join(
        ln for ln in src.splitlines() if not ln.lstrip().startswith("#")
    )
    # Count lines with 'audit'
    audit_count = sum(1 for ln in non_comment.splitlines() if "audit" in ln.lower())
    assert audit_count == 0, (
        f"gepa_wrapper.py contains {audit_count} non-comment line(s) with 'audit' — "
        "orchestrator must be the sole audit writer (T-03-63, Pitfall 5)."
    )


def test_verifier_has_no_audit_write():
    """verifier.py must not import or call audit-writing primitives (orchestrator owns writes).

    We check for actual write calls (open/write_text/_append), NOT docstring mentions.
    The verifier is allowed to say 'Does NOT write audit log' in its docstring.
    """
    from sica_eval.optimizer import verifier as v

    src = Path(v.__file__).read_text(encoding="utf-8")
    # Only check code lines (non-comment, non-docstring-only)
    # Look for actual file-write or audit-append calls
    write_calls = [
        ln for ln in src.splitlines()
        if not ln.lstrip().startswith("#")
        and not ln.lstrip().startswith('"""')
        and not ln.lstrip().startswith("'")
        and (
            ("_append_audit" in ln)
            or ("audit.jsonl" in ln and ".open(" in ln)
            or ("audit.jsonl" in ln and "write_text" in ln)
            or ("audit-genealogy" in ln and ".open(" in ln)
        )
    ]
    assert not write_calls, (
        f"verifier.py must not write to audit log — orchestrator is the sole audit writer. "
        f"Found: {write_calls}"
    )


# ---------------------------------------------------------------------------
# Test: run_loop_cycle is exported from optimizer/__init__.py
# ---------------------------------------------------------------------------

def test_run_loop_cycle_exported_from_optimizer_init():
    """run_loop_cycle must be importable from sica_eval.optimizer."""
    from sica_eval.optimizer import run_loop_cycle

    assert callable(run_loop_cycle)

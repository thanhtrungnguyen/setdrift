"""Loop manifest schemas — Phase-3 extension of ExperimentManifest (D-40).

What this module does: defines AuditRecord (one JSONL record per loop step) and
LoopManifest (ExperimentManifest subclass with config-genealogy fields), plus
scrub_for_genealogy() which strips hmac_sig before committing to experiments/.

What it does NOT do: it never writes files, never loads the HMAC key, never
references prompt/response text (data wall). Both models carry only IDs, hashes,
aggregates, and small enumerations.

AuditRecord carries all D-40 fields:
  cycle_id, step, ts, config_hash, parent_hash, f1_delta, decision, reason,
  model, seed, hmac_sig.
scrub_for_genealogy() returns all D-40 fields EXCEPT hmac_sig (T-03-22: key
material would be derivable from a committed signature).

Requirements: REQ-SAFETY-02 (genealogy + HMAC signing chain).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from setdrift_eval.schemas.experiment import ExperimentManifest


class AuditRecord(BaseModel):
    """One JSONL record per loop step (D-39/D-40).

    Shared by the full audit log (data/audit/audit.jsonl, gitignored) and — after
    scrubbing via scrub_for_genealogy — the committed genealogy summary
    (experiments/audit-genealogy.jsonl). extra='forbid' catches typos silently.
    """

    model_config = ConfigDict(extra="forbid")

    cycle_id: str = Field(description="UUID4 shared across all audit steps for this cycle")
    step: Literal["observe", "diagnose", "patch", "verify", "promote", "rollback"] = Field(
        description="Which step of the observe→diagnose→patch→verify→promote/rollback cycle"
    )
    ts: str = Field(description="ISO-8601 UTC timestamp when this step was recorded")
    config_hash: str = Field(
        description="sha256 of the canonicalized config at this step (from signer.sign_config)"
    )
    parent_hash: str = Field(
        description="config_hash of the config this cycle derives from (genealogy link)"
    )
    f1_delta: float | None = Field(
        default=None,
        description=(
            "Macro-F1 delta vs baseline; None on observe/diagnose/patch steps, "
            "float on verify/promote/rollback steps"
        ),
    )
    decision: str = Field(
        description="Short decision token, e.g. 'promoted', 'rejected', 'patch_proposed'"
    )
    reason: str = Field(description="Human-readable rationale for the decision (logged to audit)")
    model: str = Field(description="Pinned model id used this cycle, e.g. claude-sonnet-4-6")
    seed: int = Field(description="RNG seed used in this cycle run")
    hmac_sig: str = Field(
        description=(
            "HMAC-SHA256 signature of the canonicalized config at this step. "
            "EXCLUDED from the committed genealogy (scrub_for_genealogy) — "
            "key material would be derivable from the signature (T-03-22)."
        )
    )


class LoopManifest(ExperimentManifest):
    """Phase-3 extension of ExperimentManifest: adds config-genealogy fields.

    Subclasses ExperimentManifest (do NOT modify experiment.py — it is frozen).
    Overrides phase default to 3. Adds parent_hash + cycle_id for the genealogy
    chain, optimizer_backend for provenance, and promotion_decision/reason for the
    human-approval record (D-43).
    """

    phase: int = Field(default=3, description="Roadmap phase that produced this manifest")
    parent_hash: str = Field(
        description="config_hash of the parent config this cycle derives from (genealogy)"
    )
    cycle_id: str = Field(description="UUID4 shared across all audit steps for this cycle")
    optimizer_backend: Literal["gepa", "miprov2"] = Field(
        default="gepa",
        description="Which optimizer backend produced this cycle's proposal",
    )
    promotion_decision: Literal["promoted", "rejected", "pending"] = Field(
        default="pending",
        description="Outcome of the D-43 human-approval gate for this cycle",
    )
    promotion_reason: str = Field(
        default="",
        description="Human-readable rationale for the promotion decision",
    )


def scrub_for_genealogy(record: AuditRecord) -> dict:
    """Return the data-wall-clean subset of an AuditRecord for committed genealogy.

    Excludes hmac_sig: the HMAC signature must never appear in the committed
    experiments/ tree because its presence would allow key-material derivation
    (T-03-22 mitigation, D-38). All other D-40 fields are included.
    """
    return {
        "cycle_id": record.cycle_id,
        "step": record.step,
        "ts": record.ts,
        "config_hash": record.config_hash,
        "parent_hash": record.parent_hash,
        "f1_delta": record.f1_delta,
        "decision": record.decision,
        "reason": record.reason,
        "model": record.model,
        "seed": record.seed,
    }

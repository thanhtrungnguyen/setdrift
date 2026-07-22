"""Sentinel contract test: real Phase-3 genealogy output vs. figure schema (REQ-DELIV-01).

Cites v1.0-MILESTONE-AUDIT Blocker 2: the real, committed
experiments/audit-genealogy.jsonl is the optimizer AuditRecord log
(cycle_id/step/ts/config_hash/parent_hash/f1_delta/decision/reason/model/seed) —
NOT the version-promotion genealogy schema
(version_id/skill_name/f1_mean/status/parent_version_id/date/rolled_back) that
the STRICT, path-based build_genealogy_dag requires.

FIX-02 (06-04-PLAN.md) resolved Blocker 2 with a transform-on-read adapter
(figures/genealogy_adapter.py + build_genealogy_dag_from_records) that joins
the real AuditRecord log with sibling {NNN}-loop-manifest.json files at read
time. That adapter path is exercised by test_genealogy_adapter.py, not here.

This module remains a narrower sentinel: it asserts the STRICT, path-based
build_genealogy_dag(path) still REJECTS a raw AuditRecord file as its direct
input — i.e. the strict schema guard was never weakened to accommodate the
real audit log's shape. The strict function is intentionally left
byte-unchanged by FIX-02; any real-data rendering happens exclusively through
the adapter + build_genealogy_dag_from_records, never through
build_genealogy_dag(real_audit_path) directly.

References: v1.0-MILESTONE-AUDIT Blocker 2, REQ-DELIV-01, D-09, D6-05, T-05-22.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Resolve relative to this test file -> eval/setdrift_eval/figures/tests/ -> ... -> repo/sica-plugin/experiments/
_REAL_AUDIT_PATH = (
    Path(__file__).parent.parent.parent.parent.parent / "experiments" / "audit-genealogy.jsonl"
)

# Fields the REAL committed optimizer audit log actually carries (AuditRecord schema).
_REAL_AUDIT_RECORD_FIELDS = {
    "cycle_id",
    "step",
    "ts",
    "config_hash",
    "parent_hash",
    "f1_delta",
    "decision",
    "reason",
    "model",
    "seed",
}

# Fields build_genealogy_dag's schema guard requires (genealogy/version-promotion schema).
_GENEALOGY_REQUIRED_FIELDS = {"version_id", "skill_name", "f1_mean", "status"}

# Fields that must be ABSENT from a genuine AuditRecord line (proves it's the
# wrong schema for the STRICT genealogy function, not a coincidental superset).
_GENEALOGY_ONLY_FIELDS = {"version_id", "skill_name", "f1_mean"}


def _skip_if_absent() -> Path:
    if not _REAL_AUDIT_PATH.exists():
        pytest.skip(
            f"Real experiments/audit-genealogy.jsonl not found at {_REAL_AUDIT_PATH} "
            "(sparse checkout, gitignored data wall, or not-yet-run Phase-3 pipeline). "
            "This sentinel only runs against the actual committed file; skipping is "
            "expected in checkouts that don't include experiments/."
        )
    return _REAL_AUDIT_PATH


class TestRealGenealogySchemaContract:
    """REQ-DELIV-01 sentinel: real audit log schema vs. the STRICT figure input contract."""

    def test_real_audit_file_is_nonempty_auditrecord_schema(self):
        """The real committed file exists, is non-empty, and matches AuditRecord (not genealogy)."""
        audit_path = _skip_if_absent()

        lines = [
            line for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        assert lines, f"{audit_path} is empty — cannot assert schema divergence on zero records"

        first = json.loads(lines[0])
        found_fields = set(first.keys())

        # It carries the real AuditRecord fields (cycle_id/step present).
        assert "cycle_id" in found_fields, (
            f"Expected real audit-genealogy.jsonl to carry 'cycle_id' (AuditRecord schema), "
            f"found fields {found_fields!r}"
        )
        assert "step" in found_fields, (
            f"Expected real audit-genealogy.jsonl to carry 'step' (AuditRecord schema), "
            f"found fields {found_fields!r}"
        )

        # It does NOT carry the genealogy-figure-only fields.
        overlap = _GENEALOGY_ONLY_FIELDS & found_fields
        assert not overlap, (
            f"Real audit-genealogy.jsonl unexpectedly carries genealogy-schema fields "
            f"{overlap!r} — the AuditRecord schema may have changed; if so this sentinel "
            "should be revisited."
        )

    def test_strict_build_genealogy_dag_still_rejects_real_audit_file(self):
        """The STRICT, path-based build_genealogy_dag still raises on the raw AuditRecord file.

        FIX-02 (06-04-PLAN.md) adds a PARALLEL real-data path
        (figures.genealogy_adapter.adapt_audit_records +
        build_genealogy_dag_from_records) that DOES successfully consume this
        exact file — see test_genealogy_adapter.py. This assertion is narrower:
        it proves the STRICT build_genealogy_dag(path) function was never
        weakened to also accept the AuditRecord shape directly. If this stops
        raising, someone has changed the strict schema guard — that would be a
        deliberate, reviewed decision, not a silent regression.
        """
        audit_path = _skip_if_absent()

        from setdrift_eval.figures.genealogy import FigureDataError, build_genealogy_dag

        with pytest.raises(FigureDataError, match="unexpected schema"):
            build_genealogy_dag(audit_path)

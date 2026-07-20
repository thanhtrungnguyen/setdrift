"""Sentinel contract test: real Phase-3 genealogy output vs. figure schema (REQ-DELIV-01).

Cites v1.0-MILESTONE-AUDIT Blocker 2: the real, committed
experiments/audit-genealogy.jsonl is the optimizer AuditRecord log
(cycle_id/step/ts/config_hash/parent_hash/f1_delta/decision/reason/model/seed) —
NOT the version-promotion genealogy schema
(version_id/skill_name/f1_mean/status/parent_version_id/date/rolled_back) that
build_genealogy_dag requires. No adapter/transform exists between the two. The
existing test suite (test_phase3_figures.py) only ever exercises a
hand-embedded synthetic fixture and therefore never notices this divergence.

Intent: this is a SENTINEL, not a spec for the fix. It asserts the CURRENT
broken state (real file present, but structurally unusable by
build_genealogy_dag) so the real-data path's brokenness is visible in CI
instead of silently masked by --allow-fixtures. The moment an adapter or a
schema change makes the real audit-genealogy.jsonl consumable by
build_genealogy_dag, this test's third assertion (FigureDataError is raised)
will FAIL — that failure is a deliberate tripwire. Whoever ships the fix must
retire or rewrite this test, not weaken it. Do NOT convert this to an xfail:
the adapter design (transform-on-read vs. a second genealogy-schema writer)
is undecided, and pre-committing to a shape here would presume a design that
hasn't been made.

References: v1.0-MILESTONE-AUDIT Blocker 2, REQ-DELIV-01, D-09, T-05-22.
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
# wrong schema for the genealogy figure, not a coincidental superset).
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
    """REQ-DELIV-01 sentinel: real audit log schema vs. genealogy figure input contract."""

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
            f"{overlap!r} — REQ-DELIV-01 schema divergence may have been resolved; "
            f"if so, this sentinel (and the fixture-only figure path) should be retired."
        )

    def test_build_genealogy_dag_rejects_real_audit_file(self):
        """build_genealogy_dag raises FigureDataError on the REAL committed file (current brokenness).

        This is the sentinel assertion for v1.0-MILESTONE-AUDIT Blocker 2: no
        adapter exists, so the CLI's real-data path (`--genealogy` without
        `--allow-fixtures`) is structurally unable to consume the actual
        Phase-3 optimizer output. If this stops raising, an adapter/schema
        change has landed and this test (plus the fixture-only figure path
        it documents) must be deliberately retired — not silently adjusted.
        """
        audit_path = _skip_if_absent()

        from setdrift_eval.figures.genealogy import FigureDataError, build_genealogy_dag

        with pytest.raises(FigureDataError, match="unexpected schema"):
            build_genealogy_dag(audit_path)

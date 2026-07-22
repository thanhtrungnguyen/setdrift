"""Tests for the transform-on-read genealogy adapter (FIX-02, REQ-DELIV-01).

All tests are hermetic: they write synthetic audit-genealogy.jsonl +
{NNN}-loop-manifest.json fixtures to tmp_path and never touch the real
committed experiments/ tree. No live API calls.

References: 06-04-PLAN.md Task 2, D6-04 (rolled_back gap), D6-05 (fail-loud
join miss).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_audit_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n",
        encoding="utf-8",
    )


def _write_loop_manifest(experiments_dir: Path, n: int, **fields) -> Path:
    manifest_path = experiments_dir / f"{n:03d}-loop-manifest.json"
    manifest_path.write_text(json.dumps(fields, indent=2), encoding="utf-8")
    return manifest_path


def _audit_record(
    cycle_id: str,
    step: str,
    ts: str,
    config_hash: str,
    parent_hash: str,
) -> dict:
    return {
        "cycle_id": cycle_id,
        "step": step,
        "ts": ts,
        "config_hash": config_hash,
        "parent_hash": parent_hash,
        "f1_delta": 0.05 if step in ("verify", "promote", "rollback") else None,
        "decision": "promoted" if step == "promote" else step,
        "reason": f"[TEST] {step}",
        "model": "claude-sonnet-4-6",
        "seed": 42,
    }


class TestAdaptAuditRecordsSuccessfulJoin:
    """(a) a successful join -> DiGraph with skill_name/f1_mean populated, rolled_back=False."""

    def test_successful_join_populates_skill_and_f1(self, tmp_path: Path):
        from setdrift_eval.figures.genealogy import build_genealogy_dag_from_records
        from setdrift_eval.figures.genealogy_adapter import adapt_audit_records

        experiments_dir = tmp_path
        audit_path = experiments_dir / "audit-genealogy.jsonl"

        cycle_id = "cycle-root-0001"
        _write_audit_jsonl(
            audit_path,
            [
                _audit_record(cycle_id, "observe", "2026-06-01T00:00:00+00:00", "hashA", "hashA"),
                _audit_record(cycle_id, "diagnose", "2026-06-01T00:01:00+00:00", "hashA", "hashA"),
                _audit_record(cycle_id, "promote", "2026-06-01T00:02:00+00:00", "hashB", "hashA"),
            ],
        )
        _write_loop_manifest(
            experiments_dir,
            1,
            cycle_id=cycle_id,
            skill_name="spring-boot-endpoint",
            candidate_f1_mean=0.71,
        )

        records = adapt_audit_records(audit_path, experiments_dir)
        assert len(records) == 1
        rec = records[0]
        assert rec["skill_name"] == "spring-boot-endpoint"
        assert rec["f1_mean"] == 0.71
        assert rec["rolled_back"] is False

        dag = build_genealogy_dag_from_records(records)
        assert dag.number_of_nodes() == 1
        node_id = next(iter(dag.nodes))
        assert dag.nodes[node_id]["skill"] == "spring-boot-endpoint"
        assert dag.nodes[node_id]["f1"] == pytest.approx(0.71)

    def test_parent_child_chain_produces_edge(self, tmp_path: Path):
        from setdrift_eval.figures.genealogy import build_genealogy_dag_from_records
        from setdrift_eval.figures.genealogy_adapter import adapt_audit_records

        experiments_dir = tmp_path
        audit_path = experiments_dir / "audit-genealogy.jsonl"

        cycle_root = "cycle-root-0002"
        cycle_child = "cycle-child-0003"
        _write_audit_jsonl(
            audit_path,
            [
                _audit_record(cycle_root, "promote", "2026-06-01T00:00:00+00:00", "hashA", "hashA"),
                _audit_record(cycle_child, "promote", "2026-06-02T00:00:00+00:00", "hashB", "hashA"),
            ],
        )
        _write_loop_manifest(
            experiments_dir,
            1,
            cycle_id=cycle_root,
            skill_name="spring-boot-endpoint",
            candidate_f1_mean=0.60,
        )
        _write_loop_manifest(
            experiments_dir,
            2,
            cycle_id=cycle_child,
            skill_name="spring-boot-endpoint",
            candidate_f1_mean=0.75,
        )

        records = adapt_audit_records(audit_path, experiments_dir)
        dag = build_genealogy_dag_from_records(records)

        assert dag.number_of_nodes() == 2
        assert dag.number_of_edges() == 1
        (u, v, data) = next(iter(dag.edges(data=True)))
        assert data["relation"] == "promoted"


class TestAdaptAuditRecordsJoinMiss:
    """(b) a join-miss -> FigureDataError naming the orphan cycle_id."""

    def test_join_miss_raises_figure_data_error_naming_orphan_cycle(self, tmp_path: Path):
        from setdrift_eval.figures.genealogy import FigureDataError
        from setdrift_eval.figures.genealogy_adapter import adapt_audit_records

        experiments_dir = tmp_path
        audit_path = experiments_dir / "audit-genealogy.jsonl"

        orphan_cycle_id = "cycle-orphan-9999"
        _write_audit_jsonl(
            audit_path,
            [
                _audit_record(
                    orphan_cycle_id, "promote", "2026-06-01T00:00:00+00:00", "hashZ", "hashZ"
                ),
            ],
        )
        # Deliberately do NOT write a matching {NNN}-loop-manifest.json.

        with pytest.raises(FigureDataError, match=orphan_cycle_id):
            adapt_audit_records(audit_path, experiments_dir)


class TestAdaptAuditRecordsExcludesNonPromoted:
    """(c) cycles whose terminal step != "promote" are excluded."""

    def test_rollback_terminal_cycle_is_excluded(self, tmp_path: Path):
        from setdrift_eval.figures.genealogy_adapter import adapt_audit_records

        experiments_dir = tmp_path
        audit_path = experiments_dir / "audit-genealogy.jsonl"

        rejected_cycle = "cycle-rejected-0004"
        _write_audit_jsonl(
            audit_path,
            [
                _audit_record(
                    rejected_cycle, "observe", "2026-06-01T00:00:00+00:00", "hashC", "hashC"
                ),
                _audit_record(
                    rejected_cycle, "rollback", "2026-06-01T00:01:00+00:00", "hashC", "hashC"
                ),
            ],
        )
        # No loop-manifest needed — a non-promoted cycle must never be joined at all.

        records = adapt_audit_records(audit_path, experiments_dir)
        assert records == []

    def test_mixed_promoted_and_rejected_cycles(self, tmp_path: Path):
        from setdrift_eval.figures.genealogy_adapter import adapt_audit_records

        experiments_dir = tmp_path
        audit_path = experiments_dir / "audit-genealogy.jsonl"

        promoted_cycle = "cycle-promoted-0005"
        rejected_cycle = "cycle-rejected-0006"
        _write_audit_jsonl(
            audit_path,
            [
                _audit_record(
                    promoted_cycle, "promote", "2026-06-01T00:00:00+00:00", "hashD", "hashD"
                ),
                _audit_record(
                    rejected_cycle, "rollback", "2026-06-01T00:01:00+00:00", "hashE", "hashE"
                ),
            ],
        )
        _write_loop_manifest(
            experiments_dir,
            1,
            cycle_id=promoted_cycle,
            skill_name="spring-jpa-entity",
            candidate_f1_mean=0.66,
        )

        records = adapt_audit_records(audit_path, experiments_dir)
        assert len(records) == 1
        assert records[0]["skill_name"] == "spring-jpa-entity"


class TestAdaptAuditRecordsReadOnly:
    """The adapter never writes any file (D-38 sole-writer invariant)."""

    def test_adapter_module_has_no_write_call(self):
        import inspect

        from setdrift_eval.figures import genealogy_adapter

        src = inspect.getsource(genealogy_adapter)
        # No actual write-call sites (docstring may mention _append_audit by
        # name for documentation purposes; that is not a call).
        assert "_append_audit(" not in src
        assert "write_text(" not in src
        assert ".write(" not in src

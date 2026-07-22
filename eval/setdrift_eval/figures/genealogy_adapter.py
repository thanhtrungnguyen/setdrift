"""Transform-on-read genealogy adapter (FIX-02, REQ-DELIV-01).

What this module does:
  - Reads the committed experiments/audit-genealogy.jsonl (AuditRecord lines,
    D-38 scrubbed schema: cycle_id/step/ts/config_hash/parent_hash/f1_delta/
    decision/reason/model/seed).
  - Groups records by cycle_id and keeps only cycles whose TERMINAL step is
    "promote" (never-promoted / rejected cycles never became a version).
  - For each kept cycle, joins the sibling experiments/{NNN}-loop-manifest.json
    (found by matching cycle_id) to recover skill_name and candidate_f1_mean
    (mapped to f1_mean) — fields the genealogy-figure schema needs but
    AuditRecord does not carry.
  - Resolves version_id via figures.version_index.build_version_index (single
    source of truth shared with FIX-03's cost/triangulation producers).
  - Sets rolled_back=False unconditionally on every yielded record (D6-04,
    Pitfall 3): AuditRecord.step=="rollback" means "candidate rejected, never
    promoted", NOT "an active version was reverted". Manual CLI rollbacks
    (applier.restore_config) never call _append_audit and so never appear
    here — that gap is intentional and documented, not fabricated.

What it does NOT do:
  - NEVER writes any file (read-only; D-38 sole-writer invariant preserved —
    only optimizer/orchestrator.py._append_audit may write the audit log).
  - NEVER reads applier.restore_config or any manual-rollback signal.
  - NEVER skips a join miss silently — a promoted cycle_id with no matching
    loop-manifest raises FigureDataError naming the orphan cycle_id (D6-05).

References: 06-04-PLAN.md Task 1, v1.0-MILESTONE-AUDIT Blocker 2, D-38, D6-04,
D6-05, T-06-10, T-06-11, T-06-12.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from setdrift_eval.figures.genealogy import FigureDataError
from setdrift_eval.figures.version_index import build_version_index


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def _find_loop_manifest(experiments_dir: Path, cycle_id: str) -> dict | None:
    """Find the {NNN}-loop-manifest.json whose cycle_id matches. Read-only."""
    for manifest_path in sorted(experiments_dir.glob("*-loop-manifest.json")):
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if data.get("cycle_id") == cycle_id:
            return data
    return None


def adapt_audit_records(audit_path: Path, experiments_dir: Path) -> list[dict]:
    """Join audit-genealogy.jsonl with sibling loop-manifests into genealogy-schema dicts.

    Args:
        audit_path: Path to experiments/audit-genealogy.jsonl (AuditRecord lines).
        experiments_dir: Path to the experiments/ directory containing the
            sibling {NNN}-loop-manifest.json files and used to resolve the
            shared version_index.

    Returns:
        list[dict] records shaped like build_genealogy_dag's expected schema
        (version_id, skill_name, f1_mean, status, parent_version_id, date,
        rolled_back), suitable for build_genealogy_dag_from_records.

    Raises:
        FigureDataError: if a promoted cycle_id has no matching
            {NNN}-loop-manifest.json (fail loud, never skip — D6-05).
    """
    audit_path = Path(audit_path)
    experiments_dir = Path(experiments_dir)

    raw_records = _load_jsonl(audit_path)
    by_cycle: dict[str, list[dict]] = defaultdict(list)
    for r in raw_records:
        by_cycle[r["cycle_id"]].append(r)

    version_index = build_version_index(experiments_dir)

    records: list[dict] = []
    for cycle_id, recs in by_cycle.items():
        recs_sorted = sorted(recs, key=lambda r: r["ts"])
        terminal = recs_sorted[-1]
        if terminal["step"] != "promote":
            # Never-promoted / rejected cycle — never became a version (Pitfall 3).
            continue

        manifest = _find_loop_manifest(experiments_dir, cycle_id)
        if manifest is None:
            raise FigureDataError(
                f"Genealogy join miss: cycle_id {cycle_id!r} has a terminal 'promote' "
                f"step in {audit_path} but no matching {{NNN}}-loop-manifest.json was "
                f"found under {experiments_dir}. Every promoted cycle must have a "
                "sibling loop-manifest written in the same run_loop_cycle call "
                "(orchestrator.py). Investigate the missing manifest file before "
                "rendering the genealogy figure — never skip-and-render (D6-05)."
            )

        config_hash = terminal["config_hash"]
        parent_hash = terminal["parent_hash"]
        version_id = version_index.get(config_hash, config_hash)
        parent_version_id = (
            version_index.get(parent_hash) if parent_hash != config_hash else None
        )

        records.append(
            {
                "version_id": version_id,
                "skill_name": manifest["skill_name"],
                "f1_mean": manifest["candidate_f1_mean"],
                "status": "active",
                "parent_version_id": parent_version_id,
                "date": terminal["ts"],
                # D6-04 (Pitfall 3): rolled_back is set False unconditionally. Manual
                # CLI rollbacks (applier.restore_config) never call _append_audit and
                # so never appear in the audit log — this is a documented gap, not a
                # fabricated "no rollbacks ever happened" claim.
                "rolled_back": False,
            }
        )

    return records

"""Shared config_hash -> version_id resolver (FIX-02, imported by FIX-03 / Plan 05).

What this module does:
  - Reads the committed experiments/audit-genealogy.jsonl (AuditRecord lines,
    D-38 scrubbed schema) and groups records by cycle_id.
  - Keeps only cycles whose terminal (latest-by-ts) step is "promote" — those
    are the cycles that actually became a version.
  - Assigns stable "v{n}" labels to each distinct promoted config_hash, in
    ascending promotion-timestamp order, via build_version_index().

Why this exists: both the genealogy Mermaid diagram (figures/genealogy_adapter.py,
this plan) and the cost/triangulation producers (figures/producers.py, FIX-03)
need to label the same config_hash with the same version_id. Without a single
shared resolver the two figures could silently disagree (Don't-Hand-Roll table,
06-PATTERNS.md).

What it does NOT do:
  - NEVER writes any file — read-only (D-38 sole-writer invariant preserved;
    only optimizer/orchestrator.py._append_audit may write the audit log).
  - NEVER re-derives f1/skill_name — that join lives in genealogy_adapter.py.

References: 06-04-PLAN.md Task 0, D6-04 (rolled_back gap), D-38 (sole writer).
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path


def _experiments_dir() -> Path:
    """Env-var-overridable experiments/ root (query.py TELEMETRY_DIR convention).

    Re-read on every call (not cached at import time) so tests can monkeypatch
    the environment variable and get a fresh path.
    """
    return Path(os.environ.get("SETDRIFT_EXPERIMENTS_DIR", "experiments"))


def _load_audit_records(experiments_dir: Path) -> list[dict]:
    """Read experiments/audit-genealogy.jsonl as a list of AuditRecord dicts.

    Returns an empty list if the file does not exist (no promoted cycles yet
    is a valid, non-error state for a brand-new experiments/ directory).
    """
    audit_path = Path(experiments_dir) / "audit-genealogy.jsonl"
    if not audit_path.exists():
        return []
    lines = [line for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def _promoted_terminal_records(records: list[dict]) -> list[dict]:
    """Group AuditRecord dicts by cycle_id; keep only terminal step == 'promote'.

    A cycle whose terminal step is 'rollback' was rejected and never became a
    version (Pitfall 3 / D6-04) — it is excluded here, not just downstream.
    """
    by_cycle: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_cycle[r["cycle_id"]].append(r)

    terminal_promotes: list[dict] = []
    for _cycle_id, recs in by_cycle.items():
        recs_sorted = sorted(recs, key=lambda r: r["ts"])
        terminal = recs_sorted[-1]
        if terminal["step"] == "promote":
            terminal_promotes.append(terminal)
    return terminal_promotes


def build_version_index(experiments_dir: str | Path | None = None) -> dict[str, str]:
    """Map config_hash -> version_id ("v1", "v2", ...) in promotion order.

    Args:
        experiments_dir: Path to the experiments/ directory. If None, resolves
            via the SETDRIFT_EXPERIMENTS_DIR env var (default "experiments"),
            re-read each call for test monkeypatchability.

    Returns:
        dict[config_hash, version_id]. Only config_hashes belonging to a cycle
        whose terminal step is "promote" are present. Read-only — this
        function never writes a file.
    """
    base = Path(experiments_dir) if experiments_dir is not None else _experiments_dir()
    records = _load_audit_records(base)
    promoted = _promoted_terminal_records(records)
    promoted_sorted = sorted(promoted, key=lambda r: r["ts"])

    index: dict[str, str] = {}
    next_n = 1
    for r in promoted_sorted:
        config_hash = r["config_hash"]
        if config_hash not in index:
            index[config_hash] = f"v{next_n}"
            next_n += 1
    return index

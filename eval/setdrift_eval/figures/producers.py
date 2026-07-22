"""Materialize the cost and triangulation figure inputs from real manifests (FIX-03).

What this module does:
  - build_cost_tokens(experiments_dir) aggregates token_cost_total per config_hash from
    every real manifest source that already carries the field, and writes the SINGULAR
    (rebuilt-each-run, not numbered-glob) experiments/cost-tokens.json.
  - build_triangulation_series(experiments_dir) assembles ordered F1 / pass-rate series
    per promoted version and writes the SINGULAR experiments/triangulation-series.json.
  - Both mirror the materialize-then-read producer idiom of
    corpus/precision_gate.py::write_report: a plain function, living OUTSIDE the CLI,
    that writes JSON with indent=2 and returns the Path it wrote.

What it does NOT do:
  - NEVER computes these aggregates inline in figures/cli.py (Anti-Pattern D) — cli.py's
    --cost-delta / --triangulation branches only READ these two files (materialize-then-read).
  - NEVER reimplements the config_hash->version_id resolver — build_version_index is
    imported verbatim from figures/version_index.py (Don't-Hand-Roll; a second resolver
    would let the cost chart and the genealogy diagram silently disagree, T-06-14).
  - NEVER retroactively estimates a nonzero cost for drift-grid cells whose
    token_cost_total is hardcoded to 0 by grid_runner.py — that fidelity gap is
    disclosed (see DRIFT_GRID_ZERO_COST_NOTE), not silently patched over (T-06-15).

Pitfall 4 fidelity gap (disclosed, not fixed): drift/grid_runner.py line ~322 writes
every *-drift-results.json cell with token_cost_total=0 — there is no per-cell token
meter for the 12-cell drift grid today. Those cells' config_hash entries appear in
cost-tokens.json with a real (not fabricated) value of 0; the cost figure caption /
dissertation notes must cite DRIFT_GRID_ZERO_COST_NOTE so a reader does not mistake
"0" for "free" (T-06-15 anti-repudiation).

pass_rate_series provenance: no real benchmark issue->commit replay pass-rate exists
yet in this repo (Phase 7 / RUN-0x scope). Following the SAME proxy convention already
established in dashboard/health_export.py ("pass_rate": result.coverage_pct — sourced
from Phase-3 when available"), build_triangulation_series uses each version's
coverage_pct as the pass_rate_series value until a real benchmark pass-rate lands.
This is a real manifest field (not a fixture number) — the proxy nature is documented
here and must be re-derived from actual benchmark replay once RUN-0x produces it.

References: 06-05-PLAN.md, 06-PATTERNS.md (FIX-03 section), corpus/precision_gate.py
(write_report producer idiom), figures/version_index.py (shared resolver, Plan 04).
"""

from __future__ import annotations

import json
from pathlib import Path

from setdrift_eval.figures.version_index import build_version_index

DRIFT_GRID_ZERO_COST_NOTE = (
    "drift-grid cells (*-drift-results.json) report token_cost_total=0 by construction "
    "(grid_runner.py does not yet meter per-cell token cost); their cost figures are a "
    "known fidelity gap, disclosed here rather than silently estimated (Pitfall 4, T-06-15)."
)


def _iter_manifest_dicts(experiments_dir: Path, glob_pattern: str) -> list[dict]:
    """Read every JSON file matching glob_pattern under experiments_dir as a plain dict."""
    out = []
    for p in sorted(Path(experiments_dir).glob(glob_pattern)):
        out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


def _loop_cycle_config_hashes(experiments_dir: Path) -> dict[str, str]:
    """cycle_id -> config_hash, read from the terminal ('promote') audit-genealogy record.

    audit-genealogy.jsonl is the sole committed audit trail (D-38, sole writer:
    optimizer/orchestrator.py._append_audit). This reads it directly (never writes)
    to join a {NNN}-loop-manifest.json's cycle_id to the config_hash it produced —
    the same terminal-record convention version_index.py uses to build its promoted
    set, but returning a different shape (cycle_id -> config_hash, not
    config_hash -> version_id) for a different caller (build_cost_tokens' join).
    """
    audit_path = Path(experiments_dir) / "audit-genealogy.jsonl"
    if not audit_path.exists():
        return {}
    lines = [ln for ln in audit_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    records = [json.loads(ln) for ln in lines]

    by_cycle: dict[str, list[dict]] = {}
    for r in records:
        by_cycle.setdefault(r["cycle_id"], []).append(r)

    result: dict[str, str] = {}
    for cycle_id, recs in by_cycle.items():
        terminal = sorted(recs, key=lambda r: r["ts"])[-1]
        if terminal["step"] == "promote":
            result[cycle_id] = terminal["config_hash"]
    return result


def build_cost_tokens(experiments_dir: str | Path) -> Path:
    """Aggregate real token_cost_total per config_hash; write experiments/cost-tokens.json.

    Sources aggregated (summed per config_hash; a config_hash may appear in more than
    one source, e.g. a Phase-2 health run AND the GEPA loop cycle that promoted it):
      - *-results.json          (ExperimentManifest — run_health/verify_candidate; real cost)
      - *-drift-results.json    (DriftManifest — drift grid; token_cost_total=0, disclosed)
      - *-loop-manifest.json    (GEPA loop cycles; real cost from dspy.track_usage(),
                                 joined to config_hash via the cycle's terminal promote
                                 record — only cycles that were actually promoted are
                                 represented, matching build_version_index's promoted set)

    Keys of the emitted dict are raw config_hash strings (D6-09) — NOT "v1"/"v2" version
    labels. build_version_index is imported (not reimplemented) to confirm the promoted
    set used for the loop-manifest join.

    Returns the Path written (materialize-then-read producer idiom; overwrites wholesale
    on every call — singular, not numbered-glob).
    """
    experiments_dir = Path(experiments_dir)
    totals: dict[str, int] = {}

    promoted_hashes = set(build_version_index(experiments_dir).keys())

    for manifest in _iter_manifest_dicts(experiments_dir, "*-results.json"):
        cfg = manifest.get("config_hash")
        if cfg:
            totals[cfg] = totals.get(cfg, 0) + int(manifest.get("token_cost_total", 0) or 0)

    for manifest in _iter_manifest_dicts(experiments_dir, "*-drift-results.json"):
        cfg = manifest.get("config_hash")
        if cfg:
            # Real value (0) disclosed, not fabricated (Pitfall 4 / DRIFT_GRID_ZERO_COST_NOTE).
            totals[cfg] = totals.get(cfg, 0) + int(manifest.get("token_cost_total", 0) or 0)

    cycle_to_hash = _loop_cycle_config_hashes(experiments_dir)
    for manifest in _iter_manifest_dicts(experiments_dir, "*-loop-manifest.json"):
        cycle_id = manifest.get("cycle_id")
        cfg = cycle_to_hash.get(cycle_id)
        if cfg and cfg in promoted_hashes:
            totals[cfg] = totals.get(cfg, 0) + int(manifest.get("token_cost_total", 0) or 0)

    out_path = experiments_dir / "cost-tokens.json"
    out_path.write_text(json.dumps(totals, indent=2), encoding="utf-8")
    return out_path


def build_triangulation_series(experiments_dir: str | Path) -> Path:
    """Assemble ordered F1 / pass-rate series per promoted version; write
    experiments/triangulation-series.json as {"f1_series": [...], "pass_rate_series": [...]}
    (the exact shape figures/cli.py's --triangulation branch reads).

    Ordering: promoted versions in build_version_index's promotion-timestamp order
    ("v1", "v2", ... — the SAME shared resolver the genealogy diagram uses).
    Per version: macro_f1_mean -> f1_series; coverage_pct -> pass_rate_series (proxy,
    see module docstring — no real benchmark pass-rate exists yet in this repo).
    A promoted config_hash with no matching *-results.json manifest is skipped (no F1
    was ever run for that version) rather than fabricating a placeholder value.

    Returns the Path written (materialize-then-read producer idiom; overwrites wholesale
    on every call — singular, not numbered-glob).
    """
    experiments_dir = Path(experiments_dir)

    version_index = build_version_index(experiments_dir)  # config_hash -> "v1"/"v2"/...
    # config_hash -> (macro_f1_mean, coverage_pct), keeping the LAST manifest seen per hash
    by_config_hash: dict[str, tuple[float, float]] = {}
    for manifest in _iter_manifest_dicts(experiments_dir, "*-results.json"):
        cfg = manifest.get("config_hash")
        if cfg is None:
            continue
        f1 = manifest.get("macro_f1_mean")
        pass_rate = manifest.get("coverage_pct")
        if f1 is None or pass_rate is None:
            continue
        by_config_hash[cfg] = (float(f1), float(pass_rate))

    # Order by version_id number (v1, v2, ...) — the same promotion-timestamp order
    # build_version_index assigns, so the triangulation figure and the genealogy
    # diagram never disagree about version ordering.
    ordered_hashes = sorted(
        (cfg for cfg in version_index if cfg in by_config_hash),
        key=lambda cfg: int(version_index[cfg].lstrip("v")),
    )

    f1_series = [by_config_hash[cfg][0] for cfg in ordered_hashes]
    pass_rate_series = [by_config_hash[cfg][1] for cfg in ordered_hashes]

    out_path = experiments_dir / "triangulation-series.json"
    out_path.write_text(
        json.dumps({"f1_series": f1_series, "pass_rate_series": pass_rate_series}, indent=2),
        encoding="utf-8",
    )
    return out_path

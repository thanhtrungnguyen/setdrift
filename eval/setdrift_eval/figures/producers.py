"""Materialize the cost, triangulation, and drift-vs-F1 figure inputs from real
manifests (FIX-03, and 09-02's RUN-05 drift-vs-F1 overlay).

What this module does:
  - build_cost_tokens(experiments_dir) aggregates token_cost_total per config_hash from
    every real manifest source that already carries the field, and writes the SINGULAR
    (rebuilt-each-run, not numbered-glob) experiments/cost-tokens.json.
  - build_triangulation_series(experiments_dir) assembles ordered F1 / pass-rate series
    per promoted version and writes the SINGULAR experiments/triangulation-series.json.
  - build_drift_f1_series(experiments_dir) aggregates the 12-cell drift grid's
    DriftManifest files into a per-revision, per-arm F1 + drift-index series and
    writes the SINGULAR experiments/drift-f1-series.json (Phase 9 plan 09-02, RUN-05).
  - All three mirror the materialize-then-read producer idiom of
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

from setdrift_eval.figures.errors import FigureDataError
from setdrift_eval.figures.version_index import build_version_index

# X-axis ordering for the drift-vs-F1 overlay (build_drift_f1_series /
# figures/drift_f1.py). Pinned as an explicit tuple — never derived from dict or
# filesystem iteration order — because the X axis is a codebase-time axis and a
# silent reorder would invert the drift narrative (T-09-06).
DRIFT_REVISION_ORDER: tuple[str, ...] = ("early", "mid", "late")

DRIFT_INDEX_MISSING_NOTE = (
    "One or more drift-grid cells report drift_index=None (not yet computed by "
    "drift/grid_runner.py at manifest-write time). Missing cells are disclosed here "
    "and omitted from the per-revision drift-index average — never coerced to 0.0, "
    "which would fabricate a 'no drift' reading (T-09-07 anti-repudiation)."
)

DRIFT_GRID_ZERO_COST_NOTE = (
    "drift-grid cells (*-drift-results.json) report token_cost_total=0 by construction "
    "(grid_runner.py does not yet meter per-cell token cost); their cost figures are a "
    "known fidelity gap, disclosed here rather than silently estimated (Pitfall 4, T-06-15)."
)

LOOP_MANIFEST_PROPOSE_ONLY_COST_NOTE = (
    "loop-manifest token_cost_total covers the PROPOSE stage only: "
    "dspy.track_usage() in optimizer/orchestrator.py wraps configure+_propose, so "
    "verify-stage LM calls (candidate scoring on the val partition through the "
    "response-cache/backend layer, outside dspy) contribute 0. Per-cycle cost is a "
    "known systematic UNDERCOUNT — disclosed here (and to be cited in the cost-figure "
    "caption path) rather than silently estimated (WR-08, T-06-15 anti-repudiation "
    "parity with DRIFT_GRID_ZERO_COST_NOTE)."
)


def _iter_manifest_dicts(
    experiments_dir: Path, glob_pattern: str, exclude_suffix: str | None = None
) -> list[dict]:
    """Read every JSON file matching glob_pattern under experiments_dir as a plain dict.

    exclude_suffix (CR-02): `*-results.json` also glob-matches
    `*-drift-results.json`, so callers iterating health-run manifests MUST pass
    exclude_suffix="-drift-results.json" — otherwise drift manifests are
    double-processed in the cost aggregation and drift cells (hardcoded
    coverage_pct=1.0) contaminate the triangulation series.
    """
    out = []
    for p in sorted(Path(experiments_dir).glob(glob_pattern)):
        if exclude_suffix is not None and p.name.endswith(exclude_suffix):
            continue
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
      - *-loop-manifest.json    (GEPA loop cycles; real PROPOSE-stage cost from
                                 dspy.track_usage() — verify-stage LM cost is NOT metered,
                                 see LOOP_MANIFEST_PROPOSE_ONLY_COST_NOTE; joined to
                                 config_hash via the cycle's terminal promote record —
                                 only cycles that were actually promoted are represented,
                                 matching build_version_index's promoted set)

    Keys of the emitted dict are raw config_hash strings (D6-09) — NOT "v1"/"v2" version
    labels. build_version_index is imported (not reimplemented) to confirm the promoted
    set used for the loop-manifest join.

    Returns the Path written (materialize-then-read producer idiom; overwrites wholesale
    on every call — singular, not numbered-glob).
    """
    experiments_dir = Path(experiments_dir)
    totals: dict[str, int] = {}

    promoted_hashes = set(build_version_index(experiments_dir).keys())

    # exclude_suffix: drift manifests also match *-results.json (CR-02) — they are
    # handled ONCE by the dedicated *-drift-results.json pass below.
    for manifest in _iter_manifest_dicts(
        experiments_dir, "*-results.json", exclude_suffix="-drift-results.json"
    ):
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
    # config_hash -> (macro_f1_mean, coverage_pct), keeping the LAST manifest seen per hash.
    # exclude_suffix: drift manifests also match *-results.json (CR-02) — a drift cell's
    # per-cell F1 and hardcoded coverage_pct=1.0 must never replace the health run's
    # real values in the dissertation triangulation figure.
    by_config_hash: dict[str, tuple[float, float]] = {}
    for manifest in _iter_manifest_dicts(
        experiments_dir, "*-results.json", exclude_suffix="-drift-results.json"
    ):
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


def build_drift_f1_series(experiments_dir: str | Path) -> Path:
    """Aggregate the 12-cell drift grid into a drift-vs-F1 overlay series; write
    experiments/drift-f1-series.json (the exact shape figures/drift_f1.py's
    --drift-f1 branch reads).

    Iterates *-drift-results.json manifests via the shared _iter_manifest_dicts
    helper (never a hand-rolled glob — CR-02: a naive "*-results.json" glob also
    matches "*-drift-results.json", but this function only ever globs the
    drift-specific pattern, so no exclude_suffix is needed here).

    Output shape:
      {
        "revisions": ["early", "mid", "late"],           # DRIFT_REVISION_ORDER, pinned
        "arms": {
          "A": {"f1_mean": [...], "f1_noise_band_low": [...],
                "f1_noise_band_high": [...], "n_repeats": [...]},
          "B": {...}
        },
        "drift_index": [...],   # one value per revision, shared across arms, or
                                 # null when no cell for that revision reports one
        "notes": [DRIFT_INDEX_MISSING_NOTE]   # present only if any cell was missing
      }

    Aggregation rules:
      - Per (arm, revision) cell group: macro_f1_mean averaged across grid_run_idx
        repeats; the noise band is the min of the low edges / max of the high
        edges across those repeats; n_repeats records the repeat count.
      - drift_index is averaged PER REVISION across cells sharing that revision,
        regardless of arm (D9-context: "one drift-index series shared across arms
        per revision"). Cells with drift_index=None are excluded from the average
        and disclosed via DRIFT_INDEX_MISSING_NOTE rather than coerced to 0.0
        (T-09-07 anti-repudiation).
      - Any grid_revision value outside DRIFT_REVISION_ORDER raises FigureDataError
        naming the offending value — never silently dropped (T-09-06).

    Raises:
        FigureDataError: no *-drift-results.json manifests found under
            experiments_dir (naming the directory), or an unknown grid_revision.

    Returns:
        Path written (materialize-then-read producer idiom; overwrites wholesale
        on every call — singular, not numbered-glob).
    """
    experiments_dir = Path(experiments_dir)

    manifests = _iter_manifest_dicts(experiments_dir, "*-drift-results.json")
    if not manifests:
        raise FigureDataError(
            f"No drift-grid manifests (*-drift-results.json) found under "
            f"{experiments_dir}. Pass --allow-fixtures to run against fixture data "
            "(watermark applied). Do NOT include fixture figures in the dissertation (D-09)."
        )

    by_arm_revision: dict[tuple[str, str], list[dict]] = {}
    by_revision_drift: dict[str, list[float | None]] = {}
    any_missing_drift = False

    for manifest in manifests:
        revision = manifest.get("grid_revision")
        if revision not in DRIFT_REVISION_ORDER:
            raise FigureDataError(
                f"Unknown grid_revision {revision!r} in a drift manifest under "
                f"{experiments_dir} — expected one of {DRIFT_REVISION_ORDER} (T-09-06)."
            )
        arm = manifest.get("grid_arm")
        by_arm_revision.setdefault((arm, revision), []).append(manifest)

        drift_index = manifest.get("drift_index")
        by_revision_drift.setdefault(revision, []).append(drift_index)
        if drift_index is None:
            any_missing_drift = True

    arms_out: dict[str, dict[str, list]] = {}
    for arm in ("A", "B"):
        f1_means: list[float | None] = []
        band_los: list[float | None] = []
        band_his: list[float | None] = []
        n_repeats: list[int] = []
        for revision in DRIFT_REVISION_ORDER:
            cells = by_arm_revision.get((arm, revision), [])
            if not cells:
                f1_means.append(None)
                band_los.append(None)
                band_his.append(None)
                n_repeats.append(0)
                continue
            f1_vals = [float(c["macro_f1_mean"]) for c in cells]
            lo_vals = [float(c["macro_f1_noise_band_low"]) for c in cells]
            hi_vals = [float(c["macro_f1_noise_band_high"]) for c in cells]
            f1_means.append(sum(f1_vals) / len(f1_vals))
            band_los.append(min(lo_vals))
            band_his.append(max(hi_vals))
            n_repeats.append(len(cells))
        arms_out[arm] = {
            "f1_mean": f1_means,
            "f1_noise_band_low": band_los,
            "f1_noise_band_high": band_his,
            "n_repeats": n_repeats,
        }

    drift_series: list[float | None] = []
    for revision in DRIFT_REVISION_ORDER:
        values = [v for v in by_revision_drift.get(revision, []) if v is not None]
        drift_series.append(sum(values) / len(values) if values else None)

    out: dict = {
        "revisions": list(DRIFT_REVISION_ORDER),
        "arms": arms_out,
        "drift_index": drift_series,
    }
    if any_missing_drift:
        out["notes"] = [DRIFT_INDEX_MISSING_NOTE]

    out_path = experiments_dir / "drift-f1-series.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out_path

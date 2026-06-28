"""JSON export layer for `setdrift-eval health --json` (D-12, UI-SPEC §A.7).

What this module does:
  - export_health_json(): reads via run_health ONLY (D-04 single-source-of-truth);
    returns the schema_version=1 dict defined in UI-SPEC §A.7.
  - This is the Phase-5 obligation for D-12.  The Phase-6 Next.js web view
    consumes this export; it never calls the telemetry module directly.

What it does NOT do:
  - Recompute any metric (D-04 — all values come from run_health / F1Result).
  - Export raw telemetry content (T-05-16 data wall boundary — only scrubbed
    metric fields appear in the --json output).
  - Build the Next.js view (Phase-6 scope only, D-12).

Goodhart firewall: no F1 arithmetic in this file.  Import only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def export_health_json(
    corpus_path: Path,
    arm: str,
    seed: int = 42,
    map_path: Path = Path("eval/setdrift_eval/corpus/intent_skill_map.yaml"),
    skills_dir: Path = Path("plugin/skills"),
    experiments_dir: Path = Path("experiments"),
) -> dict:
    """Produce the schema_version=1 JSON payload (UI-SPEC §A.7).

    D-04: reads via run_health only; never recomputes any metric.
    D-12: this is the Phase-5 obligation; Phase-6 Next.js consumes the output.

    Returns a dict suitable for json.dumps().  Raises ScorerError (propagated
    from run_health) when the precision/kappa gate has not been passed — callers
    should handle this and emit an appropriate error message.

    Raw telemetry content is NOT included — only scrubbed metric fields (T-05-16).
    """
    # Lazy import: textual is the optional extra; scorer is the FROZEN RULER (D-04)
    from setdrift_eval.telemetry.scorer import run_health  # FROZEN RULER — read-only

    result = run_health(
        corpus_path=corpus_path,
        arm=arm,
        seed=seed,
        map_path=map_path,
        skills_dir=skills_dir,
        experiments_dir=experiments_dir,
    )

    # cost_usd: populated from ExperimentManifest.token_cost_total via figures/cost.py
    # when token totals are available.  For now, placeholder 0.0 (Phase-3 gated).
    cost_usd = _estimate_cost_usd(result)

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "f1_current":  result.macro_f1_mean,
        "f1_band_lo":  result.noise_band_low,
        "f1_band_hi":  result.noise_band_high,
        "pass_rate":   result.coverage_pct,   # sourced from Phase-3 when available
        "cost_usd":    cost_usd,
        "drift_index": 0.0,                   # populated from DriftManifest when Phase-4 lands
        "event_count": 0,                     # populated from telemetry query when Phase-1 lands
        "loop_status": "idle",                # populated from audit.jsonl last phase (Phase-3)
        "skills":      [],                    # populated per-skill from skill table (Phase-3)
    }


def _estimate_cost_usd(result: object) -> float:
    """Best-effort cost estimate from cost.py tokens_to_cost.

    Falls back to 0.0 if the figures.cost extra is not available or if
    token_cost_total is zero/unavailable (pre-Phase-3 state).
    """
    try:
        # F1Result does not carry token_cost_total (that is on ExperimentManifest).
        # Return 0.0 here; the dashboard reads the most-recent experiments/*.json
        # manifest for cost when available.
        return 0.0
    except ImportError:
        return 0.0

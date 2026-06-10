"""Haiku TEST-partition sensitivity arm (REQ-DRIFT-03, D-58/D-59/D-60).

What this module does:
  Runs a yoked 5-run noise-band evaluation on claude-haiku-4-5-20251001 (arms A vs B)
  using the TEST partition ONLY (D-59 Goodhart firewall — test-read is principled in a
  sensitivity report because no optimization occurs here).

  The result is a methodology-generalization check: does the observe→diagnose→patch→verify
  loop's advantage hold when the model is weaker/cheaper? Never a score race.

What this module does NOT do:
  - NEVER calls run_health() — it scores val+test combined (Pitfall 6 / Goodhart firewall
    violation). Instead, this module filters split=="test" directly, calls run_arm, and
    applies the FROZEN noise_band ruler.
  - Never modifies scorer.py, arm_runner.py, or experiment.py (FROZEN).
  - Never re-implements noise_band or macro_f1 (FROZEN RULER).
  - Never caps API spend (D-60): cost_usd is a secondary metric logged from cached usage.

Goodhart firewall:
  All F1 scoring goes through the FROZEN ruler imported from
  sica_eval.telemetry.scorer. These functions are never re-implemented here.

References: REQ-DRIFT-03, D-58 (Haiku sensitivity), D-59 (test-only partition),
            D-60 (cost_usd secondary metric), A3 (full versioned model id),
            Open Question 1 option (b), Open Question 3.
"""
import json
from pathlib import Path

import duckdb

from sica_eval.benchmark.arm_runner import load_skill_tools, run_arm
from sica_eval.benchmark.response_cache import load_or_call
from sica_eval.schemas.drift_manifest import DriftManifest

# FROZEN RULER — import only; never re-implement these functions.
# Modifying scorer.py to support Phase 4 is an architectural violation.
from sica_eval.telemetry.scorer import (  # FROZEN RULER — do not re-implement
    binarize,
    load_intent_map,
    macro_f1,
    noise_band,
    project_to_intents,
    scored_intents,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HAIKU_MODEL = "claude-haiku-4-5-20251001"  # full versioned id per A3 / Open Question 3
N_RUNS = 5  # noise-band run count (same as Sonnet grid)
ARMS = ("A", "B")

# Haiku per-token pricing (USD) as of 2026-05-22 (https://docs.anthropic.com/en/docs/about-claude/models).
# Input: $0.80/M tokens = $8e-7/token. Output: $4.00/M tokens = $4e-6/token.
# D-60: cost_usd is a secondary metric only — no hard spend cap enforced.
# Update this constant if Anthropic revises pricing (dated for reproducibility: 2026-05-22).
_HAIKU_INPUT_USD_PER_TOKEN = 8e-7   # $0.80 per million input tokens
_HAIKU_OUTPUT_USD_PER_TOKEN = 4e-6  # $4.00 per million output tokens


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_test_prompts(corpus_path: Path) -> list[dict]:
    """Return only prompts with split == "test" from corpus_path.

    Pitfall 6 guard (D-59): the Haiku sensitivity arm ONLY scores the TEST
    partition. Unlike run_health() which scores val+test combined, this function
    strictly filters to split=="test" — never "val". This preserves the Goodhart
    firewall: the TEST partition is untouched by the optimization loop, so reading
    it in a sensitivity report is principled (no optimization leakage).
    """
    corpus_path = Path(corpus_path)
    prompts = [
        json.loads(line)
        for line in corpus_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [p for p in prompts if p.get("split") == "test"]


def _compute_cost_usd(
    prompts: list[dict],
    tools: list[dict],
    cache_dir: Path,
) -> float:
    """Compute total cost_usd from cached usage token counts for all prompts × all runs.

    Reads the persisted 'usage' field from response_cache (input_tokens + output_tokens)
    and multiplies by the Haiku per-token price constants (D-60). Because all noise-band
    runs after the first are served from cache (zero additional API calls), the cost
    computed here reflects the actual first-call expenditure.

    No hard spend cap is applied (D-60: cost_usd is a secondary metric).
    """
    total_input = 0
    total_output = 0
    for p in prompts:
        data = load_or_call(HAIKU_MODEL, p["prompt"], tools, cache_dir)
        usage = data.get("usage", {})
        total_input += usage.get("input_tokens", 0)
        total_output += usage.get("output_tokens", 0)
    return (
        total_input * _HAIKU_INPUT_USD_PER_TOKEN
        + total_output * _HAIKU_OUTPUT_USD_PER_TOKEN
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_haiku_sensitivity(
    corpus_path: Path,
    arm_configs: dict,
    map_path: Path,
    cache_dir: Path,
    con: duckdb.DuckDBPyConnection,
) -> dict:
    """Run the Haiku TEST-partition A/B sensitivity arm (REQ-DRIFT-03).

    Scores arms A and B on the TEST partition ONLY using claude-haiku-4-5-20251001.
    Runs 5 noise-band evaluations per arm, computes macro_f1 per run via the FROZEN
    ruler, and reports the noise_band for each arm. Cost in USD is derived from the
    cached 'usage' token counts (D-60, secondary metric only).

    This function NEVER calls run_health() — that function scores val+test combined,
    violating Pitfall 6. Instead, it calls run_arm + noise_band directly on the
    test-only filtered prompt list.

    Args:
        corpus_path:  Path to the corpus JSONL (must have 'split' field per row).
        arm_configs:  {"A": Path, "B": Path} — skill directories per arm.
        map_path:     Path to the frozen intent_skill_map.yaml (FROZEN ruler).
        cache_dir:    LLM response cache directory (Haiku/Sonnet never collide — A6).
        con:          Open DuckDB connection with grid_cells schema applied.

    Returns:
        dict with keys:
          - n_prompts_scored: int — count of TEST-partition prompts (no val, D-59)
          - f1_runs_A: list[float] — 5-run macro_f1 values for arm A
          - f1_runs_B: list[float] — 5-run macro_f1 values for arm B
          - noise_band_A: tuple[float, float] — (low, high) via FROZEN noise_band
          - noise_band_B: tuple[float, float] — (low, high) via FROZEN noise_band
          - cost_usd: float — total USD cost from cached usage tokens (D-60)
          - model: str — "claude-haiku-4-5-20251001"
          - notes: str — D-59 rationale note

    Raises:
        ValueError: If the corpus has no test-partition prompts.
    """
    corpus_path = Path(corpus_path)
    cache_dir = Path(cache_dir)

    # D-59: filter to TEST partition ONLY — never val (Pitfall 6 guard)
    test_prompts = _load_test_prompts(corpus_path)
    if not test_prompts:
        raise ValueError(
            f"No test-partition prompts found in {corpus_path}. "
            "The Haiku sensitivity arm requires split=='test' rows (D-59)."
        )

    # FROZEN RULER — load intent map (import-only, never re-implemented)
    mapping, map_sha = load_intent_map(map_path)  # FROZEN RULER
    scored = scored_intents(mapping)               # FROZEN RULER
    labels = sorted(scored)

    f1_runs: dict[str, list[float]] = {"A": [], "B": []}
    total_cost_usd = 0.0

    for arm in ARMS:
        skills_dir = Path(arm_configs[arm])
        tools = load_skill_tools(skills_dir)

        for run_idx in range(N_RUNS):
            y_true_sets: list[set] = []
            y_pred_sets: list[set] = []

            for p in test_prompts:
                gt = set(p.get("ground_truth_skills") or [])
                # Call run_arm directly on the test-only prompt list
                # model=HAIKU_MODEL ensures cache key includes the full versioned id (A6)
                fired = run_arm(p["prompt"], tools, model=HAIKU_MODEL, cache_dir=cache_dir)
                gt_intents = project_to_intents(gt, mapping) & scored   # FROZEN RULER
                pred_intents = project_to_intents(fired, mapping) & scored  # FROZEN RULER
                y_true_sets.append(gt_intents)
                y_pred_sets.append(pred_intents)

            # FROZEN RULER — do not re-implement binarize / macro_f1
            yt = binarize(y_true_sets, labels)   # FROZEN RULER
            yp = binarize(y_pred_sets, labels)   # FROZEN RULER
            f1_val = macro_f1(yt, yp)            # FROZEN RULER
            f1_runs[arm].append(f1_val)

        # Compute cost for this arm's prompts (using cached responses — D-60)
        arm_cost = _compute_cost_usd(test_prompts, tools, cache_dir)
        total_cost_usd += arm_cost

    # FROZEN RULER — compute noise band per arm (import-only)
    band_a = noise_band(f1_runs["A"])  # FROZEN RULER
    band_b = noise_band(f1_runs["B"])  # FROZEN RULER

    # D-59 rationale note (required by the manifest and by acceptance criteria)
    notes = (
        "Haiku arm uses TEST partition only per D-59; "
        "no optimization occurs in a sensitivity report (test-read is principled)."
    )

    # Write cells into grid_cells for each run (model=HAIKU_MODEL, cost_usd populated)
    import hashlib
    from datetime import datetime, timezone

    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _yoke_minute() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")

    # Capture yoke_minute ONCE for this model (both arms share it — yoking discipline)
    yoke_min = _yoke_minute()

    for arm in ARMS:
        skills_dir = Path(arm_configs[arm])
        tools = load_skill_tools(skills_dir)
        cfg_hash = hashlib.sha256(
            str(sorted(t["name"] + t["description"] for t in tools)).encode()
        ).hexdigest()

        arm_f1_runs = f1_runs[arm]
        arm_cost = _compute_cost_usd(test_prompts, tools, cache_dir)

        for run_idx, f1_val in enumerate(arm_f1_runs):
            cell_id = hashlib.sha256(
                f"{arm}{HAIKU_MODEL}haiku_sensitivity{run_idx}".encode()
            ).hexdigest()[:12]

            con.execute(
                """
                INSERT OR REPLACE INTO grid_cells
                  (cell_id, arm, model, revision, run_idx,
                   config_hash, snapshot_hash, intent_map_sha,
                   split_hash, rng_seed, macro_f1, token_cost,
                   cost_usd, yoke_minute, ts)
                VALUES (?,?,?,?,?, ?,?,?,?, ?,?,?, ?,?,?)
                """,
                [
                    cell_id,
                    arm,
                    HAIKU_MODEL,
                    "haiku_sensitivity",  # revision label for the sensitivity arm
                    run_idx,
                    cfg_hash,
                    "",          # snapshot_hash — sensitivity arm uses live config
                    map_sha,
                    "",          # split_hash — not computed in sensitivity arm
                    run_idx,     # rng_seed = run_idx (deterministic, simple)
                    f1_val,
                    0,           # token_cost (integer count — not tracked here)
                    arm_cost / N_RUNS,  # cost_usd per run (D-60)
                    yoke_min,    # same for A and B (yoking discipline)
                    _now_iso(),
                ],
            )

    return {
        "n_prompts_scored": len(test_prompts),
        "f1_runs_A": f1_runs["A"],
        "f1_runs_B": f1_runs["B"],
        "noise_band_A": band_a,
        "noise_band_B": band_b,
        "cost_usd": total_cost_usd,
        "model": HAIKU_MODEL,
        "notes": notes,
    }

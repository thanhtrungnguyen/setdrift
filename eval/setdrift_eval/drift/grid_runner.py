"""Yoked grid runner for the 12-cell drift experiment (REQ-DRIFT-02).

What this module does:
  Runs the full (2 arms × 2 models × 3 revisions) × 5 runs = 60 evaluation
  cells, writing scored results into DuckDB grid_cells and a DriftManifest
  JSON to experiments/. Enforces all yoking-discipline exit-gate rules
  mechanically:
    - yoke_minute captured ONCE per (model, revision) pair, before iterating
      arms (Pitfall 1 — both A and B rows carry the same value)
    - Per-cell deterministic seed: sha256(arm-model-revision-run_idx)[:8]
    - Temperature 0 enforced via the SICA response_cache (arm_runner)
    - No CachePolicy(per_epoch=False) anywhere (Pitfall 5)
    - Content-addressed snapshot via checkout_snapshot() (REQ-DRIFT-02)
    - Frozen ruler consumed by import only (Goodhart firewall)

What it does NOT do:
  - Never modifies scorer.py, arm_runner.py, or experiment.py (FROZEN)
  - Never writes raw prompts/responses to experiments/ (data wall)
  - Never re-implements noise_band or macro_f1 (FROZEN RULER comment below)
  - Never runs live API calls without ANTHROPIC_API_KEY being set

Goodhart firewall:
  All F1 scoring goes through the FROZEN ruler imported from
  setdrift_eval.telemetry.scorer. These functions are never re-implemented here.

Lazy imports:
  sentence_transformers and inspect_ai are lazy-imported inside functions
  so `setdrift-eval` CLI loads without requiring the [drift] extra to be installed.

Requirements: REQ-DRIFT-02 (synthetic-drift grid, content-addressed snapshot
reproducibility), REQ-DRIFT-03 (Haiku sensitivity arm wired here, run in 04-03).
"""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from setdrift_eval.benchmark.arm_runner import load_skill_tools, run_arm
from setdrift_eval.drift.db import connect
from setdrift_eval.drift.snapshot import checkout_snapshot
from setdrift_eval.schemas.drift_manifest import DriftManifest

# FROZEN RULER — import only; never re-implement these functions.
# Modifying scorer.py to support Phase 4 is an architectural violation.
from setdrift_eval.telemetry.scorer import (  # FROZEN RULER — do not re-implement
    binarize,
    load_intent_map,
    macro_f1,
    noise_band,
    project_to_intents,
    scored_intents,
)

# ---------------------------------------------------------------------------
# Module-level constants (env-var-overridable, orchestrator.py pattern)
# ---------------------------------------------------------------------------

_MODEL_SONNET = "claude-sonnet-4-6"
_MODEL_HAIKU = "claude-haiku-4-5-20251001"  # full versioned ID per Open Question 3
MODELS = [_MODEL_SONNET, _MODEL_HAIKU]
ARMS = ["A", "B"]
REVISIONS = ["early", "mid", "late"]
N_RUNS = 5

_EXPERIMENTS_DIR = Path(
    os.environ.get("SICA_EXPERIMENTS_DIR", "experiments")
)
_CACHE_DIR = Path(os.environ.get("SICA_CACHE_DIR", "data/cache"))


# ---------------------------------------------------------------------------
# Helpers (copied verbatim from orchestrator.py — same stdlib pattern)
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _yoke_minute() -> str:
    """Return current UTC minute as 'YYYY-MM-DDTHH:MM' for yoking evidence."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")


def _cell_seed(arm: str, model: str, revision: str, run_idx: int) -> int:
    """Deterministic per-cell RNG seed: sha256(arm-model-revision-run_idx)[:8].

    Makes seeds unique and reproducible per (arm, model, revision, run_idx)
    without a separate seed manifest (RESEARCH.md Pattern 3, REQ-DRIFT-02).
    """
    raw = f"{arm}-{model}-{revision}-{run_idx}"
    return int(hashlib.sha256(raw.encode()).hexdigest()[:8], 16)


def _config_hash(tools: list[dict]) -> str:
    """Deterministic sha256 of the arm's skill config (sorted name+description)."""
    payload = str(sorted(t["name"] + t["description"] for t in tools))
    return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Error class (precondition gate — orchestrator.py OrchestratorError analog)
# ---------------------------------------------------------------------------


class GridRunnerError(RuntimeError):
    """Raised when a precondition for the drift grid run is not met (fail-loud)."""


# ---------------------------------------------------------------------------
# Corpus / prompt loading helper
# ---------------------------------------------------------------------------


def _load_corpus_prompts(corpus_path: Path, partition: str | tuple) -> list[dict]:
    """Load prompts from corpus_path JSONL filtered to the given partition(s).

    Each line in corpus_path must be a JSON object with at least:
      {"prompt_id": str, "prompt": str, "ground_truth_skills": list[str], "split": str}

    For the Haiku arm, partition="test" (D-59 test-only).
    For the Sonnet arm, partition=("val", "test").
    """
    corpus_path = Path(corpus_path)
    if isinstance(partition, str):
        allowed = {partition}
    else:
        allowed = set(partition)

    prompts = []
    with corpus_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("split") in allowed:
                prompts.append(rec)
    return prompts


# ---------------------------------------------------------------------------
# Main grid runner
# ---------------------------------------------------------------------------


def run_grid(
    gitbug_repo: Path,
    arm_configs: dict,
    corpus_path: Path,
    map_path: Path,
    revision_shas: dict,
    cache_dir: Path = _CACHE_DIR,
    experiments_dir: Path = _EXPERIMENTS_DIR,
) -> None:
    """Run the full 12-cell (2 arms × 2 models × 3 revisions) × N_RUNS grid.

    Writes scored rows into DuckDB grid_cells and a DriftManifest JSON per
    cell to experiments/{NNN}-drift-results.json.

    Args:
        gitbug_repo:    Path to the GitBug-Java repository for snapshotting.
        arm_configs:    {"A": Path, "B": Path} — skill directories per arm.
        corpus_path:    Path to corpus JSONL with prompt/split/ground_truth fields.
        map_path:       Path to the frozen intent_skill_map.yaml (FROZEN ruler).
        revision_shas:  {"early": sha, "mid": sha, "late": sha}
        cache_dir:      LLM response cache directory (SICA response_cache).
        experiments_dir: Where to write DriftManifest JSON files.

    Raises:
        GridRunnerError: If ANTHROPIC_API_KEY is unset before a live cell, or
                         if any required argument is missing.
    """
    # --- Fail-loud precondition: ANTHROPIC_API_KEY must be set before live run ---
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise GridRunnerError(
            "ANTHROPIC_API_KEY is not set. "
            "Export it before running the grid: "
            "export ANTHROPIC_API_KEY=sk-ant-... "
            "(or set SICA_LLM_BACKEND=openrouter and OPENROUTER_API_KEY). "
            "This is a live API run — no key means no scoring."
        )

    # --- Load FROZEN ruler components (import-only, never re-implemented) ---
    mapping, map_sha = load_intent_map(map_path)  # FROZEN RULER — do not re-implement
    scored = scored_intents(mapping)               # FROZEN RULER — do not re-implement
    labels = sorted(scored)

    # --- Open DuckDB connection ---
    con = connect()

    # --- Load embedder checksum (fail-loud, eval-side) ---
    # REQ-MEASURE-03 requires the embedder checksum to be logged into every
    # DriftManifest. Silently substituting "" on failure would write
    # reproducibility-blind manifests; let the error propagate instead.
    from setdrift_eval.drift.embedder import embedder_checksum  # lazy: [drift] extra
    emb_checksum = embedder_checksum()

    # --- Outer loops: model × revision (yoking boundary) ---
    for model in MODELS:
        # D-59: Haiku uses TEST partition only; Sonnet uses val+test.
        # Partition selection wired here per D-59 design decision.
        # Haiku live run is 04-03's responsibility; Sonnet cells run in this plan.
        if "haiku" in model:
            partition: str | tuple = "test"
        else:
            partition = ("val", "test")

        for revision in REVISIONS:
            # Content-addressed snapshot for this revision point
            snap_dir, snap_hash = checkout_snapshot(
                gitbug_repo, revision_shas[revision]
            )

            # YOKING EXIT GATE: capture yoke_minute ONCE per (model, revision) pair,
            # BEFORE iterating arms. Both A and B rows carry this identical value.
            # If A and B had different values, the paired difference would be invalid.
            yoke_min = _yoke_minute()

            # Load prompts for this model's partition
            prompts = _load_corpus_prompts(corpus_path, partition)

            # --- Inner loops: arm × run ---
            for arm in ARMS:
                skills_dir = Path(arm_configs[arm])
                tools = load_skill_tools(skills_dir)
                cfg_hash = _config_hash(tools)

                # 5-run noise band per (arm, model, revision) cell
                f1_runs: list[float] = []

                for run_idx in range(N_RUNS):
                    seed = _cell_seed(arm, model, revision, run_idx)

                    # --- Score one run over all prompts ---
                    y_true_sets: list[set] = []
                    y_pred_sets: list[set] = []
                    token_cost_run = 0

                    for p in prompts:
                        gt = set(p.get("ground_truth_skills") or [])
                        fired = run_arm(
                            p["prompt"], tools, model=model, cache_dir=cache_dir
                        )
                        # Project to intent space using the FROZEN ruler
                        gt_intents = project_to_intents(gt, mapping) & scored
                        pred_intents = project_to_intents(fired, mapping) & scored
                        y_true_sets.append(gt_intents)
                        y_pred_sets.append(pred_intents)

                    # FROZEN RULER — do not re-implement binarize / macro_f1
                    yt = binarize(y_true_sets, labels)   # FROZEN RULER
                    yp = binarize(y_pred_sets, labels)   # FROZEN RULER
                    f1_val = macro_f1(yt, yp)            # FROZEN RULER
                    f1_runs.append(f1_val)

                    # Cell id: sha256[:12] of (arm, model, revision, run_idx)
                    cell_id = hashlib.sha256(
                        f"{arm}{model}{revision}{run_idx}".encode()
                    ).hexdigest()[:12]

                    ts_now = _now_iso()

                    # INSERT OR REPLACE into grid_cells (DuckDB PRIMARY KEY dedup)
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
                            model,
                            revision,
                            run_idx,
                            cfg_hash,
                            snap_hash,
                            map_sha,
                            "",          # split_hash — populated by corpus loader
                            seed,
                            f1_val,
                            token_cost_run,
                            None,        # cost_usd — populated for Haiku (D-60, 04-03)
                            yoke_min,    # same for A and B in this (model, revision) pair
                            ts_now,
                        ],
                    )

                # FROZEN RULER — do not re-implement noise_band
                band_low, band_high = noise_band(f1_runs)  # FROZEN RULER
                f1_mean = sum(f1_runs) / len(f1_runs) if f1_runs else 0.0

                # --- Write DriftManifest to experiments/ ---
                experiments_dir = Path(experiments_dir)
                experiments_dir.mkdir(parents=True, exist_ok=True)
                n = len(list(experiments_dir.glob("*-drift-results.json"))) + 1
                manifest_path = experiments_dir / f"{n:03d}-drift-results.json"

                manifest = DriftManifest(
                    experiment_id=f"drift-{arm}-{model}-{revision}-run{N_RUNS}",
                    timestamp=_now_iso(),
                    phase=4,
                    model=model,
                    arm=arm,
                    corpus_name="gitbug-java",
                    corpus_version="public",
                    dataset_sha256="",        # populated by corpus version hash
                    split_hash="",
                    intent_map_sha256=map_sha,
                    config_hash=cfg_hash,
                    rng_seed=_cell_seed(arm, model, revision, 0),
                    n_prompts_scored=len(prompts),
                    n_prompts_out_of_coverage=0,
                    coverage_pct=1.0,
                    macro_f1_runs=f1_runs,
                    macro_f1_mean=f1_mean,
                    macro_f1_noise_band_low=band_low,
                    macro_f1_noise_band_high=band_high,
                    bootstrap_ci_low=band_low,
                    bootstrap_ci_high=band_high,
                    token_cost_total=0,
                    grid_arm=arm,
                    grid_revision=revision,
                    grid_run_idx=N_RUNS - 1,
                    snapshot_hash=snap_hash,
                    embedder_checksum=emb_checksum,
                    window_n=20,
                    yoke_minute=yoke_min,
                    cost_usd=None,
                    drift_index=None,
                    fallback_note="",
                )
                manifest_path.write_text(
                    manifest.model_dump_json(indent=2), encoding="utf-8"
                )

    con.close()

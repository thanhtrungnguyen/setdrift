"""Experiment manifest + F1 result schemas (REQ-MEASURE-01 / REQ-MEASURE-02).

ExperimentManifest is the reproducibility record committed to experiments/ — it
pins every parameter needed to re-run a cell: model + seed + dataset + config
hash, PLUS the D-30 intent-map sha256 and the build-time split_hash (Phase-3
exit-gate substrate), PLUS the REQ-MEASURE-02 secondary-metric fields. It carries
only IDs/hashes/aggregates — never prompt or response text (data wall).

intent_map_sha256 and split_hash are REQUIRED (no default) so a manifest can
never silently omit the anti-massage map hash or the partition fingerprint.
"""

from pydantic import BaseModel, ConfigDict, Field


class ExperimentManifest(BaseModel):
    """Full reproducibility manifest for one (config × arm × corpus) F1 cell."""

    model_config = ConfigDict(extra="forbid")

    # Identity / provenance
    experiment_id: str = Field(description="Unique id for this experiment cell")
    timestamp: str = Field(description="ISO-8601 UTC time the cell was run")
    phase: int = Field(default=2, description="Roadmap phase that produced this manifest")
    model: str = Field(description="Pinned model id, e.g. claude-sonnet-4-6")
    arm: str = Field(description="Measured arm: A | B | C")

    # Dataset + reproducibility fingerprints
    corpus_name: str = Field(description="Corpus name, e.g. 'public'")
    corpus_version: str = Field(description="Corpus version string")
    dataset_sha256: str = Field(description="sha256 of the corpus JSONL used")
    split_hash: str = Field(
        description="sha256 of the frozen train/val/test split (build-time, Phase-3 exit-gate substrate)"
    )
    intent_map_sha256: str = Field(
        description="sha256 of the frozen intent_skill_map.yaml (D-30 anti-massage)"
    )
    config_hash: str = Field(description="sha256 of the arm's skill configuration")
    rng_seed: int = Field(description="RNG seed for sampling / bootstrap")

    # Coverage (D-31 out-of-coverage holdout)
    n_prompts_scored: int = Field(description="Prompts in scored (mapped) intents")
    n_prompts_out_of_coverage: int = Field(
        description="Prompts whose gt intent maps to [] (holdout)"
    )
    coverage_pct: float = Field(description="scored intents / total taxonomy intents")

    # Primary metric (REQ-MEASURE-01): strict-match macro-F1, 5-run band, bootstrap CI
    macro_f1_runs: list[float] = Field(description="Per-run macro-F1 values (default 5 runs)")
    macro_f1_mean: float = Field(description="Mean macro-F1 across runs")
    macro_f1_noise_band_low: float = Field(description="Lower edge of the 5-run noise band")
    macro_f1_noise_band_high: float = Field(description="Upper edge of the 5-run noise band")
    bootstrap_ci_low: float = Field(description="Lower bootstrap CI bound over prompts")
    bootstrap_ci_high: float = Field(description="Upper bootstrap CI bound over prompts")

    # Secondary metrics (REQ-MEASURE-02) — reported alongside, not part of the claim
    token_cost_total: int = Field(description="Total input+output tokens for this cell")
    per_source_precision: dict[str, float] = Field(
        default_factory=dict, description="Mined-label precision per corpus source"
    )
    per_source_kappa: dict[str, float] = Field(
        default_factory=dict, description="Cohen's kappa (mined vs verified) per source"
    )
    per_source_label_distribution: dict[str, dict[str, int]] = Field(
        default_factory=dict, description="Per-source intent-label counts"
    )

    notes: str = Field(default="", description="Free-form notes (e.g. fallback flags)")


class F1Result(BaseModel):
    """Headline subset of the manifest for CLI stdout (setdrift-eval health)."""

    model_config = ConfigDict(extra="forbid")

    arm: str = Field(description="Measured arm: A | B | C")
    macro_f1_mean: float = Field(description="Mean macro-F1 across runs")
    noise_band_low: float = Field(description="Lower edge of the 5-run noise band")
    noise_band_high: float = Field(description="Upper edge of the 5-run noise band")
    bootstrap_ci_low: float = Field(description="Lower bootstrap CI bound")
    bootstrap_ci_high: float = Field(description="Upper bootstrap CI bound")
    coverage_pct: float = Field(description="scored intents / total taxonomy intents")

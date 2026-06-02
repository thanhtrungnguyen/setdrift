"""ExperimentManifest / F1Result schema tests (Plan 02-04 Task 3, REQ-MEASURE-02)."""
import pytest
from pydantic import ValidationError

from sica_eval.schemas.experiment import ExperimentManifest, F1Result


def _manifest_kwargs(**overrides) -> dict:
    base = dict(
        experiment_id="exp-001",
        timestamp="2026-06-01T00:00:00Z",
        model="claude-sonnet-4-6",
        arm="B",
        corpus_name="public",
        corpus_version="2026-06-01",
        dataset_sha256="a" * 64,
        split_hash="b" * 64,
        intent_map_sha256="c" * 64,
        config_hash="d" * 64,
        rng_seed=42,
        n_prompts_scored=400,
        n_prompts_out_of_coverage=156,
        coverage_pct=1 / 8,
        macro_f1_runs=[0.5, 0.51, 0.49, 0.5, 0.52],
        macro_f1_mean=0.504,
        macro_f1_noise_band_low=0.48,
        macro_f1_noise_band_high=0.53,
        bootstrap_ci_low=0.46,
        bootstrap_ci_high=0.55,
        token_cost_total=123456,
        per_source_precision={"gitbug-java": 0.9, "defects4j": 0.88},
        per_source_kappa={"gitbug-java": 0.7, "defects4j": 0.65},
        per_source_label_distribution={"gitbug-java": {"spring-annotation-fix": 40}},
    )
    base.update(overrides)
    return base


def test_manifest_roundtrips():
    m = ExperimentManifest(**_manifest_kwargs())
    assert ExperimentManifest.model_validate_json(m.model_dump_json()) == m


def test_manifest_rejects_extra_field():
    with pytest.raises(ValidationError):
        ExperimentManifest(**_manifest_kwargs(unexpected_field="x"))


def test_intent_map_sha256_is_required():
    kwargs = _manifest_kwargs()
    del kwargs["intent_map_sha256"]
    with pytest.raises(ValidationError):
        ExperimentManifest(**kwargs)


def test_split_hash_is_required():
    kwargs = _manifest_kwargs()
    del kwargs["split_hash"]
    with pytest.raises(ValidationError):
        ExperimentManifest(**kwargs)


def test_manifest_has_secondary_metric_fields():
    m = ExperimentManifest(**_manifest_kwargs())
    # REQ-MEASURE-02 secondary fields present and populated.
    assert m.token_cost_total == 123456
    assert m.per_source_precision["gitbug-java"] == 0.9
    assert m.per_source_kappa["defects4j"] == 0.65
    assert m.per_source_label_distribution["gitbug-java"]["spring-annotation-fix"] == 40


def test_f1result_headline_subset():
    r = F1Result(
        arm="C",
        macro_f1_mean=0.0,
        noise_band_low=0.0,
        noise_band_high=0.0,
        bootstrap_ci_low=0.0,
        bootstrap_ci_high=0.0,
        coverage_pct=1 / 8,
    )
    assert r.arm == "C"
    assert ExperimentManifest.model_fields["intent_map_sha256"].is_required()

"""Scorer unit tests (Plan 02-05 Task 1). Offline, no API.

Holdout / gate-guard / arm-C behaviors live in test_health_cli.py (they are
run_health-level); this file covers the pure scoring primitives.
"""
import numpy as np
import pytest
import yaml

from setdrift_eval.telemetry import scorer
from setdrift_eval.telemetry.scorer import ScorerError


def _map_file(tmp_path, mapping):
    p = tmp_path / "map.yaml"
    p.write_text(yaml.safe_dump(mapping), encoding="utf-8")
    return p


def test_load_intent_map_returns_mapping_and_sha(tmp_path):
    p = _map_file(tmp_path, {"spring-annotation-fix": ["spring_boot_endpoint"], "none": []})
    mapping, sha = scorer.load_intent_map(p)
    assert mapping["spring-annotation-fix"] == ["spring_boot_endpoint"]
    assert len(sha) == 64


def test_scored_intents_filters_empty():
    m = {"spring-annotation-fix": ["x"], "null-check": [], "none": []}
    assert scorer.scored_intents(m) == frozenset({"spring-annotation-fix"})


def test_empty_scored_intents_raises():
    with pytest.raises(ScorerError):
        scorer.scored_intents({"a": [], "none": []})


def test_project_to_intents():
    m = {
        "spring-annotation-fix": ["spring_boot_endpoint"],
        "jpa-migration": ["spring_boot_endpoint", "other"],
        "none": [],
    }
    assert scorer.project_to_intents({"spring_boot_endpoint"}, m) == {
        "spring-annotation-fix", "jpa-migration",
    }
    assert scorer.project_to_intents(set(), m) == set()


def test_strict_set_equality_macro_f1():
    labels = ["spring-annotation-fix"]
    yt = scorer.binarize([{"spring-annotation-fix"}, set(), set()], labels)
    assert scorer.macro_f1(yt, yt.copy()) == 1.0  # exact match
    yp_miss = scorer.binarize([set(), set(), set()], labels)  # missed the positive
    assert scorer.macro_f1(yt, yp_miss) < 1.0


def test_noise_band_zero_width_on_identical_runs():
    lo, hi = scorer.noise_band([0.5] * 5)  # cached determinism → width 0
    assert lo == hi == 0.5


def test_bootstrap_ci_ordered_and_seed_pinned():
    yt = np.array([[1, 0], [0, 1], [1, 1], [0, 0]] * 5)
    yp = np.array([[1, 0], [0, 0], [1, 1], [0, 0]] * 5)
    lo1, hi1 = scorer.bootstrap_ci(yt, yp, seed=7, n_resamples=300)
    lo2, hi2 = scorer.bootstrap_ci(yt, yp, seed=7, n_resamples=300)
    assert lo1 <= hi1
    assert (lo1, hi1) == (lo2, hi2)  # same seed → same CI

"""Tests for the Haiku TEST-partition sensitivity arm (REQ-DRIFT-03, D-58/D-59/D-60).

Verifies:
  1. Test-partition filter excludes val prompts — n_prompts_scored equals test count (Pitfall 6 guard).
  2. Model id is the full versioned string "claude-haiku-4-5-20251001" (A3/Open-Q3).
  3. Returned report contains 5-run macro_f1 lists per arm and noise_band computed via
     the frozen scorer.noise_band.
  4. cost_usd is populated from cached "usage" token counts (D-60).

Uses tmp_path corpus + fake split + stubbed run_arm/cache to run offline without the API.
"""
import json
import math
from pathlib import Path
from unittest.mock import patch, MagicMock

import duckdb
import pytest

from sica_eval.drift.db import DDL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_corpus(tmp_path: Path, n_val: int = 3, n_test: int = 4) -> Path:
    """Create a tiny corpus JSONL with n_val val prompts and n_test test prompts."""
    corpus_dir = tmp_path / "corpora"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    corpus_path = corpus_dir / "public.jsonl"

    lines = []
    split: dict[str, str] = {}

    for i in range(n_val):
        pid = f"val-{i}"
        rec = {
            "prompt_id": pid,
            "prompt": f"val prompt {i}",
            "ground_truth_skills": ["spring_boot_endpoint"],
            "split": "val",
        }
        lines.append(json.dumps(rec))
        split[pid] = "val"

    for i in range(n_test):
        pid = f"test-{i}"
        rec = {
            "prompt_id": pid,
            "prompt": f"test prompt {i}",
            "ground_truth_skills": ["spring_boot_endpoint"],
            "split": "test",
        }
        lines.append(json.dumps(rec))
        split[pid] = "test"

    corpus_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # split.json adjacent to corpus
    (corpus_dir / "split.json").write_text(json.dumps(split), encoding="utf-8")
    return corpus_path


def _make_skills_dirs(tmp_path: Path) -> dict:
    """Create minimal skill directories for arms A and B."""
    arm_configs = {}
    for arm in ("A", "B"):
        skill_dir = tmp_path / f"skills_{arm}" / "spring-boot"
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(
            "---\nname: spring_boot_endpoint\ndescription: Create Spring Boot REST endpoints\n---\n",
            encoding="utf-8",
        )
        arm_configs[arm] = tmp_path / f"skills_{arm}"
    return arm_configs


def _make_map(tmp_path: Path) -> Path:
    """Create a minimal intent_skill_map.yaml."""
    map_path = tmp_path / "intent_skill_map.yaml"
    map_path.write_text(
        "spring_endpoint:\n  - spring_boot_endpoint\n",
        encoding="utf-8",
    )
    return map_path


def _make_db(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    """Create an in-memory DuckDB with the grid schema."""
    con = duckdb.connect(str(tmp_path / "test.ddb"))
    con.execute(DDL)
    return con


# ---------------------------------------------------------------------------
# Test 1: Test-partition filter — no val prompts leak (Pitfall 6 guard)
# ---------------------------------------------------------------------------

def test_test_partition_filter_excludes_val(tmp_path: Path) -> None:
    """Test 1: n_prompts_scored equals test count; no val prompts are included (D-59 / Pitfall 6)."""
    from sica_eval.drift import haiku_arm

    N_VAL = 3
    N_TEST = 4
    corpus_path = _make_corpus(tmp_path, n_val=N_VAL, n_test=N_TEST)
    arm_configs = _make_skills_dirs(tmp_path)
    map_path = _make_map(tmp_path)
    con = _make_db(tmp_path)

    # Stub run_arm to return a fixed fired set (offline — no API)
    def _fake_run_arm(prompt, tools, *, model, cache_dir):
        return {"spring_boot_endpoint"}

    # Stub load_or_call to return a minimal cached response with usage tokens
    def _fake_load_or_call(model, prompt, tools, cache_dir):
        return {
            "content": [{"type": "tool_use", "name": "spring_boot_endpoint"}],
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }

    with (
        patch("sica_eval.drift.haiku_arm.run_arm", side_effect=_fake_run_arm),
        patch("sica_eval.drift.haiku_arm.load_or_call", side_effect=_fake_load_or_call),
    ):
        report = haiku_arm.run_haiku_sensitivity(
            corpus_path=corpus_path,
            arm_configs=arm_configs,
            map_path=map_path,
            cache_dir=tmp_path / "cache",
            con=con,
        )

    # n_prompts_scored must equal the test count, NOT val+test
    assert report["n_prompts_scored"] == N_TEST, (
        f"Expected n_prompts_scored={N_TEST} (test-only per D-59), "
        f"got {report['n_prompts_scored']}. Val prompts must NOT be included (Pitfall 6)."
    )


# ---------------------------------------------------------------------------
# Test 2: Model id is the full versioned string
# ---------------------------------------------------------------------------

def test_haiku_model_id_full_versioned() -> None:
    """Test 2: HAIKU_MODEL constant is the full versioned id "claude-haiku-4-5-20251001" (A3)."""
    from sica_eval.drift import haiku_arm

    assert haiku_arm.HAIKU_MODEL == "claude-haiku-4-5-20251001", (
        f"HAIKU_MODEL must be the full versioned id 'claude-haiku-4-5-20251001', "
        f"got {haiku_arm.HAIKU_MODEL!r}. Full version pin prevents snapshot drift (A3)."
    )


def test_run_haiku_sensitivity_uses_full_versioned_model(tmp_path: Path) -> None:
    """Test 2b: run_haiku_sensitivity passes the full versioned model id to run_arm (A3)."""
    from sica_eval.drift import haiku_arm

    corpus_path = _make_corpus(tmp_path, n_val=2, n_test=3)
    arm_configs = _make_skills_dirs(tmp_path)
    map_path = _make_map(tmp_path)
    con = _make_db(tmp_path)

    models_used: list[str] = []

    def _fake_run_arm(prompt, tools, *, model, cache_dir):
        models_used.append(model)
        return {"spring_boot_endpoint"}

    def _fake_load_or_call(model, prompt, tools, cache_dir):
        return {
            "content": [{"type": "tool_use", "name": "spring_boot_endpoint"}],
            "usage": {"input_tokens": 50, "output_tokens": 25},
        }

    with (
        patch("sica_eval.drift.haiku_arm.run_arm", side_effect=_fake_run_arm),
        patch("sica_eval.drift.haiku_arm.load_or_call", side_effect=_fake_load_or_call),
    ):
        haiku_arm.run_haiku_sensitivity(
            corpus_path=corpus_path,
            arm_configs=arm_configs,
            map_path=map_path,
            cache_dir=tmp_path / "cache",
            con=con,
        )

    assert models_used, "run_arm must be called at least once"
    for m in models_used:
        assert m == "claude-haiku-4-5-20251001", (
            f"run_arm was called with model={m!r} instead of 'claude-haiku-4-5-20251001'"
        )


# ---------------------------------------------------------------------------
# Test 3: Report contains 5-run macro_f1 lists per arm, noise_band via frozen scorer
# ---------------------------------------------------------------------------

def test_report_contains_5run_band_per_arm(tmp_path: Path) -> None:
    """Test 3: report contains f1_runs_A, f1_runs_B (5 values each) and noise_band from frozen scorer."""
    from sica_eval.drift import haiku_arm
    from sica_eval.telemetry.scorer import noise_band as real_noise_band

    corpus_path = _make_corpus(tmp_path, n_val=2, n_test=3)
    arm_configs = _make_skills_dirs(tmp_path)
    map_path = _make_map(tmp_path)
    con = _make_db(tmp_path)

    def _fake_run_arm(prompt, tools, *, model, cache_dir):
        return {"spring_boot_endpoint"}

    def _fake_load_or_call(model, prompt, tools, cache_dir):
        return {
            "content": [{"type": "tool_use", "name": "spring_boot_endpoint"}],
            "usage": {"input_tokens": 80, "output_tokens": 40},
        }

    with (
        patch("sica_eval.drift.haiku_arm.run_arm", side_effect=_fake_run_arm),
        patch("sica_eval.drift.haiku_arm.load_or_call", side_effect=_fake_load_or_call),
    ):
        report = haiku_arm.run_haiku_sensitivity(
            corpus_path=corpus_path,
            arm_configs=arm_configs,
            map_path=map_path,
            cache_dir=tmp_path / "cache",
            con=con,
        )

    # Must contain 5-run lists per arm
    assert "f1_runs_A" in report, "report must contain f1_runs_A"
    assert "f1_runs_B" in report, "report must contain f1_runs_B"
    assert len(report["f1_runs_A"]) == 5, (
        f"f1_runs_A must have 5 values (noise band runs), got {len(report['f1_runs_A'])}"
    )
    assert len(report["f1_runs_B"]) == 5, (
        f"f1_runs_B must have 5 values (noise band runs), got {len(report['f1_runs_B'])}"
    )

    # noise_band values must match what the frozen scorer would compute
    expected_band_a = real_noise_band(report["f1_runs_A"])
    expected_band_b = real_noise_band(report["f1_runs_B"])

    assert "noise_band_A" in report, "report must contain noise_band_A"
    assert "noise_band_B" in report, "report must contain noise_band_B"
    assert report["noise_band_A"] == expected_band_a, (
        f"noise_band_A mismatch: expected {expected_band_a}, got {report['noise_band_A']}. "
        "Must use the FROZEN scorer.noise_band."
    )
    assert report["noise_band_B"] == expected_band_b, (
        f"noise_band_B mismatch: expected {expected_band_b}, got {report['noise_band_B']}. "
        "Must use the FROZEN scorer.noise_band."
    )


# ---------------------------------------------------------------------------
# Test 4: cost_usd populated from cached usage token counts (D-60)
# ---------------------------------------------------------------------------

def test_cost_usd_populated_from_usage(tmp_path: Path) -> None:
    """Test 4: cost_usd is populated from the cached usage token counts (D-60)."""
    from sica_eval.drift import haiku_arm

    corpus_path = _make_corpus(tmp_path, n_val=1, n_test=2)
    arm_configs = _make_skills_dirs(tmp_path)
    map_path = _make_map(tmp_path)
    con = _make_db(tmp_path)

    def _fake_run_arm(prompt, tools, *, model, cache_dir):
        return {"spring_boot_endpoint"}

    # Provide predictable token counts: 100 input + 50 output per call
    def _fake_load_or_call(model, prompt, tools, cache_dir):
        return {
            "content": [{"type": "tool_use", "name": "spring_boot_endpoint"}],
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }

    with (
        patch("sica_eval.drift.haiku_arm.run_arm", side_effect=_fake_run_arm),
        patch("sica_eval.drift.haiku_arm.load_or_call", side_effect=_fake_load_or_call),
    ):
        report = haiku_arm.run_haiku_sensitivity(
            corpus_path=corpus_path,
            arm_configs=arm_configs,
            map_path=map_path,
            cache_dir=tmp_path / "cache",
            con=con,
        )

    # cost_usd must be present and > 0 (tokens were consumed)
    assert "cost_usd" in report, "report must contain cost_usd (D-60)"
    assert report["cost_usd"] is not None, "cost_usd must not be None (D-60)"
    assert report["cost_usd"] > 0.0, (
        f"cost_usd must be > 0 when tokens are consumed, got {report['cost_usd']}"
    )
    # No hard spend cap — cost_usd should be a positive finite float
    assert math.isfinite(report["cost_usd"]), "cost_usd must be a finite float"


# ---------------------------------------------------------------------------
# Test 5: Manifest note records D-59 test-only rationale
# ---------------------------------------------------------------------------

def test_manifest_note_records_d59_rationale(tmp_path: Path) -> None:
    """Test 5: DriftManifest notes field records the D-59 test-only partition rationale."""
    from sica_eval.drift import haiku_arm

    corpus_path = _make_corpus(tmp_path, n_val=2, n_test=3)
    arm_configs = _make_skills_dirs(tmp_path)
    map_path = _make_map(tmp_path)
    con = _make_db(tmp_path)

    def _fake_run_arm(prompt, tools, *, model, cache_dir):
        return {"spring_boot_endpoint"}

    def _fake_load_or_call(model, prompt, tools, cache_dir):
        return {
            "content": [{"type": "tool_use", "name": "spring_boot_endpoint"}],
            "usage": {"input_tokens": 60, "output_tokens": 30},
        }

    with (
        patch("sica_eval.drift.haiku_arm.run_arm", side_effect=_fake_run_arm),
        patch("sica_eval.drift.haiku_arm.load_or_call", side_effect=_fake_load_or_call),
    ):
        report = haiku_arm.run_haiku_sensitivity(
            corpus_path=corpus_path,
            arm_configs=arm_configs,
            map_path=map_path,
            cache_dir=tmp_path / "cache",
            con=con,
        )

    # The manifest notes must record the D-59 rationale
    assert "notes" in report, "report must contain notes field"
    assert "D-59" in report["notes"], (
        f"notes must reference D-59 (test-only partition rationale), got: {report['notes']!r}"
    )
    assert "TEST" in report["notes"].upper() or "test" in report["notes"].lower(), (
        f"notes must mention 'test' partition, got: {report['notes']!r}"
    )


# ---------------------------------------------------------------------------
# Test 6: haiku_arm.py does NOT call run_health (Goodhart firewall)
# ---------------------------------------------------------------------------

def test_haiku_arm_does_not_import_run_health() -> None:
    """Test 6: haiku_arm.py must not call run_health (Goodhart firewall / Pitfall 6)."""
    import ast

    haiku_arm_path = Path(__file__).resolve().parents[1] / "haiku_arm.py"
    assert haiku_arm_path.exists(), f"haiku_arm.py not found at {haiku_arm_path}"

    source = haiku_arm_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Check for run_health() calls in live code (not comments/docstrings)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # Direct call: run_health(...)
            if isinstance(node.func, ast.Name) and node.func.id == "run_health":
                pytest.fail(
                    "haiku_arm.py must NOT call run_health() — it mixes val+test partitions "
                    "(Goodhart firewall violation, Pitfall 6). "
                    "Use run_arm + noise_band directly on test-filtered prompts (D-59)."
                )
            # Attribute call: scorer.run_health(...) or similar
            if isinstance(node.func, ast.Attribute) and node.func.attr == "run_health":
                pytest.fail(
                    "haiku_arm.py must NOT call run_health() (attribute call detected). "
                    "Goodhart firewall: run_health mixes val+test — bypass it entirely (Pitfall 6)."
                )

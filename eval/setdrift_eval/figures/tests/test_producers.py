"""Tests for the cost/triangulation figure-input producers (FIX-03, REQ-DELIV-02).

All tests are hermetic: they write synthetic audit-genealogy.jsonl, {NNN}-results.json,
{NNN}-drift-results.json, and {NNN}-loop-manifest.json fixtures to tmp_path and never
touch the real committed experiments/ tree. No live API calls.

References: 06-05-PLAN.md Task 2, 06-PATTERNS.md (FIX-03 section, Pitfall 4).
"""

from __future__ import annotations

import json
from pathlib import Path


def _write_audit_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def _audit_record(cycle_id: str, step: str, ts: str, config_hash: str) -> dict:
    return {
        "cycle_id": cycle_id,
        "step": step,
        "ts": ts,
        "config_hash": config_hash,
        "parent_hash": config_hash,
        "f1_delta": 0.05 if step in ("verify", "promote", "rollback") else None,
        "decision": "promoted" if step == "promote" else step,
        "reason": f"[TEST] {step}",
        "model": "claude-sonnet-4-6",
        "seed": 42,
    }


def _write_json(path: Path, **fields) -> Path:
    path.write_text(json.dumps(fields, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# build_cost_tokens
# ---------------------------------------------------------------------------


class TestBuildCostTokens:
    def test_emits_config_hash_keyed_int_dict_from_results_and_drift(self, tmp_path: Path):
        from setdrift_eval.figures.producers import build_cost_tokens

        experiments_dir = tmp_path
        _write_json(
            experiments_dir / "001-results.json",
            config_hash="hashA",
            macro_f1_mean=0.7,
            coverage_pct=0.8,
            token_cost_total=1000,
        )
        _write_json(
            experiments_dir / "001-drift-results.json",
            config_hash="hashZ",
            token_cost_total=0,
        )

        out_path = build_cost_tokens(experiments_dir)

        assert out_path == experiments_dir / "cost-tokens.json"
        assert out_path.exists()
        data = json.loads(out_path.read_text(encoding="utf-8"))

        assert data["hashA"] == 1000
        assert data["hashZ"] == 0
        for k, v in data.items():
            assert isinstance(k, str)
            assert isinstance(v, int)

    def test_joins_loop_manifest_cost_via_promoted_cycle_config_hash(self, tmp_path: Path):
        from setdrift_eval.figures.producers import build_cost_tokens

        experiments_dir = tmp_path
        cycle_id = "cycle-promoted-0001"
        _write_audit_jsonl(
            experiments_dir / "audit-genealogy.jsonl",
            [
                _audit_record(cycle_id, "observe", "2026-06-01T00:00:00+00:00", "hashA"),
                _audit_record(cycle_id, "promote", "2026-06-01T00:02:00+00:00", "hashB"),
            ],
        )
        _write_json(
            experiments_dir / "001-loop-manifest.json",
            cycle_id=cycle_id,
            skill_name="spring-boot-endpoint",
            token_cost_total=500,
        )

        out_path = build_cost_tokens(experiments_dir)
        data = json.loads(out_path.read_text(encoding="utf-8"))

        assert data == {"hashB": 500}

    def test_rejected_cycle_loop_manifest_is_not_joined(self, tmp_path: Path):
        """A cycle whose terminal step is 'rollback' never becomes a version (D6-04) —
        its loop-manifest token cost must not leak into cost-tokens.json."""
        from setdrift_eval.figures.producers import build_cost_tokens

        experiments_dir = tmp_path
        cycle_id = "cycle-rejected-0002"
        _write_audit_jsonl(
            experiments_dir / "audit-genealogy.jsonl",
            [
                _audit_record(cycle_id, "observe", "2026-06-01T00:00:00+00:00", "hashC"),
                _audit_record(cycle_id, "rollback", "2026-06-01T00:01:00+00:00", "hashC"),
            ],
        )
        _write_json(
            experiments_dir / "001-loop-manifest.json",
            cycle_id=cycle_id,
            skill_name="spring-boot-endpoint",
            token_cost_total=999,
        )

        out_path = build_cost_tokens(experiments_dir)
        data = json.loads(out_path.read_text(encoding="utf-8"))

        assert data == {}

    def test_overwrites_wholesale_on_second_call(self, tmp_path: Path):
        """Singular, rebuilt-each-run — a second call must not append to the first."""
        from setdrift_eval.figures.producers import build_cost_tokens

        experiments_dir = tmp_path
        _write_json(
            experiments_dir / "001-results.json", config_hash="hashA", token_cost_total=100
        )
        build_cost_tokens(experiments_dir)

        (experiments_dir / "001-results.json").unlink()
        _write_json(
            experiments_dir / "001-results.json", config_hash="hashB", token_cost_total=200
        )
        out_path = build_cost_tokens(experiments_dir)
        data = json.loads(out_path.read_text(encoding="utf-8"))

        assert data == {"hashB": 200}

    def test_round_trips_through_figures_cli_cost_delta_consumer_shape(self, tmp_path: Path):
        """Mirrors figures/cli.py lines 71-93's read side exactly (no --allow-fixtures)."""
        from setdrift_eval.figures.producers import build_cost_tokens

        experiments_dir = tmp_path
        _write_json(
            experiments_dir / "001-results.json", config_hash="hashA", token_cost_total=42
        )
        out_path = build_cost_tokens(experiments_dir)

        raw = json.loads(out_path.read_text(encoding="utf-8"))
        per_version = {str(k): int(v) for k, v in raw.items()}  # cli.py consumer line
        assert per_version == {"hashA": 42}


# ---------------------------------------------------------------------------
# build_triangulation_series
# ---------------------------------------------------------------------------


class TestBuildTriangulationSeries:
    def test_emits_f1_and_pass_rate_series_ordered_by_promotion(self, tmp_path: Path):
        from setdrift_eval.figures.producers import build_triangulation_series

        experiments_dir = tmp_path
        _write_audit_jsonl(
            experiments_dir / "audit-genealogy.jsonl",
            [
                _audit_record("cycle-1", "promote", "2026-06-01T00:00:00+00:00", "hashA"),
                _audit_record("cycle-2", "promote", "2026-06-02T00:00:00+00:00", "hashB"),
            ],
        )
        _write_json(
            experiments_dir / "001-results.json",
            config_hash="hashA",
            macro_f1_mean=0.60,
            coverage_pct=0.50,
        )
        _write_json(
            experiments_dir / "002-results.json",
            config_hash="hashB",
            macro_f1_mean=0.75,
            coverage_pct=0.65,
        )

        out_path = build_triangulation_series(experiments_dir)

        assert out_path == experiments_dir / "triangulation-series.json"
        data = json.loads(out_path.read_text(encoding="utf-8"))

        assert set(data.keys()) == {"f1_series", "pass_rate_series"}
        assert data["f1_series"] == [0.60, 0.75]
        assert data["pass_rate_series"] == [0.50, 0.65]

    def test_promoted_hash_with_no_results_manifest_is_skipped(self, tmp_path: Path):
        from setdrift_eval.figures.producers import build_triangulation_series

        experiments_dir = tmp_path
        _write_audit_jsonl(
            experiments_dir / "audit-genealogy.jsonl",
            [_audit_record("cycle-1", "promote", "2026-06-01T00:00:00+00:00", "hashA")],
        )
        # Deliberately no {NNN}-results.json for hashA.

        out_path = build_triangulation_series(experiments_dir)
        data = json.loads(out_path.read_text(encoding="utf-8"))

        assert data == {"f1_series": [], "pass_rate_series": []}

    def test_round_trips_through_figures_cli_triangulation_consumer_shape(self, tmp_path: Path):
        """Mirrors figures/cli.py lines 132-138's read side exactly (no --allow-fixtures)."""
        from setdrift_eval.figures.producers import build_triangulation_series

        experiments_dir = tmp_path
        _write_audit_jsonl(
            experiments_dir / "audit-genealogy.jsonl",
            [_audit_record("cycle-1", "promote", "2026-06-01T00:00:00+00:00", "hashA")],
        )
        _write_json(
            experiments_dir / "001-results.json",
            config_hash="hashA",
            macro_f1_mean=0.71,
            coverage_pct=0.55,
        )

        out_path = build_triangulation_series(experiments_dir)

        raw = json.loads(out_path.read_text(encoding="utf-8"))  # cli.py consumer lines
        f1_series = [float(x) for x in raw["f1_series"]]
        pass_rate_series = [float(x) for x in raw["pass_rate_series"]]
        assert f1_series == [0.71]
        assert pass_rate_series == [0.55]


# ---------------------------------------------------------------------------
# Don't-Hand-Roll: producers import build_version_index (not reimplement it)
# ---------------------------------------------------------------------------


def test_producers_module_imports_build_version_index_not_reimplemented():
    import inspect

    from setdrift_eval.figures import producers

    src = inspect.getsource(producers)
    assert "from setdrift_eval.figures.version_index import build_version_index" in src


def test_producers_module_documents_drift_grid_zero_cost_gap():
    import inspect

    from setdrift_eval.figures import producers

    src = inspect.getsource(producers)
    assert "token_cost_total=0" in src

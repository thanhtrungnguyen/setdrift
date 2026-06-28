"""ablate.py + setdrift-eval ablate CLI tests (Plan 03-03 Task 3). Offline, no API.

Tests:
- build_ablation_table returns one row per 6 configs (full + 5 ablations)
- Each row has an F1 + delta vs full-config
- The largest-negative-delta row is flagged ROOT CAUSE
- render_table output contains required header columns
- setdrift-eval ablate --help exits 0 and shows --failure-id
- health --arm choices includes A
"""
import json
import sys
from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FULL_MAP = {
    "spring-annotation-fix": ["spring_boot_endpoint"],
    "jpa-migration": ["spring_jpa_entity"],
    "dependency-bump": [],
    "null-check": [],
    "none": [],
}

_FULL_PS = {
    "gitbug-java": {"precision": 0.9, "kappa": 0.7, "n": 10, "label_distribution": {"none": 8}}
}


def _make_skills_dir(tmp_path):
    """Create minimal skills_dir with spring-boot-endpoint and spring-jpa-entity."""
    sd = tmp_path / "skills"
    for name, desc in [
        ("spring-boot-endpoint", "Use for Spring Boot REST endpoints."),
        ("spring-jpa-entity", "Use for JPA/Hibernate entity mapping."),
    ]:
        d = sd / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {desc}\n---\n\n# {name}\n",
            encoding="utf-8",
        )
    return sd


def _make_corpus(tmp_path, failure_id="p_fail"):
    corp = tmp_path / "corpora" / "public"
    corp.mkdir(parents=True, exist_ok=True)
    cp = corp / "public.jsonl"
    rows = [
        {
            "prompt_id": failure_id,
            "prompt": "add a Spring endpoint",
            "predicted_skills": ["spring-annotation-fix"],
            "ground_truth_skills": ["spring-annotation-fix"],
            "source": {"dataset": "gitbug-java"},
        },
        {
            "prompt_id": "p_other",
            "prompt": "fix null check",
            "predicted_skills": ["none"],
            "ground_truth_skills": ["none"],
            "source": {"dataset": "gitbug-java"},
        },
    ]
    cp.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    (corp / "split.json").write_text(
        json.dumps({failure_id: "val", "p_other": "val"}),
        encoding="utf-8",
    )
    return cp


def _make_map(tmp_path):
    mp = tmp_path / "map.yaml"
    mp.write_text(yaml.safe_dump(_FULL_MAP), encoding="utf-8")
    return mp


# ---------------------------------------------------------------------------
# Test 1: build_ablation_table returns exactly 6 rows (full + 5 ablations)
# ---------------------------------------------------------------------------

def test_build_ablation_table_returns_six_rows(tmp_path, monkeypatch):
    """build_ablation_table returns one row per 6 configurations:
    full Setdrift config, 4 leave-one-out ablations, and arm-C floor.
    """
    from setdrift_eval.benchmark import arm_runner
    from setdrift_eval.optimizer.ablate import build_ablation_table

    sd = _make_skills_dir(tmp_path)
    cp = _make_corpus(tmp_path)
    mp = _make_map(tmp_path)

    # Mock run_arm to return predictable results
    def fake_run_arm(prompt, tools, **kw):
        if tools:
            return {"spring_boot_endpoint"}
        return set()

    monkeypatch.setattr(arm_runner, "run_arm", fake_run_arm)

    rows = build_ablation_table(
        failure_id="p_fail",
        corpus_path=cp,
        skills_dir=sd,
        map_path=mp,
    )

    assert len(rows) == 6, (
        f"Expected 6 rows (full + 5 ablations); got {len(rows)}: "
        + str([r.get("component") for r in rows])
    )


# ---------------------------------------------------------------------------
# Test 2: Each row has F1 + delta vs full-config
# ---------------------------------------------------------------------------

def test_build_ablation_table_row_has_f1_and_delta(tmp_path, monkeypatch):
    """Each row must have 'f1', 'delta_vs_full', and 'component' fields."""
    from setdrift_eval.benchmark import arm_runner
    from setdrift_eval.optimizer.ablate import build_ablation_table

    sd = _make_skills_dir(tmp_path)
    cp = _make_corpus(tmp_path)
    mp = _make_map(tmp_path)

    def fake_run_arm(prompt, tools, **kw):
        return {"spring_boot_endpoint"} if tools else set()

    monkeypatch.setattr(arm_runner, "run_arm", fake_run_arm)

    rows = build_ablation_table(
        failure_id="p_fail",
        corpus_path=cp,
        skills_dir=sd,
        map_path=mp,
    )

    for row in rows:
        assert "component" in row, f"Row missing 'component': {row}"
        assert "f1" in row, f"Row missing 'f1': {row}"
        assert "delta_vs_full" in row, f"Row missing 'delta_vs_full': {row}"
        assert "fired_intents" in row, f"Row missing 'fired_intents': {row}"
        assert isinstance(row["f1"], float), f"f1 must be float: {row}"


# ---------------------------------------------------------------------------
# Test 3: The largest-negative-delta row is flagged ROOT CAUSE
# ---------------------------------------------------------------------------

def test_build_ablation_table_flags_root_cause(tmp_path, monkeypatch):
    """The row with the largest negative delta_vs_full is flagged as ROOT CAUSE."""
    from setdrift_eval.benchmark import arm_runner
    from setdrift_eval.optimizer.ablate import build_ablation_table

    sd = _make_skills_dir(tmp_path)
    cp = _make_corpus(tmp_path)
    mp = _make_map(tmp_path)


    def fake_run_arm(prompt, tools, **kw):
        # Full config (2 tools): spring_boot_endpoint fires → correct prediction
        # Single-tool "spring_boot_endpoint only": still fires correctly
        # Single-tool "spring_jpa_entity only": does NOT fire spring_boot_endpoint → F1 drops
        # No tools: nothing fires
        tool_names = {t["name"] for t in tools}
        if "spring_boot_endpoint" in tool_names:
            return {"spring_boot_endpoint"}
        return set()

    monkeypatch.setattr(arm_runner, "run_arm", fake_run_arm)

    rows = build_ablation_table(
        failure_id="p_fail",
        corpus_path=cp,
        skills_dir=sd,
        map_path=mp,
    )

    # At least one row must be flagged as root cause
    root_cause_rows = [r for r in rows if r.get("root_cause") is True]
    assert len(root_cause_rows) >= 1, (
        "At least one row must be flagged root_cause=True (largest negative delta)"
    )

    # The root cause must have the most negative (or equal most negative) delta
    root_cause = root_cause_rows[0]
    most_negative_delta = min(r["delta_vs_full"] for r in rows)
    assert abs(root_cause["delta_vs_full"] - most_negative_delta) < 1e-9, (
        f"ROOT CAUSE row delta {root_cause['delta_vs_full']} != "
        f"most negative delta {most_negative_delta}"
    )


# ---------------------------------------------------------------------------
# Test 4: render_table produces required header columns
# ---------------------------------------------------------------------------

def test_render_table_contains_required_columns():
    """render_table output must contain the header columns from RESEARCH §Discretion 1."""
    from setdrift_eval.optimizer.ablate import render_table

    rows = [
        {
            "component": "None (full Setdrift config)",
            "fired_intents": ["spring-annotation-fix"],
            "f1": 1.0,
            "delta_vs_full": 0.0,
            "root_cause": False,
        },
        {
            "component": "spring-boot-endpoint desc→base",
            "fired_intents": [],
            "f1": 0.0,
            "delta_vs_full": -1.0,
            "root_cause": True,
        },
    ]

    table = render_table(rows)

    assert "Component removed" in table, f"Missing 'Component removed' column: {table[:200]}"
    assert "F1" in table, f"Missing 'F1' column: {table[:200]}"
    assert "Delta vs full-config" in table, f"Missing 'Delta vs full-config' column: {table[:200]}"


# ---------------------------------------------------------------------------
# Test 5: setdrift-eval ablate --help exits 0 and shows --failure-id
# ---------------------------------------------------------------------------

def test_ablate_cli_help_exits_zero_and_shows_failure_id(capsys):
    """setdrift-eval ablate --help exits 0 and shows --failure-id."""
    import sys
    from setdrift_eval.cli import main

    with pytest.raises(SystemExit) as exc_info:
        sys.argv = ["setdrift-eval", "ablate", "--help"]
        main()

    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "--failure-id" in out, f"--failure-id not in help output: {out}"


# ---------------------------------------------------------------------------
# Test 6: health --arm choices includes A
# ---------------------------------------------------------------------------

def test_health_arm_choices_includes_a(capsys):
    """health --arm must accept A (choices=["A","B","C"])."""
    import sys
    from setdrift_eval.cli import main

    with pytest.raises(SystemExit) as exc_info:
        sys.argv = ["setdrift-eval", "health", "--help"]
        main()

    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "A" in out, f"'A' not in health --help choices: {out}"


# ---------------------------------------------------------------------------
# Test 7: build_ablation_table full-config row has delta_vs_full == 0.0
# ---------------------------------------------------------------------------

def test_full_config_row_has_zero_delta(tmp_path, monkeypatch):
    """The 'None (full Setdrift config)' row must have delta_vs_full == 0.0 (it's the baseline)."""
    from setdrift_eval.benchmark import arm_runner
    from setdrift_eval.optimizer.ablate import build_ablation_table

    sd = _make_skills_dir(tmp_path)
    cp = _make_corpus(tmp_path)
    mp = _make_map(tmp_path)

    def fake_run_arm(prompt, tools, **kw):
        return {"spring_boot_endpoint"} if tools else set()

    monkeypatch.setattr(arm_runner, "run_arm", fake_run_arm)

    rows = build_ablation_table(
        failure_id="p_fail",
        corpus_path=cp,
        skills_dir=sd,
        map_path=mp,
    )

    full_rows = [r for r in rows if r.get("delta_vs_full") == 0.0 and "full" in r.get("component", "").lower()]
    assert len(full_rows) >= 1, (
        "Full-config row must have delta_vs_full=0.0; rows: "
        + str([(r["component"], r["delta_vs_full"]) for r in rows])
    )

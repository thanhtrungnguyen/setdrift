"""Arm-A scoring seam + val-only restriction tests (Plan 03-03 Task 1). Offline, no API.

Tests:
- arm="A" loads a non-empty toolset from skills_dir (Pitfall 3 fixed)
- arm="A" fires via run_arm (tool-based path), not run_arm_c
- val_only_prompts() returns only split=="val" rows, never "test"
"""
import json

import pytest
import yaml

from sica_eval.telemetry import scorer
from sica_eval.telemetry.scorer import ScorerError, run_health


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_FULL_MAP = {
    "spring-annotation-fix": ["spring_boot_endpoint"],
    "jpa-migration": ["spring_jpa_entity"],
    "dependency-bump": [],
    "null-check": [],
    "test-fixture-fix": [],
    "config-property": [],
    "import-fix": [],
    "none": [],
}

_FULL_PS = {
    "gitbug-java": {"precision": 0.9, "kappa": 0.7, "n": 10, "label_distribution": {"none": 8}}
}


def _make_skill_dir(tmp_path, skills):
    """Create a minimal skills_dir with one or more SKILL.md files."""
    sd = tmp_path / "skills"
    for name, description in skills.items():
        skill_dir = sd / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
            encoding="utf-8",
        )
    return sd


def _stage(tmp_path, monkeypatch, *, corpus_rows, splits, passed=True, per_source=None):
    corp = tmp_path / "corpora" / "public"
    corp.mkdir(parents=True, exist_ok=True)
    cp = corp / "public.jsonl"
    cp.write_text("\n".join(json.dumps(r) for r in corpus_rows) + "\n", encoding="utf-8")
    (corp / "split.json").write_text(json.dumps(splits), encoding="utf-8")

    mp = tmp_path / "map.yaml"
    mp.write_text(yaml.safe_dump(_FULL_MAP), encoding="utf-8")

    exp = tmp_path / "experiments"
    exp.mkdir(parents=True, exist_ok=True)
    report = {
        "passed": passed,
        "negatives_fraction": 0.5,
        "per_source": _FULL_PS if per_source is None else per_source,
    }
    (exp / "001-mining-precision.json").write_text(json.dumps(report), encoding="utf-8")

    return cp, mp, exp


def _row(pid, prompt, gt, source="gitbug-java"):
    return {
        "prompt_id": pid,
        "prompt": prompt,
        "predicted_skills": gt,
        "ground_truth_skills": gt,
        "source": {"dataset": source},
    }


# ---------------------------------------------------------------------------
# Test 1: arm="A" loads a non-empty toolset (Pitfall 3 — arm A must load tools)
# ---------------------------------------------------------------------------

def test_arm_a_loads_nonempty_toolset(tmp_path, monkeypatch):
    """arm="A" with a skills_dir containing one SKILL.md must load a non-empty toolset.

    Pitfall 3 (RESEARCH): arm=="A" was NOT handled before this plan — tools were []
    (the empty arm-C path). After the controlled fix, arm in ("A","B") loads tools.
    """
    from sica_eval.benchmark import arm_runner

    sd = _make_skill_dir(tmp_path, {"spring-boot-endpoint": "Use for Spring REST endpoints."})

    captured_tools: list = []

    def fake_run_arm(prompt, tools, **kw):
        captured_tools.extend(tools)
        return set()

    monkeypatch.setattr(arm_runner, "run_arm", fake_run_arm)
    monkeypatch.setattr(arm_runner, "run_arm_c", lambda prompt, **kw: set())

    rows = [_row("p1", "add endpoint", ["spring-annotation-fix"])]
    cp, mp, exp = _stage(tmp_path, monkeypatch, corpus_rows=rows, splits={"p1": "val"})

    run_health(cp, "A", map_path=mp, skills_dir=sd, experiments_dir=exp,
               cache_dir=tmp_path / "cache", timestamp="2026-06-01T00:00:00Z")

    # After the fix: tools must NOT be empty for arm A
    assert len(captured_tools) > 0, (
        "arm='A' should load tools from skills_dir (Pitfall 3 fix); got empty toolset"
    )


# ---------------------------------------------------------------------------
# Test 2: arm="A" uses run_arm (not run_arm_c)
# ---------------------------------------------------------------------------

def test_arm_a_fires_via_run_arm_not_run_arm_c(tmp_path, monkeypatch):
    """arm="A" must dispatch to run_arm (tool-path), not run_arm_c (empty floor)."""
    from sica_eval.benchmark import arm_runner

    sd = _make_skill_dir(tmp_path, {"spring-boot-endpoint": "Use for REST endpoints."})

    run_arm_called: list[bool] = []
    run_arm_c_called: list[bool] = []

    def fake_run_arm(prompt, tools, **kw):
        run_arm_called.append(True)
        return set()

    def fake_run_arm_c(prompt, **kw):
        run_arm_c_called.append(True)
        return set()

    monkeypatch.setattr(arm_runner, "run_arm", fake_run_arm)
    monkeypatch.setattr(arm_runner, "run_arm_c", fake_run_arm_c)

    rows = [_row("p1", "add endpoint", ["spring-annotation-fix"])]
    cp, mp, exp = _stage(tmp_path, monkeypatch, corpus_rows=rows, splits={"p1": "val"})

    run_health(cp, "A", map_path=mp, skills_dir=sd, experiments_dir=exp,
               cache_dir=tmp_path / "cache", timestamp="2026-06-01T00:00:00Z")

    assert run_arm_called, "arm='A' must call run_arm (tool-based path)"
    assert not run_arm_c_called, "arm='A' must NOT call run_arm_c (empty floor)"


# ---------------------------------------------------------------------------
# Test 3: val_only_prompts returns only split=="val" rows (never "test")
# ---------------------------------------------------------------------------

def test_val_only_prompts_excludes_test_split(tmp_path):
    """val_only_prompts() must return only split=='val' rows — never 'test' or 'train'."""
    from sica_eval.telemetry.scorer import val_only_prompts

    corp = tmp_path / "corpora" / "public"
    corp.mkdir(parents=True, exist_ok=True)
    cp = corp / "public.jsonl"

    rows = [
        {"prompt_id": "p_train", "prompt": "train prompt", "predicted_skills": []},
        {"prompt_id": "p_val1", "prompt": "val prompt 1", "predicted_skills": []},
        {"prompt_id": "p_val2", "prompt": "val prompt 2", "predicted_skills": []},
        {"prompt_id": "p_test", "prompt": "test prompt", "predicted_skills": []},
    ]
    cp.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    (corp / "split.json").write_text(
        json.dumps({"p_train": "train", "p_val1": "val", "p_val2": "val", "p_test": "test"}),
        encoding="utf-8",
    )

    result = val_only_prompts(cp)
    ids = {r["prompt_id"] for r in result}

    assert "p_val1" in ids, "p_val1 (val split) must be included"
    assert "p_val2" in ids, "p_val2 (val split) must be included"
    assert "p_test" not in ids, "p_test (test split) must be EXCLUDED — Goodhart firewall"
    assert "p_train" not in ids, "p_train (train split) must be EXCLUDED"
    assert len(result) == 2


# ---------------------------------------------------------------------------
# Test 4: arm="A" F1 is NOT the empty-toolset floor (verifies Pitfall 3 end-to-end)
# ---------------------------------------------------------------------------

def test_arm_a_f1_differs_from_arm_c_when_skill_fires(tmp_path, monkeypatch):
    """When a skill fires for arm A, its F1 must differ from the arm-C zero floor.

    This is the end-to-end Pitfall 3 test: if arm A loaded tools=[] (old behavior),
    it would return the same result as arm C (zero trigger on all prompts → same F1).
    After the fix, arm A loads real tools and can fire them.
    """
    from sica_eval.benchmark import arm_runner

    sd = _make_skill_dir(tmp_path, {"spring-boot-endpoint": "Use for REST endpoints."})

    def fake_run_arm(prompt, tools, **kw):
        # The skill fires for "endpoint" prompts when tools are provided
        if tools and "endpoint" in prompt:
            return {"spring_boot_endpoint"}
        return set()

    def fake_run_arm_c(prompt, **kw):
        return set()  # arm C: always empty

    monkeypatch.setattr(arm_runner, "run_arm", fake_run_arm)
    monkeypatch.setattr(arm_runner, "run_arm_c", fake_run_arm_c)

    rows = [
        _row("p1", "add endpoint", ["spring-annotation-fix"]),
        _row("p2", "fix null check", ["none"]),
    ]
    cp, mp, exp = _stage(tmp_path, monkeypatch, corpus_rows=rows,
                         splits={"p1": "val", "p2": "val"})

    result_a = run_health(cp, "A", map_path=mp, skills_dir=sd, experiments_dir=exp,
                          cache_dir=tmp_path / "cache", timestamp="2026-06-01T00:00:00Z")
    result_c = run_health(cp, "C", map_path=mp, skills_dir=sd, experiments_dir=exp,
                          cache_dir=tmp_path / "cache", timestamp="2026-06-01T00:00:00Z")

    # arm A with a firing skill must produce different (and better) F1 than arm C
    assert result_a.macro_f1_mean != result_c.macro_f1_mean, (
        f"arm A F1 ({result_a.macro_f1_mean:.4f}) must differ from arm C floor "
        f"({result_c.macro_f1_mean:.4f}) when a skill fires — Pitfall 3 not fixed"
    )
    assert result_a.macro_f1_mean > result_c.macro_f1_mean, (
        "arm A with a firing skill should score higher than arm C zero floor"
    )

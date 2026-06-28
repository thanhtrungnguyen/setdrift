"""run_health + `setdrift-eval health` tests (Plan 02-05 Task 2). Offline, no API."""

import json

import pytest
import yaml

from setdrift_eval.telemetry import scorer
from setdrift_eval.telemetry.scorer import ScorerError, run_health

_FULL_MAP = {
    "spring-annotation-fix": ["spring_boot_endpoint"],
    "jpa-migration": [],
    "dependency-bump": [],
    "null-check": [],
    "test-fixture-fix": [],
    "config-property": [],
    "import-fix": [],
    "none": [],
}


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

    from setdrift_eval.benchmark import arm_runner

    monkeypatch.setattr(
        arm_runner,
        "load_skill_tools",
        lambda d: [{"name": "spring_boot_endpoint", "description": "d", "input_schema": {}}],
    )
    seen: list[str] = []

    def fake_run_arm(prompt, tools, **kw):
        seen.append(prompt)
        return {"spring_boot_endpoint"} if "endpoint" in prompt else set()

    monkeypatch.setattr(arm_runner, "run_arm", fake_run_arm)
    monkeypatch.setattr(
        arm_runner, "run_arm_c", lambda prompt, **kw: (seen.append(prompt), set())[1]
    )
    return cp, mp, exp, seen


_FULL_PS = {
    "gitbug-java": {"precision": 0.9, "kappa": 0.7, "n": 10, "label_distribution": {"none": 8}}
}


def _row(pid, prompt, gt, source="gitbug-java"):
    return {
        "prompt_id": pid,
        "prompt": prompt,
        "predicted_skills": gt,
        "ground_truth_skills": gt,
        "source": {"dataset": source},
    }


def test_gate_guard_raises_without_passed_report(tmp_path, monkeypatch):
    cp, mp, exp, _ = _stage(
        tmp_path,
        monkeypatch,
        corpus_rows=[_row("p1", "add endpoint", ["spring-annotation-fix"])],
        splits={"p1": "test"},
        passed=False,  # gate not cleared
    )
    with pytest.raises(ScorerError, match="gate has not cleared"):
        run_health(
            cp,
            "B",
            map_path=mp,
            skills_dir=tmp_path,
            experiments_dir=exp,
            cache_dir=tmp_path / "cache",
        )


def test_per_source_kappa_failloud_on_empty(tmp_path, monkeypatch):
    cp, mp, exp, _ = _stage(
        tmp_path,
        monkeypatch,
        corpus_rows=[_row("p1", "add endpoint", ["spring-annotation-fix"])],
        splits={"p1": "test"},
        passed=True,
        per_source={},  # passed but no per-source metrics
    )
    with pytest.raises(ScorerError, match="per_source_kappa unavailable"):
        run_health(
            cp,
            "B",
            map_path=mp,
            skills_dir=tmp_path,
            experiments_dir=exp,
            cache_dir=tmp_path / "cache",
        )


def test_holdout_excluded_not_negative(tmp_path, monkeypatch):
    rows = [
        _row("p1", "add endpoint", ["spring-annotation-fix"]),  # scored positive
        _row("p2", "fix null bug", ["null-check"]),  # null-check maps to [] → holdout
        _row("p3", "trivial", ["none"]),  # negative (scored, all-zero row)
    ]
    cp, mp, exp, _ = _stage(
        tmp_path, monkeypatch, corpus_rows=rows, splits={"p1": "val", "p2": "val", "p3": "test"}
    )
    run_health(
        cp,
        "B",
        map_path=mp,
        skills_dir=tmp_path,
        experiments_dir=exp,
        cache_dir=tmp_path / "cache",
        timestamp="2026-06-01T00:00:00Z",
    )
    manifest = json.loads(next(exp.glob("*-results.json")).read_text(encoding="utf-8"))
    assert manifest["n_prompts_out_of_coverage"] == 1  # p2 held out
    assert manifest["n_prompts_scored"] == 2  # p1 + p3 (NOT p2; p3 negative kept)


def test_scores_val_test_only_not_train(tmp_path, monkeypatch):
    rows = [
        _row("p_train", "add endpoint train", ["spring-annotation-fix"]),
        _row("p_val", "add endpoint val", ["spring-annotation-fix"]),
    ]
    cp, mp, exp, seen = _stage(
        tmp_path, monkeypatch, corpus_rows=rows, splits={"p_train": "train", "p_val": "val"}
    )
    run_health(
        cp,
        "B",
        map_path=mp,
        skills_dir=tmp_path,
        experiments_dir=exp,
        cache_dir=tmp_path / "cache",
        timestamp="2026-06-01T00:00:00Z",
    )
    assert any("val" in s for s in seen)
    assert not any("train" in s for s in seen)  # train partition never scored


def test_arm_c_floor_and_results_fields(tmp_path, monkeypatch):
    rows = [
        _row("p1", "add endpoint", ["spring-annotation-fix"]),
        _row("p2", "trivial", ["none"]),
    ]
    cp, mp, exp, _ = _stage(
        tmp_path, monkeypatch, corpus_rows=rows, splits={"p1": "val", "p2": "test"}
    )
    result = run_health(
        cp,
        "C",
        map_path=mp,
        skills_dir=tmp_path,
        experiments_dir=exp,
        cache_dir=tmp_path / "cache",
        timestamp="2026-06-01T00:00:00Z",
    )
    assert result.arm == "C"
    manifest = json.loads(next(exp.glob("*-results.json")).read_text(encoding="utf-8"))
    for field in (
        "intent_map_sha256",
        "split_hash",
        "macro_f1_runs",
        "bootstrap_ci_low",
        "token_cost_total",
        "per_source_kappa",
        "per_source_label_distribution",
        "coverage_pct",
        "n_prompts_out_of_coverage",
    ):
        assert field in manifest
    assert len(manifest["macro_f1_runs"]) == 5
    assert manifest["per_source_kappa"]  # non-empty (REQ-MEASURE-02 populated)
    text = next(exp.glob("*-results.json")).read_text(encoding="utf-8")
    assert "add endpoint" not in text and "trivial" not in text  # data wall: no prompt text


def test_cli_arm_required_and_prints(tmp_path, monkeypatch, capsys):
    import sys

    from setdrift_eval.cli import main

    cp, mp, exp, _ = _stage(
        tmp_path,
        monkeypatch,
        corpus_rows=[
            _row("p1", "add endpoint", ["spring-annotation-fix"]),
            _row("p2", "x", ["none"]),
        ],
        splits={"p1": "val", "p2": "test"},
    )
    # --arm is required
    with pytest.raises(SystemExit):
        monkeypatch.setattr(sys, "argv", ["setdrift-eval", "health", "--corpus", "public"])
        main()
    # full invocation prints the headline line
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "setdrift-eval",
            "health",
            "--corpus",
            "public",
            "--arm",
            "B",
            "--corpus-path",
            str(cp),
            "--map",
            str(mp),
            "--skills-dir",
            str(tmp_path),
            "--experiments-dir",
            str(exp),
        ],
    )
    assert main() == 0
    out = capsys.readouterr().out
    assert "arm=B" in out and "macro_f1=" in out

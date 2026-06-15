"""GEPA/MIPROv2 wrapper tests (Plan 03-01, REQ-LOOP-01/02). Offline, no API calls.

Covers the Wave-1 deliverables: the one-flag GEPA<->MIPROv2 swap, the proposals-as-data
SkillProposal, the structural no-write/no-forbidden-import fence, the anti-overfit
CONSTRAINT injection, the cardinality penalty, the >=50 adversarial-negative floor, and
the post-optimization linter (including propose() rejecting a Goodhart-overfit candidate).
The live GEPA compile (_run_optimizer) is the 03-06 integration path and is monkeypatched
here.
"""
from pathlib import Path

import dspy
import pytest

from setdrift_eval.optimizer import gepa_wrapper as gw

_FROZEN_MAP = {"spring-annotation-fix": ["spring_boot_endpoint"], "jpa-migration": [], "none": []}


# --- Task 2: backend swap (REQ-LOOP-01) -------------------------------------------
def test_build_optimizer_default_is_gepa(monkeypatch):
    monkeypatch.delenv("SICA_OPTIMIZER", raising=False)
    opt = gw.build_optimizer(lambda *a, **k: 0.0)
    assert isinstance(opt, dspy.GEPA)


def test_build_optimizer_miprov2_on_flag(monkeypatch):
    monkeypatch.setenv("SICA_OPTIMIZER", "miprov2")
    opt = gw.build_optimizer(lambda *a, **k: 0.0)
    assert isinstance(opt, dspy.MIPROv2)


# --- Task 2: proposals-as-data --------------------------------------------------
def test_skill_proposal_validates_and_forbids_extra():
    p = gw.SkillProposal(
        target_path=Path("plugin/skills/x/SKILL.md"),
        new_content="desc",
        skill_name="x",
        cycle_id="c",
    )
    assert p.skill_name == "x" and p.target_path.as_posix().startswith("plugin/")
    with pytest.raises(Exception):  # pydantic ValidationError on extra field
        gw.SkillProposal(
            target_path=Path("plugin/skills/x/SKILL.md"),
            new_content="desc",
            skill_name="x",
            cycle_id="c",
            sneaky="payload",
        )


# --- Task 2: structural no-write / no-forbidden-import fence (D-46) ---------------
def test_wrapper_module_has_no_write_capability():
    src = Path(gw.__file__).read_text(encoding="utf-8")
    non_comment = "\n".join(
        ln for ln in src.splitlines() if not ln.lstrip().startswith("#")
    )
    assert "write_text" not in non_comment
    assert "open(" not in non_comment
    assert "import setdrift_eval.optimizer.orchestrator" not in non_comment
    assert "import setdrift_eval.optimizer.applier" not in non_comment
    assert "data/" not in src  # no storage-path reference anywhere (incl. comments)


# --- Task 2: anti-overfit CONSTRAINT literal injection ---------------------------
def test_anti_overfit_constraint_literal_present():
    assert "CONSTRAINT" in gw.ANTI_OVERFIT_CONSTRAINT
    assert "CamelCase" in gw.ANTI_OVERFIT_CONSTRAINT


def test_metric_feedback_injects_constraint_and_scores():
    metric = gw.build_metric_fn([], _FROZEN_MAP)

    class _Gold:
        gt_intents = {"spring-annotation-fix"}

    class _Pred:
        fired_intents = {"spring-annotation-fix"}

    out = metric(_Gold(), _Pred())
    assert "CONSTRAINT" in out.feedback
    assert out.score == 1.0  # exact match within the scored space


# --- Task 3: cardinality penalty (D-45) ------------------------------------------
def test_cardinality_penalty_over_firing_scores_lower_than_exact():
    gt = {"spring-annotation-fix"}
    exact = gw.score_prediction({"spring-annotation-fix"}, gt)
    over = gw.score_prediction({"spring-annotation-fix", "jpa-migration"}, gt)
    assert exact == 1.0
    assert over < exact


def test_cardinality_penalty_punishes_firing_on_a_negative():
    exact_negative = gw.score_prediction(set(), set())
    over_fired = gw.score_prediction({"spring-annotation-fix"}, set())
    assert exact_negative == 1.0
    assert over_fired < exact_negative


# --- Task 3: >=50 adversarial-negative floor -------------------------------------
def _examples(n_neg: int, n_pos: int) -> list[dict]:
    exs = [{"prompt": f"neg-{i}", "ground_truth_skills": []} for i in range(n_neg)]
    exs += [
        {"prompt": f"pos-{i}", "ground_truth_skills": ["spring_boot_endpoint"]}
        for i in range(n_pos)
    ]
    return exs


def test_trainset_meets_negative_floor():
    trainset = gw.build_optimizer_trainset(_examples(50, 5))
    negatives = sum(1 for e in trainset if not e.gt_intents)
    assert negatives >= gw.MIN_ADVERSARIAL_NEGATIVES


def test_trainset_below_floor_raises():
    # 0 corpus negatives + the ~27 hand-authored constructed negatives < 50 -> fail loud.
    with pytest.raises(gw.OptimizerError):
        gw.build_optimizer_trainset(_examples(0, 5))


# --- Task 3: post-optimization linter (Goodhart reject) --------------------------
def test_lint_flags_camelcase():
    assert "RestController" in gw.post_opt_lint("uses RestController here", set())


def test_lint_flags_snake_case():
    assert "find_by_id" in gw.post_opt_lint("calls find_by_id now", set())


def test_lint_flags_off_allowlist_proper_noun():
    assert "Kafka" in gw.post_opt_lint("integrates with Kafka now", set())


def test_lint_allowlist_suppresses_proper_noun():
    assert gw.post_opt_lint("integrates with Kafka now", {"Kafka"}) == []


def test_lint_passes_clean_description():
    desc = "use when adding spring annotations to a service; triggers on validation requests"
    assert gw.post_opt_lint(desc, set()) == []


def test_propose_rejects_linter_failing_candidate(monkeypatch, tmp_path):
    skill = tmp_path / "spring-x" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: spring-x\ndescription: use when adding spring annotations\n---\n# body\n",
        encoding="utf-8",
    )
    # Monkeypatch the live integration seam to return a Goodhart-overfit candidate.
    monkeypatch.setattr(gw, "_run_optimizer", lambda *a, **k: "Use RestController and find_by_id")
    with pytest.raises(gw.OptimizerError):
        gw.propose("spring-x", skill, [], _FROZEN_MAP, "cycle-1")

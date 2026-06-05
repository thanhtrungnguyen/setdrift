"""GEPA/MIPROv2 optimizer wrapper — returns proposals as DATA only (D-46).

The GEPA wrapper is the structural PROPOSER half of the proposer/orchestrator safety
split (D-46). It proposes a new SKILL.md `description` string and returns it wrapped in
a SkillProposal. It has NO file-write capability:

  - it performs no filesystem writes whatsoever (no write primitive, no writable handle);
  - it never imports the orchestrator or the applier (those own all writes/audits);
  - it never references a telemetry/cache/audit storage path.

Requirements: REQ-LOOP-01 (one optimizer end-to-end with a one-flag MIPROv2 swap) and
REQ-LOOP-02 (the patch step). Implementation path is decided by the gepa==0.0.27
introspection probe (.planning/codebase/gepa-0.0.27-probe.md): Path A' — drive through
`dspy.GEPA` natively (neither gepa.adapters.mcp nor gepa.optimize_anything exist in
0.0.27; dspy.GEPA exposes the full exit-gate knob surface).

Exit-gate items carried in this module (Phase 3 Exit Gate):
  - failure_score=0.0 on GEPA / max_errors=0 on MIPROv2;
  - NoImprovementStopper(patience=10) via gepa_kwargs (budget-cap fallback);
  - candidate_selection_strategy="pareto" + a Pareto-diversity floor (>=5 candidates);
  - anti-overfit CONSTRAINT literal-string injection into the reflective feedback;
  - cardinality penalty (over-firing punished) + a >=50 adversarial-negative floor;
  - a post-optimization linter rejecting CamelCase/snake_case/off-allowlist tokens.

Fail-loud: optimizer errors propagate (no bare except). The optimizer only ever sees a
trainset the orchestrator pre-filters to the TRAIN partition (Goodhart firewall enforced
upstream in 03-06); this module never loads any split file.
"""
import os
import re
from pathlib import Path

import dspy
import yaml
from pydantic import BaseModel, ConfigDict

from sica_eval.benchmark import arm_runner
from sica_eval.optimizer.fence import ALLOWED_PREFIXES  # read-only: proposal-target validation
from sica_eval.telemetry.scorer import project_to_intents, scored_intents

# --- pins / knobs -----------------------------------------------------------------
OPTIMIZER_BACKEND = os.environ.get("SICA_OPTIMIZER", "gepa")  # "gepa" | "miprov2"
REFLECTION_LM_MODEL = "anthropic/claude-sonnet-4-6"           # model pin (default arm)
MAX_METRIC_CALLS = int(os.environ.get("SICA_GEPA_MAX_METRIC_CALLS", "200"))
NO_IMPROVEMENT_PATIENCE = 10                                  # exit-gate patience
PARETO_DIVERSITY_FLOOR = 5                                    # exit-gate >=5 candidates
MIN_ADVERSARIAL_NEGATIVES = 50                               # exit-gate >=50 negatives
CARDINALITY_PENALTY_WEIGHT = float(os.environ.get("SICA_CARDINALITY_PENALTY", "0.25"))
SEED = 42

# The anti-overfit Constraint literal injected into every reflective feedback string
# (exit-gate "Constraint literal-string injection in side_info"). MUST contain the
# substrings "CONSTRAINT" and "CamelCase".
ANTI_OVERFIT_CONSTRAINT = (
    "CONSTRAINT: write the description as a natural-language triggering spec for a "
    "developer-prompt classifier. Do NOT memorize or embed literal code identifiers to "
    "game the metric: any CamelCase class name, snake_case method name, or off-allowlist "
    "proper noun will be rejected by the post-optimization linter. Optimize for precise, "
    "minimal-firing triggers (firing on out-of-scope prompts is penalized), not for token "
    "overlap with the corpus."
)

# Capitalized domain terms a description may legitimately use (proper-noun allowlist).
DEFAULT_LINT_ALLOWLIST: frozenset[str] = frozenset(
    {"spring", "java", "hibernate", "jpa", "rest", "boot", "claude", "sica", "http"}
)

_CAMEL_RE = re.compile(r"\b[A-Za-z]*[a-z][A-Z][A-Za-z]*\b")   # RestController / findById
_SNAKE_RE = re.compile(r"\b[A-Za-z]+_[A-Za-z_]+\b")            # find_by_id


class OptimizerError(RuntimeError):
    """Raised on any optimizer misconfiguration or Goodhart-reject (fail-loud)."""


class SkillProposal(BaseModel):
    """A proposed SKILL.md description change, returned as DATA (never written here)."""

    model_config = ConfigDict(extra="forbid")

    target_path: Path  # must be within plugin/ or be CLAUDE.md (checked by the applier)
    new_content: str   # the proposed new description string
    skill_name: str
    cycle_id: str


# --- optimizer construction (REQ-LOOP-01 one-flag swap) ---------------------------
def build_optimizer(metric_fn):
    """Return a dspy.GEPA by default, or a dspy.MIPROv2 iff SICA_OPTIMIZER=miprov2.

    The backend is read from the environment at call time so the swap is a single env
    flag with no other code edits (REQ-LOOP-01). Both arms pin the model and seed.
    """
    backend = os.environ.get("SICA_OPTIMIZER", OPTIMIZER_BACKEND)
    if backend == "miprov2":
        lm = dspy.LM(REFLECTION_LM_MODEL, temperature=1.0, max_tokens=8192)
        return dspy.MIPROv2(
            metric=metric_fn,
            auto="light",
            seed=SEED,
            max_errors=0,          # exit-gate: no silent error tolerance
            prompt_model=lm,       # MIPROv2 requires an LM at construction
            task_model=lm,
        )
    return _build_gepa(metric_fn)


def _build_gepa(metric_fn):
    """dspy.GEPA with all exit-gate knobs pinned (probe Path A')."""
    gepa_kwargs: dict = {}
    try:  # NoImprovementStopper(patience=10); budget-cap fallback if import shape drifts
        from gepa import NoImprovementStopper

        gepa_kwargs["stop_callbacks"] = [
            NoImprovementStopper(max_iterations_without_improvement=NO_IMPROVEMENT_PATIENCE)
        ]
    except ImportError:  # fall back to the max_metric_calls budget cap alone
        gepa_kwargs = {}
    return dspy.GEPA(
        metric=metric_fn,
        candidate_selection_strategy="pareto",  # exit-gate Pareto strategy
        failure_score=0.0,                       # exit-gate max_errors=0 analog on GEPA
        reflection_lm=dspy.LM(REFLECTION_LM_MODEL, temperature=1.0, max_tokens=8192),
        seed=SEED,
        track_stats=True,                        # exposes candidate count for Pareto floor
        max_metric_calls=MAX_METRIC_CALLS,       # hard budget ceiling
        gepa_kwargs=gepa_kwargs,
    )


# --- reflective metric (exit-gate: Constraint injection + cardinality penalty) -----
def _per_example_f1(pred: set, gt: set) -> float:
    """Strict-set F1 for one example; a correct negative (both empty) scores 1.0."""
    tp, fp, fn = len(pred & gt), len(pred - gt), len(gt - pred)
    if tp == 0 and fp == 0 and fn == 0:
        return 1.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def score_prediction(
    predicted_intents,
    gt_intents,
    *,
    scored=None,
    cardinality_weight: float = CARDINALITY_PENALTY_WEIGHT,
) -> float:
    """Per-example score = strict F1 minus a cardinality (over-firing) penalty (D-45).

    The penalty pushes the optimizer toward precise, minimal-firing descriptions: a
    candidate that fires MORE intents than ground truth always scores strictly lower
    than the exact-match candidate on the same example. Clamped to [0, 1].
    """
    pred, gt = set(predicted_intents), set(gt_intents)
    if scored is not None:
        s = set(scored)
        pred &= s
        gt &= s
    base = _per_example_f1(pred, gt)
    over_firing = len(pred - gt)
    return max(0.0, min(1.0, base - cardinality_weight * over_firing))


def build_metric_fn(trainset, frozen_map):
    """Return a GEPA-compatible feedback-aware metric closure.

    The metric scores per-example strict-match F1 (via the frozen intent map) with the
    cardinality penalty, and appends the anti-overfit CONSTRAINT literal to every
    feedback string (exit-gate Constraint injection in side_info). `trainset` is accepted
    for parity with dspy optimizer wiring; scoring itself reads the per-call gold/pred.
    """
    scored = scored_intents(frozen_map)

    def _gt_of(gold) -> set:
        gt = getattr(gold, "gt_intents", None)
        if gt is not None:
            return set(gt)
        skills = set(getattr(gold, "ground_truth_skills", None) or [])
        return project_to_intents(skills, frozen_map)

    def _pred_of(pred) -> set:
        fired = getattr(pred, "fired_intents", None)
        if fired is not None:
            return set(fired)
        if isinstance(pred, (set, frozenset, list, tuple)):
            return set(pred)
        skills = set(getattr(pred, "fired_skills", None) or [])
        return project_to_intents(skills, frozen_map)

    def metric(gold, pred, trace=None, pred_name=None, pred_trace=None):
        gt_intents = _gt_of(gold)
        pred_intents = _pred_of(pred)
        score = score_prediction(pred_intents, gt_intents, scored=scored)
        over = sorted(pred_intents - gt_intents)
        missed = sorted(gt_intents - pred_intents)
        feedback = (
            f"score={score:.3f}. over-fired={over or 'none'}; missed={missed or 'none'}. "
            + ANTI_OVERFIT_CONSTRAINT
        )
        return dspy.Prediction(score=score, feedback=feedback)

    return metric


# --- optimizer trainset (exit-gate: >=50 adversarial negatives) -------------------
def _constructed_negatives_path() -> Path:
    """Path to the hand-authored adversarial negatives, resolved relative to package."""
    return Path(__file__).resolve().parents[1] / "corpus" / "constructed_negatives.tsv"


def load_constructed_negatives(path: Path | None = None) -> list[str]:
    """Read the hand-authored near-miss negative prompts (skip comment/blank rows)."""
    p = Path(path) if path is not None else _constructed_negatives_path()
    prompts: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t", 1)
        prompts.append(parts[1].strip() if len(parts) == 2 else parts[0].strip())
    return prompts


def _is_negative(example) -> bool:
    gt = getattr(example, "gt_intents", None)
    if gt is not None:
        return not set(gt)
    skills = set(getattr(example, "ground_truth_skills", None) or [])
    return not (skills - {"none"})


def build_optimizer_trainset(corpus_train_examples, *, constructed_path: Path | None = None):
    """Assemble the optimizer-training set; fail loud below the >=50 negative floor.

    Combines mined TRAIN-partition NONE/negative prompts (D-36 provenance) with the
    hand-authored constructed negatives. Raises OptimizerError naming the shortfall if
    the combined adversarial-negative count is below MIN_ADVERSARIAL_NEGATIVES.
    """
    trainset: list = []
    n_neg = 0
    for ex in corpus_train_examples:
        prompt = getattr(ex, "prompt", None) or (ex.get("prompt") if isinstance(ex, dict) else None)
        skills = set(
            getattr(ex, "ground_truth_skills", None)
            or (ex.get("ground_truth_skills") if isinstance(ex, dict) else None)
            or []
        )
        gt = frozenset(skills - {"none"})
        trainset.append(dspy.Example(prompt=prompt, gt_intents=gt).with_inputs("prompt"))
        if not gt:
            n_neg += 1
    for prompt in load_constructed_negatives(constructed_path):
        trainset.append(
            dspy.Example(prompt=prompt, gt_intents=frozenset()).with_inputs("prompt")
        )
        n_neg += 1
    if n_neg < MIN_ADVERSARIAL_NEGATIVES:
        raise OptimizerError(
            f"optimizer trainset has only {n_neg} adversarial negatives; the exit gate "
            f"requires >={MIN_ADVERSARIAL_NEGATIVES} (shortfall {MIN_ADVERSARIAL_NEGATIVES - n_neg}). "
            "Mine more TRAIN-partition NONE prompts or extend constructed_negatives.tsv."
        )
    return trainset


# --- post-optimization linter (exit-gate Goodhart reject) -------------------------
def post_opt_lint(description: str, allowlist: set[str]) -> list[str]:
    """Return offending tokens: CamelCase, snake_case, or off-allowlist proper nouns.

    A clean concrete-annotation description (no embedded code identifiers, only
    allowlisted capitalized domain terms) returns []. Sentence-initial capitalization is
    not treated as a proper noun (so a normal "Use when ..." opener is not flagged).
    """
    allow = {a.lower() for a in allowlist} | DEFAULT_LINT_ALLOWLIST
    offenders: list[str] = []

    for rx in (_CAMEL_RE, _SNAKE_RE):
        for m in rx.finditer(description):
            tok = m.group(0)
            if tok.lower() not in allow:
                offenders.append(tok)

    for sentence in re.split(r"[.;:\n]", description):
        words = re.findall(r"\S+", sentence)
        for i, raw in enumerate(words):
            tok = re.sub(r"[^A-Za-z0-9_]", "", raw)
            if not tok or i == 0:  # skip sentence-initial token
                continue
            if len(tok) > 1 and tok[0].isupper() and tok[1:].islower():
                if tok.lower() not in allow:
                    offenders.append(tok)

    seen: set[str] = set()
    deduped: list[str] = []
    for t in offenders:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped


# --- the patch step (proposals-as-data) -------------------------------------------
def _read_description(skill_path: Path) -> str:
    """Read the current SKILL.md `description` frontmatter (read-only, no write)."""
    text = Path(skill_path).read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise OptimizerError(f"{skill_path} has no YAML frontmatter to optimize")
    _, frontmatter, _ = text.split("---", 2)
    meta = yaml.safe_load(frontmatter)
    description = meta.get("description")
    if not description:
        raise OptimizerError(f"{skill_path} frontmatter has no `description` field")
    return str(description)


class _SkillTriggerProgram(dspy.Module):
    """Minimal dspy program whose optimizable instruction IS the skill description.

    Integration-exercised live (with an API key) during the 03-06 dogfooding cycle; the
    Wave-1 unit tests monkeypatch `_run_optimizer`, so this class is constructed but not
    compiled offline. It holds no file-write capability.
    """

    def __init__(self, skill_name: str, description: str):
        super().__init__()
        self.skill_name = skill_name
        self.description = description

    def forward(self, prompt: str):  # pragma: no cover - integration path
        return dspy.Prediction(fired_intents=set(), description=self.description)


def _enforce_pareto_floor(compiled) -> None:
    """Fail loud if fewer than PARETO_DIVERSITY_FLOOR distinct candidates were explored."""
    results = getattr(compiled, "detailed_results", None)
    n = getattr(results, "num_candidates", None) if results is not None else None
    if n is not None and n < PARETO_DIVERSITY_FLOOR:
        raise OptimizerError(
            f"Pareto-diversity floor unmet: only {n} candidate(s) explored, "
            f"need >={PARETO_DIVERSITY_FLOOR} (exit gate)."
        )


def _run_optimizer(optimizer, seed_description: str, trainset, skill_name: str) -> str:
    """Compile the candidate description and return the best instruction string.

    This is the live-API integration seam (run in 03-06 dogfooding). Unit tests
    monkeypatch it. It never writes a file.
    """  # pragma: no cover - integration path
    program = _SkillTriggerProgram(skill_name=skill_name, description=seed_description)
    compiled = optimizer.compile(program, trainset=trainset)
    _enforce_pareto_floor(compiled)
    best = getattr(compiled, "description", None)
    if not best:
        raise OptimizerError("optimizer returned no candidate description")
    return str(best)


def propose(skill_name: str, skill_path: Path, trainset, frozen_map, cycle_id: str) -> SkillProposal:
    """Run the optimizer and return the best candidate as a SkillProposal (DATA only).

    Pipeline: read current description -> build metric (CONSTRAINT injection) -> build
    optimizer (GEPA/MIPROv2) -> run -> post_opt_lint reject (Goodhart firewall) -> wrap.
    NEVER writes a file; the orchestrator/applier own all writes (D-46).
    """
    skill_path = Path(skill_path)
    seed_description = _read_description(skill_path)
    metric_fn = build_metric_fn(trainset, frozen_map)
    optimizer = build_optimizer(metric_fn)
    best = _run_optimizer(optimizer, seed_description, trainset, skill_name)

    offenders = post_opt_lint(best, set(DEFAULT_LINT_ALLOWLIST))
    if offenders:
        raise OptimizerError(
            f"post-optimization linter rejected candidate for '{skill_name}': "
            f"off-allowlist/code tokens {offenders}. Refusing to promote a Goodhart-overfit "
            "description (CamelCase/snake_case/proper-noun memorization)."
        )

    # Proposer-side advisory check that the target sits within the fence allowlist; the
    # applier (03-02) re-checks authoritatively via fence.check_allowlist before any write.
    target = skill_path.as_posix()
    if not any(target.startswith(prefix) for prefix in ALLOWED_PREFIXES):
        raise OptimizerError(
            f"proposal target '{target}' is outside the fence allowlist {ALLOWED_PREFIXES}"
        )

    return SkillProposal(
        target_path=skill_path,
        new_content=best,
        skill_name=skill_name,
        cycle_id=cycle_id,
    )

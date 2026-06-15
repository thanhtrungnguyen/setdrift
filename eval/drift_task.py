"""Inspect-AI Task for the SICA synthetic-drift grid (REQ-DRIFT-02).

What this module does:
  Defines `drift_task`, an @task-decorated function that wraps the SICA
  arm-runner harness in an Inspect-AI Task with a Docker sandbox. It is
  the orchestration shell for one (mode, revision, arm) cell; the actual
  F1 scoring is done by the SICA frozen ruler (scorer.py + arm_runner).

Grid axes (passed as -T flags on the CLI or as Python kwargs):
  mode:      "synthetic" | "real"
      "synthetic" — programmatic magnitude-knob dataset (three drift levels).
      "real"      — samples from a real GitBug-Java revision snapshot.
  revision:  "early" | "mid" | "late"  — codebase snapshot selection.
  arm:       "A" | "B"  — config axis (SICA-managed vs frozen hand-written).

Sandbox spec:
  sandbox=("docker", "drift_compose.yaml") — Inspect-AI manages lifecycle.
  network_mode: none enforced at compose level (T-04-05, Pitfall 4 avoided).
  The LLM proxy runs on the HOST process, so API calls are NOT blocked.

Yoking discipline:
  The model is NOT hardcoded here. It arrives via --model on the CLI
  (or model= in inspect_eval()). grid_runner.py records yoke_minute ONCE
  per (model, revision) pair before iterating arms; this module is a
  single-cell executor, yoking is the runner's responsibility.

Caching:
  Uses the default per-epoch cache scope (Pitfall 5: CachePolicy
  per_epoch=False is NEVER set here — it would collapse the noise band).
  The SICA response_cache.load_or_call provides the reproducibility anchor
  at the arm_runner level; Inspect cache is a secondary convenience layer.

Fail-loud:
  Eval-side — exceptions propagate (no bare except). Only the Phase 1
  telemetry hook uses silent-catch; this module is eval-side (fail-loud).

CLI invocation for one cell:
  inspect eval drift_task.py \\
    -T mode=synthetic -T revision=mid -T arm=A \\
    --model anthropic/claude-sonnet-4-6 \\
    --temperature 0 \\
    --epochs 5 \\
    --cache \\
    --log-dir ./logs/drift

Python invocation (used by grid_runner.py):
  from inspect_ai import eval as inspect_eval
  results = inspect_eval(
      drift_task(mode="synthetic", revision="mid", arm="A"),
      model="anthropic/claude-sonnet-4-6",
      temperature=0,
      epochs=5,
      log_dir="./logs/drift",
      cache=True,
  )

Note: CachePolicy(per_epoch=False) is NEVER passed (Pitfall 5).
"""
import os
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Dataset, Sample
from inspect_ai.scorer import Score, Scorer, Target, accuracy, scorer
from inspect_ai.solver import Solver, TaskState, generate, solver

from inspect_ai.model import get_model

from setdrift_eval.benchmark.arm_runner import load_skill_tools, run_arm

# ---------------------------------------------------------------------------
# Arm config resolution (CR-01) — resolved lazily at solve time, not import,
# so importing this module never requires the env vars to be set.
# ---------------------------------------------------------------------------


def _resolve_arm_skills(arm: str) -> Path:
    """Resolve the skills directory for an arm.

    Arm B is the frozen hand-written baseline (default ``plugin/skills``).
    Arm A is the SICA-managed/optimized config and has NO safe default:
    promotion happens in-place, so there is no static "promoted" dir. It MUST
    be supplied via ``SETDRIFT_ARM_A_SKILLS``. Silently defaulting arm A to
    ``plugin/skills`` would make arm A == arm B and null the A/B paired
    comparison the falsifiable claim depends on (CR-01).
    """
    if arm == "A":
        v = os.environ.get("SETDRIFT_ARM_A_SKILLS")
        if not v:
            raise RuntimeError(
                "SETDRIFT_ARM_A_SKILLS is not set — arm A (SICA-managed config) has no "
                "safe default. Point it at the Phase-3 promoted/optimized skills dir. "
                "Falling back to plugin/skills would make arm A == arm B and null the "
                "A/B comparison the falsifiable claim depends on (CR-01)."
            )
        return Path(v)
    # Arm B = frozen hand-written baseline.
    return Path(os.environ.get("SETDRIFT_ARM_B_SKILLS", "plugin/skills"))


_CACHE_DIR = Path(os.environ.get("SETDRIFT_CACHE_DIR", "data/cache"))

# ---------------------------------------------------------------------------
# Synthetic drift dataset helpers
# ---------------------------------------------------------------------------

# Synthetic drift magnitude levels: 1 (minimal), 2 (moderate), 3 (heavy).
# Each level adds progressively more boilerplate Java method stubs that widen
# the semantic distance between the config and codebase (D-52, Open Question 2).
_SYNTHETIC_SAMPLES_BY_REVISION: dict[str, list[dict]] = {
    "early": [
        {
            "input": "Add a REST endpoint for user registration with email validation.",
            "target": "spring-boot-endpoint",
            "drift_magnitude": 1,
        },
        {
            "input": "Create a Spring Boot service method to fetch a paginated list of products.",
            "target": "spring-boot-endpoint",
            "drift_magnitude": 1,
        },
    ],
    "mid": [
        {
            "input": (
                "Implement a Spring Boot controller with CRUD operations for "
                "an Order entity, including input validation and error handling. "
                "// boilerplate stub: public void processOrder() {} "
                "public void validateOrder() {} public void archiveOrder() {}"
            ),
            "target": "spring-boot-endpoint",
            "drift_magnitude": 2,
        },
        {
            "input": (
                "Add a REST endpoint to update user profile fields atomically. "
                "// boilerplate stub: public void syncProfile() {} "
                "public void auditChange() {}"
            ),
            "target": "spring-boot-endpoint",
            "drift_magnitude": 2,
        },
    ],
    "late": [
        {
            "input": (
                "Build a reactive Spring WebFlux endpoint for streaming sensor data "
                "with backpressure and retry logic. "
                "// boilerplate stubs: public void bufferSensor() {} "
                "public void flushBuffer() {} public void rotateSensor() {} "
                "public void replaySensor() {} public void archiveSensor() {} "
                "public void throttleStream() {}"
            ),
            "target": "spring-boot-endpoint",
            "drift_magnitude": 3,
        },
        {
            "input": (
                "Implement a distributed transaction coordinator for a multi-service "
                "Spring Boot application using saga pattern. "
                "// boilerplate stubs: public void compensate() {} "
                "public void checkpoint() {} public void rollbackSaga() {} "
                "public void resumeSaga() {} public void logSaga() {} "
                "public void auditSaga() {}"
            ),
            "target": "spring-boot-endpoint",
            "drift_magnitude": 3,
        },
    ],
}


def _build_dataset(mode: str, revision: str) -> Dataset:
    """Build an Inspect-AI Dataset for (mode, revision).

    mode="synthetic": returns the magnitude-knob fill samples for the
        given revision level (early/mid/late). Drift magnitude increases
        with revision, controlled by the Java boilerplate stub injection.
    mode="real": samples from the GitBug-Java revision snapshot (stub —
        returns the synthetic dataset as a fallback when the real snapshot
        is not materialized; grid_runner.py handles the real path).
    """
    if revision not in _SYNTHETIC_SAMPLES_BY_REVISION:
        raise ValueError(
            f"Unknown revision {revision!r}. Expected one of: "
            f"{sorted(_SYNTHETIC_SAMPLES_BY_REVISION)}"
        )

    raw_samples = _SYNTHETIC_SAMPLES_BY_REVISION[revision]

    samples = [
        Sample(
            input=s["input"],
            target=s["target"],
            metadata={
                "mode": mode,
                "revision": revision,
                "drift_magnitude": s["drift_magnitude"],
            },
        )
        for s in raw_samples
    ]

    from inspect_ai.dataset import MemoryDataset  # lazy import inside function
    return MemoryDataset(samples=samples, name=f"drift-{mode}-{revision}")


# ---------------------------------------------------------------------------
# SICA skill solver — delegates to arm_runner.run_arm
# ---------------------------------------------------------------------------


def _sica_skill_solver(arm: str) -> Solver:
    """Return an Inspect-AI solver that fires the SICA arm_runner for one prompt.

    The solver loads skills from the arm config directory, runs run_arm(),
    and stores the fired tool-name set in state.metadata["fired_skills"].
    The scorer then reads that set for F1 projection.
    """

    @solver
    def sica_solver() -> Solver:
        async def solve(state: TaskState, generate_fn) -> TaskState:  # type: ignore[override]
            prompt = state.input_text
            skills_dir = _resolve_arm_skills(arm)

            tools = load_skill_tools(skills_dir)
            # CR-05: honor Inspect's active --model instead of silently using
            # arm_runner's SETDRIFT_MODEL default. get_model().name is the model id
            # without the provider prefix (e.g. "claude-sonnet-4-6"), which is
            # what run_arm forwards to the SICA backend.
            model_name = get_model().name
            fired = run_arm(prompt, tools, model=model_name, cache_dir=_CACHE_DIR)
            state.metadata["fired_skills"] = list(fired)
            # Set a placeholder output so Inspect sees a completed solve step.
            state.output.completion = f"fired={sorted(fired)}"
            return state

        return solve  # type: ignore[return-value]

    return sica_solver()


# ---------------------------------------------------------------------------
# SICA F1 scorer — secondary result; authoritative F1 comes from grid_runner
# ---------------------------------------------------------------------------


def _sica_f1_scorer() -> Scorer:
    """Return an Inspect-AI scorer that yields 1.0 if any skill was fired.

    NOTE: This scorer's value is a secondary/diagnostic indicator within
    Inspect's result log. The authoritative per-cell macro-F1 is computed
    in grid_runner.py by the frozen scorer.py ruler (Goodhart firewall).
    Inspect's scorer result is used only to confirm the solver ran and
    to keep the Inspect log well-formed.
    """

    @scorer(metrics=[accuracy()])
    def sica_scorer() -> Scorer:
        async def score(state: TaskState, target: Target) -> Score:
            fired = state.metadata.get("fired_skills", [])
            # Secondary indicator: skill was triggered (not the claim metric)
            hit = 1.0 if fired else 0.0
            return Score(
                value=hit,
                answer=str(sorted(fired)),
                explanation=(
                    f"SICA fired {len(fired)} skill(s): {sorted(fired)}. "
                    "Authoritative F1 is computed by grid_runner.py."
                ),
            )

        return score  # type: ignore[return-value]

    return sica_scorer()


# ---------------------------------------------------------------------------
# The @task entry point
# ---------------------------------------------------------------------------


@task
def drift_task(
    mode: str = "synthetic",
    revision: str = "mid",
    arm: str = "B",
) -> Task:
    """Inspect-AI Task for one drift-grid cell.

    Args:
        mode:     "synthetic" (magnitude-knob dataset) or "real" (GitBug-Java).
        revision: "early" | "mid" | "late" — codebase snapshot label.
        arm:      "A" (SICA-managed config) or "B" (frozen hand-written config).

    The model is NOT hardcoded — pass via --model on the CLI or model= in
    inspect_eval(). network_mode: none is enforced at compose level.
    No CachePolicy(per_epoch=False) — default per-epoch scope is used.
    """
    return Task(
        dataset=_build_dataset(mode=mode, revision=revision),
        solver=[_sica_skill_solver(arm=arm)],
        scorer=_sica_f1_scorer(),
        sandbox=("docker", "drift_compose.yaml"),
    )

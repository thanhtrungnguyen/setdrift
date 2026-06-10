"""Smoke tests for drift_task.py (REQ-DRIFT-02 Inspect-AI sandbox).

Tests the following:
  1. drift_task constructs a Task without error (offline, no API, no Docker).
  2. _build_dataset returns correct samples for each revision with mode metadata.
  3. drift_compose.yaml exists and contains required fields (network_mode: none,
     pinned image digest, no CachePolicy(per_epoch=False)).
  4. Full sandbox end-to-end smoke test — only runs when Docker is up; skips
     with an explicit reason when Docker is unavailable.

Gating:
  - inspect_ai: gated by pytest.importorskip("inspect_ai")
  - Docker: gated by a _docker_info() check that skips with a clear reason.
    The test NEVER silently passes when Docker is down.
"""
import subprocess
import sys
from pathlib import Path

import pytest

# Guard: skip the entire module if inspect_ai is not installed.
inspect_ai = pytest.importorskip(
    "inspect_ai",
    reason="inspect-ai not installed; install sica-eval[drift] to run these tests",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EVAL_ROOT = Path(__file__).resolve().parents[3]  # repo/sica-plugin/eval/


def _docker_available() -> bool:
    """Return True if `docker info` exits 0 (Docker daemon is reachable)."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _load_compose_text() -> str:
    """Load drift_compose.yaml text from the eval root."""
    compose_path = _EVAL_ROOT / "drift_compose.yaml"
    assert compose_path.exists(), (
        f"drift_compose.yaml not found at {compose_path}. "
        "It must be created in the eval/ directory."
    )
    return compose_path.read_text(encoding="utf-8")


def _import_drift_task():
    """Import drift_task module, inserting eval/ into sys.path if needed."""
    if str(_EVAL_ROOT) not in sys.path:
        sys.path.insert(0, str(_EVAL_ROOT))
    import drift_task  # noqa: PLC0415
    return drift_task


# ---------------------------------------------------------------------------
# Test 1: drift_task constructs without error (offline, no Docker, no API)
# ---------------------------------------------------------------------------


def test_drift_task_constructs() -> None:
    """Test 1: drift_task() returns an Inspect Task object with required attributes."""
    drift_task_mod = _import_drift_task()

    # Patch arm_runner.load_skill_tools to not require a real skills directory.
    import unittest.mock as mock
    with mock.patch(
        "drift_task.load_skill_tools", return_value=[]
    ):
        task_obj = drift_task_mod.drift_task(
            mode="synthetic", revision="mid", arm="B"
        )

    # Inspect Task must be constructed
    from inspect_ai import Task
    assert isinstance(task_obj, Task), (
        f"drift_task() must return an inspect_ai.Task, got {type(task_obj)}"
    )
    # Sandbox must be the docker tuple
    assert task_obj.sandbox is not None, "Task must have a sandbox configured"
    # Dataset must be non-empty
    assert task_obj.dataset is not None, "Task must have a dataset"


# ---------------------------------------------------------------------------
# Test 2: _build_dataset returns correct samples for each revision
# ---------------------------------------------------------------------------


def test_build_dataset_revisions() -> None:
    """Test 2: _build_dataset returns samples with correct mode/revision metadata."""
    drift_task_mod = _import_drift_task()

    for revision in ("early", "mid", "late"):
        dataset = drift_task_mod._build_dataset(mode="synthetic", revision=revision)
        assert len(dataset) > 0, (
            f"_build_dataset(mode='synthetic', revision={revision!r}) "
            "returned an empty dataset"
        )
        for sample in dataset:
            assert sample.metadata["mode"] == "synthetic", (
                f"Sample metadata should have mode='synthetic', got {sample.metadata}"
            )
            assert sample.metadata["revision"] == revision, (
                f"Sample metadata should have revision={revision!r}"
            )
            assert "drift_magnitude" in sample.metadata, (
                "Sample must carry drift_magnitude metadata"
            )


def test_build_dataset_drift_magnitude_increases() -> None:
    """Test 3: Drift magnitude increases from early → mid → late."""
    drift_task_mod = _import_drift_task()

    def max_magnitude(revision: str) -> int:
        dataset = drift_task_mod._build_dataset(mode="synthetic", revision=revision)
        return max(s.metadata["drift_magnitude"] for s in dataset)

    assert max_magnitude("early") < max_magnitude("mid"), (
        "Early revision must have lower drift magnitude than mid"
    )
    assert max_magnitude("mid") < max_magnitude("late"), (
        "Mid revision must have lower drift magnitude than late"
    )


def test_build_dataset_unknown_revision_raises() -> None:
    """Test 4: _build_dataset raises ValueError for an unknown revision."""
    drift_task_mod = _import_drift_task()
    with pytest.raises(ValueError, match="Unknown revision"):
        drift_task_mod._build_dataset(mode="synthetic", revision="unknown_xyz")


# ---------------------------------------------------------------------------
# Test 5: drift_compose.yaml structure (offline — no Docker needed)
# ---------------------------------------------------------------------------


def test_compose_contains_network_none() -> None:
    """Test 5: drift_compose.yaml contains network_mode: none."""
    text = _load_compose_text()
    assert "network_mode: none" in text, (
        "drift_compose.yaml must contain 'network_mode: none' "
        "(T-04-05 yoking discipline enforcement)"
    )


def test_compose_pinned_digest() -> None:
    """Test 6: drift_compose.yaml has the pinned python:3.12-slim image digest."""
    text = _load_compose_text()
    # Pinned digest from the spike (inspect-ai-spike.md)
    PINNED_DIGEST = "sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203"
    assert PINNED_DIGEST in text, (
        f"drift_compose.yaml must contain the pinned digest {PINNED_DIGEST} "
        "(T-04-05 tag-swap prevention)"
    )


def test_no_per_epoch_false_in_task() -> None:
    """Test 7: drift_task.py must not import or instantiate CachePolicy with per_epoch=False.

    Uses AST analysis so docstring mentions of the anti-pattern do not trigger
    a false failure.
    """
    import ast

    task_path = _EVAL_ROOT / "drift_task.py"
    assert task_path.exists(), f"drift_task.py not found at {task_path}"
    source = task_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Walk all Call nodes; flag any CachePolicy(..., per_epoch=False, ...)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            if func_name == "CachePolicy":
                for kw in node.keywords:
                    if kw.arg == "per_epoch" and isinstance(kw.value, ast.Constant):
                        assert kw.value.value is not False, (
                            "drift_task.py must NOT call CachePolicy(per_epoch=False) — "
                            "this collapses the noise band (RESEARCH.md Pitfall 5)"
                        )

    # Also confirm CachePolicy is not imported (belt-and-suspenders)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names]
            assert "CachePolicy" not in names, (
                "drift_task.py must NOT import CachePolicy (Pitfall 5)"
            )


# ---------------------------------------------------------------------------
# Test 8: Full end-to-end sandbox smoke test (Docker-gated)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _docker_available(),
    reason=(
        "Docker daemon is not available (docker info returned non-zero or timed out). "
        "This test requires Docker Desktop to be running. "
        "Start Docker Desktop and re-run to execute the sandbox smoke test. "
        "Decision: WSL2-WORKING (inspect-ai-spike.md) — test skipped, not absent."
    ),
)
def test_drift_task_runs_in_sandbox() -> None:
    """Test 8: drift_task runs end-to-end with mockllm/model when Docker is up.

    Mirrors the spike pass-criteria from inspect-ai-spike.md:
    (a) Sandbox Docker container started
    (b) The task ran (>0 samples)
    (c) The scorer returned a result
    (d) Teardown was clean (no orphaned containers)

    Uses mockllm/model — no API quota spent.
    """
    import unittest.mock as mock
    from inspect_ai import eval as inspect_eval

    drift_task_mod = _import_drift_task()

    # Patch load_skill_tools and run_arm so no real plugin/skills/ is needed
    with (
        mock.patch("drift_task.load_skill_tools", return_value=[]),
        mock.patch("drift_task.run_arm", return_value=set()),
    ):
        results = inspect_eval(
            drift_task_mod.drift_task(mode="synthetic", revision="mid", arm="B"),
            model="mockllm/model",
            log_dir=None,
        )

    assert results is not None, "inspect_eval must return a result"
    assert len(results) > 0, "inspect_eval must return at least one EvalLog"
    log = results[0]
    # (b) Task ran
    assert log.samples is not None and len(log.samples) > 0, (
        "EvalLog must contain at least one sample result"
    )
    # (c) Scorer returned a result — each sample should have a score
    for sample in log.samples:
        assert sample.scores is not None, (
            f"Sample {sample.id} must have scorer results"
        )

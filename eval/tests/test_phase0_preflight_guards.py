"""Phase 0 pre-flight regression guards (repo-internal artifacts only).

These tests exist so the public `setdrift` repo never silently regresses on
two Phase 0 (REQ-FOUND-01 / REQ-DESIGN-01) deliverables:

1. The `dspy` dependency pin in `eval/pyproject.toml` (no `dspy-ai` leftovers).
2. The dated, append-only Change Log amendment in the falsifiable-claim design
   doc, cross-referenced from the pre-registration.

Workspace-only `.planning/` artifacts (SkillUse decision, Inspect-AI spike,
Phase 0 checklist) are covered separately in
`.planning/tests/test_phase0_artifacts.py` — NOT here, because this repo is
public and must not depend on files outside it.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]  # repo/sica-plugin/
EVAL_ROOT = Path(__file__).resolve().parents[1]  # repo/sica-plugin/eval/

PYPROJECT = EVAL_ROOT / "pyproject.toml"
DESIGN_DOC = REPO_ROOT / "docs" / "design" / "2026-05-20-falsifiable-claim.md"
REGISTRATION = REPO_ROOT / "registrations" / "01-hypothesis.md"


def test_pyproject_pins_dspy_with_no_dspy_ai_leftovers():
    """REQ-FOUND-01: optimize extra must pin dspy>=3.2,<4.0 and never dspy-ai."""
    text = PYPROJECT.read_text(encoding="utf-8")

    assert "dspy>=3.2,<4.0" in text, (
        "expected the optimize extra to pin 'dspy>=3.2,<4.0' in "
        f"{PYPROJECT}, but the exact pin string was not found"
    )
    assert "dspy-ai" not in text, (
        "found a leftover 'dspy-ai' reference in "
        f"{PYPROJECT} — the rename to 'dspy' must be complete"
    )


@pytest.mark.skipif(
    importlib.util.find_spec("dspy") is None,
    reason="dspy is not installed in this test environment (optimize extra not installed)",
)
def test_dspy_gepa_importable_when_optimize_extra_installed():
    """When the optimize extra IS installed, `from dspy import GEPA` must work.

    This only runs if dspy is importable in the current environment; it is
    intentionally not a hard requirement of the base test env (dspy is an
    optional extra), but if it's present it must actually expose GEPA.
    """
    from dspy import GEPA  # noqa: F401


def test_design_doc_has_exactly_one_req_design_01_amendment_heading():
    """REQ-DESIGN-01: exactly one dated Change Log heading for the amendment batch."""
    text = DESIGN_DOC.read_text(encoding="utf-8")
    heading = "### 2026-05-31 — Methodology amendment batch (REQ-DESIGN-01)"

    count = text.count(heading)
    assert count == 1, (
        f"expected exactly one occurrence of the amendment heading in {DESIGN_DOC}, "
        f"found {count}"
    )


def test_design_doc_append_only_sentinel_intact():
    """The append-only footer sentinel must still precede the Change Log."""
    text = DESIGN_DOC.read_text(encoding="utf-8")
    sentinel = "*Approved 2026-05-20. Edit only by appending dated change-log entries below.*"

    assert sentinel in text, (
        f"append-only sentinel missing or altered in {DESIGN_DOC}"
    )

    sentinel_idx = text.index(sentinel)
    changelog_idx = text.index("## Change Log")
    assert sentinel_idx < changelog_idx, (
        "append-only sentinel must appear BEFORE the '## Change Log' section "
        f"in {DESIGN_DOC}"
    )


def test_registration_cross_references_the_2026_05_31_amendment():
    """The pre-registration must carry a matching dated cross-ref to the amendment."""
    text = REGISTRATION.read_text(encoding="utf-8")

    assert "2026-05-31" in text, (
        f"expected a 2026-05-31 dated cross-reference in {REGISTRATION}"
    )
    assert "docs/design/2026-05-20-falsifiable-claim.md" in text, (
        f"expected the cross-reference in {REGISTRATION} to name the design doc"
    )

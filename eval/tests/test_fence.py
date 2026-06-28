"""Blast-radius fence unit tests (REQ-SAFETY-04). Offline, no API.

This file IS the green REQ-SAFETY-04 / Phase-3 Success-Criterion-5 CI test:
optimizer-owned writes to eval/, experiments/, or data/ MUST fail fast with a
FenceViolation; plugin/ and CLAUDE.md targets MUST pass.

ALLOWED_PREFIXES / FenceViolation / check_allowlist are imported FROM fence.py — the
SAME constant the applier (03-02) uses — never redefined here. That import is the
no-drift guarantee (D-48): the test cannot pass against a stale or forked allowlist.
"""

import pytest

from setdrift_eval.optimizer.fence import ALLOWED_PREFIXES, FenceViolation, check_allowlist


def test_eval_target_rejected():
    with pytest.raises(FenceViolation):
        check_allowlist("eval/setdrift_eval/telemetry/scorer.py")


def test_experiments_target_rejected():
    with pytest.raises(FenceViolation):
        check_allowlist("experiments/001-results.json")


def test_data_target_rejected():
    with pytest.raises(FenceViolation):
        check_allowlist("data/telemetry/events.jsonl")


def test_plugin_target_allowed():
    # Must NOT raise.
    check_allowlist("plugin/skills/spring-boot-endpoint/SKILL.md")


def test_claude_md_allowed():
    # Must NOT raise.
    check_allowlist("CLAUDE.md")


def test_windows_backslash_plugin_target_allowed():
    # Backslash paths normalize to plugin/ and pass (as_posix normalization).
    check_allowlist("plugin\\skills\\spring-jpa-entity\\SKILL.md")


def test_allowed_prefixes_constant():
    assert ALLOWED_PREFIXES == ("plugin/", "CLAUDE.md")

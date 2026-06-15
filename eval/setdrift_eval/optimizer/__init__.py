"""setdrift_eval.optimizer — closed-loop optimizer (Phase 3, REQ-LOOP-01/02).

Entry point: run_loop_cycle() coordinates the observe→diagnose→patch→verify→promote|rollback
cycle. It is the SOLE audit writer (D-38/T-03-63); gepa_wrapper/verifier write nothing.
See eval/README.md for full usage.
"""
from setdrift_eval.optimizer.orchestrator import run_loop_cycle
from setdrift_eval.optimizer.gepa_wrapper import build_optimizer, SkillProposal
from setdrift_eval.optimizer.fence import ALLOWED_PREFIXES, FenceViolation, check_allowlist

__all__ = [
    "run_loop_cycle",
    "build_optimizer",
    "SkillProposal",
    "ALLOWED_PREFIXES",
    "FenceViolation",
    "check_allowlist",
]

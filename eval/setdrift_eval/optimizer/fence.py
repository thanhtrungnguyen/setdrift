"""Blast-radius fence — single source-of-truth allowlist (D-48, REQ-SAFETY-04).

What this module does: defines the ONE allowlist of path prefixes the optimizer is
permitted to write, and a fail-loud `check_allowlist()` gate called before any write.

What it does NOT do: it never writes a file, never reads config, never imports the
applier/orchestrator. It is a pure request-response guard.

ALLOWED_PREFIXES is imported by applier.py (03-02) AND the CI test
(tests/test_fence.py). The pre-commit hook (scripts/pre-commit-fence.sh) mirrors it
in shell. ONE PLACE TO AUDIT — impossible to drift between guard, test, and hook.

This is the inverse of the telemetry hook's silent-catch pattern: a violation MUST
raise loudly, never silently return.
"""

from pathlib import Path

ALLOWED_PREFIXES: tuple[str, ...] = (
    "plugin/",  # all skill/hook/agent/command files under the published plugin
    "CLAUDE.md",  # the project CLAUDE.md
)


class FenceViolation(RuntimeError):
    """Raised when an optimizer proposal targets a path outside the allowlist."""


def check_allowlist(target_path: Path | str) -> None:
    """Fail fast if target_path is outside the allowlist. Called before any write.

    Normalizes to a POSIX-style relative string (`as_posix()`) so Windows backslash
    paths and `plugin\\skills\\...` inputs are checked identically to `plugin/...`.
    Raises FenceViolation (fail-loud) on any path that does not start with an allowed
    prefix — eval/, experiments/, and data/ are all rejected.
    """
    p = Path(target_path).as_posix()
    if not any(p.startswith(prefix) for prefix in ALLOWED_PREFIXES):
        raise FenceViolation(
            f"BLAST-RADIUS VIOLATION: optimizer proposed write to '{p}', "
            f"which is outside the allowed prefixes {ALLOWED_PREFIXES}. "
            "Proposal rejected. Logged to audit.jsonl."
        )

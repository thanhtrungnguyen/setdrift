"""Evidence-artifact scrub check: secrets + raw-prompt leakage (D7-20, RUN-01).

What this module does:
  Scans one or more evidence artifacts (JSON/Markdown files under experiments/,
  or a directory of them) for two classes of data-wall violation before they
  are `git add`-ed:
    1. Secret patterns — reuses the canonical `SECRET_RE` regex verbatim from
       `plugin/hooks/capture_event.py` (sk-*, AKIA*, ghp_*). Do NOT invent a
       second regex (RESEARCH "Don't Hand-Roll").
    2. Raw developer-prompt leakage — evidence JSON should carry prompt IDs
       and numeric metrics, never raw prompt bodies (mirrors
       `optimizer/orchestrator.py`'s scrub_for_genealogy/scrub_for_public
       convention: full audit records may carry sensitive content, but the
       committed, data-wall-clean copy never does).

CLI convention: mirrors `corpus/precision_gate_cli.py` — prints violations,
exits non-zero on any match, zero on a clean scan. Fail-loud: no bare `except`.
"""

import argparse
import re
import sys
from pathlib import Path

# Canonical secret regex, reused VERBATIM from plugin/hooks/capture_event.py.
# Do not invent a second regex — a divergent copy risks drifting from the
# canonical scrubber and silently under- or over-matching.
SECRET_RE = re.compile(r"(sk-[A-Za-z0-9-]{8,}|AKIA[0-9A-Z]{12,}|ghp_[A-Za-z0-9]{20,})")


def scan_artifact(path: Path, raw_prompts: set[str] | None = None) -> list[str]:
    """Scan a single artifact file for secrets and raw-prompt leakage.

    Args:
        path: Path to the artifact file (JSON or Markdown).
        raw_prompts: Optional set of raw developer-prompt strings. A violation
            is recorded for each raw prompt string that appears verbatim in
            the artifact text — evidence JSON must carry prompt IDs/metrics
            only, never raw prompt bodies.

    Returns:
        A list of human-readable violation descriptions, one per match. Empty
        list means the artifact is clean.

    Raises:
        OSError: if the file cannot be read (fail-loud — no bare except).
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")

    violations: list[str] = []

    for match in SECRET_RE.finditer(text):
        violations.append(
            f"{path}: secret pattern match {match.group(0)!r} at offset {match.start()}"
        )

    if raw_prompts:
        for prompt in raw_prompts:
            if prompt and prompt in text:
                violations.append(
                    f"{path}: raw developer-prompt text found verbatim "
                    f"(prompt starts: {prompt[:40]!r}...)"
                )

    return violations


def _iter_artifact_paths(paths: list[Path]) -> list[Path]:
    """Expand a list of file/directory paths into a flat list of artifact files.

    Directories are walked for *.json and *.md files (the two evidence-artifact
    formats produced by this harness: experiment JSON manifests and any
    Markdown sizing/remediation docs).
    """
    out: list[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            out.extend(sorted(p.glob("*.json")))
            out.extend(sorted(p.glob("*.md")))
        else:
            out.append(p)
    return out


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: scan artifacts, print violations, exit non-zero on any match.

    Mirrors corpus/precision_gate_cli.py's exit convention.
    """
    parser = argparse.ArgumentParser(
        prog="setdrift-eval-scrub-check",
        description="Scan evidence artifacts for secrets and raw-prompt leakage before commit (D7-20)",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="artifact file(s) or directory/directories to scan (*.json, *.md)",
    )
    args = parser.parse_args(argv)

    artifact_paths = _iter_artifact_paths(args.paths)
    if not artifact_paths:
        print("[scrub-check] no artifacts found to scan")
        return 0

    all_violations: list[str] = []
    for artifact_path in artifact_paths:
        violations = scan_artifact(artifact_path)
        all_violations.extend(violations)

    if all_violations:
        for v in all_violations:
            print(f"[FAIL] {v}")
        print(
            f"[FAIL] scrub check found {len(all_violations)} violation(s) across "
            f"{len(artifact_paths)} artifact(s) — refusing to allow commit"
        )
        return 1

    print(f"[PASS] scrub check clean across {len(artifact_paths)} artifact(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

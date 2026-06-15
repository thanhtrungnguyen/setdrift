#!/bin/sh
# Blast-radius pre-commit hook (D-47, defense-in-depth for REQ-SAFETY-04).
#
# SOURCE OF TRUTH: eval/setdrift_eval/optimizer/fence.py (ALLOWED_PREFIXES). This shell
# script is a deliberate MIRROR of that allowlist, because a git hook cannot import
# Python. If you change ALLOWED_PREFIXES in fence.py you MUST update the case pattern
# below to match. The fence.py CI test (tests/test_fence.py) is the primary gate; this
# hook is the second layer that stops a config-write landing outside plugin/+CLAUDE.md
# from ever being committed.
#
# INSTALL (run once, from repo root):
#   ln -s ../../scripts/pre-commit-fence.sh .git/hooks/pre-commit
#   chmod +x .git/hooks/pre-commit
#
# It does NOT block unrelated commits: it only enforces the allowlist on optimizer
# config-write targets — staged SKILL.md or CLAUDE.md files. Any other path is ignored.

set -eu

violations=0

# Only inspect staged (cached) files; tolerate the no-commit-yet case.
staged=$(git diff --cached --name-only 2>/dev/null || true)

for f in $staged; do
    # Restrict enforcement to optimizer config-write targets: a SKILL.md anywhere,
    # or a CLAUDE.md anywhere. Everything else is out of scope for this hook.
    case "$f" in
        *SKILL.md|*CLAUDE.md|CLAUDE.md)
            # Mirror of fence.py ALLOWED_PREFIXES = ("plugin/", "CLAUDE.md").
            case "$f" in
                plugin/*|CLAUDE.md)
                    : ;;  # allowed
                *)
                    echo "BLAST-RADIUS VIOLATION: staged config-write '$f' is outside the" >&2
                    echo "  allowed prefixes (plugin/, CLAUDE.md). See" >&2
                    echo "  eval/setdrift_eval/optimizer/fence.py (source of truth). Commit rejected." >&2
                    violations=1 ;;
            esac ;;
        *)
            : ;;  # not a config-write target — ignore
    esac
done

if [ "$violations" -ne 0 ]; then
    exit 1
fi
exit 0

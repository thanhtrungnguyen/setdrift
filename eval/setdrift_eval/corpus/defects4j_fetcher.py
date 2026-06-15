"""Defects4J V1.2 fetcher — patch-file extraction path (per the 02-01 spike).

The 02-01 Windows spike (`.planning/codebase/defects4j-windows-spike.md`,
verdict DEFECTS4J-VIABLE) found that every bug ships its buggy↔fixed source diff
as `framework/projects/<P>/patches/<id>.src.patch` INSIDE the framework repo. So
this fetcher reads patch files directly:
  - NO `defects4j init`, NO `project_repos/`, NO `git diff`, NO SVN-id translation
    (Chart's SVN revision ids are harmless — we never diff by revision).
  - Emits the identical `fetcher.BugRecord` so labeler.py / synthesizer.py consume
    it unchanged (D-34 source-agnostic promise — BugRecord is imported, not redefined).

The `.src.patch` is the REVERSE patch in SVN `Index:` format (applied to the FIXED
tree it yields the BUGGY tree: `-` lines are fixed code, `+` lines are buggy code).
`iter_bug_records` normalizes each patch to git-diff format (`diff --git a/ b/`,
`--- a/`, `+++ b/`) AND reverses direction so `+` = the FIX — matching GitBug-Java
and the labeler's added-line rules.
"""
import csv
import os
import re
from collections.abc import Iterator
from pathlib import Path

from setdrift_eval.corpus.fetcher import BugRecord

DEFECTS4J_REPO = "https://github.com/rjust/defects4j"
"""Pinned upstream — clone at tag v1.2.0 into DEFAULT_D4J_DIR."""

DEFAULT_D4J_DIR = Path(os.environ.get("SETDRIFT_DEFECTS4J_DIR", "data/raw/defects4j"))

# All 6 projects are extractable via .src.patch (02-01 spike — no exclusions).
D4J_PROJECTS = ["Chart", "Closure", "Lang", "Math", "Mockito", "Time"]

_INDEX_RE = re.compile(r"^Index:\s+(.+)$")
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


def _projects_root(d4j_dir: Path) -> Path:
    return d4j_dir / "framework" / "projects"


def normalize_and_reverse(src_patch: str) -> str:
    """Convert a Defects4J `.src.patch` (SVN reverse patch) to a forward git diff.

    Output is git-diff format with `+` = the FIX. Drops the SVN `Index:`/`===`/
    `--- (rev)`/`+++ (rev)` headers and emits `diff --git a/<path> b/<path>` so the
    labeler's path-based rules (test/config/pom) and `^\\+` content rules both fire.
    """
    lines = src_patch.splitlines()
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        m = _INDEX_RE.match(lines[i])
        if not m:
            i += 1
            continue
        path = m.group(1).strip()
        out.append(f"diff --git a/{path} b/{path}")
        out.append(f"--- a/{path}")
        out.append(f"+++ b/{path}")
        i += 1
        while i < n and not _INDEX_RE.match(lines[i]):
            line = lines[i]
            hunk = _HUNK_RE.match(line)
            if hunk:
                obuggy_s, obuggy_l, ofixed_s, ofixed_l, tail = hunk.groups()
                obuggy_l = obuggy_l if obuggy_l is not None else "1"
                ofixed_l = ofixed_l if ofixed_l is not None else "1"
                # reverse: swap the two side ranges
                out.append(f"@@ -{ofixed_s},{ofixed_l} +{obuggy_s},{obuggy_l} @@{tail}")
            elif line.startswith(("--- ", "+++ ", "===")):
                pass  # drop SVN file headers; git headers already emitted
            elif line.startswith("+"):
                out.append("-" + line[1:])
            elif line.startswith("-"):
                out.append("+" + line[1:])
            else:
                out.append(line)
            i += 1
    return "\n".join(out) + "\n"


def iter_bug_records(d4j_dir: Path = DEFAULT_D4J_DIR) -> Iterator[BugRecord]:
    """Yield one ``fetcher.BugRecord`` per Defects4J bug, via its ``.src.patch``.

    Fail-loud if the framework checkout is absent (RuntimeError) — never a silent
    empty iterator. A bug whose patch file is missing/unreadable is skipped
    (continue), mirroring fetcher.py's parse-skip discipline.
    """
    d4j_dir = Path(d4j_dir)
    projects_root = _projects_root(d4j_dir)
    if not projects_root.is_dir():
        raise RuntimeError(
            f"Defects4J framework not found at {projects_root}. "
            f"Clone it: git clone --branch v1.2.0 {DEFECTS4J_REPO} {d4j_dir} "
            f"(no `defects4j init` needed — extraction reads patches/*.src.patch)."
        )
    for project in D4J_PROJECTS:
        commit_db = projects_root / project / "commit-db"
        patches_dir = projects_root / project / "patches"
        if not commit_db.is_file():
            continue
        with commit_db.open(encoding="utf-8") as fh:
            for row in csv.reader(fh):
                if len(row) < 3:
                    continue
                bug_num, buggy_rev, fixed_rev = row[0], row[1], row[2]
                patch_file = patches_dir / f"{bug_num}.src.patch"
                if not patch_file.is_file():
                    continue
                try:
                    raw = patch_file.read_text(encoding="utf-8", errors="replace")
                    diff = normalize_and_reverse(raw)
                except OSError:
                    continue
                yield BugRecord(
                    bug_id=f"d4j-{project}-{bug_num}",  # globally collision-safe
                    commit=fixed_rev,
                    parent_commit=buggy_rev,
                    diff=diff,
                    commit_message="",
                    issue_text="",
                    project_id=project,
                )

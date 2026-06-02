"""Defects4J fetcher tests (Plan 02-02 Task 1). Offline, fixture-based.

Implements the 02-01 spike's `.src.patch` extraction path (commit-db +
patches/<id>.src.patch), NOT the pre-spike active-bugs.csv + git-diff approach —
the spike (DEFECTS4J-VIABLE) proved patch-file reading needs no init/project_repos.
"""
import pytest

from sica_eval.corpus import fetcher
from sica_eval.corpus.defects4j_fetcher import iter_bug_records, normalize_and_reverse

# Defects4J .src.patch = SVN reverse patch: `--- (fixed rev)` / `+++ (buggy rev)`,
# body `-` = fixed code, `+` = buggy code.
_SAMPLE_PATCH = (
    "Index: src/main/java/Foo.java\n"
    "===================================================================\n"
    "--- src/main/java/Foo.java\t(revision 2)\n"
    "+++ src/main/java/Foo.java\t(revision 1)\n"
    "@@ -10,7 +10,7 @@\n"
    "     public int f() {\n"
    "-        return compute();\n"
    "+        return computeBuggy();\n"
    "     }\n"
)


def _make_d4j(tmp_path, project, rows, patches):
    root = tmp_path / "framework" / "projects" / project
    (root / "patches").mkdir(parents=True)
    (root / "commit-db").write_text(
        "\n".join(",".join(r) for r in rows) + "\n", encoding="utf-8"
    )
    for bug_num, text in patches.items():
        (root / "patches" / f"{bug_num}.src.patch").write_text(text, encoding="utf-8")
    return tmp_path


def test_yields_bugrecord_with_prefixed_id(tmp_path):
    d = _make_d4j(tmp_path, "Lang", [("1", "aaa", "bbb")], {"1": _SAMPLE_PATCH})
    recs = list(iter_bug_records(d))
    assert len(recs) == 1
    assert recs[0].bug_id == "d4j-Lang-1"  # globally collision-safe prefix
    assert recs[0].project_id == "Lang"
    assert recs[0].commit == "bbb"  # fixed rev
    assert recs[0].parent_commit == "aaa"  # buggy rev


def test_missing_framework_raises_fail_loud(tmp_path):
    """Absent framework checkout → RuntimeError (not a silent empty iterator)."""
    with pytest.raises(RuntimeError, match="Defects4J framework not found"):
        list(iter_bug_records(tmp_path / "does-not-exist"))


def test_missing_patch_file_is_skipped(tmp_path):
    """A commit-db row with no .src.patch is skipped (continue), not raised."""
    d = _make_d4j(
        tmp_path, "Math", [("1", "a", "b"), ("2", "c", "d")], {"1": _SAMPLE_PATCH}
    )
    recs = list(iter_bug_records(d))
    assert [r.bug_id for r in recs] == ["d4j-Math-1"]  # bug 2 (no patch) skipped


def test_yields_fetcher_bugrecord_identity(tmp_path):
    """Yielded objects are the imported fetcher.BugRecord, not a redefinition."""
    d = _make_d4j(tmp_path, "Time", [("1", "a", "b")], {"1": _SAMPLE_PATCH})
    recs = list(iter_bug_records(d))
    assert isinstance(recs[0], fetcher.BugRecord)


def test_normalize_reverses_direction_and_emits_git_header():
    out = normalize_and_reverse(_SAMPLE_PATCH)
    lines = out.splitlines()
    assert lines[0] == "diff --git a/src/main/java/Foo.java b/src/main/java/Foo.java"
    assert "--- a/src/main/java/Foo.java" in lines
    assert "+++ b/src/main/java/Foo.java" in lines
    # reversed: the FIX (compute()) lands on + ; the bug (computeBuggy()) on -.
    assert "+        return compute();" in lines
    assert "-        return computeBuggy();" in lines

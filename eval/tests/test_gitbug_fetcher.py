"""GitBug-Java fetcher tests (Plan 02-02 GitBug integration). Offline, fixture-based.

GitBug-Java bundles the source diff inline as `bug_patch` (already git-diff,
`+` = fix) in data/bugs/<repo>.json — no Docker/reproduction needed.
"""
import json

import pytest

from setdrift_eval.corpus import fetcher
from setdrift_eval.corpus.gitbug_fetcher import iter_bug_records

_BUG = {
    "repository": "owner/repo",
    "commit_hash": "f" * 40,
    "previous_commit_hash": "b" * 40,
    "commit_message": "Fix NPE on missing id",
    "bug_patch": "diff --git a/A.java b/A.java\n+import java.util.List;\n",
    "issues": [{"title": "NPE", "body": "crashes on null"}],
}


def _make(tmp_path, files: dict[str, str]):
    d = tmp_path / "data" / "bugs"
    d.mkdir(parents=True)
    for name, content in files.items():
        (d / name).write_text(content, encoding="utf-8")
    return tmp_path


def test_reads_object_and_jsonl_skips_empty_patch(tmp_path):
    obj = json.dumps(_BUG)
    jsonl = "\n".join(json.dumps({**_BUG, "commit_hash": c * 40}) for c in "12")
    empty = json.dumps({**_BUG, "commit_hash": "e" * 40, "bug_patch": ""})
    meta = _make(tmp_path, {"a.json": obj, "b.json": jsonl, "c.json": empty})

    recs = list(iter_bug_records(meta))
    assert len(recs) == 3  # 1 object + 2 JSONL; empty-patch bug skipped
    assert all(isinstance(r, fetcher.BugRecord) for r in recs)

    r0 = next(r for r in recs if r.commit == "f" * 40)
    assert r0.bug_id == "gitbug-owner-repo-ffffffffffff"
    assert r0.parent_commit == "b" * 40
    assert "import" in r0.diff
    assert "NPE" in r0.issue_text  # issue title/body folded in


def test_missing_data_raises_fail_loud(tmp_path):
    with pytest.raises(RuntimeError, match="GitBug-Java data not found"):
        list(iter_bug_records(tmp_path / "does-not-exist"))

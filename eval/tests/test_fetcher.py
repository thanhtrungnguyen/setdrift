"""Fetcher tests — exercise parsing logic with synthetic on-disk records."""
import json
from pathlib import Path

import pydantic
import pytest

from sica_eval.corpus.fetcher import BugRecord, parse_bug_manifest


def test_parse_bug_manifest_extracts_required_fields(data_dir: Path):
    """A bug manifest JSON file produces a BugRecord with all required fields."""
    manifest = {
        "bug_id": "spring-boot-001",
        "commit_hash": "abc123def456",
        "parent_commit_hash": "111aaa222bbb",
        "diff": "diff --git a/Foo.java b/Foo.java\n+    return null;\n",
        "commit_message": "fix: return null on missing user",
        "issue_text": "NPE when user missing",
        "project_id": "spring-projects/spring-boot",
    }
    manifest_path = data_dir / "spring-boot-001.json"
    manifest_path.write_text(json.dumps(manifest))

    record = parse_bug_manifest(manifest_path)

    assert record.bug_id == "spring-boot-001"
    assert record.commit == "abc123def456"
    assert record.parent_commit == "111aaa222bbb"
    assert "return null" in record.diff
    assert record.commit_message.startswith("fix:")
    assert record.issue_text == "NPE when user missing"
    assert record.project_id == "spring-projects/spring-boot"


def test_bug_record_is_frozen():
    """BugRecord uses a frozen Pydantic model so it can be safely shared across pipeline stages."""
    record = BugRecord(
        bug_id="x",
        commit="c",
        parent_commit="p",
        diff="d",
        commit_message="m",
        issue_text="i",
        project_id="org/repo",
    )
    with pytest.raises(pydantic.ValidationError):
        record.bug_id = "y"  # type: ignore[misc]

"""GitBug-Java fetcher.

Clones the gitbugactions/gitbug-java repository into a local raw-data directory
(default: data/raw/gitbug-java/) and exposes an iterator over BugRecord objects
parsed from per-bug manifest JSON files inside the cloned tree.

The dataset URL is pinned as a constant. If the upstream repo moves, update
GITBUG_JAVA_REPO and document the change in docs/corpus.md.
"""

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path

from pydantic import BaseModel, ConfigDict

GITBUG_JAVA_REPO = "https://github.com/gitbugactions/gitbug-java"
"""Pinned upstream. Verify resolves before relying on it; if 404, search the paper
arxiv 2402.02961 for the current location."""

DEFAULT_RAW_DIR = Path("data/raw/gitbug-java")


class BugRecord(BaseModel):
    """One parsed bug from the GitBug-Java manifest."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    bug_id: str
    commit: str
    parent_commit: str
    diff: str
    commit_message: str = ""
    issue_text: str = ""
    project_id: str = ""


def clone_or_update(target_dir: Path = DEFAULT_RAW_DIR, repo_url: str = GITBUG_JAVA_REPO) -> Path:
    """Idempotently clone the dataset; if already present, run `git pull`."""
    target_dir = Path(target_dir)
    if (target_dir / ".git").is_dir():
        subprocess.run(
            ["git", "-C", str(target_dir), "pull", "--ff-only"],
            check=True,
            capture_output=True,
        )
    else:
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth=1", repo_url, str(target_dir)],
            check=True,
            capture_output=True,
        )
    return target_dir


def parse_bug_manifest(manifest_path: Path) -> BugRecord:
    """Parse one bug manifest JSON file into a BugRecord.

    Tolerates missing optional fields (commit_message, issue_text, project_id);
    bug_id, commit_hash, parent_commit_hash, and diff are required.
    """
    data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    return BugRecord(
        bug_id=data["bug_id"],
        commit=data["commit_hash"],
        parent_commit=data["parent_commit_hash"],
        diff=data["diff"],
        commit_message=data.get("commit_message", ""),
        issue_text=data.get("issue_text", ""),
        project_id=data.get("project_id", ""),
    )


def iter_bug_records(raw_dir: Path = DEFAULT_RAW_DIR) -> Iterator[BugRecord]:
    """Yield every BugRecord from the cloned dataset's manifest JSONs.

    The dataset layout puts one manifest per bug under raw_dir/**/manifest.json
    or raw_dir/*.json (varies by upstream version). We accept both patterns.
    """
    raw_dir = Path(raw_dir)
    candidates: list[Path] = list(raw_dir.glob("**/manifest.json")) + list(raw_dir.glob("*.json"))
    seen: set[str] = set()
    for path in candidates:
        try:
            record = parse_bug_manifest(path)
        except KeyError, json.JSONDecodeError:
            continue
        if record.bug_id in seen:
            continue
        seen.add(record.bug_id)
        yield record

"""GitBug-Java fetcher — bundled-patch extraction path.

GitBug-Java ships each bug's source diff INLINE as ``bug_patch`` (already in
``diff --git a/ b/`` format, with ``+`` = the fix) inside
``data/bugs/<repo>.json`` — so this fetcher reads the patch directly: NO Docker,
NO reproduction toolchain, NO per-repo clone (the Docker repro is only needed to
RUN tests, not to extract the source diff). Emits the identical
``fetcher.BugRecord`` so labeler.py / synthesizer.py consume it unchanged (D-34).

Per-file JSONs are either a single bug object or JSON-Lines (one bug per line).
Bugs with an empty ``bug_patch`` (test-only / non-code-only changes) are skipped —
the corpus needs a source diff to label.
"""
import json
import os
from collections.abc import Iterator
from pathlib import Path

from setdrift_eval.corpus.fetcher import BugRecord

GITBUG_JAVA_REPO = "https://github.com/gitbugactions/gitbug-java"
DEFAULT_GITBUG_DIR = Path(os.environ.get("SETDRIFT_GITBUG_DIR", "data/raw/gitbug-java-meta"))


def _load_bugs(path: Path) -> list[dict]:
    """Read one data/bugs/*.json — tolerates a single object, a list, or JSONL."""
    txt = path.read_text(encoding="utf-8").strip()
    if not txt:
        return []
    try:
        obj = json.loads(txt)
        return obj if isinstance(obj, list) else [obj]
    except json.JSONDecodeError:
        return [json.loads(line) for line in txt.splitlines() if line.strip()]


def _issue_text(bug: dict) -> str:
    parts: list[str] = []
    for issue in bug.get("issues") or []:
        if isinstance(issue, dict):
            parts.append(f"{issue.get('title', '')}\n{issue.get('body', '')}".strip())
        elif isinstance(issue, str):
            parts.append(issue)
    return "\n\n".join(p for p in parts if p)


def iter_bug_records(meta_dir: Path = DEFAULT_GITBUG_DIR) -> Iterator[BugRecord]:
    """Yield one ``fetcher.BugRecord`` per GitBug-Java bug with a source patch.

    Fail-loud if the metadata checkout is absent (RuntimeError) — never a silent
    empty iterator.
    """
    meta_dir = Path(meta_dir)
    bugs_dir = meta_dir / "data" / "bugs"
    if not bugs_dir.is_dir():
        raise RuntimeError(
            f"GitBug-Java data not found at {bugs_dir}. "
            f"Clone it: git clone --depth 1 {GITBUG_JAVA_REPO} {meta_dir}"
        )
    seen: set[str] = set()
    for bug_file in sorted(bugs_dir.glob("*.json")):
        for bug in _load_bugs(bug_file):
            patch = bug.get("bug_patch") or ""
            if not patch.strip():
                continue  # no source change to label
            repo = bug.get("repository", bug_file.stem)
            commit = bug.get("commit_hash", "")
            bug_id = f"gitbug-{repo.replace('/', '-')}-{commit[:12]}"
            if bug_id in seen:
                continue
            seen.add(bug_id)
            yield BugRecord(
                bug_id=bug_id,
                commit=commit,
                parent_commit=bug.get("previous_commit_hash", ""),
                diff=patch,
                commit_message=bug.get("commit_message", ""),
                issue_text=_issue_text(bug),
                project_id=repo,
            )

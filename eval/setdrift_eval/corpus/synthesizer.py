"""Prompt synthesizer.

Converts an issue title/body + commit message into a single 'developer prompt'
string that approximates what a real developer would type to Claude Code when
encountering the bug.

The conversion is deliberately simple:
- If issue text exists, use it (it's already in developer voice).
- Otherwise, transform 'fix: X' commit messages into 'Help me X' phrasing.
- Cap the final string at MAX_PROMPT_CHARS so no single prompt dominates the corpus.
"""

import re

from setdrift_eval.corpus.fetcher import BugRecord

MAX_PROMPT_CHARS = 4000


def synthesize_prompt(record: BugRecord) -> str:
    """Return a single developer-style prompt string for this bug."""
    if record.issue_text and record.issue_text.strip():
        prompt = record.issue_text.strip()
    else:
        prompt = _commit_message_to_request(record.commit_message)
    if len(prompt) > MAX_PROMPT_CHARS:
        prompt = prompt[: MAX_PROMPT_CHARS - 3] + "..."
    return prompt


def _commit_message_to_request(commit_message: str) -> str:
    """Convert 'fix: X' / 'fix(scope): X' into 'Help me X'."""
    msg = (commit_message or "").strip()
    if not msg:
        return "Help me debug this issue."
    stripped = re.sub(
        r"^(fix|chore|feat|refactor)(\([^)]+\))?:\s*", "", msg, count=1, flags=re.IGNORECASE
    )
    return f"Help me {stripped.rstrip('.')}."

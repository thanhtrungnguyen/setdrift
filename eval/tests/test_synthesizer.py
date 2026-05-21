"""Prompt synthesizer tests — issue+commit text becomes a realistic prompt."""
from sica_eval.corpus.fetcher import BugRecord
from sica_eval.corpus.synthesizer import synthesize_prompt


def test_prompt_includes_issue_title_when_present():
    record = BugRecord(
        bug_id="x",
        commit="c",
        parent_commit="p",
        diff="diff --git a/Foo.java b/Foo.java\n",
        issue_text="NullPointerException in /api/users\n\nDetails: ...",
        commit_message="fix: handle null id",
    )
    prompt = synthesize_prompt(record)
    assert "NullPointerException in /api/users" in prompt


def test_prompt_falls_back_to_commit_message_when_no_issue():
    record = BugRecord(
        bug_id="x",
        commit="c",
        parent_commit="p",
        diff="diff --git a/Foo.java b/Foo.java\n",
        issue_text="",
        commit_message="fix: add missing @Component on UserService",
    )
    prompt = synthesize_prompt(record)
    assert "add missing @Component" in prompt


def test_prompt_is_first_person_and_imperative():
    """The synthesizer normalizes 'fix: X' commit messages into 'help me X' phrasing."""
    record = BugRecord(
        bug_id="x",
        commit="c",
        parent_commit="p",
        diff="d",
        issue_text="",
        commit_message="fix: NullPointerException when user not found",
    )
    prompt = synthesize_prompt(record)
    assert prompt.lower().startswith(("help me", "i'm", "i ", "when "))


def test_prompt_is_under_token_budget():
    """Sanity cap so synthesized prompts don't blow past Claude's context window."""
    record = BugRecord(
        bug_id="x",
        commit="c",
        parent_commit="p",
        diff="d",
        issue_text="x" * 50_000,
        commit_message="fix: y",
    )
    prompt = synthesize_prompt(record)
    assert len(prompt) <= 4000

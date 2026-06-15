"""Shared fixtures: synthetic bug records for offline labeler/synthesizer tests."""
import textwrap
from pathlib import Path

import pytest


@pytest.fixture
def sample_diff_dependency_bump() -> str:
    return textwrap.dedent(
        """\
        diff --git a/pom.xml b/pom.xml
        --- a/pom.xml
        +++ b/pom.xml
        @@ -25,7 +25,7 @@
             <dependency>
                 <groupId>org.springframework.boot</groupId>
                 <artifactId>spring-boot-starter</artifactId>
        -        <version>2.7.0</version>
        +        <version>2.7.18</version>
             </dependency>
        """
    )


@pytest.fixture
def sample_diff_null_check() -> str:
    return textwrap.dedent(
        """\
        diff --git a/src/main/java/UserService.java b/src/main/java/UserService.java
        --- a/src/main/java/UserService.java
        +++ b/src/main/java/UserService.java
        @@ -10,6 +10,9 @@
             public User findById(Long id) {
        +        if (id == null) {
        +            return null;
        +        }
                 return repository.findOne(id);
             }
        """
    )


@pytest.fixture
def sample_diff_spring_annotation() -> str:
    return textwrap.dedent(
        """\
        diff --git a/src/main/java/UserService.java b/src/main/java/UserService.java
        --- a/src/main/java/UserService.java
        +++ b/src/main/java/UserService.java
        @@ -1,5 +1,6 @@
         package com.example;

        +@Service
         public class UserService {
             private final UserRepository repository;
         }
        """
    )


@pytest.fixture
def sample_issue_text() -> dict:
    return {
        "title": "NullPointerException when calling /api/users/{id} with non-existent ID",
        "body": (
            "When I hit /api/users/999 (a user that doesn't exist), the application crashes "
            "with NullPointerException at UserService.java:12 instead of returning 404. "
            "Expected: 404 response. Actual: 500 + stack trace."
        ),
        "commit_message": "fix: handle null id in UserService.findById",
    }


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Per-test isolated data directory."""
    d = tmp_path / "data" / "raw" / "gitbug-java"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def mock_anthropic_client(monkeypatch):
    """Offline mock of ``anthropic.Anthropic()`` (Plan 02-04).

    Returns the list of recorded ``create(**kwargs)`` calls so tests can assert
    the Arm C path omits BOTH ``tools`` and ``tool_choice``. The mock fires a
    ``tool_use`` block (named after the first supplied tool) ONLY when a non-empty
    toolset is passed (Arm B); with no tools (Arm C) it returns a plain text block
    so ``run_arm_c`` observes zero ``tool_use`` blocks. No network, no API key.
    """
    calls: list[dict] = []

    class _Block:
        def __init__(self, block_type: str, name: str | None = None):
            self.type = block_type
            self.name = name

        def model_dump(self) -> dict:
            if self.type == "tool_use":
                return {"type": "tool_use", "name": self.name, "input": {}}
            return {"type": "text", "text": "No applicable skill."}

    class _Usage:
        input_tokens = 100
        output_tokens = 10

        def model_dump(self) -> dict:
            return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}

    class _Response:
        def __init__(self, blocks: list):
            self.content = blocks
            self.usage = _Usage()
            self.stop_reason = (
                "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
            )

    class _Messages:
        @staticmethod
        def create(**kwargs):
            calls.append(kwargs)
            tools = kwargs.get("tools")
            if tools:
                return _Response([_Block("tool_use", tools[0]["name"])])
            return _Response([_Block("text")])

    class _FakeClient:
        messages = _Messages()

    monkeypatch.setattr("setdrift_eval.benchmark.llm_backend.anthropic.Anthropic", lambda: _FakeClient())
    return calls


@pytest.fixture
def sample_intent_skill_map() -> dict:
    """A minimal frozen intent→skill projection mirroring the shipped YAML (D-30/D-31)."""
    return {
        "jpa-migration": [],
        "spring-annotation-fix": ["spring_boot_endpoint"],
        "dependency-bump": [],
        "null-check": [],
        "test-fixture-fix": [],
        "config-property": [],
        "import-fix": [],
        "none": [],
    }

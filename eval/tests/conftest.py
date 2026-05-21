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

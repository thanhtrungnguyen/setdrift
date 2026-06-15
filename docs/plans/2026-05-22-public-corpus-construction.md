# Public Corpus Construction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible mining pipeline that turns the 199 reproducible Java bugs in GitBug-Java into a labeled developer-prompt corpus (`data/corpus/gitbug-java.jsonl`) suitable for measuring skill-trigger F1 under conditions A/B/C of the falsifiable claim (see `docs/design/2026-05-20-falsifiable-claim.md`).

**Architecture:** A new Python subpackage `eval/setdrift_eval/corpus/` containing a fetcher (clones the GitBug-Java GitHub repo into `data/raw/gitbug-java/`), a heuristic labeler (rule-based diff → `SkillLabel` mapper over a fixed 8-label taxonomy), a prompt synthesizer (issue+commit → developer-prompt string), a corpus builder pipeline that combines them and writes JSONL, a `setdrift-eval corpus build` CLI subcommand, and a verification sampler that emits a CSV for manual labeling of a 20% random sample. All code is Python 3.14+, schemas are Pydantic v2, tests use pytest. Output ≈199 labeled prompts; reaching the ≥500 target requires a follow-up Defects4J plan (out of scope here).

**Tech Stack:** Python 3.14+, Pydantic 2.x, pytest 8.x, GitPython 3.x (for diff parsing), subprocess (for `git clone`). Existing `eval/pyproject.toml` already declares Pydantic and Anthropic; this plan adds `gitpython` and bumps `pytest` from optional `dev` extra to a runtime test dependency declared the standard way.

---

## File Structure

| Action | Path | Responsibility |
|---|---|---|
| Create | `repo/sica-plugin/eval/setdrift_eval/corpus/__init__.py` | Package marker + public exports |
| Create | `repo/sica-plugin/eval/setdrift_eval/corpus/schemas.py` | Pydantic models: `SkillLabel`, `BugSource`, `LabeledPrompt`, `Corpus` |
| Create | `repo/sica-plugin/eval/setdrift_eval/corpus/fetcher.py` | Clone/refresh `gitbugactions/gitbug-java` into `data/raw/gitbug-java/` and yield `BugRecord` |
| Create | `repo/sica-plugin/eval/setdrift_eval/corpus/labeler.py` | Rule-based diff → `SkillLabel` mapping |
| Create | `repo/sica-plugin/eval/setdrift_eval/corpus/synthesizer.py` | issue+commit text → developer-prompt string |
| Create | `repo/sica-plugin/eval/setdrift_eval/corpus/builder.py` | Pipeline: fetcher → labeler+synthesizer → JSONL writer |
| Create | `repo/sica-plugin/eval/setdrift_eval/corpus/sampler.py` | Random 20% sample → CSV for manual verification |
| Modify | `repo/sica-plugin/eval/setdrift_eval/cli.py` | Add `corpus build` + `corpus verify` subcommands |
| Modify | `repo/sica-plugin/eval/pyproject.toml` | Add `gitpython>=3.1` to runtime deps; declare test config |
| Create | `repo/sica-plugin/eval/tests/__init__.py` | Test package marker |
| Create | `repo/sica-plugin/eval/tests/conftest.py` | Shared fixtures (sample diffs, sample issues) |
| Create | `repo/sica-plugin/eval/tests/test_schemas.py` | Pydantic round-trip + validation tests |
| Create | `repo/sica-plugin/eval/tests/test_labeler.py` | Heuristic-rule unit tests |
| Create | `repo/sica-plugin/eval/tests/test_synthesizer.py` | Prompt formatting tests |
| Create | `repo/sica-plugin/eval/tests/test_builder.py` | End-to-end pipeline integration test (with fixtures, no network) |
| Create | `repo/sica-plugin/docs/corpus.md` | Usage doc: how to build, verify, and extend the corpus |

The new code lives entirely under `eval/setdrift_eval/corpus/` so it stays self-contained. Output JSONL is written under `data/` which is fully gitignored per `.gitignore` lines 3-4.

---

## Task 1: Test Infrastructure

**Files:**
- Modify: `repo/sica-plugin/eval/pyproject.toml`
- Create: `repo/sica-plugin/eval/tests/__init__.py`
- Create: `repo/sica-plugin/eval/tests/test_smoke.py`

- [ ] **Step 1: Pin runtime dependencies and add pytest config**

Edit `repo/sica-plugin/eval/pyproject.toml`. Replace the `[project]` and `[project.optional-dependencies]` sections so dev/test deps are declared and pytest knows where to look:

```toml
[project]
name = "setdrift-eval"
version = "0.0.1"
description = "Evaluation harness for the SICA self-improving Claude Code plugin"
readme = "README.md"
requires-python = ">=3.14"
authors = [{ name = "Nguyen Thanh Trung" }]
license = { text = "MIT" }
dependencies = [
  "anthropic>=0.40,<1.0",
  "pydantic>=2.5,<3.0",
  "rich>=13",
  "gitpython>=3.1,<4.0",
]

[project.optional-dependencies]
optimize = ["dspy-ai>=2.5", "gepa"]
dev = ["pytest>=8", "ruff>=0.6", "mypy>=1.10"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra -q"
```

- [ ] **Step 2: Install the package editable with dev extras**

Run:

```bash
cd repo/sica-plugin/eval
python -m venv .venv
.venv/Scripts/activate  # Windows; use source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
```

Expected: install completes, `pytest --version` reports >=8.

- [ ] **Step 3: Create the test package**

Create `repo/sica-plugin/eval/tests/__init__.py` as an empty file (one blank line).

- [ ] **Step 4: Write the failing smoke test**

Create `repo/sica-plugin/eval/tests/test_smoke.py`:

```python
"""Smoke test — the test infrastructure itself is alive."""
import setdrift_eval


def test_package_version_is_set():
    assert setdrift_eval.__version__ == "0.0.1"
```

- [ ] **Step 5: Run test to verify it passes**

Run from `repo/sica-plugin/eval/`:

```bash
pytest tests/test_smoke.py -v
```

Expected: `1 passed`. If `ModuleNotFoundError: setdrift_eval`, re-run `pip install -e .` from this directory.

- [ ] **Step 6: Commit**

```bash
cd repo/sica-plugin
git add eval/pyproject.toml eval/tests/__init__.py eval/tests/test_smoke.py
git commit -m "test: add pytest infrastructure and smoke test"
```

---

## Task 2: Schemas + Skill Taxonomy

**Files:**
- Create: `repo/sica-plugin/eval/setdrift_eval/corpus/__init__.py`
- Create: `repo/sica-plugin/eval/setdrift_eval/corpus/schemas.py`
- Create: `repo/sica-plugin/eval/tests/test_schemas.py`

- [ ] **Step 1: Write the failing schema tests**

Create `repo/sica-plugin/eval/tests/test_schemas.py`:

```python
"""Schema round-trip and validation tests."""
import json

import pytest
from pydantic import ValidationError

from setdrift_eval.corpus.schemas import (
    BugSource,
    Corpus,
    LabeledPrompt,
    SkillLabel,
)


def test_skill_label_taxonomy_is_eight_labels():
    """The fixed taxonomy must have exactly the labels the labeler rules can produce."""
    assert set(SkillLabel) == {
        SkillLabel.JPA_MIGRATION,
        SkillLabel.SPRING_ANNOTATION_FIX,
        SkillLabel.DEPENDENCY_BUMP,
        SkillLabel.NULL_CHECK,
        SkillLabel.TEST_FIXTURE_FIX,
        SkillLabel.CONFIG_PROPERTY,
        SkillLabel.IMPORT_FIX,
        SkillLabel.NONE,
    }


def test_labeled_prompt_roundtrip_via_json():
    """A LabeledPrompt survives JSON round-trip without loss."""
    original = LabeledPrompt(
        prompt_id="gitbug-java-org-springframework-spring-boot-001",
        prompt="My Spring Boot app fails to start with NullPointerException in UserService.",
        predicted_skills=[SkillLabel.NULL_CHECK],
        ground_truth_skills=None,
        source=BugSource(
            dataset="gitbug-java",
            bug_id="spring-boot-001",
            commit="abc123",
            parent_commit="def456",
        ),
        metadata={"language": "java", "framework": "spring-boot"},
    )
    restored = LabeledPrompt.model_validate_json(original.model_dump_json())
    assert restored == original


def test_labeled_prompt_rejects_unknown_skill_label():
    """Pydantic must reject string labels outside the taxonomy."""
    with pytest.raises(ValidationError):
        LabeledPrompt.model_validate(
            {
                "prompt_id": "x",
                "prompt": "y",
                "predicted_skills": ["not-a-real-label"],
                "source": {
                    "dataset": "gitbug-java",
                    "bug_id": "z",
                    "commit": "c",
                    "parent_commit": "p",
                },
                "metadata": {},
            }
        )


def test_corpus_holds_multiple_prompts():
    """Corpus is a thin container with a list and metadata."""
    p1 = LabeledPrompt(
        prompt_id="a",
        prompt="...",
        predicted_skills=[SkillLabel.NONE],
        source=BugSource(dataset="gitbug-java", bug_id="1", commit="c1", parent_commit="p1"),
        metadata={},
    )
    p2 = LabeledPrompt(
        prompt_id="b",
        prompt="...",
        predicted_skills=[SkillLabel.IMPORT_FIX],
        source=BugSource(dataset="gitbug-java", bug_id="2", commit="c2", parent_commit="p2"),
        metadata={},
    )
    corpus = Corpus(name="gitbug-java", version="2026-05-22", prompts=[p1, p2])
    serialized = corpus.model_dump_json()
    parsed = json.loads(serialized)
    assert len(parsed["prompts"]) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run from `repo/sica-plugin/eval/`:

```bash
pytest tests/test_schemas.py -v
```

Expected: 4 errors, all `ModuleNotFoundError: setdrift_eval.corpus`.

- [ ] **Step 3: Create the corpus subpackage**

Create `repo/sica-plugin/eval/setdrift_eval/corpus/__init__.py`:

```python
"""Public corpus construction subsystem.

See docs/plans/2026-05-22-public-corpus-construction.md for the plan
and docs/design/2026-05-20-falsifiable-claim.md §4 for the methodology.
"""
from setdrift_eval.corpus.schemas import (
    BugSource,
    Corpus,
    LabeledPrompt,
    SkillLabel,
)

__all__ = ["BugSource", "Corpus", "LabeledPrompt", "SkillLabel"]
```

- [ ] **Step 4: Implement the schemas**

Create `repo/sica-plugin/eval/setdrift_eval/corpus/schemas.py`:

```python
"""Pydantic schemas for the public corpus.

The SkillLabel taxonomy is fixed at eight values. Extending the taxonomy
requires updating the labeler rules in labeler.py and bumping the corpus
version string so downstream consumers know labels may have shifted.
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SkillLabel(str, Enum):
    """Canonical skill labels. See docs/corpus.md for definitions."""

    JPA_MIGRATION = "jpa-migration"
    SPRING_ANNOTATION_FIX = "spring-annotation-fix"
    DEPENDENCY_BUMP = "dependency-bump"
    NULL_CHECK = "null-check"
    TEST_FIXTURE_FIX = "test-fixture-fix"
    CONFIG_PROPERTY = "config-property"
    IMPORT_FIX = "import-fix"
    NONE = "none"


class BugSource(BaseModel):
    """Provenance for a single labeled prompt — how to reproduce it."""

    model_config = ConfigDict(extra="forbid")

    dataset: str = Field(description="Source dataset, e.g. 'gitbug-java'")
    bug_id: str = Field(description="Dataset-local identifier")
    commit: str = Field(description="Git SHA of the fix commit")
    parent_commit: str = Field(description="Git SHA of the buggy parent")


class LabeledPrompt(BaseModel):
    """One developer prompt with provenance and labels."""

    model_config = ConfigDict(extra="forbid")

    prompt_id: str
    prompt: str
    predicted_skills: list[SkillLabel] = Field(
        description="Labels assigned by the heuristic labeler"
    )
    ground_truth_skills: Optional[list[SkillLabel]] = Field(
        default=None,
        description="Labels assigned by a human verifier; None until verified",
    )
    source: BugSource
    metadata: dict = Field(default_factory=dict)


class Corpus(BaseModel):
    """A versioned collection of labeled prompts."""

    model_config = ConfigDict(extra="forbid")

    name: str
    version: str = Field(description="ISO date or semantic version of the corpus snapshot")
    prompts: list[LabeledPrompt]
```

- [ ] **Step 5: Run tests to verify they pass**

Run from `repo/sica-plugin/eval/`:

```bash
pytest tests/test_schemas.py -v
```

Expected: `4 passed`.

- [ ] **Step 6: Commit**

```bash
cd repo/sica-plugin
git add eval/setdrift_eval/corpus/__init__.py eval/setdrift_eval/corpus/schemas.py eval/tests/test_schemas.py
git commit -m "feat(corpus): add SkillLabel taxonomy and Pydantic schemas"
```

---

## Task 3: GitBug-Java Fetcher

**Files:**
- Create: `repo/sica-plugin/eval/setdrift_eval/corpus/fetcher.py`
- Create: `repo/sica-plugin/eval/tests/conftest.py`
- Modify: `repo/sica-plugin/eval/tests/test_smoke.py` *(not modified — separate test file)*

The fetcher clones `https://github.com/gitbugactions/gitbug-java` into `data/raw/gitbug-java/` (path is gitignored). It exposes an iterator over `BugRecord` objects parsed from the dataset's bug manifest files.

- [ ] **Step 1: Write conftest fixtures**

Create `repo/sica-plugin/eval/tests/conftest.py`:

```python
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
```

- [ ] **Step 2: Write the failing fetcher tests**

Create `repo/sica-plugin/eval/tests/test_fetcher.py`:

```python
"""Fetcher tests — exercise parsing logic with synthetic on-disk records."""
import json
from pathlib import Path

from setdrift_eval.corpus.fetcher import BugRecord, parse_bug_manifest


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
    import pydantic
    import pytest

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
```

Expected: `pytest tests/test_fetcher.py -v` fails with `ModuleNotFoundError: setdrift_eval.corpus.fetcher`.

- [ ] **Step 3: Implement the fetcher**

Create `repo/sica-plugin/eval/setdrift_eval/corpus/fetcher.py`:

```python
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
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

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


def clone_or_update(
    target_dir: Path = DEFAULT_RAW_DIR, repo_url: str = GITBUG_JAVA_REPO
) -> Path:
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
    candidates: list[Path] = list(raw_dir.glob("**/manifest.json")) + list(
        raw_dir.glob("*.json")
    )
    seen: set[str] = set()
    for path in candidates:
        try:
            record = parse_bug_manifest(path)
        except (KeyError, json.JSONDecodeError):
            continue
        if record.bug_id in seen:
            continue
        seen.add(record.bug_id)
        yield record
```

- [ ] **Step 4: Run fetcher tests to verify they pass**

Run from `repo/sica-plugin/eval/`:

```bash
pytest tests/test_fetcher.py -v
```

Expected: `2 passed`. (The frozen-model test confirms attribute assignment is rejected.)

- [ ] **Step 5: Commit**

```bash
cd repo/sica-plugin
git add eval/setdrift_eval/corpus/fetcher.py eval/tests/conftest.py eval/tests/test_fetcher.py
git commit -m "feat(corpus): add GitBug-Java fetcher and BugRecord schema"
```

---

## Task 4: Heuristic Labeler

**Files:**
- Create: `repo/sica-plugin/eval/setdrift_eval/corpus/labeler.py`
- Create: `repo/sica-plugin/eval/tests/test_labeler.py`

The labeler is a pure function: `(BugRecord) -> list[SkillLabel]`. It applies a fixed rule set to the diff text and file paths. Multiple labels can apply to one bug; the catch-all is `SkillLabel.NONE`.

- [ ] **Step 1: Write the failing labeler tests**

Create `repo/sica-plugin/eval/tests/test_labeler.py`:

```python
"""Heuristic labeler unit tests."""
from setdrift_eval.corpus.fetcher import BugRecord
from setdrift_eval.corpus.labeler import label_bug
from setdrift_eval.corpus.schemas import SkillLabel


def _make_record(diff: str, commit_message: str = "") -> BugRecord:
    return BugRecord(
        bug_id="x",
        commit="c",
        parent_commit="p",
        diff=diff,
        commit_message=commit_message,
    )


def test_pom_version_change_yields_dependency_bump(sample_diff_dependency_bump):
    labels = label_bug(_make_record(sample_diff_dependency_bump))
    assert SkillLabel.DEPENDENCY_BUMP in labels


def test_added_null_check_yields_null_check(sample_diff_null_check):
    labels = label_bug(_make_record(sample_diff_null_check))
    assert SkillLabel.NULL_CHECK in labels


def test_added_spring_annotation_yields_annotation_fix(sample_diff_spring_annotation):
    labels = label_bug(_make_record(sample_diff_spring_annotation))
    assert SkillLabel.SPRING_ANNOTATION_FIX in labels


def test_test_path_yields_test_fixture_fix():
    diff = "diff --git a/src/test/java/UserServiceTest.java b/src/test/java/UserServiceTest.java\n+@Mock private UserRepository repo;\n"
    labels = label_bug(_make_record(diff))
    assert SkillLabel.TEST_FIXTURE_FIX in labels


def test_application_properties_yields_config_property():
    diff = "diff --git a/src/main/resources/application.properties b/src/main/resources/application.properties\n-server.port=8080\n+server.port=8081\n"
    labels = label_bug(_make_record(diff))
    assert SkillLabel.CONFIG_PROPERTY in labels


def test_added_import_yields_import_fix():
    diff = "diff --git a/Foo.java b/Foo.java\n+import java.util.Optional;\n public class Foo {}\n"
    labels = label_bug(_make_record(diff))
    assert SkillLabel.IMPORT_FIX in labels


def test_jpa_annotation_change_yields_jpa_migration():
    diff = "diff --git a/User.java b/User.java\n+@Column(nullable = false)\n private String email;\n"
    labels = label_bug(_make_record(diff))
    assert SkillLabel.JPA_MIGRATION in labels


def test_unmatched_diff_yields_none():
    diff = "diff --git a/README.md b/README.md\n-old text\n+new text\n"
    labels = label_bug(_make_record(diff))
    assert labels == [SkillLabel.NONE]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_labeler.py -v
```

Expected: 8 errors, all `ModuleNotFoundError: setdrift_eval.corpus.labeler`.

- [ ] **Step 3: Implement the labeler**

Create `repo/sica-plugin/eval/setdrift_eval/corpus/labeler.py`:

```python
"""Rule-based heuristic labeler.

Each rule inspects the diff (and optionally the commit message) and contributes
zero or more SkillLabel values. The catch-all SkillLabel.NONE is appended only
when no other label matched.

These rules are intentionally simple and conservative. Precision matters more
than recall here because the labels feed into the 20% manual verification pass
(sampler.py); high recall with low precision wastes the verifier's time.
"""
import re

from setdrift_eval.corpus.fetcher import BugRecord
from setdrift_eval.corpus.schemas import SkillLabel

_POM_VERSION_RE = re.compile(r"^[-+].*<version>.*</version>", re.MULTILINE)
_NULL_CHECK_RE = re.compile(r"^\+.*(?:!= null|== null|Optional\.|Objects\.requireNonNull)", re.MULTILINE)
_SPRING_ANNOTATION_RE = re.compile(
    r"^\+.*@(?:Component|Service|Repository|Controller|RestController|Autowired|Configuration|Bean)\b",
    re.MULTILINE,
)
_JPA_ANNOTATION_RE = re.compile(
    r"^\+.*@(?:Entity|Table|Column|Id|GeneratedValue|JoinColumn|OneToMany|ManyToOne|ManyToMany)\b",
    re.MULTILINE,
)
_ADDED_IMPORT_RE = re.compile(r"^\+import\s", re.MULTILINE)
_TEST_PATH_RE = re.compile(r"diff --git a/.*(?:/test/|Test\.java|IT\.java)\b")
_CONFIG_PATH_RE = re.compile(r"diff --git a/.*(?:application\.properties|application\.ya?ml)\b")
_POM_PATH_RE = re.compile(r"diff --git a/.*(?:pom\.xml|build\.gradle)\b")


def label_bug(record: BugRecord) -> list[SkillLabel]:
    """Apply all rules and return the matching labels, or [NONE] if no rule fired.

    Order of checks is independent — every rule sees the full diff. We append
    NONE only when no other rule fired.
    """
    labels: list[SkillLabel] = []
    diff = record.diff

    if _POM_PATH_RE.search(diff) and _POM_VERSION_RE.search(diff):
        labels.append(SkillLabel.DEPENDENCY_BUMP)
    if _NULL_CHECK_RE.search(diff):
        labels.append(SkillLabel.NULL_CHECK)
    if _SPRING_ANNOTATION_RE.search(diff):
        labels.append(SkillLabel.SPRING_ANNOTATION_FIX)
    if _JPA_ANNOTATION_RE.search(diff):
        labels.append(SkillLabel.JPA_MIGRATION)
    if _TEST_PATH_RE.search(diff):
        labels.append(SkillLabel.TEST_FIXTURE_FIX)
    if _CONFIG_PATH_RE.search(diff):
        labels.append(SkillLabel.CONFIG_PROPERTY)
    if _ADDED_IMPORT_RE.search(diff) and SkillLabel.JPA_MIGRATION not in labels:
        # Avoid double-tagging JPA fixes that also touch imports.
        labels.append(SkillLabel.IMPORT_FIX)

    if not labels:
        labels.append(SkillLabel.NONE)
    return labels
```

- [ ] **Step 4: Run labeler tests to verify they pass**

Run:

```bash
pytest tests/test_labeler.py -v
```

Expected: `8 passed`. If a regex misses a fixture, tighten the rule and re-run; do not weaken the test.

- [ ] **Step 5: Commit**

```bash
cd repo/sica-plugin
git add eval/setdrift_eval/corpus/labeler.py eval/tests/test_labeler.py
git commit -m "feat(corpus): add rule-based heuristic labeler"
```

---

## Task 5: Prompt Synthesizer

**Files:**
- Create: `repo/sica-plugin/eval/setdrift_eval/corpus/synthesizer.py`
- Create: `repo/sica-plugin/eval/tests/test_synthesizer.py`

The synthesizer turns an issue's title + body + commit message into a single "developer prompt" string in the form a Claude Code user would actually type.

- [ ] **Step 1: Write the failing synthesizer tests**

Create `repo/sica-plugin/eval/tests/test_synthesizer.py`:

```python
"""Prompt synthesizer tests — issue+commit text becomes a realistic prompt."""
from setdrift_eval.corpus.fetcher import BugRecord
from setdrift_eval.corpus.synthesizer import synthesize_prompt


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_synthesizer.py -v
```

Expected: 4 errors, all `ModuleNotFoundError: setdrift_eval.corpus.synthesizer`.

- [ ] **Step 3: Implement the synthesizer**

Create `repo/sica-plugin/eval/setdrift_eval/corpus/synthesizer.py`:

```python
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
    stripped = re.sub(r"^(fix|chore|feat|refactor)(\([^)]+\))?:\s*", "", msg, count=1, flags=re.IGNORECASE)
    return f"Help me {stripped.rstrip('.')}."
```

- [ ] **Step 4: Run synthesizer tests to verify they pass**

Run:

```bash
pytest tests/test_synthesizer.py -v
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
cd repo/sica-plugin
git add eval/setdrift_eval/corpus/synthesizer.py eval/tests/test_synthesizer.py
git commit -m "feat(corpus): add prompt synthesizer with conventional-commit normalization"
```

---

## Task 6: Corpus Builder Pipeline

**Files:**
- Create: `repo/sica-plugin/eval/setdrift_eval/corpus/builder.py`
- Create: `repo/sica-plugin/eval/tests/test_builder.py`

The builder is the orchestration layer: iterate over bug records, label and synthesize each, write JSONL to the output path. It does not call out to the network in tests — tests run against a fixture directory of pre-staged manifest JSONs.

- [ ] **Step 1: Write the failing builder test**

Create `repo/sica-plugin/eval/tests/test_builder.py`:

```python
"""End-to-end builder integration test (network-free)."""
import json
from pathlib import Path

from setdrift_eval.corpus.builder import build_corpus
from setdrift_eval.corpus.schemas import Corpus, SkillLabel


def _write_manifest(target: Path, payload: dict) -> None:
    target.write_text(json.dumps(payload))


def test_build_corpus_produces_one_prompt_per_manifest(tmp_path: Path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_manifest(
        raw_dir / "bug-001.json",
        {
            "bug_id": "bug-001",
            "commit_hash": "c1",
            "parent_commit_hash": "p1",
            "diff": "diff --git a/pom.xml b/pom.xml\n-<version>1.0</version>\n+<version>1.1</version>\n",
            "commit_message": "fix: bump dependency",
            "issue_text": "Build fails after upgrading.",
            "project_id": "org/repo",
        },
    )
    _write_manifest(
        raw_dir / "bug-002.json",
        {
            "bug_id": "bug-002",
            "commit_hash": "c2",
            "parent_commit_hash": "p2",
            "diff": "diff --git a/Foo.java b/Foo.java\n+if (x != null) {}\n",
            "commit_message": "fix: NPE when x missing",
            "issue_text": "",
            "project_id": "org/repo",
        },
    )

    output_path = tmp_path / "corpus.jsonl"
    corpus = build_corpus(raw_dir=raw_dir, output_path=output_path, corpus_version="test-1")

    assert isinstance(corpus, Corpus)
    assert len(corpus.prompts) == 2

    # JSONL written to disk
    lines = output_path.read_text().strip().splitlines()
    assert len(lines) == 2

    # Labels reflect the diff content
    labels_by_id = {p.prompt_id: p.predicted_skills for p in corpus.prompts}
    assert SkillLabel.DEPENDENCY_BUMP in labels_by_id["gitbug-java-bug-001"]
    assert SkillLabel.NULL_CHECK in labels_by_id["gitbug-java-bug-002"]


def test_build_corpus_handles_empty_dir(tmp_path: Path):
    raw_dir = tmp_path / "raw-empty"
    raw_dir.mkdir()
    output_path = tmp_path / "empty.jsonl"
    corpus = build_corpus(raw_dir=raw_dir, output_path=output_path, corpus_version="test-empty")
    assert corpus.prompts == []
    assert output_path.read_text() == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_builder.py -v
```

Expected: 2 errors, `ModuleNotFoundError: setdrift_eval.corpus.builder`.

- [ ] **Step 3: Implement the builder**

Create `repo/sica-plugin/eval/setdrift_eval/corpus/builder.py`:

```python
"""Corpus builder pipeline.

Reads BugRecord objects from a raw data directory, applies the labeler and
synthesizer, and writes JSONL to disk. Returns the in-memory Corpus so callers
can compute aggregate stats without re-reading.
"""
from pathlib import Path

from setdrift_eval.corpus.fetcher import iter_bug_records
from setdrift_eval.corpus.labeler import label_bug
from setdrift_eval.corpus.schemas import BugSource, Corpus, LabeledPrompt
from setdrift_eval.corpus.synthesizer import synthesize_prompt


def build_corpus(
    raw_dir: Path,
    output_path: Path,
    corpus_version: str,
    corpus_name: str = "gitbug-java",
) -> Corpus:
    """Build a corpus from a directory of bug manifest JSON files.

    Each bug becomes one LabeledPrompt. Output is written as JSONL (one
    LabeledPrompt per line) to ``output_path``; the parent directory is created
    if missing.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    prompts: list[LabeledPrompt] = []
    with output_path.open("w", encoding="utf-8") as out:
        for record in iter_bug_records(Path(raw_dir)):
            labels = label_bug(record)
            prompt_text = synthesize_prompt(record)
            entry = LabeledPrompt(
                prompt_id=f"{corpus_name}-{record.bug_id}",
                prompt=prompt_text,
                predicted_skills=labels,
                source=BugSource(
                    dataset=corpus_name,
                    bug_id=record.bug_id,
                    commit=record.commit,
                    parent_commit=record.parent_commit,
                ),
                metadata={"project_id": record.project_id} if record.project_id else {},
            )
            out.write(entry.model_dump_json() + "\n")
            prompts.append(entry)

    return Corpus(name=corpus_name, version=corpus_version, prompts=prompts)
```

- [ ] **Step 4: Run builder tests to verify they pass**

Run:

```bash
pytest tests/test_builder.py -v
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
cd repo/sica-plugin
git add eval/setdrift_eval/corpus/builder.py eval/tests/test_builder.py
git commit -m "feat(corpus): add JSONL corpus builder pipeline"
```

---

## Task 7: CLI Subcommand

**Files:**
- Modify: `repo/sica-plugin/eval/setdrift_eval/cli.py`
- Create: `repo/sica-plugin/eval/tests/test_cli.py`

Add a `corpus` parent subcommand with `build` and `verify` children. The `build` action delegates to the builder pipeline; `verify` delegates to the sampler (Task 8).

- [ ] **Step 1: Write the failing CLI test**

Create `repo/sica-plugin/eval/tests/test_cli.py`:

```python
"""CLI argparse wiring tests."""
import sys
from pathlib import Path

from setdrift_eval.cli import main


def test_corpus_build_invokes_pipeline(monkeypatch, tmp_path: Path, capsys):
    """`setdrift-eval corpus build --raw-dir X --output Y --version Z` runs the builder."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    output_path = tmp_path / "out.jsonl"

    calls: dict[str, object] = {}

    def fake_build_corpus(raw_dir: Path, output_path: Path, corpus_version: str, corpus_name: str = "gitbug-java"):
        from setdrift_eval.corpus.schemas import Corpus

        calls["raw_dir"] = raw_dir
        calls["output_path"] = output_path
        calls["corpus_version"] = corpus_version
        return Corpus(name=corpus_name, version=corpus_version, prompts=[])

    monkeypatch.setattr("setdrift_eval.cli.build_corpus", fake_build_corpus, raising=True)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "setdrift-eval",
            "corpus",
            "build",
            "--raw-dir",
            str(raw_dir),
            "--output",
            str(output_path),
            "--version",
            "2026-05-22",
        ],
    )

    exit_code = main()

    assert exit_code == 0
    assert calls["raw_dir"] == raw_dir
    assert calls["output_path"] == output_path
    assert calls["corpus_version"] == "2026-05-22"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_cli.py -v
```

Expected: `AttributeError` or `ImportError` on the `setdrift_eval.cli.build_corpus` reference.

- [ ] **Step 3: Update the CLI**

Replace the contents of `repo/sica-plugin/eval/setdrift_eval/cli.py` with:

```python
"""CLI entrypoint for the setdrift-eval harness."""
import argparse
from pathlib import Path

from setdrift_eval.corpus.builder import build_corpus


def main() -> int:
    parser = argparse.ArgumentParser(prog="setdrift-eval", description="SICA evaluation harness")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("benchmark", help="run the offline replay benchmark")
    sub.add_parser("optimize", help="run the skill-trigger optimizer")
    sub.add_parser("health", help="compute config health metrics from telemetry")

    corpus_parser = sub.add_parser("corpus", help="build and verify the public prompt corpus")
    corpus_sub = corpus_parser.add_subparsers(dest="corpus_cmd")

    build_p = corpus_sub.add_parser("build", help="build the labeled corpus JSONL")
    build_p.add_argument("--raw-dir", type=Path, default=Path("data/raw/gitbug-java"))
    build_p.add_argument("--output", type=Path, default=Path("data/corpus/gitbug-java.jsonl"))
    build_p.add_argument("--version", required=True, help="corpus version tag, e.g. 2026-05-22")

    verify_p = corpus_sub.add_parser("verify", help="emit a 20%% manual-verification CSV")
    verify_p.add_argument("--corpus", type=Path, required=True)
    verify_p.add_argument("--output", type=Path, default=Path("data/corpus/verify.csv"))
    verify_p.add_argument("--seed", type=int, default=42)

    args = parser.parse_args()

    if args.cmd == "corpus" and args.corpus_cmd == "build":
        corpus = build_corpus(
            raw_dir=args.raw_dir, output_path=args.output, corpus_version=args.version
        )
        print(f"[setdrift-eval] built corpus with {len(corpus.prompts)} prompts -> {args.output}")
        return 0
    if args.cmd == "corpus" and args.corpus_cmd == "verify":
        from setdrift_eval.corpus.sampler import emit_verification_csv

        emit_verification_csv(
            corpus_path=args.corpus, output_path=args.output, seed=args.seed
        )
        print(f"[setdrift-eval] verification CSV written -> {args.output}")
        return 0

    print(f"[setdrift-eval] '{args.cmd or 'help'}' not yet implemented — scaffold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run CLI tests to verify they pass**

Run:

```bash
pytest tests/test_cli.py -v
```

Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
cd repo/sica-plugin
git add eval/setdrift_eval/cli.py eval/tests/test_cli.py
git commit -m "feat(cli): wire 'corpus build' and 'corpus verify' subcommands"
```

---

## Task 8: Manual Verification Sampler

**Files:**
- Create: `repo/sica-plugin/eval/setdrift_eval/corpus/sampler.py`
- Create: `repo/sica-plugin/eval/tests/test_sampler.py`

The sampler reads a JSONL corpus, randomly samples 20% (seeded for reproducibility), and writes a CSV with columns `[prompt_id, prompt, predicted_skills, verified_skills, notes]` for a human to fill in. After the human edits `verified_skills` and saves, a separate command (out of scope here — covered in Task 9 docs) can compute heuristic precision against the human labels.

- [ ] **Step 1: Write the failing sampler test**

Create `repo/sica-plugin/eval/tests/test_sampler.py`:

```python
"""Verification sampler tests."""
import csv
from pathlib import Path

from setdrift_eval.corpus.sampler import emit_verification_csv


def _write_jsonl(path: Path, n: int) -> None:
    import json

    with path.open("w", encoding="utf-8") as f:
        for i in range(n):
            f.write(
                json.dumps(
                    {
                        "prompt_id": f"p-{i}",
                        "prompt": f"prompt text {i}",
                        "predicted_skills": ["none"],
                        "ground_truth_skills": None,
                        "source": {
                            "dataset": "gitbug-java",
                            "bug_id": str(i),
                            "commit": "c",
                            "parent_commit": "p",
                        },
                        "metadata": {},
                    }
                )
                + "\n"
            )


def test_sampler_emits_twenty_percent(tmp_path: Path):
    corpus_path = tmp_path / "corpus.jsonl"
    output_path = tmp_path / "verify.csv"
    _write_jsonl(corpus_path, n=100)

    emit_verification_csv(corpus_path=corpus_path, output_path=output_path, seed=42)

    with output_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 20
    assert set(rows[0].keys()) == {"prompt_id", "prompt", "predicted_skills", "verified_skills", "notes"}
    assert rows[0]["verified_skills"] == ""  # for human to fill in


def test_sampler_is_deterministic_under_same_seed(tmp_path: Path):
    corpus_path = tmp_path / "corpus.jsonl"
    _write_jsonl(corpus_path, n=50)

    out_a = tmp_path / "a.csv"
    out_b = tmp_path / "b.csv"
    emit_verification_csv(corpus_path=corpus_path, output_path=out_a, seed=7)
    emit_verification_csv(corpus_path=corpus_path, output_path=out_b, seed=7)

    assert out_a.read_text() == out_b.read_text()


def test_sampler_handles_small_corpus(tmp_path: Path):
    """A 3-prompt corpus produces at least 1 row (rounded up)."""
    corpus_path = tmp_path / "corpus.jsonl"
    output_path = tmp_path / "verify.csv"
    _write_jsonl(corpus_path, n=3)

    emit_verification_csv(corpus_path=corpus_path, output_path=output_path, seed=1)

    with output_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_sampler.py -v
```

Expected: 3 errors, `ModuleNotFoundError: setdrift_eval.corpus.sampler`.

- [ ] **Step 3: Implement the sampler**

Create `repo/sica-plugin/eval/setdrift_eval/corpus/sampler.py`:

```python
"""Manual-verification sampler.

Reads a JSONL corpus, samples 20% (rounded up, minimum 1), and writes a CSV
with one row per sampled prompt. The CSV's verified_skills column is left
blank for a human verifier to fill in; the notes column is free-form.
"""
import csv
import json
import math
import random
from pathlib import Path

DEFAULT_FRACTION = 0.20


def emit_verification_csv(
    corpus_path: Path,
    output_path: Path,
    seed: int = 42,
    fraction: float = DEFAULT_FRACTION,
) -> None:
    corpus_path = Path(corpus_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    with corpus_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))

    n = max(1, math.ceil(len(rows) * fraction)) if rows else 0
    rng = random.Random(seed)
    sample = rng.sample(rows, k=n) if rows else []

    with output_path.open("w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(
            out,
            fieldnames=["prompt_id", "prompt", "predicted_skills", "verified_skills", "notes"],
        )
        writer.writeheader()
        for row in sample:
            writer.writerow(
                {
                    "prompt_id": row["prompt_id"],
                    "prompt": row["prompt"],
                    "predicted_skills": ",".join(row.get("predicted_skills", [])),
                    "verified_skills": "",
                    "notes": "",
                }
            )
```

- [ ] **Step 4: Run sampler tests to verify they pass**

Run:

```bash
pytest tests/test_sampler.py -v
```

Expected: `3 passed`.

- [ ] **Step 5: Run the full test suite as a regression check**

Run:

```bash
pytest -v
```

Expected: every test introduced in tasks 1-8 passes (totals: smoke 1 + schemas 4 + fetcher 2 + labeler 8 + synthesizer 4 + builder 2 + cli 1 + sampler 3 = **25 passed**).

- [ ] **Step 6: Commit**

```bash
cd repo/sica-plugin
git add eval/setdrift_eval/corpus/sampler.py eval/tests/test_sampler.py
git commit -m "feat(corpus): add seeded 20%% verification sampler"
```

---

## Task 9: Documentation + Real Run

**Files:**
- Create: `repo/sica-plugin/docs/corpus.md`
- Modify: `repo/sica-plugin/README.md` (add a "Building the public corpus" link)

The doc captures the recipe for a human to run end-to-end against the real GitBug-Java repo, plus how to extend the skill taxonomy.

- [ ] **Step 1: Write the corpus docs**

Create `repo/sica-plugin/docs/corpus.md`:

````markdown
# Public Corpus Construction

The public prompt corpus (`data/corpus/gitbug-java.jsonl`) is the GitBug-Java–derived prompt corpus that feeds the falsifiable claim's skill-trigger F1 measurement (see `docs/design/2026-05-20-falsifiable-claim.md` §4).

## Build pipeline

```bash
cd eval
pip install -e ".[dev]"

# 1. Fetch the upstream dataset (idempotent; clones or pulls).
python -c "from setdrift_eval.corpus.fetcher import clone_or_update; clone_or_update()"

# 2. Build the labeled corpus.
setdrift-eval corpus build --version 2026-05-22

# 3. Emit a 20% manual-verification sample.
setdrift-eval corpus verify --corpus data/corpus/gitbug-java.jsonl
```

Output files (all gitignored under `data/`):
- `data/raw/gitbug-java/` — upstream dataset clone
- `data/corpus/gitbug-java.jsonl` — one `LabeledPrompt` per line
- `data/corpus/verify.csv` — 20% sample for manual labeling

## Skill taxonomy (eight labels)

| Label | Heuristic trigger |
|---|---|
| `dependency-bump` | `pom.xml` / `build.gradle` with `<version>` changes |
| `null-check` | Added lines containing `!= null`, `Optional.`, `Objects.requireNonNull` |
| `spring-annotation-fix` | Added `@Component`, `@Service`, `@Autowired`, etc. |
| `jpa-migration` | Added `@Entity`, `@Table`, `@Column`, etc. |
| `test-fixture-fix` | Diff touches `**/test/**` or `*Test.java` / `*IT.java` |
| `config-property` | Diff touches `application.properties` / `application.yml` |
| `import-fix` | Added `import` lines (excluding JPA double-tags) |
| `none` | Catch-all when no other rule fires |

The taxonomy is fixed for v1 of the corpus. Adding labels requires:
1. Adding the value to `SkillLabel` in `eval/setdrift_eval/corpus/schemas.py`.
2. Adding the heuristic rule to `eval/setdrift_eval/corpus/labeler.py`.
3. Bumping the corpus version string so downstream consumers re-verify.

## Manual verification protocol

1. Open `data/corpus/verify.csv` in any spreadsheet tool.
2. For each row, read the `prompt` and decide which skill labels from the taxonomy *should* fire. Fill `verified_skills` as a comma-separated list. Use `notes` if the prompt is ambiguous or out-of-scope.
3. Save the file. Heuristic precision is then computed as the fraction of rows where `predicted_skills == verified_skills`. A precision floor of 0.85 is the design-spec gate; if precision is lower, expand manual labeling before proceeding.

## Reaching the ≥500-prompt target

GitBug-Java provides 199 reproducible Java bugs. To reach the ≥500 target in the falsifiable claim's pre-registered fallback corpus list, layer in Defects4J (357 bugs) via a follow-up plan that reuses this corpus's schemas and labeler but adds a Defects4J-specific fetcher.
````

- [ ] **Step 2: Add a link from the top-level README**

Edit `repo/sica-plugin/README.md`. Find the "Quickstart" section (around line 40-50) and add immediately after it:

```markdown
## Building the public corpus

The skill-trigger F1 measurement runs on a labeled prompt corpus mined from
GitBug-Java. See `docs/corpus.md` for the build and verification recipe.
```

- [ ] **Step 3: Real-world smoke run**

Run end-to-end against the actual upstream dataset (this DOES hit the network):

```bash
cd repo/sica-plugin/eval
python -c "from setdrift_eval.corpus.fetcher import clone_or_update; clone_or_update()"
setdrift-eval corpus build --version 2026-05-22
```

Expected output: `[setdrift-eval] built corpus with N prompts -> data/corpus/gitbug-java.jsonl` where N is in the range 150-199.

If N is 0: the upstream manifest schema has changed since this plan was written. Inspect a few files under `data/raw/gitbug-java/` and update `parse_bug_manifest` in `fetcher.py` to match the actual field names.

- [ ] **Step 4: Spot-check the output**

Run:

```bash
head -3 data/corpus/gitbug-java.jsonl
```

Each line should parse as JSON and contain `prompt_id`, `prompt`, `predicted_skills`, `source.commit`, etc. Sanity-check that at least one prompt has a non-`none` label.

- [ ] **Step 5: Commit**

```bash
cd repo/sica-plugin
git add docs/corpus.md README.md
git commit -m "docs: add public corpus build recipe and skill-taxonomy reference"
```

- [ ] **Step 6: Push to GitHub**

```bash
git push origin main
```

Expected: push succeeds; visible at https://github.com/thanhtrungnguyen/sica-plugin

---

## Out of Scope (Follow-up Plans)

- **Defects4J fetcher/labeler** — needed to reach the ≥500-prompt target in the design spec's primary corpus.
- **Benchmark harness MVP** — runs Claude Code under arms B and C on this corpus and computes skill-trigger F1.
- **Telemetry parser** — for the enterprise (parking) corpus, gated on the VinSmart IP ruling.
- **Optimizer integration (arm A)** — DSPy/GEPA wiring; runs only after arms B and C are producing stable F1 numbers.

These four follow-up plans (in roughly this order) complete the eval-harness build outlined in `docs/design/2026-05-20-falsifiable-claim.md`.

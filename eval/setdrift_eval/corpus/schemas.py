"""Pydantic schemas for the public corpus.

The SkillLabel taxonomy is fixed at eight values. Extending the taxonomy
requires updating the labeler rules in labeler.py and bumping the corpus
version string so downstream consumers know labels may have shifted.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class SkillLabel(str, Enum):
    """Canonical skill labels.

    Definitions live in docs/design/2026-05-20-falsifiable-claim.md §4 (until
    docs/corpus.md is added in Task 9 of the plan).
    """

    JPA_MIGRATION = "jpa-migration"
    SPRING_ANNOTATION_FIX = "spring-annotation-fix"
    DEPENDENCY_BUMP = "dependency-bump"
    NULL_CHECK = "null-check"
    TEST_FIXTURE_FIX = "test-fixture-fix"
    CONFIG_PROPERTY = "config-property"
    IMPORT_FIX = "import-fix"
    # NONE means: a labeler explicitly inspected the diff and found no rule
    # applies. It is distinct from an empty list (labeling not attempted) and
    # from ground_truth_skills=None (not yet manually verified).
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
    ground_truth_skills: list[SkillLabel] | None = Field(
        default=None,
        description="Labels assigned by a human verifier; None until verified",
    )
    source: BugSource
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Freeform string-keyed metadata (e.g. language, framework). Not part of the labeling spine.",
    )


class Corpus(BaseModel):
    """A versioned collection of labeled prompts."""

    model_config = ConfigDict(extra="forbid")

    name: str
    version: str = Field(description="ISO date or semantic version of the corpus snapshot")
    prompts: list[LabeledPrompt]

"""Schema round-trip and validation tests."""
import json

import pytest
from pydantic import ValidationError

from sica_eval.corpus.schemas import (
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

    restored = Corpus.model_validate_json(serialized)
    assert restored == corpus
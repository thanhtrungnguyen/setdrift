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

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

    Order of checks is independent -- every rule sees the full diff. We append
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
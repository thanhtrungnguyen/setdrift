"""Task 1 TDD tests (Plan 03-06): spring-jpa-entity SKILL.md + re-frozen intent map.

RED phase: these tests must FAIL before the implementation is in place.

Covers:
  - load_skill_tools returns a tool named 'spring_jpa_entity' (name sanitization)
  - load_intent_map includes jpa-migration -> [spring_jpa_entity] (no longer holdout)
  - scored_intents() includes jpa-migration (not held out)
  - Both SKILL.md descriptions contain the deliberate D-45 overlap phrase
    "Spring annotation patterns in the parking services"
"""
from pathlib import Path

import pytest
import yaml

# Resolve paths relative to the sica-plugin root (parents[2] = sica-plugin/)
# test file: eval/tests/test_*.py -> parents[0]=eval/tests, [1]=eval, [2]=sica-plugin
_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
_SKILLS_DIR = _PLUGIN_ROOT / "plugin" / "skills"
_JPA_SKILL_MD = _SKILLS_DIR / "spring-jpa-entity" / "SKILL.md"
_ENDPOINT_SKILL_MD = _SKILLS_DIR / "spring-boot-endpoint" / "SKILL.md"
_INTENT_MAP_PATH = _PLUGIN_ROOT / "eval" / "setdrift_eval" / "corpus" / "intent_skill_map.yaml"

OVERLAP_PHRASE = "Spring annotation patterns in the parking services"


def test_spring_jpa_entity_tool_is_loaded():
    """load_skill_tools(plugin/skills) returns a tool named 'spring_jpa_entity'."""
    from setdrift_eval.benchmark.arm_runner import load_skill_tools

    tools = load_skill_tools(_SKILLS_DIR)
    names = [t["name"] for t in tools]
    assert "spring_jpa_entity" in names, (
        f"Expected 'spring_jpa_entity' in loaded tools but got {names}. "
        "Create plugin/skills/spring-jpa-entity/SKILL.md."
    )


def test_spring_jpa_entity_skill_md_exists():
    """plugin/skills/spring-jpa-entity/SKILL.md must exist."""
    assert _JPA_SKILL_MD.exists(), (
        f"Missing: {_JPA_SKILL_MD}. "
        "Create the SKILL.md for the confusable-pair JPA skill (D-44)."
    )


def test_spring_jpa_entity_has_entity_annotation():
    """SKILL.md for spring-jpa-entity must mention @Entity."""
    assert _JPA_SKILL_MD.exists(), "SKILL.md not found — create it first."
    content = _JPA_SKILL_MD.read_text(encoding="utf-8")
    assert "@Entity" in content, (
        "spring-jpa-entity/SKILL.md must mention '@Entity' per D-44 scope."
    )


def test_intent_map_includes_jpa_migration_skill():
    """intent_skill_map.yaml must map jpa-migration -> [spring_jpa_entity]."""
    raw = yaml.safe_load(_INTENT_MAP_PATH.read_text(encoding="utf-8"))
    jpa_skills = raw.get("jpa-migration", [])
    assert "spring_jpa_entity" in (jpa_skills or []), (
        f"jpa-migration maps to {jpa_skills!r}; expected ['spring_jpa_entity']. "
        "Update intent_skill_map.yaml per D-44."
    )


def test_jpa_migration_no_longer_holdout():
    """After the map update, scored_intents() must include 'jpa-migration'."""
    from setdrift_eval.telemetry.scorer import load_intent_map, scored_intents

    mapping, _ = load_intent_map(_INTENT_MAP_PATH)
    scored = scored_intents(mapping)
    assert "jpa-migration" in scored, (
        f"'jpa-migration' not in scored_intents; scored={scored}. "
        "The map re-freeze must lift jpa-migration out of the holdout (D-44)."
    )


def test_spring_boot_endpoint_description_has_overlap_phrase():
    """spring-boot-endpoint SKILL.md description must contain the D-45 overlap phrase."""
    text = _ENDPOINT_SKILL_MD.read_text(encoding="utf-8")
    assert OVERLAP_PHRASE in text, (
        f"spring-boot-endpoint/SKILL.md must contain '{OVERLAP_PHRASE}' "
        "for the D-45 confusable-pair baseline cross-firing."
    )


def test_spring_jpa_entity_description_has_overlap_phrase():
    """spring-jpa-entity SKILL.md description must contain the D-45 overlap phrase."""
    assert _JPA_SKILL_MD.exists(), "SKILL.md not found — create it first."
    text = _JPA_SKILL_MD.read_text(encoding="utf-8")
    assert OVERLAP_PHRASE in text, (
        f"spring-jpa-entity/SKILL.md must contain '{OVERLAP_PHRASE}' "
        "for the D-45 confusable-pair baseline cross-firing."
    )

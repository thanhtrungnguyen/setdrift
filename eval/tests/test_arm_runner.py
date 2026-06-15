"""Offline arm-harness tests (Plan 02-04 Task 3, D-32). Fully offline."""
import re

from setdrift_eval.benchmark import arm_runner

_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def test_build_skill_tool_sanitizes_name():
    tool = arm_runner.build_skill_tool("spring-boot-endpoint", "Create a REST endpoint.")
    assert tool["name"] == "spring_boot_endpoint"
    assert _NAME_RE.match(tool["name"])
    assert tool["input_schema"] == {"type": "object", "properties": {}, "required": []}


def test_load_skill_tools_reads_frontmatter(tmp_path):
    skill = tmp_path / "spring-boot-endpoint" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: spring-boot-endpoint\ndescription: Create a REST endpoint.\n---\n# body\n",
        encoding="utf-8",
    )
    tools = arm_runner.load_skill_tools(tmp_path)
    assert len(tools) == 1
    assert tools[0]["name"] == "spring_boot_endpoint"
    assert "endpoint" in tools[0]["description"]


def test_run_arm_returns_fired_set(tmp_path, mock_anthropic_client):
    tools = [arm_runner.build_skill_tool("spring-boot-endpoint", "Create a REST endpoint.")]
    fired = arm_runner.run_arm("add an endpoint", tools, cache_dir=tmp_path)
    assert fired == {"spring_boot_endpoint"}


def test_arm_c_empty(tmp_path, mock_anthropic_client):
    """Arm C returns an empty set and the mock produced no tool_use block."""
    fired = arm_runner.run_arm_c("what is 2+2?", cache_dir=tmp_path)
    assert fired == set()
    # The recorded call carried no toolset (zero-config floor).
    assert "tools" not in mock_anthropic_client[-1]

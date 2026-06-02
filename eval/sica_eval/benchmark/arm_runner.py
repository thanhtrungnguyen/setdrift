"""Offline tool-use arm harness (D-32).

Registers skills as Anthropic API tools and runs each prompt at temperature 0 on
the pinned model; the FIRED set is the tool names the model chose to invoke
(intent-space projection is the scorer's job, 02-05 — not here). Results are
content-addressed/cached via response_cache so the noise-band runs are cheap and
replay is deterministic.

- Arm B: real skill toolset → fired = {tool_use block names}.
- Arm C: empty toolset → always-NONE zero-configuration floor (fires nothing).

Model is pinned via SICA_MODEL (default claude-sonnet-4-6). The tool_choice /
empty-toolset decision lives entirely in response_cache.load_or_call — this
module never builds the create kwargs itself.
"""
import os
from pathlib import Path

import yaml

from sica_eval.benchmark.response_cache import CACHE_DIR, load_or_call

MODEL = os.environ.get("SICA_MODEL", "claude-sonnet-4-6")


def build_skill_tool(name: str, description: str) -> dict:
    """Convert a SKILL.md name+description into a minimal Anthropic tool spec.

    Sanitizes the name to the Anthropic tool-name constraint
    ^[a-zA-Z0-9_-]{1,64}$ (spaces and dashes → underscores, truncated to 64).
    """
    sanitized = name.replace(" ", "_").replace("-", "_")[:64]
    return {
        "name": sanitized,
        "description": description,
        "input_schema": {"type": "object", "properties": {}, "required": []},
    }


def load_skill_tools(skills_dir: Path) -> list[dict]:
    """Read each `<skill>/SKILL.md` frontmatter (name + description) into a tool spec."""
    skills_dir = Path(skills_dir)
    tools: list[dict] = []
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        text = skill_md.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        _, frontmatter, _ = text.split("---", 2)
        meta = yaml.safe_load(frontmatter)
        tools.append(build_skill_tool(meta["name"], meta["description"]))
    return tools


def run_arm(
    prompt: str,
    tools: list[dict],
    *,
    model: str = MODEL,
    cache_dir: Path = CACHE_DIR,
) -> set[str]:
    """Arm B (and future Arm A): return the set of fired tool names for one prompt."""
    data = load_or_call(model=model, prompt=prompt, tools=tools, cache_dir=cache_dir)
    return {b["name"] for b in data["content"] if b.get("type") == "tool_use"}


def run_arm_c(prompt: str, *, model: str = MODEL, cache_dir: Path = CACHE_DIR) -> set[str]:
    """Arm C: empty toolset → always-NONE floor. Provably fires nothing."""
    data = load_or_call(model=model, prompt=prompt, tools=[], cache_dir=cache_dir)
    assert not any(
        b.get("type") == "tool_use" for b in data["content"]
    ), "Arm C must never fire a tool_use block (empty toolset)"
    return set()

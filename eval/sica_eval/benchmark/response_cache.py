"""Content-addressed response cache for the offline arm harness (D-32).

Cache key = sha256(model + prompt + sorted_tool_specs). The same (model, prompt,
tools) replays from disk with zero API calls, so all 5 noise-band runs after the
first are free and replay is deterministic. Cache lives under data/cache/
(gitignored — inside the data wall).

Eval-side fail-loud: API errors propagate (no bare except). The tool_choice /
empty-toolset decision lives ENTIRELY here — Arm B (tools present) sends
tool_choice={"type":"auto"}; Arm C (empty toolset) omits BOTH tools and
tool_choice, because the Anthropic API rejects tool_choice without >=1 tool.
"""
import hashlib
import json
import os
from pathlib import Path

import anthropic

CACHE_DIR = Path(os.environ.get("SICA_CACHE_DIR", "data/cache"))
MAX_TOKENS = 256  # only tool selection matters; generated text is irrelevant


def cache_key(model: str, prompt: str, tools: list[dict]) -> str:
    """Deterministic SHA-256 key. Tools sorted by name so order can't change it.

    The key includes the model and the FULL toolset, so Arm B, Arm C, and any
    future Arm A never collide on a cache entry (cache-poisoning defense).
    """
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "tools": sorted(tools, key=lambda t: t["name"]),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_or_call(model: str, prompt: str, tools: list[dict], cache_dir: Path) -> dict:
    """Return the cached response dict, or call the API once and persist it."""
    cache_dir = Path(cache_dir)
    key = cache_key(model, prompt, tools)
    cached = cache_dir / f"{key}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))

    # Cache miss — call the API (fail-loud: let anthropic.APIError propagate).
    client = anthropic.Anthropic()
    kwargs: dict = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = {"type": "auto"}  # D-32 — only valid with >=1 tool
    # else (Arm C): omit BOTH tools and tool_choice — passing tool_choice with an
    # empty/absent toolset raises "tool_choice requires at least one tool".
    response = client.messages.create(**kwargs)

    data = {
        "content": [b.model_dump() for b in response.content],
        "usage": response.usage.model_dump(),
        "stop_reason": response.stop_reason,
    }
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(data), encoding="utf-8")
    return data

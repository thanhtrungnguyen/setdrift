"""Content-addressed response cache for the offline arm harness (D-32).

Cache key = sha256(model + prompt + sorted_tool_specs). The same (model, prompt,
tools) replays from disk with zero API calls, so all 5 noise-band runs after the
first are free and replay is deterministic. Cache lives under data/cache/
(gitignored — inside the data wall).

This module is a pluggable-transport delegate, NOT part of the Goodhart firewall.
The frozen firewall files are scorer.py, experiment.py, and arm_runner.py.
The tool_choice / max_tokens / temperature decision lives in llm_backend.py;
response_cache.py is responsible only for key generation, cache lookup, and
persistence. The actual model call is delegated to llm_backend.call_model so
the backend (anthropic | openrouter) is transparent to this layer.

Eval-side fail-loud: API errors propagate (no bare except).
"""
import hashlib
import json
import os
from pathlib import Path

from setdrift_eval.benchmark.llm_backend import call_model

CACHE_DIR = Path(os.environ.get("SICA_CACHE_DIR", "data/cache"))


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

    # Cache miss — delegate to the pluggable transport (fail-loud: API errors propagate).
    data = call_model(model, prompt, tools)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(data), encoding="utf-8")
    return data

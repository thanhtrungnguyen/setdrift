"""Pluggable LLM transport layer for the SICA eval harness.

Dispatches on SICA_LLM_BACKEND (default: "anthropic"):
  - "anthropic" : Anthropic Messages API — behavior byte-identical to the original
                  inline call in response_cache.py (pre-refactor t=0 baseline).
  - "openrouter": OpenAI Chat-Completions wire format routed through OpenRouter,
                  provider-locked to first-party Anthropic by default.

The tool_choice / empty-toolset decision lives entirely here:
  - Arm B (tools present):  sends tool_choice={"type":"auto"} (anthropic) or "auto" (openrouter).
  - Arm C (empty toolset):  omits BOTH tools and tool_choice, because the Anthropic API
                            rejects tool_choice without >=1 tool.

eval-side fail-loud: API errors propagate — no bare except anywhere in this module.
"""
import json
import os

import anthropic  # module-level so the test fixture can patch sica_eval.benchmark.llm_backend.anthropic.Anthropic
import openai  # module-level so the test fixture can patch sica_eval.benchmark.llm_backend.openai.OpenAI

MAX_TOKENS = 256  # only tool selection matters; generated text is irrelevant


def call_model(model: str, prompt: str, tools: list[dict]) -> dict:
    """Dispatch to the configured LLM backend and return the canonical response dict.

    The returned dict always has the shape:
        {
            "content":     list[dict]  — tool_use blocks: {"type":"tool_use","name":<str>,"input":<dict>}
            "usage":       dict        — {"input_tokens": int, "output_tokens": int}
            "stop_reason": str         — e.g. "tool_use" or "end_turn"
        }

    This shape is the contract consumed verbatim by arm_runner.py and scorer.py;
    do NOT change field names or nesting.

    Raises:
        ValueError: if SICA_LLM_BACKEND is set to an unrecognised backend.
    """
    backend = os.environ.get("SICA_LLM_BACKEND", "anthropic")
    if backend == "anthropic":
        return _call_anthropic(model, prompt, tools)
    if backend == "openrouter":
        return _call_openrouter(model, prompt, tools)
    raise ValueError(
        f"Unknown SICA_LLM_BACKEND={backend!r}. Supported values: 'anthropic', 'openrouter'."
    )


# ---------------------------------------------------------------------------
# Anthropic backend (default)
# ---------------------------------------------------------------------------

def _call_anthropic(model: str, prompt: str, tools: list[dict]) -> dict:
    """Call the Anthropic Messages API.

    Logic moved verbatim from response_cache.py (pre-refactor) so the default
    backend is byte-identical to the t=0 baseline.
    """
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
    return {
        "content": [b.model_dump() for b in response.content],
        "usage": response.usage.model_dump(),
        "stop_reason": response.stop_reason,
    }


# ---------------------------------------------------------------------------
# OpenRouter backend (OpenAI Chat-Completions wire format)
# ---------------------------------------------------------------------------

def _call_openrouter(model: str, prompt: str, tools: list[dict]) -> dict:
    """Call the OpenRouter API using the OpenAI Chat-Completions wire format.

    Provider-locked to first-party Anthropic by default (configurable via env).
    Model ids for OpenRouter MUST use dot notation, e.g. "anthropic/claude-sonnet-4.6".

    Environment variables (all optional except OPENROUTER_API_KEY):
        OPENROUTER_API_KEY            — required; KeyError propagates if unset (fail-loud).
        SICA_OPENROUTER_PROVIDER      — JSON list of provider names; default '["Anthropic"]'.
        SICA_OPENROUTER_ALLOW_FALLBACKS — "true"/"false"; default "false" (no fallbacks).
    """
    client = openai.OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],  # KeyError propagates — fail-loud
    )

    # Provider lock: default to first-party Anthropic, no fallbacks.
    provider_order: list[str] = json.loads(
        os.environ.get("SICA_OPENROUTER_PROVIDER", '["Anthropic"]')
    )
    allow_fallbacks: bool = (
        os.environ.get("SICA_OPENROUTER_ALLOW_FALLBACKS", "false").lower() == "true"
    )

    # Convert Anthropic tool specs to OpenAI function specs.
    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]

    kwargs: dict = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
        "extra_body": {
            "provider": {
                "order": provider_order,
                "allow_fallbacks": allow_fallbacks,
            }
        },
    }
    if tools:
        kwargs["tools"] = openai_tools
        kwargs["tool_choice"] = "auto"
    # else (Arm C): omit both tools and tool_choice.

    response = client.chat.completions.create(**kwargs)

    msg = response.choices[0].message
    tcs = msg.tool_calls or []
    content = [
        {
            "type": "tool_use",
            "name": tc.function.name,
            "input": json.loads(tc.function.arguments or "{}"),
        }
        for tc in tcs
    ]

    # Map OpenAI finish_reason to Anthropic stop_reason vocabulary.
    finish_reason = response.choices[0].finish_reason
    stop_reason_map = {"tool_calls": "tool_use", "stop": "end_turn"}
    stop_reason = stop_reason_map.get(finish_reason, finish_reason)

    # Serialise usage: handle both Pydantic models and plain objects.
    usage_obj = response.usage
    if hasattr(usage_obj, "model_dump"):
        usage = usage_obj.model_dump()
    else:
        usage = dict(usage_obj)

    return {
        "content": content,
        "usage": usage,
        "stop_reason": stop_reason,
    }

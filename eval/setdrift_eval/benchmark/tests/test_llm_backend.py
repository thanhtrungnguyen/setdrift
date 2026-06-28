"""Offline unit tests for llm_backend.py — openrouter backend.

All tests are fully offline: no network calls, no API key required (we set
OPENROUTER_API_KEY=test via monkeypatch.setenv). The openai.OpenAI client is
stubbed by replacing the `openai` module attribute on llm_backend directly:
    monkeypatch.setattr(lb, "openai", fake_openai_module)

This works because llm_backend imports openai at module level, making it a
patchable attribute of the module object.

Tests cover:
  1. Anthropic->OpenAI tool-schema conversion.
  2. tool_calls response mapping -> {"type":"tool_use","name","input"} blocks;
     tool_calls=None -> empty content list.
  3. extra_body provider-lock: order=["Anthropic"], allow_fallbacks=False;
     tool_choice="auto" when tools non-empty, absent when tools=[].
"""

import types

import setdrift_eval.benchmark.llm_backend as lb

# ---------------------------------------------------------------------------
# Shared tool fixture — matches the Anthropic tool spec from arm_runner.build_skill_tool
# ---------------------------------------------------------------------------
_TOOLS = [
    {
        "name": "spring_boot_endpoint",
        "description": "Create a Spring Boot REST endpoint",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    }
]


# ---------------------------------------------------------------------------
# Fake OpenAI client helpers
# ---------------------------------------------------------------------------


def _make_tool_call(name: str, arguments: str = "{}"):
    """Return a minimal fake tool-call object."""
    func = types.SimpleNamespace(name=name, arguments=arguments)
    return types.SimpleNamespace(function=func)


def _make_usage(input_tokens: int = 10, output_tokens: int = 5):
    """Return a fake usage object with model_dump()."""

    class _Usage:
        def __init__(self) -> None:
            self.input_tokens = input_tokens
            self.output_tokens = output_tokens

        def model_dump(self):
            return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}

    return _Usage()


def _make_fake_openai(tool_calls, finish_reason: str = "tool_calls"):
    """Build a fake openai module replacement recording create kwargs.

    Returns (fake_openai_module, recorded_kwargs_list).
    The fake module exposes .OpenAI as a constructor returning a client whose
    chat.completions.create(**kwargs) records kwargs and returns a fake response.
    """
    recorded: list[dict] = []

    msg = types.SimpleNamespace(tool_calls=tool_calls)
    choice = types.SimpleNamespace(message=msg, finish_reason=finish_reason)
    fake_response = types.SimpleNamespace(
        choices=[choice],
        usage=_make_usage(),
    )

    class _Completions:
        @staticmethod
        def create(**kwargs):
            recorded.append(kwargs)
            return fake_response

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    def _fake_openai_constructor(**kwargs):
        return _Client()

    fake_module = types.SimpleNamespace(OpenAI=_fake_openai_constructor)
    return fake_module, recorded


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_anthropic_to_openai_tool_conversion(monkeypatch):
    """Anthropic tool spec converts to OpenAI function spec shape."""
    monkeypatch.setenv("SETDRIFT_LLM_BACKEND", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")

    fake_openai, recorded = _make_fake_openai([_make_tool_call("spring_boot_endpoint")])
    monkeypatch.setattr(lb, "openai", fake_openai)

    lb.call_model("anthropic/claude-sonnet-4.6", "add an endpoint", _TOOLS)

    assert len(recorded) == 1
    sent_tools = recorded[0]["tools"]
    assert sent_tools[0] == {
        "type": "function",
        "function": {
            "name": "spring_boot_endpoint",
            "description": "Create a Spring Boot REST endpoint",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }


def test_tool_calls_map_to_tool_use_blocks(monkeypatch):
    """OpenAI tool_calls response maps correctly to internal tool_use block list."""
    monkeypatch.setenv("SETDRIFT_LLM_BACKEND", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")

    # --- case 1: one tool call ---
    fake_openai1, _ = _make_fake_openai(
        [_make_tool_call("spring_boot_endpoint", "{}")],
        finish_reason="tool_calls",
    )
    monkeypatch.setattr(lb, "openai", fake_openai1)
    result = lb.call_model("anthropic/claude-sonnet-4.6", "add endpoint", _TOOLS)
    assert result["content"] == [{"type": "tool_use", "name": "spring_boot_endpoint", "input": {}}]
    assert result["stop_reason"] == "tool_use"

    # --- case 2: tool_calls=None -> empty content ---
    fake_openai2, _ = _make_fake_openai(None, finish_reason="stop")
    monkeypatch.setattr(lb, "openai", fake_openai2)
    result2 = lb.call_model("anthropic/claude-sonnet-4.6", "add endpoint", _TOOLS)
    assert result2["content"] == []
    assert result2["stop_reason"] == "end_turn"


def test_provider_lock_in_extra_body(monkeypatch):
    """extra_body carries provider lock; tool_choice present iff tools non-empty."""
    monkeypatch.setenv("SETDRIFT_LLM_BACKEND", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")

    # --- case 1: tools non-empty -> tool_choice="auto" ---
    fake_openai1, recorded1 = _make_fake_openai([_make_tool_call("spring_boot_endpoint")])
    monkeypatch.setattr(lb, "openai", fake_openai1)
    lb.call_model("anthropic/claude-sonnet-4.6", "add endpoint", _TOOLS)

    assert len(recorded1) == 1
    kwargs1 = recorded1[0]
    assert kwargs1["extra_body"] == {"provider": {"order": ["Anthropic"], "allow_fallbacks": False}}
    assert kwargs1.get("tool_choice") == "auto"

    # --- case 2: tools empty -> NO tool_choice ---
    fake_openai2, recorded2 = _make_fake_openai(None, finish_reason="stop")
    monkeypatch.setattr(lb, "openai", fake_openai2)
    lb.call_model("anthropic/claude-sonnet-4.6", "what is 2+2?", [])

    assert len(recorded2) == 1
    kwargs2 = recorded2[0]
    assert kwargs2["extra_body"] == {"provider": {"order": ["Anthropic"], "allow_fallbacks": False}}
    assert "tool_choice" not in kwargs2


def test_call_model_accepts_per_call_max_tokens(monkeypatch):
    """D-13a: max_tokens param overrides default; existing callers without it are unaffected."""
    monkeypatch.setenv("SETDRIFT_LLM_BACKEND", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    fake_openai, recorded = _make_fake_openai([_make_tool_call("spring_boot_endpoint")])
    monkeypatch.setattr(lb, "openai", fake_openai)

    lb.call_model("anthropic/claude-sonnet-4.6", "add endpoint", _TOOLS, max_tokens=512)
    assert recorded[0]["max_tokens"] == 512

    fake_openai2, recorded2 = _make_fake_openai([_make_tool_call("spring_boot_endpoint")])
    monkeypatch.setattr(lb, "openai", fake_openai2)
    lb.call_model("anthropic/claude-sonnet-4.6", "add endpoint", _TOOLS)  # default
    assert recorded2[0]["max_tokens"] == 256  # lb.MAX_TOKENS unchanged


def test_call_openrouter_fail_loud_on_empty_choices(monkeypatch):
    """D-13b: _call_openrouter raises RuntimeError (not TypeError) on empty choices."""
    import pytest

    monkeypatch.setenv("SETDRIFT_LLM_BACKEND", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")

    fake_response = types.SimpleNamespace(choices=[], usage=_make_usage(), model_extra={})

    class _Completions:
        @staticmethod
        def create(**kwargs):
            return fake_response

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    fake_module = types.SimpleNamespace(OpenAI=lambda **kw: _Client())
    monkeypatch.setattr(lb, "openai", fake_module)

    with pytest.raises(RuntimeError, match="OpenRouter returned no choices"):
        lb.call_model("openai/gpt-4o", "judge this", [], max_tokens=512)

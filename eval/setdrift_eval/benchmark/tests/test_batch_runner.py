"""Offline unit tests for batch_runner.py — Batches cache-prewarm wrapper (D7-03).

All tests are fully offline: no network calls, no API key required. The
`anthropic.Anthropic().messages.batches` client is stubbed by replacing the
`anthropic` module attribute on batch_runner directly, mirroring the fake-client
idiom in test_llm_backend.py (monkeypatch.setattr(br, "anthropic", fake_module)).

Tests cover the four behaviors in 07-02-PLAN.md Task 1:
  1. collect_misses returns only absent triples.
  2. prewarm_cache writes the exact {content, usage, stop_reason} shape; a
     subsequent response_cache.load_or_call for the same triple is a cache
     hit (zero transport calls, asserted by a transport spy).
  3. prewarm_cache calls assert_evidence_run before batches.create; when
     preflight raises, no batch is submitted.
  4. A non-terminal poll status loops until "ended"; a failed batch request
     result raises (no bare except swallows it).
"""

import json
import types

import pytest

import setdrift_eval.benchmark.batch_runner as br
import setdrift_eval.benchmark.llm_backend as lb
import setdrift_eval.benchmark.response_cache as response_cache
from setdrift_eval.evidence.preflight import EvidenceRunError

_TOOLS = [
    {
        "name": "spring_boot_endpoint",
        "description": "Create a Spring Boot REST endpoint",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    }
]

_PINNED_MODEL = "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Fake anthropic.messages.batches client helpers
# ---------------------------------------------------------------------------


def _make_content_block(name: str = "spring_boot_endpoint", input_: dict | None = None):
    block = types.SimpleNamespace(type="tool_use", name=name, input=input_ or {})
    block.model_dump = lambda: {"type": "tool_use", "name": name, "input": input_ or {}}
    return block


def _make_usage(input_tokens: int = 10, output_tokens: int = 5):
    usage = types.SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    usage.model_dump = lambda: {"input_tokens": input_tokens, "output_tokens": output_tokens}
    return usage


def _make_result_item(custom_id: str, *, succeeded: bool = True):
    if succeeded:
        message = types.SimpleNamespace(
            content=[_make_content_block()],
            usage=_make_usage(),
            stop_reason="tool_use",
        )
        result = types.SimpleNamespace(type="succeeded", message=message)
    else:
        result = types.SimpleNamespace(type="errored", message=None, error="boom")
    return types.SimpleNamespace(custom_id=custom_id, result=result)


def _make_fake_batches_module(
    *,
    statuses: list[str],
    result_items: list,
    create_calls: list,
    retrieve_calls: list,
):
    """Build a fake `anthropic` module replacement with a messages.batches surface.

    statuses: sequence of processing_status values returned by successive
        .retrieve() calls (last one repeats if retrieve is called more times
        than len(statuses)).
    """
    state = {"retrieve_idx": 0}

    class _Batches:
        @staticmethod
        def create(requests):
            create_calls.append(requests)
            return types.SimpleNamespace(id="batch_123")

        @staticmethod
        def retrieve(batch_id):
            retrieve_calls.append(batch_id)
            idx = min(state["retrieve_idx"], len(statuses) - 1)
            status = statuses[idx]
            state["retrieve_idx"] += 1
            return types.SimpleNamespace(processing_status=status)

        @staticmethod
        def results(batch_id):
            return iter(result_items)

    class _Messages:
        batches = _Batches()

    class _Client:
        messages = _Messages()

    fake_anthropic = types.SimpleNamespace(Anthropic=lambda: _Client())
    return fake_anthropic


# ---------------------------------------------------------------------------
# Test 1: collect_misses
# ---------------------------------------------------------------------------


def test_collect_misses_returns_only_absent_triples(tmp_path):
    triple_hit = (_PINNED_MODEL, "prompt already cached", _TOOLS)
    triple_miss = (_PINNED_MODEL, "prompt not cached", _TOOLS)

    hit_key = response_cache.cache_key(*triple_hit)
    (tmp_path / f"{hit_key}.json").write_text(
        json.dumps({"content": [], "usage": {}, "stop_reason": "end_turn"}), encoding="utf-8"
    )

    misses = br.collect_misses([triple_hit, triple_miss], tmp_path)

    assert misses == [triple_miss]


# ---------------------------------------------------------------------------
# Test 2: prewarm_cache writes exact shape; subsequent load_or_call is a cache hit
# ---------------------------------------------------------------------------


def test_prewarm_cache_writes_exact_shape_and_load_or_call_hits_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SETDRIFT_LLM_BACKEND", "anthropic")
    triple = (_PINNED_MODEL, "add a spring boot endpoint", _TOOLS)
    key = response_cache.cache_key(*triple)

    create_calls: list = []
    retrieve_calls: list = []
    fake_anthropic = _make_fake_batches_module(
        statuses=["ended"],
        result_items=[_make_result_item(key)],
        create_calls=create_calls,
        retrieve_calls=retrieve_calls,
    )
    monkeypatch.setattr(br, "anthropic", fake_anthropic)

    summary = br.prewarm_cache([triple], _PINNED_MODEL, cache_dir=tmp_path, poll_interval=0)

    assert summary["written"] == 1
    written_path = tmp_path / f"{key}.json"
    assert written_path.exists()
    persisted = json.loads(written_path.read_text(encoding="utf-8"))
    assert persisted == {
        "content": [{"type": "tool_use", "name": "spring_boot_endpoint", "input": {}}],
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "stop_reason": "tool_use",
    }

    # Transport spy: load_or_call for the same triple must NOT call call_model.
    def _spy_call_model(*args, **kwargs):
        raise AssertionError("call_model should not be invoked — expected a cache hit")

    monkeypatch.setattr(response_cache, "call_model", _spy_call_model)
    result = response_cache.load_or_call(*triple, tmp_path)
    assert result == persisted


# ---------------------------------------------------------------------------
# Test 3: preflight gate — no batch submitted when preflight raises
# ---------------------------------------------------------------------------


def test_prewarm_cache_calls_preflight_before_submission(tmp_path, monkeypatch):
    """Non-pinned model must raise EvidenceRunError before batches.create runs."""
    monkeypatch.setenv("SETDRIFT_LLM_BACKEND", "anthropic")
    triple = ("not-a-pinned-model", "add a spring boot endpoint", _TOOLS)

    create_calls: list = []
    retrieve_calls: list = []
    fake_anthropic = _make_fake_batches_module(
        statuses=["ended"],
        result_items=[],
        create_calls=create_calls,
        retrieve_calls=retrieve_calls,
    )
    monkeypatch.setattr(br, "anthropic", fake_anthropic)

    with pytest.raises(EvidenceRunError):
        br.prewarm_cache([triple], "not-a-pinned-model", cache_dir=tmp_path, poll_interval=0)

    assert create_calls == []


# ---------------------------------------------------------------------------
# Test 4: poll loop until "ended"; fail-loud on errored result
# ---------------------------------------------------------------------------


def test_prewarm_cache_polls_until_ended(tmp_path, monkeypatch):
    monkeypatch.setenv("SETDRIFT_LLM_BACKEND", "anthropic")
    triple = (_PINNED_MODEL, "poll me", _TOOLS)
    key = response_cache.cache_key(*triple)

    create_calls: list = []
    retrieve_calls: list = []
    fake_anthropic = _make_fake_batches_module(
        statuses=["in_progress", "ended"],
        result_items=[_make_result_item(key)],
        create_calls=create_calls,
        retrieve_calls=retrieve_calls,
    )
    monkeypatch.setattr(br, "anthropic", fake_anthropic)

    summary = br.prewarm_cache([triple], _PINNED_MODEL, cache_dir=tmp_path, poll_interval=0)

    assert len(retrieve_calls) == 2
    assert summary["written"] == 1


def test_prewarm_cache_raises_on_errored_batch_result(tmp_path, monkeypatch):
    """No bare except swallows a failed request result — it must raise."""
    monkeypatch.setenv("SETDRIFT_LLM_BACKEND", "anthropic")
    triple = (_PINNED_MODEL, "this one fails", _TOOLS)
    key = response_cache.cache_key(*triple)

    create_calls: list = []
    retrieve_calls: list = []
    fake_anthropic = _make_fake_batches_module(
        statuses=["ended"],
        result_items=[_make_result_item(key, succeeded=False)],
        create_calls=create_calls,
        retrieve_calls=retrieve_calls,
    )
    monkeypatch.setattr(br, "anthropic", fake_anthropic)

    with pytest.raises(br.BatchRunnerError):
        br.prewarm_cache([triple], _PINNED_MODEL, cache_dir=tmp_path, poll_interval=0)

    # Fail-loud: no partial file written for the failed request.
    assert not (tmp_path / f"{key}.json").exists()


# ---------------------------------------------------------------------------
# Smoke test: confirm the installed anthropic SDK exposes messages.batches (A5)
# ---------------------------------------------------------------------------


def test_anthropic_sdk_exposes_messages_batches_attribute():
    # Attribute-only check (offline, no client instantiation, no API key): the
    # installed anthropic SDK exposes a Batches resource under messages (A5).
    import anthropic as real_anthropic

    assert hasattr(real_anthropic.resources.messages, "Batches")
    assert hasattr(lb.anthropic, "Anthropic")

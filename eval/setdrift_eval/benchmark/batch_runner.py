"""Anthropic Message Batches cache-prewarm wrapper (D7-03, RUN-01).

What this module does:
  Enumerates the distinct `(model, prompt, tools)` cache-miss triples for a
  batch-shaped workload (5-run arm B/C noise bands, the 12-cell drift grid,
  the Haiku sensitivity run), submits ONE `messages.batches` job covering only
  the misses, polls it to completion, and writes each result into
  `data/cache/{key}.json` in the EXACT `{content, usage, stop_reason}` shape
  `response_cache.load_or_call`'s cache-miss branch produces.

Why it exists as a separate module (not a change to arm_runner/grid_runner):
  `arm_runner.py`, `scorer.py`, and `schemas/experiment.py` are FROZEN
  Goodhart-firewall files. This wrapper is a cache-PREWARM step that runs
  BEFORE any frozen runner executes; once prewarmed, every frozen call path
  hits `response_cache.load_or_call`'s cache-HIT branch with zero call-path
  edits, capturing the Batches API's 50% discount transparently.

Firewall/fail-loud discipline:
  - `assert_evidence_run(model)` is called FIRST, before any batch is
    submitted — a wrong backend/model can never spend money via this path
    (D7-19, T-07-06).
  - A batch request whose result is anything other than "succeeded" raises
    `BatchRunnerError` — no bare `except`, no silent skip (T-07-08).

No new dependency: `anthropic` (already pinned >=0.40, installed 0.108.0)
hosts `client.messages.batches.create/retrieve/results` directly.
"""

import json
import time
from pathlib import Path

import anthropic  # module-level so tests can monkeypatch batch_runner.anthropic

from setdrift_eval.benchmark.response_cache import CACHE_DIR, cache_key
from setdrift_eval.evidence.preflight import assert_evidence_run

MAX_TOKENS = 256  # mirrors llm_backend.MAX_TOKENS default for the frozen arm-runner path

# Anthropic messages.batches processing_status values that mean "done, go read results".
_TERMINAL_STATUSES = frozenset({"ended"})


class BatchRunnerError(RuntimeError):
    """Raised when a Batches API submission or a batch request result is invalid.

    Fail-loud: a batch request whose result is an error must raise, never be
    silently skipped or partially persisted (T-07-08).
    """


def collect_misses(triples: list[tuple[str, str, list[dict]]], cache_dir: Path) -> list:
    """Return only the (model, prompt, tools) triples NOT already cached.

    Reuses response_cache.cache_key so the miss set is byte-identical to what
    response_cache.load_or_call would treat as a cache miss.
    """
    cache_dir = Path(cache_dir)
    misses = []
    for triple in triples:
        model, prompt, tools = triple
        key = cache_key(model, prompt, tools)
        if not (cache_dir / f"{key}.json").exists():
            misses.append(triple)
    return misses


def _build_request(key: str, model: str, prompt: str, tools: list[dict]) -> dict:
    """Build one Message Batches request, mirroring llm_backend._call_anthropic's kwargs."""
    params: dict = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
    }
    if tools:
        params["tools"] = tools
        params["tool_choice"] = {"type": "auto"}
    # else (Arm C): omit both tools and tool_choice — same rule as llm_backend.
    return {"custom_id": key, "params": params}


def prewarm_cache(
    triples: list[tuple[str, str, list[dict]]],
    model: str,
    *,
    cache_dir: Path = CACHE_DIR,
    poll_interval: float = 5.0,
) -> dict:
    """Submit one Batches job for the cache misses in `triples`, poll, persist results.

    Args:
        triples: distinct (model, prompt, tools) triples the caller will need.
        model: the pinned model for this evidence run; checked via
            `assert_evidence_run` BEFORE any batch is submitted (D7-19).
        cache_dir: response_cache cache directory (default: response_cache.CACHE_DIR).
        poll_interval: seconds between `messages.batches.retrieve` polls.

    Returns:
        Summary dict: {"batch_id": str | None, "total_triples": int,
        "misses": int, "written": int}.

    Raises:
        EvidenceRunError: if the preflight backend/model check fails — no
            batch is submitted (propagated from assert_evidence_run).
        BatchRunnerError: if a batch request's result is not "succeeded".
    """
    assert_evidence_run(model)  # FIRST — no batch submission on a wrong backend/model (T-07-06)

    cache_dir = Path(cache_dir)
    misses = collect_misses(triples, cache_dir)

    summary = {
        "batch_id": None,
        "total_triples": len(triples),
        "misses": len(misses),
        "written": 0,
    }
    if not misses:
        return summary

    keyed_misses = [(cache_key(m, p, t), m, p, t) for (m, p, t) in misses]
    requests = [_build_request(key, m, p, t) for (key, m, p, t) in keyed_misses]

    client = anthropic.Anthropic()
    batch = client.messages.batches.create(requests=requests)
    batch_id = batch.id
    summary["batch_id"] = batch_id

    # Poll until terminal. stdlib sleep loop — no custom async queue (Don't Hand-Roll).
    status = client.messages.batches.retrieve(batch_id).processing_status
    while status not in _TERMINAL_STATUSES:
        time.sleep(poll_interval)
        status = client.messages.batches.retrieve(batch_id).processing_status

    key_by_custom_id = {key: key for (key, _m, _p, _t) in keyed_misses}
    cache_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for item in client.messages.batches.results(batch_id):
        custom_id = item.custom_id
        if custom_id not in key_by_custom_id:
            raise BatchRunnerError(
                f"Batch result custom_id {custom_id!r} does not match any submitted "
                "request — refusing to persist an unattributable result."
            )
        result = item.result
        if getattr(result, "type", None) != "succeeded":
            raise BatchRunnerError(
                f"Batch request {custom_id!r} did not succeed "
                f"(result.type={getattr(result, 'type', None)!r}): {result!r}"
            )
        message = result.message
        data = {
            "content": [b.model_dump() for b in message.content],
            "usage": message.usage.model_dump(),
            "stop_reason": message.stop_reason,
        }
        (cache_dir / f"{custom_id}.json").write_text(json.dumps(data), encoding="utf-8")
        written += 1

    summary["written"] = written
    return summary

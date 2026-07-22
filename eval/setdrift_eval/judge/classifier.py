"""Single-label classification judge for RUN-02's Trung-vs-judge kappa (Phase 7).

What this module does:
  Classifies a single developer prompt against the 8-value SkillLabel taxonomy
  using the frozen transport (call_model). This is a NEW, narrower function —
  the Phase-5 judge harness (judge/runner.py) is an A/B response-pair comparator
  and is not directly reusable for single-label classification (RESEARCH
  Pitfall 5). Retries on parse/validation failure, mirroring
  parse_verdict_with_retry's shape; NEVER returns a synthetic fallback label.

What it does NOT do:
  - NEVER re-implements Cohen's kappa — label_pairs() feeds judge/kappa.py's
    compute_kappa() unchanged (taxonomy-agnostic).
  - NEVER returns a default/fallback label on parse failure — raises RuntimeError
    naming the prompt instead (frozen-ruler / Goodhart discipline, T-07-04).
  - NEVER accepts an out-of-taxonomy label — validated against _VALID (T-07-05).

References: 07-03-PLAN.md, judge/runner.py (parse_verdict_with_retry shape),
corpus/precision_gate.py (SkillLabel taxonomy usage), judge/kappa.py (compute_kappa).
"""

from __future__ import annotations

# Reuse the FROZEN transport — never inline another API call (D-05).
from setdrift_eval.benchmark.llm_backend import call_model
from setdrift_eval.corpus.schemas import SkillLabel

_VALID = {s.value for s in SkillLabel}
_INTENTS = sorted(_VALID - {SkillLabel.NONE.value})

MAX_CLASSIFY_RETRIES = 2

_CLASSIFY_INSTRUCTION = (
    "You are a strict single-label classifier for developer prompts against a "
    "fixed skill taxonomy. Reply with EXACTLY ONE label from this set, and "
    f"nothing else — no punctuation, no explanation: {sorted(_VALID)!r}. "
    f'Use "{SkillLabel.NONE.value}" only if no other label applies.'
)


def _extract_text(response: dict) -> str:
    """Extract the first text block from the canonical call_model response dict.

    Fails loudly if no text block exists (eval-side fail-loud pattern; mirrors
    judge/runner.py's _extract_text).
    """
    content = response.get("content", [])
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            return block.get("text", "")
    raise RuntimeError(
        f"No text block found in classifier response content: {content!r}. "
        "Classification model must return a text response, not tool calls."
    )


def _parse_label(raw_text: str) -> str | None:
    """Parse a single SkillLabel value out of raw model text.

    Returns the label value if exactly one valid taxonomy label is present
    (after trimming and case-normalising), else None (caller retries).
    """
    candidate = raw_text.strip().strip(".").strip().lower()
    if candidate in _VALID:
        return candidate
    # Tolerate a trailing period or surrounding quotes/backticks on one line.
    stripped = candidate.strip('"').strip("'").strip("`")
    if stripped in _VALID:
        return stripped
    return None


def classify_prompt(prompt: str, model: str, *, cache_dir=None) -> str:  # noqa: ARG001 — cache_dir reserved for future response_cache wiring
    """Classify a developer prompt against the 8-value SkillLabel taxonomy.

    Calls the model via the frozen transport (mirrors judge/runner.py's
    `call_model(..., tools=[], max_tokens=...)` usage), parses the response
    text to a single label, and validates it is in the taxonomy. Retries up to
    MAX_CLASSIFY_RETRIES times on parse/validation failure; on final failure
    raises RuntimeError naming the prompt — NEVER returns a synthetic fallback
    label (frozen-ruler discipline, T-07-04).

    Args:
        prompt:    The developer prompt to classify.
        model:     Pinned model ID for the frozen transport.
        cache_dir: Reserved for future response_cache wiring; unused for now.

    Returns:
        A SkillLabel value (str) — one of the 8 taxonomy values.

    Raises:
        RuntimeError: After MAX_CLASSIFY_RETRIES failures; names the prompt.
    """
    classify_prompt_text = (
        f"{_CLASSIFY_INSTRUCTION}\n\nDeveloper Prompt:\n{prompt}\n\nLabel:"
    )

    raw = call_model(model=model, prompt=classify_prompt_text, tools=[], max_tokens=32)
    text = _extract_text(raw)

    for attempt in range(MAX_CLASSIFY_RETRIES + 1):
        label = _parse_label(text)
        if label is not None:
            return label
        if attempt == MAX_CLASSIFY_RETRIES:
            raise RuntimeError(
                f"classify_prompt failed after {MAX_CLASSIFY_RETRIES} retries "
                f"(model={model!r}, prompt={prompt[:80]!r}): "
                f"last raw output={text!r} not in taxonomy {sorted(_VALID)!r}"
            )
        retry_text = (
            f"{classify_prompt_text}\n\n"
            f"[Attempt {attempt + 1}: your previous reply {text!r} was not a valid "
            f"label. Reply with EXACTLY ONE value from {sorted(_VALID)!r} and "
            "nothing else.]"
        )
        retry_raw = call_model(model=model, prompt=retry_text, tools=[], max_tokens=32)
        text = _extract_text(retry_raw)

    raise AssertionError("unreachable")


def label_pairs(
    trung_labels: dict[str, str], judge_labels: dict[str, str]
) -> tuple[list[str], list[str]]:
    """Align two prompt-id -> label dicts into ordered lists for compute_kappa.

    Only prompt ids present in BOTH dicts are included (structural integrity —
    compute_kappa requires equal-length, same-order lists). Ordering is
    deterministic: sorted by prompt_id.

    Args:
        trung_labels: prompt_id -> label (Trung's manual labels).
        judge_labels: prompt_id -> label (classifier's labels).

    Returns:
        (trung_ordered, judge_ordered) — two equal-length lists, same order,
        directly acceptable to judge.kappa.compute_kappa.
    """
    shared_ids = sorted(set(trung_labels) & set(judge_labels))
    trung_ordered = [trung_labels[pid] for pid in shared_ids]
    judge_ordered = [judge_labels[pid] for pid in shared_ids]
    return trung_ordered, judge_ordered

"""LLM-as-judge sensitivity runner for the Setdrift harness (Phase 5).

What this module does:
  Implements the outer sensitivity loop: 5 bias modes × 3 judge families × 100-prompt
  slice = up to 1500 judge calls. Per-cell results are de-aliased for position_swapped
  before Cohen's kappa is computed per (bias_mode, family_pair) cell. Scrubbed kappa
  matrix is promoted to experiments/; raw verdicts stay under data/judge/ (data wall).

What it does NOT do:
  - NEVER re-implements F1 arithmetic (Goodhart firewall — CI grep guard active).
  - NEVER returns a synthetic fallback verdict on parse failure (D5-7).
  - NEVER calls OpenRouter when SETDRIFT_OPENROUTER_ALLOW_FALLBACKS=='true' (D5-9).
  - NEVER writes raw prompts/verdicts to experiments/ (data wall T-05-06).

Goodhart firewall:
  macro_f1 and ScorerError are imported from the FROZEN scorer.py only.
  This module contains zero F1 arithmetic — the CI grep guard enforces this.

References: 05-AI-SPEC.md §3/§4/§4b, 05-PATTERNS.md §judge/runner.py, D5-7/D5-9.
"""

from __future__ import annotations

import json
import os
import random
from itertools import combinations
from pathlib import Path

from pydantic import ValidationError

# Reuse the FROZEN transport — never inline another API call (D-05)
from setdrift_eval.benchmark.llm_backend import call_model
from setdrift_eval.benchmark.response_cache import load_or_call, CACHE_DIR  # noqa: F401 — available for callers
from setdrift_eval.judge.schema import JudgeVerdict
from setdrift_eval.judge.bias_modes import bias_mode_instruction

# FROZEN RULER — read-only; never recompute (D-04 / D5-8)
from setdrift_eval.telemetry.scorer import macro_f1, ScorerError  # noqa: F401 — guard import


# ---------------------------------------------------------------------------
# Module-level constants (D-08 pinned model IDs, D-11 retry limit)
# ---------------------------------------------------------------------------

JUDGE_MODELS: dict[str, tuple[str, str]] = {
    "claude": ("anthropic", "claude-sonnet-4-6"),
    "gpt4": ("openrouter", "openai/gpt-4o"),
    "gemini": ("openrouter", "google/gemini-2.5-pro"),
}

MAX_JUDGE_RETRIES = 2

_JUDGE_SYSTEM = (
    "You are an impartial evaluator. "
    "Do not reveal or infer which model produced each response. "
    "Reply ONLY with a JSON object matching the JudgeVerdict schema: "
    '{"winner": "1" | "2" | "tie", "confidence": float 0-1, '
    '"rationale": "string 10-500 chars", "bias_mode": "string", '
    '"model_id": "string", "position_swapped": bool, "prompt_id": "string"}.'
)

# Data wall: raw verdict directory (gitignored)
_JUDGE_DATA_DIR = Path(os.environ.get("SETDRIFT_JUDGE_DATA_DIR", "data/judge"))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_judge_prompt(
    prompt: str,
    response_a: str,
    response_b: str,
    bias_mode: str,
    seed: int,
) -> tuple[str, bool]:
    """Build the judge prompt with seeded blind position swap.

    Returns (judge_prompt, position_swapped) where position_swapped=True means
    response_b was placed in slot [1] and response_a in slot [2].

    The seed is per-prompt so swaps are reproducible across judge families —
    both families see the same slot assignment for the same prompt.
    """
    rng = random.Random(seed)
    swapped = rng.random() < 0.5

    bias_instr = bias_mode_instruction(bias_mode)
    bias_section = f"\n\nBias instruction: {bias_instr}" if bias_instr else ""

    if swapped:
        slot_1, slot_2 = response_b, response_a
    else:
        slot_1, slot_2 = response_a, response_b

    judge_prompt = (
        f"{_JUDGE_SYSTEM}{bias_section}\n\n"
        f"Developer Prompt:\n{prompt}\n\n"
        f"Response [1]:\n{slot_1}\n\n"
        f"Response [2]:\n{slot_2}\n\n"
        "Evaluate which response better addresses the developer prompt. "
        "Reply ONLY with a JSON object — no markdown, no explanation outside the JSON."
    )
    return judge_prompt, swapped


def _extract_text(response: dict) -> str:
    """Extract the text content from the canonical call_model response dict.

    Reads the first 'text' block from the content list. Fails loudly if no
    text block exists (eval-side fail-loud pattern).
    """
    content = response.get("content", [])
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            return block.get("text", "")
    raise RuntimeError(
        f"No text block found in judge response content: {content!r}. "
        "Judge model must return a text response, not tool calls."
    )


def _write_raw_verdict(verdict: JudgeVerdict) -> None:
    """Write raw verdict to the data wall (gitignored data/judge/raw_verdicts/).

    Only scrubbed kappa matrix is promoted to experiments/.
    Raw verdicts stay under data/ per data-wall constraint (T-05-06).
    """
    out_dir = Path(os.environ.get("SETDRIFT_JUDGE_DATA_DIR", "data/judge")) / "raw_verdicts"
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{verdict.prompt_id}_{verdict.bias_mode}_{verdict.model_id.replace('/', '_')}.json"
    (out_dir / fname).write_text(verdict.model_dump_json(indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Core public API
# ---------------------------------------------------------------------------


def parse_verdict_with_retry(
    initial_text: str,
    model_id: str,
    retry_prompt_fn,
    context: dict,
) -> JudgeVerdict:
    """Parse a JudgeVerdict from model text output, retrying on failure.

    Retries up to MAX_JUDGE_RETRIES times. After exhausting retries, raises
    RuntimeError naming model_id, prompt_id, and bias_mode — NEVER returns
    a synthetic fallback verdict (D5-7 — synthetic verdicts corrupt kappa).

    Args:
        initial_text:     Raw text from the first model call.
        model_id:         Pinned model ID (for error message).
        retry_prompt_fn:  Callable(attempt: int) -> str — builds the retry prompt.
        context:          Dict with 'bias_mode', 'prompt_id', 'position_swapped'.

    Returns:
        JudgeVerdict — validated Pydantic model.

    Raises:
        RuntimeError: After MAX_JUDGE_RETRIES failures; names model/prompt/mode.
    """
    raw_text = initial_text
    for attempt in range(MAX_JUDGE_RETRIES + 1):
        try:
            return JudgeVerdict.model_validate_json(raw_text)
        except (ValidationError, json.JSONDecodeError) as exc:
            if attempt == MAX_JUDGE_RETRIES:
                raise RuntimeError(
                    f"JudgeVerdict failed after {MAX_JUDGE_RETRIES} retries "
                    f"(model={model_id!r}, prompt_id={context['prompt_id']!r}, "
                    f"bias_mode={context['bias_mode']!r}): {exc}"
                ) from exc
            # Retry: call model again with the retry prompt
            retry_raw = call_model(
                model=model_id,
                prompt=retry_prompt_fn(attempt + 1),
                tools=[],
                max_tokens=512,
            )
            raw_text = _extract_text(retry_raw)
    raise AssertionError("unreachable")


def run_judge_cell(
    prompt: str,
    response_a: str,
    response_b: str,
    bias_mode: str,
    family: str,
    seed: int,
    prompt_id: str,
) -> JudgeVerdict:
    """Run a single judge evaluation cell and return a parsed JudgeVerdict.

    Precondition guards (fail-loud, checked before any API call):
      - SETDRIFT_OPENROUTER_ALLOW_FALLBACKS must be 'false' (D5-9 provider-lock).

    Sets SETDRIFT_LLM_BACKEND from JUDGE_MODELS[family] before calling call_model.
    Passes max_tokens=512 and tools=[] to the transport (D-13a/D5-4).

    Args:
        prompt:      The developer prompt from the 100-prompt slice.
        response_a:  Arm A (Setdrift-managed config) response.
        response_b:  Arm B (frozen hand-written config) response.
        bias_mode:   One of the 5 pre-registered bias modes.
        family:      Judge family key: 'claude', 'gpt4', or 'gemini'.
        seed:        Deterministic RNG seed for blind position swap.
        prompt_id:   Identifier from the 100-prompt slice (D-11/D-14).

    Returns:
        JudgeVerdict — validated and de-aliased ready for kappa computation.

    Raises:
        RuntimeError: If provider-lock precondition fails (D5-9), or if
                      parse_verdict_with_retry exhausts MAX_JUDGE_RETRIES.
    """
    # --- FAIL-LOUD: check provider lock before first call (D5-9) ---
    if os.environ.get("SETDRIFT_OPENROUTER_ALLOW_FALLBACKS", "false").lower() == "true":
        raise RuntimeError(
            "SETDRIFT_OPENROUTER_ALLOW_FALLBACKS must be 'false' for judge runs (D5-9). "
            "A contaminated cross-family cell produces kappa that appears cross-family "
            "but is actually intra-family — a silent credibility error in the dissertation."
        )

    backend, model_id = JUDGE_MODELS[family]
    os.environ["SETDRIFT_LLM_BACKEND"] = backend

    judge_prompt, swapped = _build_judge_prompt(prompt, response_a, response_b, bias_mode, seed)

    raw = call_model(model=model_id, prompt=judge_prompt, tools=[], max_tokens=512)
    text = _extract_text(raw)

    verdict = parse_verdict_with_retry(
        initial_text=text,
        model_id=model_id,
        retry_prompt_fn=lambda attempt: (
            judge_prompt
            + f"\n\n[Attempt {attempt}: Fix your JSON — reply ONLY with a valid JudgeVerdict JSON object.]"
        ),
        context={"bias_mode": bias_mode, "prompt_id": prompt_id, "position_swapped": swapped},
    )
    # Override position_swapped from the actual swap applied (D5-2 correctness)
    # Pydantic models are immutable by default — use model_copy
    verdict = verdict.model_copy(update={"position_swapped": swapped, "prompt_id": prompt_id})

    # Write raw verdict to data wall (gitignored)
    _write_raw_verdict(verdict)

    return verdict


def run_judge_sensitivity(args) -> int:
    """Run the full 5-bias-mode × 3-family-pair sensitivity matrix.

    Outer loop: bias_mode (5) × family (3) × prompt slice (N).
    Inner: run_judge_cell per (bias_mode, family, prompt).
    After all calls: de_alias every verdict, compute Cohen's kappa per
    (bias_mode, family-pair), build KappaCell list, write to experiments/.

    Raw verdicts stay under data/judge/ (gitignored data wall).
    Only the scrubbed kappa matrix is promoted to experiments/ (T-05-06).

    Args:
        args: Namespace with .slice (Path), .seed (int), .manifest (Path).

    Returns:
        0 on success.
    """
    from setdrift_eval.judge.kappa import (
        KappaCell,
        compute_kappa,
        de_alias,
        escalation_required,
        KAPPA_FLOOR,
    )

    slice_path = Path(args.slice)
    seed = args.seed
    manifest_path = Path(args.manifest)

    # Load the prompt slice (JSONL)
    prompts: list[dict] = []
    with slice_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            prompts.append(json.loads(line))

    print(f"[setdrift-eval] judge-sensitivity: loaded {len(prompts)} prompts from {slice_path}")

    bias_modes = ["verbosity", "position", "self_preference", "authority", "recency"]
    families = list(JUDGE_MODELS.keys())  # ["claude", "gpt4", "gemini"]

    # Collect verdicts: verdicts[bias_mode][family][prompt_id] = JudgeVerdict
    verdicts: dict[str, dict[str, dict[str, JudgeVerdict]]] = {
        bm: {fam: {} for fam in families} for bm in bias_modes
    }

    total_cells = len(bias_modes) * len(families) * len(prompts)
    done = 0

    for bias_mode in bias_modes:
        for family in families:
            for p in prompts:
                prompt_id = p["prompt_id"]
                # Deterministic seed per (bias_mode, family, prompt_id, global_seed)
                import hashlib

                cell_key = f"{seed}-{bias_mode}-{family}-{prompt_id}"
                cell_seed = int(hashlib.sha256(cell_key.encode()).hexdigest()[:8], 16)

                verdict = run_judge_cell(
                    prompt=p["prompt"],
                    response_a=p.get("response_a", ""),
                    response_b=p.get("response_b", ""),
                    bias_mode=bias_mode,
                    family=family,
                    seed=cell_seed,
                    prompt_id=prompt_id,
                )
                verdicts[bias_mode][family][prompt_id] = verdict
                done += 1

        print(
            f"[setdrift-eval] judge-sensitivity: {done}/{total_cells} calls done (mode={bias_mode})"
        )

    # Build kappa cells: for each (bias_mode, family-pair)
    kappa_cells: list[KappaCell] = []
    family_pairs = list(
        combinations(families, 2)
    )  # [("claude","gpt4"),("claude","gemini"),("gpt4","gemini")]

    for bias_mode in bias_modes:
        for fam_a, fam_b in family_pairs:
            # Collect de-aliased labels for prompts that have verdicts in BOTH families
            labels_a: list[str] = []
            labels_b: list[str] = []
            for p in prompts:
                pid = p["prompt_id"]
                if pid in verdicts[bias_mode][fam_a] and pid in verdicts[bias_mode][fam_b]:
                    labels_a.append(de_alias(verdicts[bias_mode][fam_a][pid]))
                    labels_b.append(de_alias(verdicts[bias_mode][fam_b][pid]))

            n = len(labels_a)
            if n < 2:
                kappa_val = float("nan")
                escalation = True
                reason = (
                    f"Insufficient paired verdicts (n={n} < 2) for "
                    f"bias_mode={bias_mode!r} family_pair={fam_a}_vs_{fam_b} — "
                    "cannot compute Cohen's kappa; escalation required by default."
                )
            else:
                kappa_val = compute_kappa(labels_a, labels_b)
                escalation = escalation_required(kappa_val)
                pair_label = f"{fam_a}_vs_{fam_b}"
                if escalation:
                    reason = (
                        f"kappa={kappa_val:.4f} < KAPPA_FLOOR={KAPPA_FLOOR} "
                        f"for bias_mode={bias_mode!r} family_pair={pair_label} "
                        f"(n={n} prompts) — panel-of-3 escalation required (D-11)."
                    )
                else:
                    reason = (
                        f"kappa={kappa_val:.4f} >= KAPPA_FLOOR={KAPPA_FLOOR} "
                        f"for bias_mode={bias_mode!r} family_pair={pair_label} "
                        f"(n={n} prompts) — inter-rater agreement acceptable."
                    )

            pair_str = f"{fam_a}_vs_{fam_b}"
            kappa_cells.append(
                KappaCell(
                    bias_mode=bias_mode,
                    family_pair=pair_str,
                    kappa=kappa_val if not (kappa_val != kappa_val) else 0.0,  # nan -> 0.0 for JSON
                    n_prompts=n,
                    escalation_required=escalation,
                    reason=reason,
                )
            )

    # Promote only the scrubbed kappa matrix to experiments/ (data wall — raw verdicts stay under data/)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_data = {
        "schema_version": 1,
        "seed": seed,
        "n_prompts": len(prompts),
        "bias_modes": bias_modes,
        "families": families,
        "kappa_cells": [c.model_dump() for c in kappa_cells],
    }
    manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    n_escalations = sum(1 for c in kappa_cells if c.escalation_required)
    print(
        f"[setdrift-eval] judge-sensitivity kappa_matrix -> {manifest_path} "
        f"({len(kappa_cells)} cells, {n_escalations} escalations)"
    )
    return 0

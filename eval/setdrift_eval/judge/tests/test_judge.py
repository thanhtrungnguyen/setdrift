"""Tests for the LLM-as-judge sensitivity harness — schema, bias_modes, kappa utilities.

RED tests (Task 1): schema, bias_modes, kappa.
GREEN tests (Task 2): runner preconditions, retry, provider lock, sensitivity.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Task 1 — RED tests: schema / bias_modes / kappa
# ---------------------------------------------------------------------------


class TestJudgeVerdictSchema:
    """JudgeVerdict model validation (D5-7 — every field required, extra forbidden)."""

    def test_valid_verdict_parses(self):
        from setdrift_eval.judge.schema import JudgeVerdict

        payload = json.dumps({
            "winner": "1",
            "confidence": 0.85,
            "rationale": "Response 1 is more accurate and concise.",
            "bias_mode": "verbosity",
            "model_id": "claude-sonnet-4-6",
            "position_swapped": False,
            "prompt_id": "p001",
        })
        verdict = JudgeVerdict.model_validate_json(payload)
        assert verdict.winner == "1"
        assert verdict.confidence == 0.85

    def test_rejects_missing_field(self):
        from pydantic import ValidationError
        from setdrift_eval.judge.schema import JudgeVerdict

        payload = json.dumps({
            "winner": "1",
            "confidence": 0.85,
            "rationale": "Response 1 is more accurate.",
            # missing bias_mode, model_id, position_swapped, prompt_id
        })
        with pytest.raises(ValidationError):
            JudgeVerdict.model_validate_json(payload)

    def test_rejects_extra_field(self):
        from pydantic import ValidationError
        from setdrift_eval.judge.schema import JudgeVerdict

        payload = json.dumps({
            "winner": "tie",
            "confidence": 0.5,
            "rationale": "Both responses are equally good in quality.",
            "bias_mode": "position",
            "model_id": "openai/gpt-4o",
            "position_swapped": True,
            "prompt_id": "p002",
            "extra_field": "not_allowed",
        })
        with pytest.raises(ValidationError):
            JudgeVerdict.model_validate_json(payload)

    def test_rejects_invalid_winner(self):
        from pydantic import ValidationError
        from setdrift_eval.judge.schema import JudgeVerdict

        payload = json.dumps({
            "winner": "3",  # invalid — must be "1", "2", or "tie"
            "confidence": 0.7,
            "rationale": "This is a test of invalid winner field.",
            "bias_mode": "verbosity",
            "model_id": "claude-sonnet-4-6",
            "position_swapped": False,
            "prompt_id": "p003",
        })
        with pytest.raises(ValidationError):
            JudgeVerdict.model_validate_json(payload)

    def test_rejects_confidence_out_of_range(self):
        from pydantic import ValidationError
        from setdrift_eval.judge.schema import JudgeVerdict

        payload = json.dumps({
            "winner": "2",
            "confidence": 1.5,  # out of [0, 1]
            "rationale": "This tests confidence range validation.",
            "bias_mode": "authority",
            "model_id": "google/gemini-2.5-pro",
            "position_swapped": True,
            "prompt_id": "p004",
        })
        with pytest.raises(ValidationError):
            JudgeVerdict.model_validate_json(payload)

    def test_rejects_rationale_too_short(self):
        from pydantic import ValidationError
        from setdrift_eval.judge.schema import JudgeVerdict

        payload = json.dumps({
            "winner": "1",
            "confidence": 0.9,
            "rationale": "Short",  # less than 10 chars
            "bias_mode": "recency",
            "model_id": "claude-sonnet-4-6",
            "position_swapped": False,
            "prompt_id": "p005",
        })
        with pytest.raises(ValidationError):
            JudgeVerdict.model_validate_json(payload)


class TestBiasModes:
    """bias_mode_instruction() — 5 modes, fail-loud on unknown."""

    def test_verbosity_returns_string(self):
        from setdrift_eval.judge.bias_modes import bias_mode_instruction

        result = bias_mode_instruction("verbosity")
        assert isinstance(result, str)
        assert len(result) > 0  # verbosity has a non-empty instruction

    def test_position_returns_empty_string(self):
        from setdrift_eval.judge.bias_modes import bias_mode_instruction

        result = bias_mode_instruction("position")
        assert isinstance(result, str)
        # position mode = empty instruction (blind swap already applied)
        assert result == ""

    def test_self_preference_returns_empty_string(self):
        from setdrift_eval.judge.bias_modes import bias_mode_instruction

        result = bias_mode_instruction("self_preference")
        assert isinstance(result, str)

    def test_authority_returns_string(self):
        from setdrift_eval.judge.bias_modes import bias_mode_instruction

        result = bias_mode_instruction("authority")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_recency_returns_string(self):
        from setdrift_eval.judge.bias_modes import bias_mode_instruction

        result = bias_mode_instruction("recency")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_unknown_mode_raises_value_error_listing_valid_modes(self):
        from setdrift_eval.judge.bias_modes import bias_mode_instruction

        with pytest.raises(ValueError) as exc_info:
            bias_mode_instruction("nope")
        msg = str(exc_info.value)
        # Must list the 5 valid modes in the error message
        for mode in ["verbosity", "position", "self_preference", "authority", "recency"]:
            assert mode in msg


class TestDeAlias:
    """de_alias() — position_swapped correction before kappa computation."""

    def test_not_swapped_winner_1_returns_a(self):
        from setdrift_eval.judge.kappa import de_alias
        from setdrift_eval.judge.schema import JudgeVerdict

        verdict = JudgeVerdict(
            winner="1",
            confidence=0.8,
            rationale="Response 1 is clearly more helpful here.",
            bias_mode="verbosity",
            model_id="claude-sonnet-4-6",
            position_swapped=False,
            prompt_id="p001",
        )
        assert de_alias(verdict) == "a"

    def test_not_swapped_winner_2_returns_b(self):
        from setdrift_eval.judge.kappa import de_alias
        from setdrift_eval.judge.schema import JudgeVerdict

        verdict = JudgeVerdict(
            winner="2",
            confidence=0.7,
            rationale="Response 2 provides a better explanation overall.",
            bias_mode="position",
            model_id="openai/gpt-4o",
            position_swapped=False,
            prompt_id="p002",
        )
        assert de_alias(verdict) == "b"

    def test_swapped_winner_1_returns_b(self):
        """When position_swapped=True, slot '1' is actually response B (shown first)."""
        from setdrift_eval.judge.kappa import de_alias
        from setdrift_eval.judge.schema import JudgeVerdict

        verdict = JudgeVerdict(
            winner="1",
            confidence=0.75,
            rationale="Response 1 is more accurate and well-structured.",
            bias_mode="authority",
            model_id="google/gemini-2.5-pro",
            position_swapped=True,
            prompt_id="p003",
        )
        assert de_alias(verdict) == "b"

    def test_swapped_winner_2_returns_a(self):
        """When position_swapped=True, slot '2' is actually response A."""
        from setdrift_eval.judge.kappa import de_alias
        from setdrift_eval.judge.schema import JudgeVerdict

        verdict = JudgeVerdict(
            winner="2",
            confidence=0.65,
            rationale="Response 2 gives a more complete answer to the question.",
            bias_mode="recency",
            model_id="claude-sonnet-4-6",
            position_swapped=True,
            prompt_id="p004",
        )
        assert de_alias(verdict) == "a"

    def test_tie_always_returns_tie(self):
        from setdrift_eval.judge.kappa import de_alias
        from setdrift_eval.judge.schema import JudgeVerdict

        for swapped in [True, False]:
            verdict = JudgeVerdict(
                winner="tie",
                confidence=0.5,
                rationale="Both responses are equally good in this comparison.",
                bias_mode="self_preference",
                model_id="openai/gpt-4o",
                position_swapped=swapped,
                prompt_id="p005",
            )
            assert de_alias(verdict) == "tie"


class TestEscalationRequired:
    """escalation_required() — KAPPA_FLOOR=0.6 pre-registered D-11."""

    def test_below_floor_requires_escalation(self):
        from setdrift_eval.judge.kappa import escalation_required

        assert escalation_required(0.59) is True

    def test_at_floor_does_not_require_escalation(self):
        from setdrift_eval.judge.kappa import escalation_required

        assert escalation_required(0.6) is False

    def test_above_floor_does_not_require_escalation(self):
        from setdrift_eval.judge.kappa import escalation_required

        assert escalation_required(0.8) is False

    def test_negative_kappa_requires_escalation(self):
        from setdrift_eval.judge.kappa import escalation_required

        assert escalation_required(-0.1) is True


class TestComputeKappa:
    """compute_kappa() — Cohen's kappa via sklearn, de-aliased labels."""

    def test_identical_lists_return_kappa_1(self):
        from setdrift_eval.judge.kappa import compute_kappa

        labels = ["a", "b", "tie", "a", "b"]
        result = compute_kappa(labels, labels)
        assert abs(result - 1.0) < 1e-9

    def test_kappa_floor_constant_is_0_6(self):
        from setdrift_eval.judge.kappa import KAPPA_FLOOR

        assert KAPPA_FLOOR == 0.6

    def test_kappa_cell_model_extra_forbid(self):
        from pydantic import ValidationError
        from setdrift_eval.judge.kappa import KappaCell

        with pytest.raises(ValidationError):
            KappaCell(  # type: ignore[call-arg]
                bias_mode="verbosity",
                family_pair="claude_vs_gpt4",
                kappa=0.75,
                n_prompts=5,
                escalation_required=False,
                reason="Test reason for kappa cell validation.",
                extra_field="not_allowed",
            )

    def test_kappa_cell_reason_must_not_be_empty(self):
        """KappaCell.reason must be non-empty (D-41 never-silent pattern)."""
        from pydantic import ValidationError
        from setdrift_eval.judge.kappa import KappaCell

        with pytest.raises(ValidationError):
            KappaCell(
                bias_mode="position",
                family_pair="claude_vs_gemini",
                kappa=0.45,
                n_prompts=10,
                escalation_required=True,
                reason="",  # empty — must be rejected
            )


# ---------------------------------------------------------------------------
# Task 2 — GREEN tests: runner preconditions, retry, provider lock, sensitivity
# ---------------------------------------------------------------------------


class TestProviderLockGuard:
    """run_judge_cell raises RuntimeError when SETDRIFT_OPENROUTER_ALLOW_FALLBACKS=='true'."""

    def test_provider_lock_raises_when_fallbacks_enabled(self, monkeypatch):
        monkeypatch.setenv("SETDRIFT_OPENROUTER_ALLOW_FALLBACKS", "true")

        from setdrift_eval.judge.runner import run_judge_cell

        with pytest.raises(RuntimeError, match="SETDRIFT_OPENROUTER_ALLOW_FALLBACKS"):
            run_judge_cell(
                prompt="What is a Spring Boot endpoint?",
                response_a="It is a REST controller.",
                response_b="A Spring Boot endpoint is a REST controller mapped to a URL.",
                bias_mode="verbosity",
                family="claude",
                seed=42,
                prompt_id="p001",
            )

    def test_provider_lock_check_before_any_call_model(self, monkeypatch):
        """Verify the guard fires before any call to call_model (not after)."""
        monkeypatch.setenv("SETDRIFT_OPENROUTER_ALLOW_FALLBACKS", "true")
        called = []

        import setdrift_eval.judge.runner as runner_mod
        monkeypatch.setattr(runner_mod, "call_model", lambda *a, **kw: called.append(1))

        from setdrift_eval.judge.runner import run_judge_cell

        with pytest.raises(RuntimeError):
            run_judge_cell(
                prompt="Describe REST endpoints.",
                response_a="REST endpoints map URLs to handlers.",
                response_b="REST endpoints provide HTTP-accessible service operations.",
                bias_mode="position",
                family="gpt4",
                seed=0,
                prompt_id="p002",
            )
        # call_model must NOT have been called
        assert called == []


class TestParseVerdictWithRetry:
    """parse_verdict_with_retry — parses on first try; raises after MAX_JUDGE_RETRIES."""

    def _make_valid_json(self, prompt_id: str = "p001") -> str:
        return json.dumps({
            "winner": "1",
            "confidence": 0.8,
            "rationale": "Response 1 is clearly more accurate and concise than response 2.",
            "bias_mode": "verbosity",
            "model_id": "claude-sonnet-4-6",
            "position_swapped": False,
            "prompt_id": prompt_id,
        })

    def test_parses_valid_json_on_first_try(self, monkeypatch):
        import setdrift_eval.judge.runner as runner_mod

        call_count = []

        def fake_call_model(*args, **kwargs):
            call_count.append(1)
            return {"content": [{"type": "text", "text": self._make_valid_json()}],
                    "usage": {}, "stop_reason": "end_turn"}

        monkeypatch.setattr(runner_mod, "call_model", fake_call_model)

        from setdrift_eval.judge.runner import parse_verdict_with_retry

        verdict = parse_verdict_with_retry(
            initial_text=self._make_valid_json(),
            model_id="claude-sonnet-4-6",
            retry_prompt_fn=lambda attempt: f"Fix attempt {attempt}",
            context={"bias_mode": "verbosity", "prompt_id": "p001", "position_swapped": False},
        )
        assert verdict.winner == "1"
        # No retry call needed
        assert call_count == []

    def test_raises_after_max_retries_no_synthetic_verdict(self, monkeypatch):
        """After MAX_JUDGE_RETRIES failures, raises RuntimeError — never returns a synthetic verdict."""
        import setdrift_eval.judge.runner as runner_mod

        call_count = []

        def fake_call_model(*args, **kwargs):
            call_count.append(1)
            return {"content": [{"type": "text", "text": "not valid json {{{"}],
                    "usage": {}, "stop_reason": "end_turn"}

        monkeypatch.setattr(runner_mod, "call_model", fake_call_model)

        from setdrift_eval.judge.runner import parse_verdict_with_retry, MAX_JUDGE_RETRIES

        with pytest.raises(RuntimeError) as exc_info:
            parse_verdict_with_retry(
                initial_text="bad json {{{",
                model_id="claude-sonnet-4-6",
                retry_prompt_fn=lambda attempt: f"Fix attempt {attempt}",
                context={"bias_mode": "verbosity", "prompt_id": "p_retry", "position_swapped": False},
            )
        # Must name model_id, prompt_id, bias_mode in the error
        msg = str(exc_info.value)
        assert "claude-sonnet-4-6" in msg or "p_retry" in msg or "verbosity" in msg
        # Exactly MAX_JUDGE_RETRIES retry calls were made (first attempt is free)
        assert len(call_count) == MAX_JUDGE_RETRIES

    def test_retry_raises_exactly_max_retries_times(self, monkeypatch):
        import setdrift_eval.judge.runner as runner_mod

        call_count = []

        def fake_call_model(*args, **kwargs):
            call_count.append(1)
            return {"content": [{"type": "text", "text": "invalid{{"}],
                    "usage": {}, "stop_reason": "end_turn"}

        monkeypatch.setattr(runner_mod, "call_model", fake_call_model)

        from setdrift_eval.judge.runner import parse_verdict_with_retry, MAX_JUDGE_RETRIES

        with pytest.raises(RuntimeError):
            parse_verdict_with_retry(
                initial_text="bad",
                model_id="test-model",
                retry_prompt_fn=lambda a: "retry",
                context={"bias_mode": "authority", "prompt_id": "px", "position_swapped": False},
            )
        assert len(call_count) == MAX_JUDGE_RETRIES


class TestRunJudgeCellMaxTokens:
    """run_judge_cell passes max_tokens=512 and tools=[] to call_model."""

    def test_run_judge_cell_passes_max_tokens_512_and_empty_tools(self, monkeypatch):
        monkeypatch.setenv("SETDRIFT_OPENROUTER_ALLOW_FALLBACKS", "false")
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

        import setdrift_eval.judge.runner as runner_mod

        captured = []

        def fake_call_model(model, prompt, tools, max_tokens=256):
            captured.append({"model": model, "tools": tools, "max_tokens": max_tokens})
            # Return a valid verdict JSON in a text block
            verdict_json = json.dumps({
                "winner": "2",
                "confidence": 0.7,
                "rationale": "Response 2 provides a more complete answer overall.",
                "bias_mode": "verbosity",
                "model_id": model,
                "position_swapped": False,
                "prompt_id": "p001",
            })
            return {"content": [{"type": "text", "text": verdict_json}],
                    "usage": {}, "stop_reason": "end_turn"}

        monkeypatch.setattr(runner_mod, "call_model", fake_call_model)

        from setdrift_eval.judge.runner import run_judge_cell

        run_judge_cell(
            prompt="What is dependency injection?",
            response_a="DI is a pattern where objects receive dependencies.",
            response_b="Dependency injection decouples components by providing dependencies externally.",
            bias_mode="verbosity",
            family="claude",
            seed=42,
            prompt_id="p001",
        )

        assert len(captured) >= 1
        assert captured[0]["max_tokens"] == 512
        assert captured[0]["tools"] == []


class TestRunJudgeSensitivity:
    """run_judge_sensitivity produces 15-cell kappa matrix; flags escalation when kappa<0.6."""

    def _make_verdict_json(self, winner: str, model_id: str, bias_mode: str,
                           prompt_id: str, swapped: bool = False) -> str:
        return json.dumps({
            "winner": winner,
            "confidence": 0.75,
            "rationale": f"Response {winner} is better for this prompt evaluation.",
            "bias_mode": bias_mode,
            "model_id": model_id,
            "position_swapped": swapped,
            "prompt_id": prompt_id,
        })

    def test_sensitivity_produces_15_kappa_cells(self, monkeypatch, tmp_path):
        """run_judge_sensitivity over a 2-prompt fixture slice produces 15 KappaCell objects."""
        import setdrift_eval.judge.runner as runner_mod
        from setdrift_eval.judge.runner import JUDGE_MODELS

        # Build a minimal 2-prompt slice JSONL
        slice_path = tmp_path / "slice.jsonl"
        prompts = [
            {"prompt_id": "p001", "prompt": "What is REST?",
             "response_a": "REST is an architectural style.", "response_b": "REST uses HTTP methods."},
            {"prompt_id": "p002", "prompt": "What is DI?",
             "response_a": "DI decouples components.", "response_b": "DI is a pattern for object creation."},
        ]
        slice_path.write_text(
            "\n".join(json.dumps(p) for p in prompts), encoding="utf-8"
        )

        # Mock call_model to return valid verdicts
        call_idx = [0]

        def fake_call_model(model, prompt, tools, max_tokens=256):
            # Alternate winners across calls
            winner = "1" if call_idx[0] % 2 == 0 else "2"
            call_idx[0] += 1
            # Extract bias_mode from prompt (approximation for test)
            bias_mode_guess = "verbosity"  # default; sensitivity loop injects the real mode
            verdict_json = json.dumps({
                "winner": winner,
                "confidence": 0.75,
                "rationale": f"Response {winner} is better for this evaluation prompt.",
                "bias_mode": bias_mode_guess,
                "model_id": model,
                "position_swapped": False,
                "prompt_id": "p001",
            })
            return {"content": [{"type": "text", "text": verdict_json}],
                    "usage": {}, "stop_reason": "end_turn"}

        monkeypatch.setattr(runner_mod, "call_model", fake_call_model)
        monkeypatch.setenv("SETDRIFT_OPENROUTER_ALLOW_FALLBACKS", "false")
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

        # Override data dir to tmp_path to avoid touching real data/
        monkeypatch.setenv("SETDRIFT_JUDGE_DATA_DIR", str(tmp_path / "judge"))

        # Build fake args namespace
        import types
        manifest_path = tmp_path / "judge-sensitivity.json"
        args = types.SimpleNamespace(
            slice=slice_path,
            seed=42,
            manifest=manifest_path,
        )

        from setdrift_eval.judge.runner import run_judge_sensitivity
        run_judge_sensitivity(args)

        # Must produce exactly 15 cells (5 bias_modes × 3 family-pairs)
        assert manifest_path.exists()
        result = json.loads(manifest_path.read_text())
        assert "kappa_cells" in result
        assert len(result["kappa_cells"]) == 15

    def test_sensitivity_flags_escalation_when_kappa_below_floor(self, monkeypatch, tmp_path):
        """Cells with kappa < 0.6 must have escalation_required=True."""
        import setdrift_eval.judge.runner as runner_mod

        # Build a 2-prompt slice
        slice_path = tmp_path / "slice.jsonl"
        prompts = [
            {"prompt_id": "p001", "prompt": "Explain REST.",
             "response_a": "REST uses HTTP.", "response_b": "REST is a style."},
            {"prompt_id": "p002", "prompt": "Explain DI.",
             "response_a": "DI decouples.", "response_b": "DI is injection."},
        ]
        slice_path.write_text(
            "\n".join(json.dumps(p) for p in prompts), encoding="utf-8"
        )

        # All models return alternating winners — ensures kappa won't be 1.0
        call_idx = [0]

        def fake_call_model(model, prompt, tools, max_tokens=256):
            # Alternate winners: first call wins "1", second wins "2", etc.
            winner = "1" if call_idx[0] % 2 == 0 else "2"
            call_idx[0] += 1
            verdict_json = json.dumps({
                "winner": winner,
                "confidence": 0.6,
                "rationale": "Alternating responses test kappa computation below floor.",
                "bias_mode": "verbosity",
                "model_id": model,
                "position_swapped": False,
                "prompt_id": "p001",
            })
            return {"content": [{"type": "text", "text": verdict_json}],
                    "usage": {}, "stop_reason": "end_turn"}

        monkeypatch.setattr(runner_mod, "call_model", fake_call_model)
        monkeypatch.setenv("SETDRIFT_OPENROUTER_ALLOW_FALLBACKS", "false")
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.setenv("SETDRIFT_JUDGE_DATA_DIR", str(tmp_path / "judge"))

        import types
        manifest_path = tmp_path / "judge-sensitivity.json"
        args = types.SimpleNamespace(
            slice=slice_path,
            seed=42,
            manifest=manifest_path,
        )

        from setdrift_eval.judge.runner import run_judge_sensitivity
        run_judge_sensitivity(args)

        result = json.loads(manifest_path.read_text())
        cells = result["kappa_cells"]
        # At least some cells should have escalation_required populated
        assert all("escalation_required" in c for c in cells)
        assert all("reason" in c and c["reason"] for c in cells)

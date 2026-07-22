"""Tests for the single-label classification judge (Phase 7, RUN-02).

Behaviors (07-03-PLAN.md):
  1. Valid label on first call -> classify_prompt returns it.
  2. Unparseable/out-of-taxonomy on every attempt -> raises RuntimeError,
     NEVER returns a synthetic/default label.
  3. Garbage once then valid -> classify_prompt succeeds on retry.
"""

from __future__ import annotations

import pytest


def _resp(text: str) -> dict:
    """Build a canonical call_model response dict wrapping a single text block."""
    return {
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "stop_reason": "end_turn",
    }


class TestClassifyPrompt:
    def test_valid_label_returned_on_first_call(self, monkeypatch):
        import setdrift_eval.judge.classifier as classifier_mod

        calls = []

        def fake_call_model(model, prompt, tools, max_tokens=32):
            calls.append((model, prompt, tools, max_tokens))
            return _resp("jpa-migration")

        monkeypatch.setattr(classifier_mod, "call_model", fake_call_model)

        label = classifier_mod.classify_prompt("Fix the JPA entity mapping", "claude-sonnet-4-6")

        assert label == "jpa-migration"
        assert len(calls) == 1
        assert calls[0][2] == []  # tools=[]

    def test_raises_after_max_retries_no_synthetic_label(self, monkeypatch):
        import setdrift_eval.judge.classifier as classifier_mod

        def fake_call_model(model, prompt, tools, max_tokens=32):
            return _resp("I cannot classify this prompt.")

        monkeypatch.setattr(classifier_mod, "call_model", fake_call_model)

        with pytest.raises(RuntimeError, match="classify_prompt failed"):
            classifier_mod.classify_prompt("Some ambiguous prompt", "claude-sonnet-4-6")

    def test_succeeds_on_retry_after_garbage_once(self, monkeypatch):
        import setdrift_eval.judge.classifier as classifier_mod

        responses = iter(["not-a-real-label", "null-check"])

        def fake_call_model(model, prompt, tools, max_tokens=32):
            return _resp(next(responses))

        monkeypatch.setattr(classifier_mod, "call_model", fake_call_model)

        label = classifier_mod.classify_prompt("Add a null check before dereference", "claude-sonnet-4-6")

        assert label == "null-check"


class TestLabelPairs:
    def test_aligns_shared_ids_in_sorted_order(self):
        from setdrift_eval.judge.classifier import label_pairs

        trung = {"p003": "none", "p001": "import-fix", "p002": "dependency-bump"}
        judge = {"p001": "import-fix", "p002": "config-property", "p004": "none"}

        trung_ordered, judge_ordered = label_pairs(trung, judge)

        assert trung_ordered == ["import-fix", "dependency-bump"]
        assert judge_ordered == ["import-fix", "config-property"]
        assert len(trung_ordered) == len(judge_ordered)

    def test_feeds_compute_kappa_unchanged(self):
        from setdrift_eval.judge.classifier import label_pairs
        from setdrift_eval.judge.kappa import compute_kappa

        trung = {"p1": "jpa-migration", "p2": "none", "p3": "import-fix", "p4": "null-check"}
        judge = {"p1": "jpa-migration", "p2": "none", "p3": "import-fix", "p4": "test-fixture-fix"}

        trung_ordered, judge_ordered = label_pairs(trung, judge)
        kappa = compute_kappa(trung_ordered, judge_ordered)

        assert isinstance(kappa, float)

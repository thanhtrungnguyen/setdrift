"""Goodhart Exit-Gate CI test (Plan 03-06 Task 3, T-03-60).

Exit-Gate invariant: optimizer code paths structurally cannot receive a test-partition
(or val-partition) example. This test enforces the invariant at the CI level.

Two layers of proof:
  1. Runtime spy: drives run_loop_cycle with a corpus where some examples are val/test;
     asserts the spy on _propose sees ONLY train-split examples (by prompt_id).
  2. Structural source check: asserts gepa_wrapper.py does not import a split loader
     and does not contain any direct reference to 'split.json' in non-comment lines.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_SETDRIFT_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
_GEPA_WRAPPER_SRC = _SETDRIFT_PLUGIN_ROOT / "eval" / "setdrift_eval" / "optimizer" / "gepa_wrapper.py"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mixed_corpus(tmp_path):
    """Corpus with train/val/test examples — val and test must NEVER reach propose()."""
    corpus_dir = tmp_path / "corpora" / "public"
    corpus_dir.mkdir(parents=True)
    corpus_file = corpus_dir / "public.jsonl"

    records = [
        {"prompt_id": "train-1", "prompt": "add REST endpoint", "ground_truth_skills": ["spring-annotation-fix"]},
        {"prompt_id": "train-2", "prompt": "create controller", "ground_truth_skills": ["spring-annotation-fix"]},
        {"prompt_id": "train-3", "prompt": "no skill needed", "ground_truth_skills": ["none"]},
        {"prompt_id": "val-1", "prompt": "expose REST API (val)", "ground_truth_skills": ["spring-annotation-fix"]},
        {"prompt_id": "val-2", "prompt": "REST method (val)", "ground_truth_skills": ["none"]},
        {"prompt_id": "test-1", "prompt": "reserved test prompt", "ground_truth_skills": ["spring-annotation-fix"]},
        {"prompt_id": "test-2", "prompt": "another test prompt", "ground_truth_skills": ["none"]},
    ]
    corpus_file.write_text(
        "\n".join(json.dumps(r) for r in records), encoding="utf-8"
    )

    split = {
        "train-1": "train",
        "train-2": "train",
        "train-3": "train",
        "val-1": "val",
        "val-2": "val",
        "test-1": "test",
        "test-2": "test",
    }
    (corpus_dir / "split.json").write_text(json.dumps(split), encoding="utf-8")
    return corpus_file, split


@pytest.fixture()
def skills_dir(tmp_path):
    """Minimal skills directory with one skill."""
    import textwrap

    sd = tmp_path / "skills"
    (sd / "spring-boot-endpoint").mkdir(parents=True)
    (sd / "spring-boot-endpoint" / "SKILL.md").write_text(
        textwrap.dedent("""\
            ---
            name: spring-boot-endpoint
            description: >-
              Use when creating a REST endpoint.
              Applies to Spring annotation patterns in the parking services.
            ---
            # Spring Boot Endpoint
        """),
        encoding="utf-8",
    )
    return sd


@pytest.fixture()
def map_path():
    return _SETDRIFT_PLUGIN_ROOT / "eval" / "setdrift_eval" / "corpus" / "intent_skill_map.yaml"


@pytest.fixture()
def experiments_dir(tmp_path):
    ed = tmp_path / "experiments"
    ed.mkdir()
    return ed


@pytest.fixture()
def hmac_key(tmp_path, monkeypatch):
    key_file = tmp_path / "sica-hmac.key"
    key_file.write_text("b" * 64, encoding="utf-8")
    monkeypatch.setenv("SETDRIFT_SIGNING_KEY", str(key_file))
    return key_file


# ---------------------------------------------------------------------------
# Layer 1: Runtime spy — only train examples reach propose()
# ---------------------------------------------------------------------------

def test_only_train_examples_reach_propose(
    mixed_corpus, skills_dir, map_path, experiments_dir, hmac_key, monkeypatch, tmp_path
):
    """Spy on _propose: assert ALL examples have split=='train'."""
    from setdrift_eval.optimizer.orchestrator import run_loop_cycle
    from setdrift_eval.optimizer import gepa_wrapper as gw

    corpus_file, split = mixed_corpus

    audit_path = tmp_path / "data" / "audit" / "audit.jsonl"
    monkeypatch.setenv("SETDRIFT_AUDIT_PATH", str(audit_path))
    genealogy_path = tmp_path / "experiments" / "audit-genealogy.jsonl"
    monkeypatch.setenv("SETDRIFT_GENEALOGY_PATH", str(genealogy_path))

    seen_trainsets: list = []

    def fake_build_trainset(train_examples, *, constructed_path=None):
        """Return raw examples as dspy-compatible objects (no floor check)."""
        import dspy

        examples = []
        for ex in train_examples:
            pid = ex.get("prompt_id") if isinstance(ex, dict) else getattr(ex, "prompt_id", None)
            prompt = ex.get("prompt", "") if isinstance(ex, dict) else getattr(ex, "prompt", "")
            skills = set(
                (ex.get("ground_truth_skills") or []) if isinstance(ex, dict)
                else (getattr(ex, "ground_truth_skills", None) or [])
            )
            gt = frozenset(skills - {"none"})
            examples.append(dspy.Example(
                prompt=prompt, gt_intents=gt, prompt_id=pid,
            ).with_inputs("prompt"))
        return examples

    def spy_propose(sn, skill_path, trainset, frozen_map, cycle_id):
        seen_trainsets.append(list(trainset))
        return gw.SkillProposal(
            target_path=skill_path,
            new_content="improved description",
            skill_name=sn,
            cycle_id=cycle_id,
        )

    from setdrift_eval.optimizer.verifier import VerifyResult

    def fake_verify(*a, **k):
        return VerifyResult(
            promote=False,
            candidate_f1_mean=0.5,
            baseline_band_high=0.75,
            f1_delta=-0.25,
            reason="rejected: 0.5000 <= 0.7500",
        )

    monkeypatch.setattr("setdrift_eval.optimizer.orchestrator._build_optimizer_trainset", fake_build_trainset)
    monkeypatch.setattr("setdrift_eval.optimizer.orchestrator._propose", spy_propose)
    monkeypatch.setattr("setdrift_eval.optimizer.orchestrator._verify_candidate", fake_verify)
    monkeypatch.setattr("setdrift_eval.optimizer.orchestrator._check_precision_gate", lambda *a, **k: None)

    run_loop_cycle(
        skill_name="spring-boot-endpoint",
        corpus_path=corpus_file,
        skills_dir=skills_dir,
        map_path=map_path,
        experiments_dir=experiments_dir,
        seed=42,
        dry_run=True,
        approve=False,
    )

    # Verify propose() was called and received only train examples
    assert len(seen_trainsets) == 1, "propose() must be called exactly once"
    trainset_seen = seen_trainsets[0]
    assert len(trainset_seen) > 0, "trainset must not be empty"

    for ex in trainset_seen:
        pid = ex.get("prompt_id") if isinstance(ex, dict) else getattr(ex, "prompt_id", None)
        if pid is not None:
            assert split.get(pid) == "train", (
                f"prompt_id={pid!r} has split={split.get(pid)!r}; "
                "ONLY train examples must reach propose() (Goodhart Exit Gate, T-03-60)"
            )

    # Explicitly check that no val or test prompt_ids made it
    seen_pids = set()
    for ex in trainset_seen:
        pid = ex.get("prompt_id") if isinstance(ex, dict) else getattr(ex, "prompt_id", None)
        if pid is not None:
            seen_pids.add(pid)

    val_pids = {"val-1", "val-2"}
    test_pids = {"test-1", "test-2"}
    leaked_val = val_pids & seen_pids
    leaked_test = test_pids & seen_pids
    assert not leaked_val, f"VAL examples leaked to optimizer: {leaked_val}"
    assert not leaked_test, f"TEST examples leaked to optimizer: {leaked_test}"


# ---------------------------------------------------------------------------
# Layer 2: Structural source check — gepa_wrapper.py never reads split.json
# ---------------------------------------------------------------------------

def test_gepa_wrapper_does_not_import_split_loader():
    """gepa_wrapper.py must not import corpus split-loader or read split.json."""
    assert _GEPA_WRAPPER_SRC.exists(), f"gepa_wrapper.py not found at {_GEPA_WRAPPER_SRC}"
    src = _GEPA_WRAPPER_SRC.read_text(encoding="utf-8")

    non_comment = "\n".join(
        ln for ln in src.splitlines() if not ln.lstrip().startswith("#")
    )

    # Must not reference split.json or split-reading functions
    assert "split.json" not in non_comment, (
        "gepa_wrapper.py must not reference 'split.json' — "
        "the orchestrator owns split loading (Goodhart structural firewall, T-03-60)"
    )
    assert "freeze_split" not in non_comment, (
        "gepa_wrapper.py must not import freeze_split — "
        "structural firewall: split loading belongs in the orchestrator"
    )


def test_gepa_wrapper_has_no_split_json_read():
    """Structural check: gepa_wrapper.py contains no direct split.json file read."""
    src = _GEPA_WRAPPER_SRC.read_text(encoding="utf-8")
    lines_with_split = [
        (i + 1, ln)
        for i, ln in enumerate(src.splitlines())
        if "split.json" in ln and not ln.lstrip().startswith("#")
    ]
    assert not lines_with_split, (
        f"gepa_wrapper.py references 'split.json' at lines: "
        f"{[l for l, _ in lines_with_split]} — "
        "the optimizer must never read the split file (T-03-60 structural firewall)"
    )


# ---------------------------------------------------------------------------
# Layer 3: Verify the _load_trainset function filters correctly
# ---------------------------------------------------------------------------

def test_load_trainset_filters_to_train_only(mixed_corpus, map_path, tmp_path):
    """_load_trainset returns only split=='train' examples."""
    from setdrift_eval.optimizer.orchestrator import _load_trainset

    corpus_file, split = mixed_corpus
    train_examples, frozen_map = _load_trainset(corpus_file, map_path)

    # All returned examples must be train
    for ex in train_examples:
        pid = ex.get("prompt_id") if isinstance(ex, dict) else getattr(ex, "prompt_id", None)
        if pid is not None:
            assert split.get(pid) == "train", (
                f"_load_trainset returned non-train example: prompt_id={pid!r}, "
                f"split={split.get(pid)!r}"
            )

    # Verify val and test are excluded
    train_pids = {
        (ex.get("prompt_id") if isinstance(ex, dict) else getattr(ex, "prompt_id", None))
        for ex in train_examples
    }
    assert "val-1" not in train_pids, "val examples must not be in trainset"
    assert "test-1" not in train_pids, "test examples must not be in trainset"
    assert "train-1" in train_pids, "train examples must be present"

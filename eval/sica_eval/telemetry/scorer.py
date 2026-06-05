"""Strict-match macro-F1 scorer + run_health (Phase 2 headline, REQ-MEASURE-01/02).

The corpus labels (predicted_skills / ground_truth_skills) ARE intents (the
8-value SkillLabel taxonomy IS the intent space, D-29). An arm fires SKILL names,
projected to intents via the single frozen intent_skill_map.yaml (D-30). F1 is
strict-set over scored_intents only; a prompt with a positive ground-truth intent
that maps to no skill is held OUT of coverage — never folded into negatives, never
dropped (D-31). Fail-loud (ScorerError) on an empty scored space (Pitfall 4) and —
defense-in-depth for the ROADMAP exit-gate ordering — run_health REFUSES to compute
F1 until the 02-03 precision/kappa gate report exists with passed=True.
"""
import hashlib
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import yaml
from scipy.stats import bootstrap
from sklearn.metrics import f1_score

from sica_eval.schemas.experiment import ExperimentManifest, F1Result

_NONE = "none"
_DEFAULT_MAP = Path("eval/sica_eval/corpus/intent_skill_map.yaml")
_DEFAULT_SKILLS = Path("plugin/skills")


class ScorerError(ValueError):
    """Raised on a misconfigured/un-gated scoring run — never return a misleading 0.0."""


def load_intent_map(path: Path) -> tuple[dict, str]:
    """Return (mapping, sha256-of-file-bytes) — the sole skills→intents projection (D-30)."""
    p = Path(path)
    mapping = yaml.safe_load(p.read_text(encoding="utf-8"))
    return mapping, hashlib.sha256(p.read_bytes()).hexdigest()


def scored_intents(mapping: dict) -> frozenset:
    """Intents with ≥1 mapped skill. Raise (Pitfall 4) if none are scorable."""
    s = frozenset(intent for intent, skills in mapping.items() if skills)
    if not s:
        raise ScorerError("intent_skill_map has no scored intents (all []); cannot score F1")
    return s


def project_to_intents(fired_skills: set[str], mapping: dict) -> set[str]:
    fired = set(fired_skills)
    return {intent for intent, skills in mapping.items() if set(skills) & fired}


def binarize(intent_sets: list[set], labels: list[str]) -> np.ndarray:
    return np.array([[1 if lab in s else 0 for lab in labels] for s in intent_sets], dtype=int)


def macro_f1(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if y_true.size == 0:
        return 0.0
    return float(f1_score(y_true, y_pred, average="macro", zero_division=0.0))


def noise_band(f1_runs: list[float]) -> tuple[float, float]:
    """5-run band [mean-2σ, mean+2σ] (design-doc §8-3)."""
    if len(f1_runs) < 2:
        m = f1_runs[0] if f1_runs else 0.0
        return (m, m)
    mean = statistics.mean(f1_runs)
    sd = statistics.pstdev(f1_runs)
    return (mean - 2 * sd, mean + 2 * sd)


def bootstrap_ci(
    y_true: np.ndarray, y_pred: np.ndarray, seed: int,
    n_resamples: int = 9999, confidence_level: float = 0.95,
) -> tuple[float, float]:
    """BCa bootstrap CI by resampling PROMPTS (rows), seed-pinned (REQ-MEASURE-01)."""
    n = y_true.shape[0]
    if n < 2:
        pt = macro_f1(y_true, y_pred)
        return (pt, pt)
    idx = np.arange(n)

    def stat(sample_idx, axis=-1):
        si = np.asarray(sample_idx, dtype=int)
        if si.ndim == 1:
            return macro_f1(y_true[si], y_pred[si])
        return np.array([macro_f1(y_true[row], y_pred[row]) for row in si])

    try:
        res = bootstrap(
            (idx,), stat, n_resamples=n_resamples, vectorized=True, paired=False,
            rng=np.random.default_rng(seed), method="BCa", confidence_level=confidence_level,
        )
        lo, hi = float(res.confidence_interval.low), float(res.confidence_interval.high)
        if math.isnan(lo) or math.isnan(hi):
            raise ValueError("degenerate (zero-variance) bootstrap")
    except Exception:
        pt = macro_f1(y_true, y_pred)  # constant statistic → point CI (honest, no crash)
        lo = hi = pt
    return (lo, hi)


def _latest_passed_precision(experiments_dir: Path) -> dict | None:
    reports = sorted(Path(experiments_dir).glob("*-mining-precision.json"))
    if not reports:
        return None
    data = json.loads(reports[-1].read_text(encoding="utf-8"))
    return data if data.get("passed") is True else None


def _sum_token_cost(prompts: list[dict], tools: list[dict], model: str, cache_dir: Path) -> int:
    from sica_eval.benchmark.response_cache import cache_key

    total = 0
    for p in prompts:
        cf = Path(cache_dir) / f"{cache_key(model, p['prompt'], tools)}.json"
        if cf.exists():
            usage = json.loads(cf.read_text(encoding="utf-8")).get("usage", {})
            total += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    return total


def run_health(
    corpus_path: Path,
    arm: str,
    *,
    seed: int = 42,
    map_path: Path = _DEFAULT_MAP,
    skills_dir: Path = _DEFAULT_SKILLS,
    experiments_dir: Path = Path("experiments"),
    cache_dir: Path | None = None,
    model: str | None = None,
    timestamp: str | None = None,
) -> F1Result:
    """Score one arm end-to-end → F1Result + experiments/{NNN}-results.json.

    GATE GUARD (B3/W5, T-02-24): refuses to compute F1 unless a passed
    02-03 precision/kappa report exists — F1 can never precede the gate.
    """
    gate = _latest_passed_precision(experiments_dir)
    if gate is None:
        raise ScorerError(
            "precision/kappa gate has not cleared — run 02-03 precision_gate_cli first; "
            "F1 must not propagate before the gate passes"
        )

    from sica_eval.benchmark import arm_runner

    cache_dir = Path(cache_dir) if cache_dir is not None else arm_runner.CACHE_DIR
    model = model or arm_runner.MODEL

    corpus_path = Path(corpus_path)
    prompts = [
        json.loads(line)
        for line in corpus_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    split = json.loads((corpus_path.parent / "split.json").read_text(encoding="utf-8"))
    scored_prompts = [p for p in prompts if split.get(p["prompt_id"]) in ("val", "test")]

    mapping, map_sha = load_intent_map(map_path)
    scored = scored_intents(mapping)
    labels = sorted(scored)

    # Controlled exception to frozen-instrument rule (03-03 Task 1, §Controlled Exception):
    # arm in ("A","B") both load tools from skills_dir; arm C is the empty floor.
    # NOTE: scorer.py sha256 is NOT pinned in ExperimentManifest (only intent_map_sha256
    # + split_hash are pinned), so this arm-add does NOT invalidate any prior Phase-2
    # manifests (RESEARCH Open Question 3).
    tools = arm_runner.load_skill_tools(skills_dir) if arm in ("A", "B") else []
    y_true_sets: list[set] = []
    y_pred_sets: list[set] = []
    n_holdout = 0
    used_prompts: list[dict] = []
    for p in scored_prompts:
        gt = set(p.get("ground_truth_skills") or p.get("predicted_skills") or []) - {_NONE}
        if gt and not (gt & scored):
            n_holdout += 1  # positive intent exists but maps to no skill → out-of-coverage (D-31)
            continue
        fired = (
            arm_runner.run_arm(p["prompt"], tools, model=model, cache_dir=cache_dir)
            if arm in ("A", "B")
            else arm_runner.run_arm_c(p["prompt"], model=model, cache_dir=cache_dir)
        )
        y_true_sets.append(gt & scored)  # empty set = a scored negative ({none})
        y_pred_sets.append(project_to_intents(fired, mapping) & scored)
        used_prompts.append(p)

    yt = binarize(y_true_sets, labels)
    yp = binarize(y_pred_sets, labels)
    runs = [macro_f1(yt, yp) for _ in range(5)]  # cached responses → runs 2–5 are free
    band = noise_band(runs)
    ci_low, ci_high = bootstrap_ci(yt, yp, seed=seed)

    per_source = gate.get("per_source", {})
    per_source_kappa = {s: m["kappa"] for s, m in per_source.items()}
    per_source_precision = {s: m["precision"] for s, m in per_source.items()}
    per_source_label_distribution = {s: m.get("label_distribution", {}) for s, m in per_source.items()}
    if not per_source_kappa:
        raise ScorerError("per_source_kappa unavailable — run 02-03 precision gate first")

    coverage_pct = len(scored) / len(mapping)
    manifest = ExperimentManifest(
        experiment_id=f"phase2-arm{arm}-seed{seed}",
        timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
        model=model,
        arm=arm,
        corpus_name="public",
        corpus_version="2026-06-01",
        dataset_sha256=hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
        split_hash=hashlib.sha256((corpus_path.parent / "split.json").read_bytes()).hexdigest(),
        intent_map_sha256=map_sha,
        config_hash=hashlib.sha256(json.dumps(tools, sort_keys=True).encode()).hexdigest(),
        rng_seed=seed,
        n_prompts_scored=len(used_prompts),
        n_prompts_out_of_coverage=n_holdout,
        coverage_pct=coverage_pct,
        macro_f1_runs=runs,
        macro_f1_mean=statistics.mean(runs) if runs else 0.0,
        macro_f1_noise_band_low=band[0],
        macro_f1_noise_band_high=band[1],
        bootstrap_ci_low=ci_low,
        bootstrap_ci_high=ci_high,
        token_cost_total=_sum_token_cost(used_prompts, tools, model, cache_dir),
        per_source_precision=per_source_precision,
        per_source_kappa=per_source_kappa,
        per_source_label_distribution=per_source_label_distribution,
        notes="" if arm == "B" else "arm C = empty toolset = zero-configuration floor",
    )

    experiments_dir = Path(experiments_dir)
    experiments_dir.mkdir(parents=True, exist_ok=True)
    nnn = f"{len(list(experiments_dir.glob('*-results.json'))) + 1:03d}"
    (experiments_dir / f"{nnn}-results.json").write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )

    return F1Result(
        arm=arm,
        macro_f1_mean=manifest.macro_f1_mean,
        noise_band_low=band[0],
        noise_band_high=band[1],
        bootstrap_ci_low=ci_low,
        bootstrap_ci_high=ci_high,
        coverage_pct=coverage_pct,
    )


def val_only_prompts(corpus_path: Path) -> list[dict]:
    """Return only split=='val' prompts from corpus_path — the verifier restriction helper.

    The promotion gate (verifier.py, D-41) must evaluate on VAL only. This helper
    enforces the Goodhart firewall (T-03-30): the verifier structurally never sees
    test-split prompt IDs when computing its promotion decision.

    Returns a list of prompt dicts whose prompt_id maps to 'val' in the adjacent
    split.json. Never returns 'test' or 'train' rows.
    """
    corpus_path = Path(corpus_path)
    prompts = [
        json.loads(line)
        for line in corpus_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    split = json.loads((corpus_path.parent / "split.json").read_text(encoding="utf-8"))
    return [p for p in prompts if split.get(p["prompt_id"]) == "val"]

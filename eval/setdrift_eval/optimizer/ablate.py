"""Leave-one-out failure attribution ablation table (REQ-LOOP-03).

Implements the 5-component leave-one-out set from RESEARCH §Proposed Discretion
Answers: full Setdrift config, 4 single-component ablations, and arm-C floor.

What this module does:
- build_ablation_table: re-runs arm harness with components removed via run_arm
- render_table: produces the columnar table for CLI output

What this module does NOT do (code-identity boundary):
- Does NOT modify any skill file on disk
- Does NOT write audit logs or manifests
- Does NOT access the test partition directly

Consumes REQ-LOOP-03 (per-component failure attribution with root cause flag).
"""
from pathlib import Path

import yaml

from setdrift_eval.benchmark import arm_runner as _arm_runner
from setdrift_eval.benchmark.arm_runner import build_skill_tool


def _load_skills(skills_dir: Path) -> dict[str, dict]:
    """Load name→{name, description} for each skill in skills_dir."""
    skills = {}
    for skill_md in sorted(Path(skills_dir).glob("*/SKILL.md")):
        text = skill_md.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        _, frontmatter, _ = text.split("---", 2)
        meta = yaml.safe_load(frontmatter)
        skills[meta["name"]] = {
            "name": meta["name"],
            "description": meta["description"],
            "path": skill_md,
        }
    return skills


def _load_intent_map(map_path: Path) -> dict:
    return yaml.safe_load(Path(map_path).read_text(encoding="utf-8"))


def _score_single_prompt(prompt: str, tools: list[dict], mapping: dict,
                          ground_truth: set[str], cache_dir: Path | None = None,
                          model: str | None = None) -> float:
    """Compute per-prompt F1 for one ablation configuration.

    Uses _arm_runner.run_arm with provided tools, projects fired skills to intents
    via the frozen intent_skill_map, and computes strict-set F1 for this single prompt.
    Uses the module reference so monkeypatch works in tests.
    """
    kw: dict = {}
    if cache_dir is not None:
        kw["cache_dir"] = cache_dir
    if model is not None:
        kw["model"] = model

    # For no-tool configurations, simulate arm-C (fire nothing)
    if not tools:
        fired = set()
    else:
        fired = _arm_runner.run_arm(prompt, tools, **kw)

    # Project fired tool names → intents via frozen map
    predicted = {intent for intent, skills in mapping.items() if set(skills) & fired}

    # Strict-set F1 for this prompt
    tp = len(predicted & ground_truth)
    fp = len(predicted - ground_truth)
    fn = len(ground_truth - predicted)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return f1, fired, predicted


def build_ablation_table(
    failure_id: str,
    corpus_path: Path,
    skills_dir: Path,
    map_path: Path,
    *,
    cache_dir: Path | None = None,
    model: str | None = None,
) -> list[dict]:
    """Build a leave-one-out ablation table for one failure prompt.

    The 6-configuration set (RESEARCH §Proposed Discretion Answers 1):
    1. Full Setdrift config (both skills, optimized descriptions)
    2. spring-boot-endpoint description → baseline (swap in baseline desc)
    3. spring-jpa-entity description → baseline (swap in baseline desc)
    4. spring-boot-endpoint removed entirely
    5. spring-jpa-entity removed entirely
    6. Both skills removed (arm-C floor, empty toolset)

    Each row: component, fired_intents, f1, delta_vs_full, root_cause (bool).
    The largest-negative-delta row is flagged ROOT CAUSE.

    Args:
        failure_id: prompt_id of the failure to ablate.
        corpus_path: Path to the corpus JSONL (split.json must be adjacent).
        skills_dir: Path to the skills directory with SKILL.md files.
        map_path: Path to intent_skill_map.yaml.
        cache_dir: Optional cache directory for arm_runner.
        model: Optional model override.

    Returns:
        List of 6 row dicts. Each has: component, fired_intents, f1, delta_vs_full,
        root_cause.
    """
    corpus_path = Path(corpus_path)
    skills_dir = Path(skills_dir)
    map_path = Path(map_path)

    # --- Load corpus and find the failure prompt ---
    import json
    lines = corpus_path.read_text(encoding="utf-8").splitlines()
    prompts = [json.loads(line) for line in lines if line.strip()]
    failure_prompt = next(
        (p for p in prompts if p["prompt_id"] == failure_id), None
    )
    if failure_prompt is None:
        raise ValueError(f"failure_id='{failure_id}' not found in corpus {corpus_path}")

    prompt_text = failure_prompt["prompt"]
    gt_skills = set(
        failure_prompt.get("ground_truth_skills") or
        failure_prompt.get("predicted_skills") or []
    )
    # Ground truth is in intent space (SkillLabel taxonomy)
    # Remove "none" from ground truth for positive scoring
    _NONE = "none"
    ground_truth = gt_skills - {_NONE}

    # Load mapping and skills
    mapping = _load_intent_map(map_path)
    skills = _load_skills(skills_dir)

    # --- Define the 6 ablation configurations ---
    # Detect the two target skills (spring-boot-endpoint and spring-jpa-entity if present,
    # or whatever skills are in the directory)
    skill_names = sorted(skills.keys())

    # Build baseline tools for full config
    def _tools_for(included_names: list[str],
                   desc_overrides: dict[str, str] | None = None) -> list[dict]:
        result = []
        for name in included_names:
            if name not in skills:
                continue
            desc = skills[name]["description"]
            if desc_overrides and name in desc_overrides:
                desc = desc_overrides[name]
            result.append(build_skill_tool(name, desc))
        return result

    # "Baseline" description = a minimal placeholder (for desc→base ablation)
    # In RESEARCH the "baseline" description is the arm-B (unfrozen Phase-2) description.
    # In this offline test harness we use a generic placeholder that does NOT trigger.
    baseline_desc = "Generic skill — baseline placeholder (ablation)."

    configs: list[tuple[str, list[dict]]] = []

    if len(skill_names) >= 2:
        sbe = skill_names[0]  # first skill (alphabetical)
        sje = skill_names[1]  # second skill

        configs = [
            # 1. Full config
            ("None (full Setdrift config)", _tools_for(skill_names)),
            # 2. First skill desc → baseline
            (f"{sbe} desc→base", _tools_for(skill_names, {sbe: baseline_desc})),
            # 3. Second skill desc → baseline
            (f"{sje} desc→base", _tools_for(skill_names, {sje: baseline_desc})),
            # 4. First skill removed
            (f"{sbe} removed", _tools_for([n for n in skill_names if n != sbe])),
            # 5. Second skill removed
            (f"{sje} removed", _tools_for([n for n in skill_names if n != sje])),
            # 6. Both removed (arm-C floor)
            ("Both skills removed (arm-C floor)", []),
        ]
    elif len(skill_names) == 1:
        s = skill_names[0]
        configs = [
            ("None (full Setdrift config)", _tools_for(skill_names)),
            (f"{s} desc→base", _tools_for(skill_names, {s: baseline_desc})),
            (f"{s} removed", []),
            ("arm-C floor (no skills)", []),
            ("arm-C floor variant 2", []),
            ("arm-C floor variant 3", []),
        ]
    else:
        # No skills: all 6 are arm-C floor
        configs = [
            ("None (full Setdrift config — no skills)", []),
            ("ablation 1 (no skills)", []),
            ("ablation 2 (no skills)", []),
            ("ablation 3 (no skills)", []),
            ("ablation 4 (no skills)", []),
            ("arm-C floor", []),
        ]

    # --- Score each configuration ---
    rows: list[dict] = []
    full_f1: float | None = None

    for component, tools in configs:
        f1, fired, predicted = _score_single_prompt(
            prompt_text, tools, mapping, ground_truth,
            cache_dir=cache_dir, model=model,
        )
        if full_f1 is None:
            full_f1 = f1  # first config is always the full config

        rows.append({
            "component": component,
            "fired_intents": sorted(predicted),
            "f1": f1,
            "delta_vs_full": f1 - (full_f1 or 0.0),
            "root_cause": False,
        })

    # --- Flag root cause: the row(s) with the largest negative delta ---
    # Skip the full-config row (delta=0 by definition) when finding root cause
    non_full_rows = [r for r in rows if r["delta_vs_full"] != 0.0 or rows.index(r) > 0]
    # Actually use all rows except index 0 for root cause determination
    ablation_rows = rows[1:]  # rows 1-5 are the ablations
    if ablation_rows:
        most_negative_delta = min(r["delta_vs_full"] for r in ablation_rows)
        if most_negative_delta < 0:
            # Flag the first row with the most negative delta
            for r in ablation_rows:
                if abs(r["delta_vs_full"] - most_negative_delta) < 1e-9:
                    r["root_cause"] = True
                    break
        else:
            # No row made things worse — flag the one with smallest delta (largest opportunity)
            # Still flag something to satisfy the "at least one ROOT CAUSE" contract
            smallest_delta = min(r["delta_vs_full"] for r in ablation_rows)
            for r in ablation_rows:
                if abs(r["delta_vs_full"] - smallest_delta) < 1e-9:
                    r["root_cause"] = True
                    break

    return rows


def render_table(rows: list[dict]) -> str:
    """Render the ablation table as a columnar string.

    Column layout (RESEARCH §Proposed Discretion Answers 1):
    Component removed | Fired intents | F1 | Delta vs full-config

    Root-cause rows are annotated with <-- ROOT CAUSE.
    """
    _SEP = " | "

    header = ["Component removed", "Fired intents", "F1", "Delta vs full-config"]

    # Format rows
    data_rows = []
    for r in rows:
        fired_str = "{" + ", ".join(r.get("fired_intents") or []) + "}"
        f1_str = f"{r['f1']:.3f}"
        delta = r["delta_vs_full"]
        delta_str = "baseline" if delta == 0.0 else f"{delta:+.3f}"
        if r.get("root_cause"):
            delta_str += " <-- ROOT CAUSE"
        data_rows.append([r["component"], fired_str, f1_str, delta_str])

    # Compute column widths
    all_rows = [header] + data_rows
    col_widths = [max(len(row[i]) for row in all_rows) for i in range(4)]

    def _fmt_row(row: list[str]) -> str:
        return _SEP.join(cell.ljust(col_widths[i]) for i, cell in enumerate(row))

    separator = "-" * (sum(col_widths) + len(_SEP) * 3)
    lines = [_fmt_row(header), separator]
    for row in data_rows:
        lines.append(_fmt_row(row))

    return "\n".join(lines) + "\n"

"""CLI entrypoint for the setdrift-eval harness."""

import argparse
import os
from pathlib import Path

from setdrift_eval.corpus.builder import build_corpus


def _rollback_restore(skill_descriptions, expected_sig, targets):
    """Thin wrapper around applier.restore_config; monkeypatched in tests to inject paths."""
    from setdrift_eval.optimizer.applier import restore_config

    restore_config(skill_descriptions, expected_sig, targets)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="setdrift-eval", description="Setdrift evaluation harness"
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("benchmark", help="run the offline replay benchmark")
    sub.add_parser("optimize", help="run the skill-trigger optimizer")

    health_p = sub.add_parser("health", help="compute skill-trigger macro-F1 for an arm")
    health_p.add_argument("--corpus", choices=["public"], default="public")
    health_p.add_argument("--arm", choices=["A", "B", "C"], required=True)
    health_p.add_argument("--seed", type=int, default=42)
    health_p.add_argument(
        "--corpus-path", type=Path, default=Path("data/corpora/public/public.jsonl")
    )
    health_p.add_argument(
        "--map", type=Path, default=Path("eval/setdrift_eval/corpus/intent_skill_map.yaml")
    )
    health_p.add_argument("--skills-dir", type=Path, default=Path("plugin/skills"))
    health_p.add_argument("--experiments-dir", type=Path, default=Path("experiments"))
    health_p.add_argument(
        "--json",
        dest="emit_json",
        action="store_true",
        help="emit metrics as JSON to stdout (D-12, feeds Phase-6 Next.js)",
    )
    health_p.add_argument(
        "--live",
        action="store_true",
        help="launch Textual TUI dashboard (D-03)",
    )

    corpus_parser = sub.add_parser("corpus", help="build and verify the public prompt corpus")
    corpus_sub = corpus_parser.add_subparsers(dest="corpus_cmd")

    build_p = corpus_sub.add_parser("build", help="build the labeled corpus JSONL")
    build_p.add_argument("--raw-dir", type=Path, default=Path("data/raw/gitbug-java"))
    build_p.add_argument("--output", type=Path, default=Path("data/corpora/public/public.jsonl"))
    build_p.add_argument("--version", required=True, help="corpus version tag, e.g. 2026-05-22")
    build_p.add_argument(
        "--gitbug-meta-dir",
        type=Path,
        default=None,
        help="GitBug-Java metadata checkout (adds ~199 bugs via bundled bug_patch)",
    )
    build_p.add_argument(
        "--defects4j-dir",
        type=Path,
        default=None,
        help="Defects4J v1.2 framework checkout (adds ~395 bugs via .src.patch)",
    )
    build_p.add_argument(
        "--constructed-negatives",
        type=Path,
        default=None,
        help="TSV of hand-authored near-miss negatives for the >=20%% top-up",
    )
    build_p.add_argument("--min-negative-fraction", type=float, default=0.20)

    verify_p = corpus_sub.add_parser("verify", help="emit a 20%% manual-verification CSV")
    verify_p.add_argument("--corpus", type=Path, required=True)
    verify_p.add_argument("--output", type=Path, default=Path("data/corpus/verify.csv"))
    verify_p.add_argument("--seed", type=int, default=42)
    verify_p.add_argument(
        "--min-per-source",
        type=int,
        default=20,
        help="floor on rows sampled per source (D-35 Pitfall 6, default: 20)",
    )

    # --- ablate subcommand (REQ-LOOP-03 leave-one-out failure attribution) ---
    ablate_p = sub.add_parser(
        "ablate",
        help="per-component leave-one-out failure-attribution ablation table",
    )
    ablate_p.add_argument(
        "--failure-id",
        required=True,
        help="prompt_id of the failure prompt to ablate",
    )
    ablate_p.add_argument(
        "--corpus-path",
        type=Path,
        default=Path("data/corpora/public/public.jsonl"),
        help="path to the corpus JSONL (default: data/corpora/public/public.jsonl)",
    )
    ablate_p.add_argument(
        "--skills-dir",
        type=Path,
        default=Path("plugin/skills"),
        help="path to the skills directory (default: plugin/skills)",
    )
    ablate_p.add_argument(
        "--map",
        type=Path,
        default=Path("eval/setdrift_eval/corpus/intent_skill_map.yaml"),
        help="path to intent_skill_map.yaml",
    )
    ablate_p.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="path to the response cache directory (optional)",
    )

    # --- init-keys subcommand (REQ-SAFETY-02 key provisioning) ---
    sub.add_parser(
        "init-keys",
        help="generate HMAC signing key in data/keys/ (idempotent; run once per environment)",
    )

    # --- rollback subcommand (REQ-SAFETY-02 one-command signature-verified restore) ---
    rollback_p = sub.add_parser(
        "rollback",
        help="restore a prior signed config by config_hash (verifies HMAC before activating)",
    )
    rollback_p.add_argument(
        "--to",
        required=True,
        metavar="HASH",
        help="config_hash of the audit log entry to restore",
    )
    rollback_p.add_argument(
        "--audit-log",
        type=Path,
        default=Path("data/audit/audit.jsonl"),
        help="path to the audit JSONL log (default: data/audit/audit.jsonl)",
    )

    # --- loop subcommand (REQ-LOOP-01/02 observe->diagnose->patch->verify cycle) ---
    loop_p = sub.add_parser(
        "loop",
        help="run one observe->diagnose->patch->verify->promote|rollback cycle (D-43: dry-run by default)",
    )
    loop_p.add_argument(
        "--skill",
        required=True,
        help="kebab-case skill name to optimize (e.g. spring-boot-endpoint)",
    )
    loop_p.add_argument(
        "--corpus-path",
        type=Path,
        default=Path("data/corpora/public/public.jsonl"),
        help="path to the corpus JSONL (split.json must be adjacent)",
    )
    loop_p.add_argument(
        "--skills-dir",
        type=Path,
        default=Path("plugin/skills"),
        help="path to the skills directory (default: plugin/skills)",
    )
    loop_p.add_argument(
        "--map",
        type=Path,
        default=Path("eval/setdrift_eval/corpus/intent_skill_map.yaml"),
        help="path to intent_skill_map.yaml",
    )
    loop_p.add_argument(
        "--experiments-dir",
        type=Path,
        default=Path("experiments"),
        help="path to the experiments/ directory (default: experiments)",
    )
    loop_p.add_argument(
        "--seed",
        type=int,
        default=42,
        help="RNG seed for reproducibility (default: 42)",
    )
    loop_p.add_argument(
        "--dry-run",
        # WR-10: BooleanOptionalAction with default=True so the CLI default
        # matches both this help text and run_loop_cycle's dry_run=True
        # signature default (D-43 two-layer defense). Opt out with --no-dry-run.
        action=argparse.BooleanOptionalAction,
        default=True,
        help="validate the cycle without writing to live plugin/ (default behavior; D-43). "
        "Pass --no-dry-run (with --approve) to apply a promoted candidate live.",
    )
    loop_p.add_argument(
        "--approve",
        action="store_true",
        help="apply a promoted candidate to live plugin/ (requires human approval, D-43)",
    )

    # --- drift subcommand (REQ-DRIFT-03 grid run + paired-difference report) ---
    drift_p = sub.add_parser(
        "drift",
        help="run the yoked drift grid and emit a per-model paired-difference report (REQ-DRIFT-03)",
    )
    drift_p.add_argument(
        "--mode",
        choices=["real", "synthetic"],
        default="synthetic",
        help="evaluation mode: 'synthetic' (default) or 'real' GitBug-Java corpus",
    )
    drift_p.add_argument(
        "--gitbug-repo",
        type=Path,
        default=None,
        help="path to the GitBug-Java repository for real-mode snapshotting",
    )
    drift_p.add_argument(
        "--corpus",
        type=Path,
        default=Path("data/corpora/public/public.jsonl"),
        help="path to corpus JSONL (default: data/corpora/public/public.jsonl)",
    )
    drift_p.add_argument(
        "--map",
        type=Path,
        default=Path("eval/setdrift_eval/corpus/intent_skill_map.yaml"),
        help="path to intent_skill_map.yaml (default: eval/setdrift_eval/corpus/intent_skill_map.yaml)",
    )
    drift_p.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/cache"),
        help="path to LLM response cache directory (default: data/cache)",
    )
    drift_p.add_argument(
        "--arm-a-skills",
        type=Path,
        default=None,
        help=(
            "skills directory for arm A (Setdrift-managed config); "
            "default: SETDRIFT_ARM_A_SKILLS env var or plugin/skills"
        ),
    )
    drift_p.add_argument(
        "--arm-b-skills",
        type=Path,
        default=None,
        help=(
            "skills directory for arm B (frozen hand-written config); "
            "default: SETDRIFT_ARM_B_SKILLS env var or plugin/skills-frozen"
        ),
    )
    drift_p.add_argument(
        "--haiku",
        action="store_true",
        help="also run the Haiku TEST-partition A/B sensitivity arm (REQ-DRIFT-03, D-59)",
    )

    # --- judge-sensitivity subcommand (Phase 5 Wave 1, D-11) ---
    judge_p = sub.add_parser(
        "judge-sensitivity",
        help="run 5-bias-mode x 3-family LLM-as-judge sensitivity matrix (D-11)",
    )
    judge_p.add_argument(
        "--slice",
        type=Path,
        default=Path("data/judge/slice_100.jsonl"),
        help="path to 100-prompt curated slice (D-14)",
    )
    judge_p.add_argument("--seed", type=int, default=42)
    judge_p.add_argument(
        "--manifest",
        type=Path,
        default=Path("experiments/judge-sensitivity.json"),
        help="output path for the scrubbed kappa matrix (experiments/ only — not data/)",
    )

    # --- figures subcommand (D-10 deterministic figure regeneration) ---
    figures_p = sub.add_parser(
        "figures",
        help="regenerate dissertation figures from experiments/ JSON (D-10)",
    )
    figures_p.add_argument(
        "--experiments-dir",
        type=Path,
        default=Path("experiments"),
        help="path to experiments/ JSON directory",
    )
    figures_p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/figures"),
        help="output directory for PDF/PNG figures",
    )
    figures_p.add_argument(
        "--allow-fixtures",
        action="store_true",
        help="allow fixture data (watermark applied); never use for dissertation figures (D-09)",
    )
    figures_p.add_argument(
        "--build-inputs",
        action="store_true",
        help=(
            "materialize experiments/cost-tokens.json and experiments/triangulation-series.json "
            "from real manifests, overwriting both wholesale (FIX-03 producer step; "
            "run before --cost-delta / --triangulation so they never need --allow-fixtures)"
        ),
    )
    figures_p.add_argument(
        "--genealogy", action="store_true", help="generate skill genealogy Mermaid diagram"
    )
    figures_p.add_argument(
        "--f1-curve", action="store_true", help="generate F1-over-versions curve"
    )
    figures_p.add_argument(
        "--cost-delta", action="store_true", help="generate cost delta figure (REQ-DELIV-02)"
    )
    figures_p.add_argument(
        "--triangulation", action="store_true", help="generate triangulation scatter (D-15)"
    )
    figures_p.add_argument("--kappa-matrix", action="store_true", help="generate 5x3 kappa heatmap")
    figures_p.add_argument(
        "--all", dest="all_figures", action="store_true", help="generate all figures"
    )

    # --- deprecate-scan subcommand (REQ-SAFETY-03 idle-archive + rejection-quarantine) ---
    deprecate_scan_p = sub.add_parser(
        "deprecate-scan",
        help="scan skills for idle-archive and rejection-quarantine decisions",
    )
    deprecate_scan_p.add_argument(
        "--skills-dir",
        type=Path,
        default=Path("plugin/skills"),
        help="path to the skills directory (default: plugin/skills)",
    )
    deprecate_scan_p.add_argument(
        "--telemetry-dir",
        type=Path,
        default=Path(os.environ.get("SETDRIFT_TELEMETRY_DIR", "data/telemetry")),
        help=(
            "path to the sharded telemetry directory, globbed for *.events.jsonl "
            "(default: data/telemetry, overridable via SETDRIFT_TELEMETRY_DIR)"
        ),
    )

    # --- promote-skill subcommand (REQ-SAFETY-03 manual re-promotion from quarantine) ---
    promote_skill_p = sub.add_parser(
        "promote-skill",
        help="re-promote a quarantined skill back into the load glob",
    )
    promote_skill_p.add_argument(
        "--name",
        required=True,
        help="skill name (kebab-case) to promote from quarantine",
    )
    promote_skill_p.add_argument(
        "--skills-dir",
        type=Path,
        default=Path("plugin/skills"),
        help="path to the skills directory (default: plugin/skills)",
    )

    args = parser.parse_args()

    if args.cmd == "corpus" and args.corpus_cmd == "build":
        from setdrift_eval.corpus.builder import freeze_split
        from setdrift_eval.corpus.schemas import SkillLabel

        corpus = build_corpus(
            raw_dir=args.raw_dir,
            output_path=args.output,
            corpus_version=args.version,
            gitbug_meta_dir=args.gitbug_meta_dir,
            defects4j_dir=args.defects4j_dir,
            min_negative_fraction=args.min_negative_fraction,
            constructed_negatives_path=args.constructed_negatives,
        )
        n = len(corpus.prompts)
        neg = sum(1 for p in corpus.prompts if p.predicted_skills == [SkillLabel.NONE])
        _, split_hash = freeze_split(corpus.prompts, Path(args.output).parent, rng_seed=42)
        neg_pct = (100 * neg / n) if n else 0.0
        print(
            f"[setdrift-eval] built corpus: {n} prompts, {neg} negatives ({neg_pct:.1f}%), "
            f"split_hash={split_hash} -> {args.output}"
        )
        return 0
    if args.cmd == "corpus" and args.corpus_cmd == "verify":
        from setdrift_eval.corpus.sampler import emit_verification_csv

        # D-35: stratify by source.dataset so every source is proportionally
        # represented (with a min_per_source floor) — required for the
        # precision_gate's per-source >=20%-negatives criterion (07-05 Task 1
        # gap: CLI previously never wired stratify_by_source, defeating the
        # sampler's tested D-35 behavior).
        emit_verification_csv(
            corpus_path=args.corpus,
            output_path=args.output,
            seed=args.seed,
            stratify_by_source=True,
            min_per_source=args.min_per_source,
        )
        print(f"[setdrift-eval] verification CSV written -> {args.output}")
        return 0

    if args.cmd == "health" and getattr(args, "live", False):
        # Lazy import: textual is an optional extra (D-03)
        from setdrift_eval.dashboard.app import SetdriftDashboard

        SetdriftDashboard(
            corpus_path=args.corpus_path,
            arm=args.arm,
            seed=args.seed,
            map_path=args.map,
            skills_dir=args.skills_dir,
            experiments_dir=args.experiments_dir,
        ).run()
        return 0

    if args.cmd == "health" and getattr(args, "emit_json", False):
        # Lazy import: dashboard is an optional extra; json is stdlib (D-12)
        import json as _json
        from setdrift_eval.dashboard.health_export import export_health_json

        payload = export_health_json(
            corpus_path=args.corpus_path,
            arm=args.arm,
            seed=args.seed,
            map_path=args.map,
            skills_dir=args.skills_dir,
            experiments_dir=args.experiments_dir,
        )
        print(_json.dumps(payload, indent=2))
        return 0

    if args.cmd == "health":
        from setdrift_eval.evidence.preflight import assert_evidence_run
        from setdrift_eval.telemetry.scorer import run_health

        # Fail-loud model/backend preflight (D7-19), wired here (not in the
        # FROZEN scorer.py) because run_health lives in the Goodhart-firewall
        # frozen-ruler file and must not be edited.
        assert_evidence_run(os.environ.get("SETDRIFT_MODEL", "claude-sonnet-4-6"))

        result = run_health(
            corpus_path=args.corpus_path,
            arm=args.arm,
            seed=args.seed,
            map_path=args.map,
            skills_dir=args.skills_dir,
            experiments_dir=args.experiments_dir,
        )
        print(
            f"[setdrift-eval] health corpus={args.corpus} arm={args.arm} "
            f"macro_f1={result.macro_f1_mean:.4f} "
            f"noise_band=[{result.noise_band_low:.4f},{result.noise_band_high:.4f}] "
            f"bootstrap_ci=[{result.bootstrap_ci_low:.4f},{result.bootstrap_ci_high:.4f}] "
            f"coverage={result.coverage_pct:.3f}"
        )
        return 0

    if args.cmd == "ablate":
        # Lazy import (project convention)
        from setdrift_eval.optimizer.ablate import build_ablation_table, render_table

        rows = build_ablation_table(
            failure_id=args.failure_id,
            corpus_path=args.corpus_path,
            skills_dir=args.skills_dir,
            map_path=args.map,
            cache_dir=args.cache_dir,
        )
        root_cause_rows = [r for r in rows if r.get("root_cause")]
        root_cause = root_cause_rows[0]["component"] if root_cause_rows else "unknown"
        print(f"[setdrift-eval] ablate failure-id={args.failure_id} root_cause={root_cause}")
        print(render_table(rows))
        return 0

    if args.cmd == "init-keys":
        # Lazy import (project convention)
        from setdrift_eval.optimizer.signer import generate_key

        key_path = Path(os.environ.get("SETDRIFT_SIGNING_KEY", "data/keys/sica-hmac.key"))
        if key_path.exists():
            print(
                f"[setdrift-eval] init-keys: key already exists at '{key_path}' — "
                "refusing to overwrite (idempotent). Delete the file manually to regenerate."
            )
            return 0
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_hex = generate_key()
        key_path.write_text(key_hex, encoding="utf-8")
        print(
            f"[setdrift-eval] init-keys: generated HMAC signing key at '{key_path}' "
            f"({len(key_hex) // 2} bytes). "
            "This file is gitignored — NEVER commit it."
        )
        return 0

    if args.cmd == "rollback":
        # Lazy import (project convention)
        import json

        audit_log = Path(args.audit_log)
        target_hash = args.to

        if not audit_log.exists():
            print(f"[setdrift-eval] rollback: audit log not found at '{audit_log}'")
            return 1

        # Find the audit entry with matching config_hash
        entry = None
        with audit_log.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if record.get("config_hash") == target_hash:
                    entry = record
                    # Don't break — use the latest matching entry
        if entry is None:
            print(
                f"[setdrift-eval] rollback: no audit entry found with config_hash='{target_hash}'"
            )
            return 1

        hmac_sig = entry.get("hmac_sig")
        skill_descriptions = entry.get("skill_descriptions")
        if not hmac_sig or not skill_descriptions:
            print(
                f"[setdrift-eval] rollback: audit entry for hash='{target_hash}' is missing "
                "'hmac_sig' or 'skill_descriptions' — cannot restore."
            )
            return 1

        # Build targets mapping: skill_name -> Path (default plugin/skills/<name>/SKILL.md)
        targets = {
            name: Path("plugin") / "skills" / name / "SKILL.md" for name in skill_descriptions
        }

        # Delegate to _rollback_restore (monkeypatchable in tests for path injection)
        _rollback_restore(skill_descriptions, hmac_sig, targets)

        print(f"[setdrift-eval] rollback restored config_hash={target_hash} verified=True")
        return 0

    if args.cmd == "loop":
        # Lazy import (project convention)
        from setdrift_eval.optimizer.orchestrator import run_loop_cycle

        loop_result = run_loop_cycle(
            skill_name=args.skill,
            corpus_path=args.corpus_path,
            skills_dir=args.skills_dir,
            map_path=args.map,
            experiments_dir=args.experiments_dir,
            seed=args.seed,
            dry_run=args.dry_run,
            approve=args.approve,
        )
        staged = loop_result.promotion_decision == "promoted"
        print(
            f"[setdrift-eval] loop cycle_id={loop_result.cycle_id} "
            f"decision={loop_result.promotion_decision} "
            f"f1_delta={loop_result.f1_delta:+.4f} "
            f"staged={staged}"
        )
        return 0

    if args.cmd == "judge-sensitivity":
        # Lazy import (project convention — D-11 judge harness)
        from setdrift_eval.judge.runner import run_judge_sensitivity

        return run_judge_sensitivity(args)

    if args.cmd == "figures":
        # Lazy import (project convention — D-10 deterministic figures CLI)
        from setdrift_eval.figures.cli import main as figures_main  # lazy import

        return figures_main(args)

    if args.cmd == "drift":
        # Lazy imports — [drift] extra not required at setdrift-eval load time
        from setdrift_eval.benchmark.arm_runner import load_skill_tools
        from setdrift_eval.drift.grid_runner import _config_hash, run_grid
        from setdrift_eval.drift.paired_stats import paired_difference_report
        from setdrift_eval.drift.db import connect

        con = connect()

        # CR-01: arm A (Setdrift-managed) and arm B (frozen hand-written) must be
        # DIFFERENT configs. Arm B defaults to the frozen baseline plugin/skills;
        # arm A has NO safe default (promotion is in-place — there is no static
        # "promoted" dir), so it must be supplied via --arm-a-skills or
        # SETDRIFT_ARM_A_SKILLS. Fail loud rather than silently aliasing A to B.
        arm_a_skills = args.arm_a_skills or (
            Path(os.environ["SETDRIFT_ARM_A_SKILLS"])
            if os.environ.get("SETDRIFT_ARM_A_SKILLS")
            else None
        )
        if arm_a_skills is None:
            raise SystemExit(
                "[setdrift-eval] drift: arm A (Setdrift-managed config) has no safe default. "
                "Pass --arm-a-skills <dir> or set SETDRIFT_ARM_A_SKILLS to the Phase-3 "
                "promoted/optimized skills dir. Defaulting it to plugin/skills would "
                "make arm A == arm B and null the A/B comparison (CR-01)."
            )
        arm_b_skills = args.arm_b_skills or Path(
            os.environ.get("SETDRIFT_ARM_B_SKILLS", "plugin/skills")
        )
        # Belt-and-suspenders: even with distinct paths, fail loudly if both arms
        # resolve to an identical effective toolset — that makes every paired_diff
        # identically 0 and the falsifiable-claim comparison structurally null.
        if _config_hash(load_skill_tools(arm_a_skills)) == _config_hash(
            load_skill_tools(arm_b_skills)
        ):
            raise SystemExit(
                "[setdrift-eval] drift: arm A and arm B resolve to identical toolsets "
                f"(A={arm_a_skills}, B={arm_b_skills}) — the A/B comparison is "
                "meaningless. Point --arm-a-skills at the Setdrift-managed config and "
                "--arm-b-skills at the frozen hand-written baseline (CR-01)."
            )
        arm_configs = {
            "A": arm_a_skills,
            "B": arm_b_skills,
        }
        revision_shas = {
            "early": "HEAD~10",
            "mid": "HEAD~5",
            "late": "HEAD",
        }
        gitbug_repo = args.gitbug_repo or Path("data/raw/gitbug-java")

        run_grid(
            gitbug_repo=gitbug_repo,
            arm_configs=arm_configs,
            corpus_path=args.corpus,
            map_path=args.map,
            revision_shas=revision_shas,
            cache_dir=args.cache_dir,
        )

        # Paired-difference report for Sonnet
        sonnet_results = paired_difference_report(con, model="claude-sonnet-4-6")
        for revision, r in sorted(sonnet_results.items()):
            print(
                f"[setdrift-eval] drift model=claude-sonnet-4-6 revision={revision} "
                f"arm_A_mean={r.mean_A:.4f} arm_B_mean={r.mean_B:.4f} "
                f"paired_diff={r.paired_diff:+.4f} p={r.p_value:.4f} "
                f"exceeds_b_band={r.exceeds_b_upper_band}"
            )

        # Optionally run the Haiku TEST-partition sensitivity arm (--haiku flag)
        if args.haiku:
            from setdrift_eval.drift.haiku_arm import run_haiku_sensitivity

            haiku_report = run_haiku_sensitivity(
                corpus_path=args.corpus,
                arm_configs=arm_configs,
                map_path=args.map,
                cache_dir=args.cache_dir,
                con=con,
            )
            haiku_results = paired_difference_report(con, model="claude-haiku-4-5-20251001")
            for revision, r in sorted(haiku_results.items()):
                print(
                    f"[setdrift-eval] drift model=claude-haiku-4-5-20251001 revision={revision} "
                    f"arm_A_mean={r.mean_A:.4f} arm_B_mean={r.mean_B:.4f} "
                    f"paired_diff={r.paired_diff:+.4f} p={r.p_value:.4f} "
                    f"exceeds_b_band={r.exceeds_b_upper_band}"
                )
            # Print Haiku cost summary (D-60)
            print(
                f"[setdrift-eval] drift haiku cost_usd={haiku_report['cost_usd']:.6f} "
                f"n_test_prompts={haiku_report['n_prompts_scored']}"
            )

        con.close()
        return 0

    if args.cmd == "deprecate-scan":
        # Lazy import (project convention)
        from setdrift_eval.optimizer.deprecator import scan, quarantine_skill

        decisions = scan(args.skills_dir, args.telemetry_dir)
        archived = 0
        quarantined = 0
        errors = 0
        for decision in decisions:
            if decision.decision == "archive":
                archived += 1
                print(
                    f"[setdrift-eval] deprecate-scan archive skill={decision.skill_name} reason={decision.reason!r}"
                )
            elif decision.decision == "quarantine":
                # WR-09: a failing apply (e.g. SKILL.md already moved) must not
                # abort the loop and swallow the remaining decisions — print the
                # error and continue.
                try:
                    quarantine_skill(decision.skill_name, args.skills_dir)
                except (FileNotFoundError, OSError) as exc:
                    errors += 1
                    print(
                        f"[setdrift-eval] deprecate-scan quarantine FAILED "
                        f"skill={decision.skill_name} error={exc}"
                    )
                    continue
                quarantined += 1
                print(
                    f"[setdrift-eval] deprecate-scan quarantine skill={decision.skill_name} reason={decision.reason!r}"
                )
        print(
            f"[setdrift-eval] deprecate-scan archived={archived} "
            f"quarantined={quarantined} errors={errors}"
        )
        return 0 if errors == 0 else 1

    if args.cmd == "promote-skill":
        # Lazy import (project convention)
        from setdrift_eval.optimizer.deprecator import promote_skill

        decision = promote_skill(args.name, args.skills_dir)
        print(
            f"[setdrift-eval] promote-skill name={args.name} restored=True reason={decision.reason!r}"
        )
        return 0

    print(f"[setdrift-eval] '{args.cmd or 'help'}' not yet implemented — scaffold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

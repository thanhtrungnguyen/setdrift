"""CLI entrypoint for the sica-eval harness."""
import argparse
from pathlib import Path

from sica_eval.corpus.builder import build_corpus


def _rollback_restore(skill_descriptions, expected_sig, targets):
    """Thin wrapper around applier.restore_config; monkeypatched in tests to inject paths."""
    from sica_eval.optimizer.applier import restore_config
    restore_config(skill_descriptions, expected_sig, targets)


def main() -> int:
    parser = argparse.ArgumentParser(prog="sica-eval", description="SICA evaluation harness")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("benchmark", help="run the offline replay benchmark")
    sub.add_parser("optimize", help="run the skill-trigger optimizer")

    health_p = sub.add_parser("health", help="compute skill-trigger macro-F1 for an arm")
    health_p.add_argument("--corpus", choices=["public"], default="public")
    health_p.add_argument("--arm", choices=["B", "C"], required=True)
    health_p.add_argument("--seed", type=int, default=42)
    health_p.add_argument("--corpus-path", type=Path, default=Path("data/corpora/public/public.jsonl"))
    health_p.add_argument("--map", type=Path, default=Path("eval/sica_eval/corpus/intent_skill_map.yaml"))
    health_p.add_argument("--skills-dir", type=Path, default=Path("plugin/skills"))
    health_p.add_argument("--experiments-dir", type=Path, default=Path("experiments"))

    corpus_parser = sub.add_parser("corpus", help="build and verify the public prompt corpus")
    corpus_sub = corpus_parser.add_subparsers(dest="corpus_cmd")

    build_p = corpus_sub.add_parser("build", help="build the labeled corpus JSONL")
    build_p.add_argument("--raw-dir", type=Path, default=Path("data/raw/gitbug-java"))
    build_p.add_argument("--output", type=Path, default=Path("data/corpora/public/public.jsonl"))
    build_p.add_argument("--version", required=True, help="corpus version tag, e.g. 2026-05-22")
    build_p.add_argument("--gitbug-meta-dir", type=Path, default=None,
                         help="GitBug-Java metadata checkout (adds ~199 bugs via bundled bug_patch)")
    build_p.add_argument("--defects4j-dir", type=Path, default=None,
                         help="Defects4J v1.2 framework checkout (adds ~395 bugs via .src.patch)")
    build_p.add_argument("--constructed-negatives", type=Path, default=None,
                         help="TSV of hand-authored near-miss negatives for the >=20%% top-up")
    build_p.add_argument("--min-negative-fraction", type=float, default=0.20)

    verify_p = corpus_sub.add_parser("verify", help="emit a 20%% manual-verification CSV")
    verify_p.add_argument("--corpus", type=Path, required=True)
    verify_p.add_argument("--output", type=Path, default=Path("data/corpus/verify.csv"))
    verify_p.add_argument("--seed", type=int, default=42)

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
        "--to", required=True, metavar="HASH",
        help="config_hash of the audit log entry to restore",
    )
    rollback_p.add_argument(
        "--audit-log", type=Path, default=Path("data/audit/audit.jsonl"),
        help="path to the audit JSONL log (default: data/audit/audit.jsonl)",
    )

    args = parser.parse_args()

    if args.cmd == "corpus" and args.corpus_cmd == "build":
        from sica_eval.corpus.builder import freeze_split
        from sica_eval.corpus.schemas import SkillLabel

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
            f"[sica-eval] built corpus: {n} prompts, {neg} negatives ({neg_pct:.1f}%), "
            f"split_hash={split_hash} -> {args.output}"
        )
        return 0
    if args.cmd == "corpus" and args.corpus_cmd == "verify":
        from sica_eval.corpus.sampler import emit_verification_csv

        emit_verification_csv(
            corpus_path=args.corpus, output_path=args.output, seed=args.seed
        )
        print(f"[sica-eval] verification CSV written -> {args.output}")
        return 0

    if args.cmd == "health":
        from sica_eval.telemetry.scorer import run_health

        result = run_health(
            corpus_path=args.corpus_path,
            arm=args.arm,
            seed=args.seed,
            map_path=args.map,
            skills_dir=args.skills_dir,
            experiments_dir=args.experiments_dir,
        )
        print(
            f"[sica-eval] health corpus={args.corpus} arm={args.arm} "
            f"macro_f1={result.macro_f1_mean:.4f} "
            f"noise_band=[{result.noise_band_low:.4f},{result.noise_band_high:.4f}] "
            f"bootstrap_ci=[{result.bootstrap_ci_low:.4f},{result.bootstrap_ci_high:.4f}] "
            f"coverage={result.coverage_pct:.3f}"
        )
        return 0

    if args.cmd == "init-keys":
        # Lazy import (project convention)
        import os
        from sica_eval.optimizer.signer import generate_key

        key_path = Path(os.environ.get("SICA_SIGNING_KEY", "data/keys/sica-hmac.key"))
        if key_path.exists():
            print(
                f"[sica-eval] init-keys: key already exists at '{key_path}' — "
                "refusing to overwrite (idempotent). Delete the file manually to regenerate."
            )
            return 0
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_hex = generate_key()
        key_path.write_text(key_hex, encoding="utf-8")
        print(
            f"[sica-eval] init-keys: generated HMAC signing key at '{key_path}' "
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
            print(f"[sica-eval] rollback: audit log not found at '{audit_log}'")
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
            print(f"[sica-eval] rollback: no audit entry found with config_hash='{target_hash}'")
            return 1

        hmac_sig = entry.get("hmac_sig")
        skill_descriptions = entry.get("skill_descriptions")
        if not hmac_sig or not skill_descriptions:
            print(
                f"[sica-eval] rollback: audit entry for hash='{target_hash}' is missing "
                "'hmac_sig' or 'skill_descriptions' — cannot restore."
            )
            return 1

        # Build targets mapping: skill_name -> Path (default plugin/skills/<name>/SKILL.md)
        targets = {
            name: Path("plugin") / "skills" / name / "SKILL.md"
            for name in skill_descriptions
        }

        # Delegate to _rollback_restore (monkeypatchable in tests for path injection)
        _rollback_restore(skill_descriptions, hmac_sig, targets)

        print(
            f"[sica-eval] rollback restored config_hash={target_hash} verified=True"
        )
        return 0

    print(f"[sica-eval] '{args.cmd or 'help'}' not yet implemented — scaffold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

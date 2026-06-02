"""CLI entrypoint for the sica-eval harness."""
import argparse
from pathlib import Path

from sica_eval.corpus.builder import build_corpus


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

    print(f"[sica-eval] '{args.cmd or 'help'}' not yet implemented — scaffold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

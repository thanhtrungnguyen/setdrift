"""CLI entrypoint for the sica-eval harness."""
import argparse
from pathlib import Path

from sica_eval.corpus.builder import build_corpus


def main() -> int:
    parser = argparse.ArgumentParser(prog="sica-eval", description="SICA evaluation harness")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("benchmark", help="run the offline replay benchmark")
    sub.add_parser("optimize", help="run the skill-trigger optimizer")
    sub.add_parser("health", help="compute config health metrics from telemetry")

    corpus_parser = sub.add_parser("corpus", help="build and verify the public prompt corpus")
    corpus_sub = corpus_parser.add_subparsers(dest="corpus_cmd")

    build_p = corpus_sub.add_parser("build", help="build the labeled corpus JSONL")
    build_p.add_argument("--raw-dir", type=Path, default=Path("data/raw/gitbug-java"))
    build_p.add_argument("--output", type=Path, default=Path("data/corpus/gitbug-java.jsonl"))
    build_p.add_argument("--version", required=True, help="corpus version tag, e.g. 2026-05-22")

    verify_p = corpus_sub.add_parser("verify", help="emit a 20%% manual-verification CSV")
    verify_p.add_argument("--corpus", type=Path, required=True)
    verify_p.add_argument("--output", type=Path, default=Path("data/corpus/verify.csv"))
    verify_p.add_argument("--seed", type=int, default=42)

    args = parser.parse_args()

    if args.cmd == "corpus" and args.corpus_cmd == "build":
        corpus = build_corpus(
            raw_dir=args.raw_dir, output_path=args.output, corpus_version=args.version
        )
        print(f"[sica-eval] built corpus with {len(corpus.prompts)} prompts -> {args.output}")
        return 0
    if args.cmd == "corpus" and args.corpus_cmd == "verify":
        from sica_eval.corpus.sampler import emit_verification_csv

        emit_verification_csv(
            corpus_path=args.corpus, output_path=args.output, seed=args.seed
        )
        print(f"[sica-eval] verification CSV written -> {args.output}")
        return 0

    print(f"[sica-eval] '{args.cmd or 'help'}' not yet implemented — scaffold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

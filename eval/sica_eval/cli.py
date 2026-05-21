"""Thin CLI entrypoint (scaffold)."""
import argparse


def main() -> int:
    parser = argparse.ArgumentParser(prog="sica-eval", description="SICA evaluation harness")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("benchmark", help="run the offline replay benchmark")
    sub.add_parser("optimize", help="run the skill-trigger optimizer")
    sub.add_parser("health", help="compute config health metrics from telemetry")
    args = parser.parse_args()
    print(f"[sica-eval] '{args.cmd or 'help'}' not yet implemented — scaffold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Dedicated CLI for the mining-precision/kappa/negatives gate (Plan 02-03).

Separate from cli.py so 02-03 does not edit the shared CLI (revision Blocker 3 —
avoids a same-wave write conflict with 02-02/02-05). Exits NON-ZERO on any gate
violation so it can block CI and the Phase-2 exit:

    python -m setdrift_eval.corpus.precision_gate_cli \\
        --csv data/corpora/public/verify.filled.csv \\
        --corpus data/corpora/public/public.jsonl \\
        --experiments-dir experiments/
"""

import argparse
from pathlib import Path

from setdrift_eval.corpus.precision_gate import (
    check_gate,
    compute_precision_and_kappa,
    load_verification,
    write_report,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="setdrift-eval-precision-gate")
    p.add_argument("--csv", type=Path, required=True, help="human-filled verification CSV")
    p.add_argument("--corpus", type=Path, required=True, help="corpus JSONL (for source join)")
    p.add_argument("--experiments-dir", type=Path, default=Path("experiments"))
    p.add_argument("--precision-threshold", type=float, default=0.85)
    p.add_argument("--kappa-threshold", type=float, default=0.6)
    p.add_argument("--min-negatives", type=float, default=0.20)
    args = p.parse_args(argv)

    rows_by_source = load_verification(args.csv, args.corpus)
    report = compute_precision_and_kappa(rows_by_source)
    report = check_gate(
        report,
        precision_threshold=args.precision_threshold,
        kappa_threshold=args.kappa_threshold,
        min_negatives_fraction=args.min_negatives,
    )
    out = write_report(report, args.experiments_dir, csv_path=args.csv)

    for source, m in sorted(report["per_source"].items()):
        verdict = "PASS" if (m["passed_precision"] and m["passed_kappa"]) else "FAIL"
        print(
            f"[{verdict}] {source}: precision={m['precision']:.3f} "
            f"(>={args.precision_threshold}), kappa={m['kappa']:.3f} "
            f"(>={args.kappa_threshold}), n={m['n']}"
        )
    neg_verdict = "PASS" if report["passed_negatives"] else "FAIL"
    print(
        f"[{neg_verdict}] negatives_fraction={report['negatives_fraction']:.3f} (>={args.min_negatives})"
    )
    print(f"[{'PASS' if report['passed'] else 'FAIL'}] overall gate -> {out}")

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

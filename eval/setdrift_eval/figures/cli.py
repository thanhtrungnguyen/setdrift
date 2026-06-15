"""CLI entry point for `setdrift-eval figures` (D-10).

What this module does:
  - Parses figures-specific args (--experiments-dir, --output-dir, --allow-fixtures,
    per-figure flags --cost-delta, --genealogy, --triangulation, --kappa-matrix, --f1-curve)
  - Calls rcparams.apply() (Agg backend) BEFORE any figure function
  - Dispatches to figure generators with fixture-gate enforcement (RESEARCH Pitfall 4)
  - Defines FigureDataError: raised when real data absent and --allow-fixtures not set

What it does NOT do:
  - Never calls plt.show() — headless Agg only (D-10 anti-pattern)
  - Never passes fixture figures to the dissertation path (D-09)
  - Never touches FROZEN files (scorer.py, arm_runner.py, experiment.py, response_cache.py)
"""
from __future__ import annotations

import argparse
from pathlib import Path


class FigureDataError(RuntimeError):
    """Raised when required Phase-3 output data is absent (D-09 / RESEARCH Pitfall 4).

    Gate: if the data file does not exist and --allow-fixtures was not passed,
    raise this error. This prevents a fixture figure from silently entering the
    dissertation as real data.
    """


def main(args: argparse.Namespace) -> int:
    """Entry point for `setdrift-eval figures` (called from top-level cli.py dispatch).

    Args:
        args: parsed Namespace from the figures subparser in cli.py.

    Returns:
        int exit code (0 = success)
    """
    # Apply shared rcParams + Agg backend BEFORE any figure function (D-10)
    from setdrift_eval.figures.rcparams import apply as apply_rcparams  # lazy import
    apply_rcparams()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    experiments_dir = Path(args.experiments_dir)
    allow_fixtures = args.allow_fixtures
    any_figure_requested = (
        args.all_figures
        or getattr(args, "cost_delta", False)
        or getattr(args, "genealogy", False)
        or getattr(args, "triangulation", False)
        or getattr(args, "kappa_matrix", False)
        or getattr(args, "f1_curve", False)
    )

    if not any_figure_requested:
        print(
            "[setdrift-eval figures] No figure flag specified. "
            "Pass --cost-delta, --all, or another figure flag. "
            "Use --help for the full option list."
        )
        return 0

    # --- cost-delta figure (REQ-DELIV-02, D-02 survives-cut substrate) ---
    if args.all_figures or getattr(args, "cost_delta", False):
        from setdrift_eval.figures.cost import plot_cost_delta  # lazy import

        cost_data_path = experiments_dir / "cost-tokens.json"
        per_version: dict[str, int]

        if cost_data_path.exists():
            import json as _json
            raw = _json.loads(cost_data_path.read_text(encoding="utf-8"))
            per_version = {str(k): int(v) for k, v in raw.items()}
            fixture_mode = False
        elif allow_fixtures:
            # Fixture data — watermark will be applied (D-09)
            per_version = {
                "v1-baseline":  100_000,
                "v2-candidate": 120_000,
                "v3-promoted":  110_000,
            }
            fixture_mode = True
        else:
            raise FigureDataError(
                f"Cost token data not found: {cost_data_path}. "
                "Pass --allow-fixtures to run against fixture data (watermark applied). "
                "Do NOT include fixture figures in the dissertation (D-09)."
            )

        output = output_dir / "cost-delta"
        plot_cost_delta(per_version, output, fixture=fixture_mode)
        watermark_note = " [FIXTURE DATA — watermarked]" if fixture_mode else ""
        print(f"[setdrift-eval figures] cost-delta -> {output}.pdf + .png{watermark_note}")

    # --- genealogy figure (REQ-DELIV-01) — placeholder; Plan 06 fills in ---
    if args.all_figures or getattr(args, "genealogy", False):
        audit_path = experiments_dir / "audit-genealogy.jsonl"
        if not audit_path.exists() and not allow_fixtures:
            raise FigureDataError(
                f"Genealogy audit source not found: {audit_path}. "
                "Pass --allow-fixtures to run against fixture data (watermark applied). "
                "Do NOT include fixture figures in the dissertation (D-09)."
            )
        # NOTE: Plan 06 wires the full genealogy implementation here.
        print("[setdrift-eval figures] genealogy — not yet implemented (Plan 06)")

    # --- triangulation figure (D-15) — placeholder; Plan 06 fills in ---
    if args.all_figures or getattr(args, "triangulation", False):
        # NOTE: Plan 06 wires the triangulation implementation here.
        print("[setdrift-eval figures] triangulation — not yet implemented (Plan 06)")

    # --- kappa-matrix figure (D-11) — placeholder; Plan 06 fills in ---
    if args.all_figures or getattr(args, "kappa_matrix", False):
        # NOTE: Plan 06 wires the kappa heatmap implementation here.
        print("[setdrift-eval figures] kappa-matrix — not yet implemented (Plan 06)")

    # --- f1-curve figure — placeholder; Plan 06 fills in ---
    if args.all_figures or getattr(args, "f1_curve", False):
        # NOTE: Plan 06 wires the F1-over-versions curve implementation here.
        print("[setdrift-eval figures] f1-curve — not yet implemented (Plan 06)")

    return 0

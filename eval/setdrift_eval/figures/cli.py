"""CLI entry point for `setdrift-eval figures` (D-10).

What this module does:
  - Parses figures-specific args (--experiments-dir, --output-dir, --allow-fixtures,
    per-figure flags --cost-delta, --genealogy, --triangulation, --kappa-matrix,
    --drift-f1, --f1-curve)
  - Calls rcparams.apply() (Agg backend) BEFORE any figure function
  - Dispatches to figure generators with fixture-gate enforcement (RESEARCH Pitfall 4)
  - Imports the SHARED FigureDataError (figures/errors.py, WR-01): raised when real
    data is absent and --allow-fixtures not set; caught once at the top of main()
    and converted to a printed error + non-zero exit

What it does NOT do:
  - Never calls plt.show() — headless Agg only (D-10 anti-pattern)
  - Never passes fixture figures to the dissertation path (D-09)
  - Never touches FROZEN files (scorer.py, arm_runner.py, experiment.py, response_cache.py)
"""

from __future__ import annotations

import argparse
from pathlib import Path

# Shared error type (WR-01): the ONE FigureDataError every figures module
# raises — lightweight import (no matplotlib/networkx/scorer dependencies).
from setdrift_eval.figures.errors import FigureDataError


def main(args: argparse.Namespace) -> int:
    """Entry point for `setdrift-eval figures` (called from top-level cli.py dispatch).

    Catches FigureDataError once at this top level (WR-01) and converts it to
    a printed error + non-zero exit code instead of a raw traceback.

    Args:
        args: parsed Namespace from the figures subparser in cli.py.

    Returns:
        int exit code (0 = success, 1 = missing real data / D-09 gate)
    """
    try:
        return _run(args)
    except FigureDataError as exc:
        print(f"[setdrift-eval figures] ERROR: {exc}")
        return 1


def _run(args: argparse.Namespace) -> int:
    """Figure dispatch body (see main for the FigureDataError boundary)."""
    # Apply shared rcParams + Agg backend BEFORE any figure function (D-10)
    from setdrift_eval.figures.rcparams import apply as apply_rcparams  # lazy import

    apply_rcparams()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    experiments_dir = Path(args.experiments_dir)
    allow_fixtures = args.allow_fixtures
    build_inputs = getattr(args, "build_inputs", False)
    any_figure_requested = (
        args.all_figures
        or getattr(args, "cost_delta", False)
        or getattr(args, "genealogy", False)
        or getattr(args, "triangulation", False)
        or getattr(args, "kappa_matrix", False)
        or getattr(args, "drift_f1", False)
        or getattr(args, "f1_curve", False)
    )

    if not any_figure_requested and not build_inputs:
        print(
            "[setdrift-eval figures] No figure flag specified. "
            "Pass --cost-delta, --all, --build-inputs, or another figure flag. "
            "Use --help for the full option list."
        )
        return 0

    # --- --build-inputs (FIX-03 producer step; materialize-then-read, D6-10) ---
    # A SEPARATE explicit CLI step (Open Question 2 resolution) that overwrites the two
    # singular experiments/*.json files wholesale from real manifests. The --cost-delta
    # / --triangulation branches below only READ these files — they never compute the
    # aggregate inline (Anti-Pattern D).
    if build_inputs:
        from setdrift_eval.figures.producers import (  # lazy import
            build_cost_tokens,
            build_drift_f1_series,
            build_triangulation_series,
        )

        cost_out = build_cost_tokens(experiments_dir)
        triangulation_out = build_triangulation_series(experiments_dir)
        print(f"[setdrift-eval figures] build-inputs -> {cost_out}")
        print(f"[setdrift-eval figures] build-inputs -> {triangulation_out}")

        # build_drift_f1_series raises FigureDataError when no drift-grid manifests
        # exist yet (RUN-05 not landed). A repo with only cost/triangulation
        # manifests must still succeed for those two producers — guard this one
        # call with an explicit skip line (never a silent skip; never a hard
        # failure of the whole --build-inputs step, D-09 never-silent discipline).
        try:
            drift_f1_out = build_drift_f1_series(experiments_dir)
            print(f"[setdrift-eval figures] build-inputs -> {drift_f1_out}")
        except FigureDataError as exc:
            print(f"[setdrift-eval figures] build-inputs -> SKIPPED drift-f1-series.json: {exc}")

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
                "v1-baseline": 100_000,
                "v2-candidate": 120_000,
                "v3-promoted": 110_000,
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

    # --- genealogy figure (REQ-DELIV-01, D-10) ---
    if args.all_figures or getattr(args, "genealogy", False):
        from setdrift_eval.figures.genealogy import (  # lazy import
            build_genealogy_dag,
            build_genealogy_dag_from_records,
            dag_to_mermaid,
        )
        from setdrift_eval.figures.genealogy_adapter import adapt_audit_records  # lazy import

        audit_path = experiments_dir / "audit-genealogy.jsonl"
        fixture_mode = False

        if audit_path.exists():
            # Real-data path (FIX-02): transform-on-read adapter joins the committed
            # AuditRecord log with sibling {NNN}-loop-manifest.json files and bypasses
            # the strict path-based build_genealogy_dag entirely. A join miss raises
            # FigureDataError naming the orphan cycle_id and is NEVER caught here —
            # never skip-and-render a partial graph (D6-05).
            records = adapt_audit_records(audit_path, experiments_dir)
            dag = build_genealogy_dag_from_records(records)
        elif allow_fixtures:
            # --allow-fixtures: load the committed genealogy fixture (D-09 watermark applied)
            fixture_path = Path(__file__).parent / "fixtures" / "genealogy_fixture.jsonl"
            dag = build_genealogy_dag(fixture_path)
            fixture_mode = True
        else:
            raise FigureDataError(
                f"Genealogy audit source not found: {audit_path}. "
                "Pass --allow-fixtures to run against fixture data (watermark applied). "
                "Do NOT include fixture figures in the dissertation (D-09)."
            )

        mermaid_src = dag_to_mermaid(dag, fixture=fixture_mode)
        genealogy_out = output_dir / "skill-genealogy.md"
        genealogy_out.write_text(mermaid_src, encoding="utf-8")
        watermark_note = " [FIXTURE DATA — watermarked]" if fixture_mode else ""
        print(f"[setdrift-eval figures] genealogy -> {genealogy_out}{watermark_note}")

    # --- triangulation figure (D-15 pre-registered statistic) ---
    if args.all_figures or getattr(args, "triangulation", False):
        import json as _json
        from setdrift_eval.figures.triangulation import triangulate, plot_triangulation  # lazy

        triangulation_data_path = experiments_dir / "triangulation-series.json"
        fixture_mode = False

        if triangulation_data_path.exists():
            raw = _json.loads(triangulation_data_path.read_text(encoding="utf-8"))
            f1_series = [float(x) for x in raw["f1_series"]]
            pass_rate_series = [float(x) for x in raw["pass_rate_series"]]
        elif allow_fixtures:
            # --allow-fixtures: load the committed triangulation fixture (D-09)
            fixture_path = Path(__file__).parent / "fixtures" / "triangulation_fixture.json"
            fixture_data = _json.loads(fixture_path.read_text(encoding="utf-8"))
            # Use the concordant series from the fixture (small-N permutation path)
            f1_series = fixture_data["concordant"]["f1_series"]
            pass_rate_series = fixture_data["concordant"]["pass_rate_series"]
            fixture_mode = True
        else:
            raise FigureDataError(
                f"Triangulation series data not found: {triangulation_data_path}. "
                "Pass --allow-fixtures to run against fixture data (watermark applied). "
                "Do NOT include fixture figures in the dissertation (D-09)."
            )

        stats = triangulate(f1_series, pass_rate_series)
        triangulation_out = output_dir / "triangulation"
        plot_triangulation(
            f1_series, pass_rate_series, stats, triangulation_out, fixture=fixture_mode
        )

        # Persist the triangulate() result dict as companion JSON (D-15: null result is recorded)
        companion_path = output_dir / "triangulation-stats.json"
        companion_path.write_text(_json.dumps(stats, indent=2), encoding="utf-8")

        watermark_note = " [FIXTURE DATA — watermarked]" if fixture_mode else ""
        null_note = (
            " [NULL RESULT — reported per pre-registration]" if stats.get("null_result") else ""
        )
        print(
            f"[setdrift-eval figures] triangulation -> {triangulation_out}.pdf + .png"
            f"{watermark_note}{null_note}"
        )
        print(f"[setdrift-eval figures] triangulation stats -> {companion_path}")

    # --- drift-f1 figure (RUN-05, the falsifiable claim's own axis) ---
    if args.all_figures or getattr(args, "drift_f1", False):
        import json as _json
        from setdrift_eval.figures.drift_f1 import (  # lazy import
            compute_drift_f1_stats,
            plot_drift_f1,
        )

        drift_f1_data_path = experiments_dir / "drift-f1-series.json"
        fixture_mode = False

        if drift_f1_data_path.exists():
            series = _json.loads(drift_f1_data_path.read_text(encoding="utf-8"))
        elif allow_fixtures:
            # --allow-fixtures: load the committed drift-f1 fixture (D-09)
            fixture_path = Path(__file__).parent / "fixtures" / "drift_f1_fixture.json"
            series = _json.loads(fixture_path.read_text(encoding="utf-8"))
            fixture_mode = True
        else:
            raise FigureDataError(
                f"Drift-vs-F1 series data not found: {drift_f1_data_path}. "
                "Pass --allow-fixtures to run against fixture data (watermark applied). "
                "Do NOT include fixture figures in the dissertation (D-09)."
            )

        stats = compute_drift_f1_stats(series)
        drift_f1_out = output_dir / "drift-f1"
        plot_drift_f1(series, stats, drift_f1_out, fixture=fixture_mode)

        # Persist the triangulate() result dict as companion JSON (D-15: null result
        # is recorded in text as well as pixels — same convention as triangulation).
        drift_f1_stats_path = output_dir / "drift-f1-stats.json"
        drift_f1_stats_path.write_text(_json.dumps(stats, indent=2), encoding="utf-8")

        watermark_note = " [FIXTURE DATA — watermarked]" if fixture_mode else ""
        null_note = (
            " [NULL RESULT — reported per pre-registration]" if stats.get("null_result") else ""
        )
        print(
            f"[setdrift-eval figures] drift-f1 -> {drift_f1_out}.pdf + .png"
            f"{watermark_note}{null_note}"
        )
        print(f"[setdrift-eval figures] drift-f1 stats -> {drift_f1_stats_path}")

    # --- kappa-matrix figure (D-11 judge sensitivity 5×3 heatmap) ---
    if args.all_figures or getattr(args, "kappa_matrix", False):
        import json as _json
        from setdrift_eval.figures.kappa_heatmap import plot_kappa_heatmap  # lazy
        from setdrift_eval.judge.kappa import KappaCell  # lazy

        kappa_data_path = experiments_dir / "judge-sensitivity.json"
        fixture_mode = False

        if kappa_data_path.exists():
            raw = _json.loads(kappa_data_path.read_text(encoding="utf-8"))
            kappa_cells = [KappaCell.model_validate(cell) for cell in raw["kappa_cells"]]
        elif allow_fixtures:
            # --allow-fixtures: synthesize a fixture 5×3 KappaCell matrix (D-09)
            bias_modes = ["verbosity", "position", "self_preference", "authority", "recency"]
            family_pairs = ["claude_vs_gpt4", "claude_vs_gemini", "gpt4_vs_gemini"]
            kappa_cells = []
            for i, bm in enumerate(bias_modes):
                for j, fp in enumerate(family_pairs):
                    kappa_val = round(0.5 + i * 0.05 + j * 0.03, 3)
                    esc = kappa_val < 0.6
                    kappa_cells.append(
                        KappaCell(
                            bias_mode=bm,
                            family_pair=fp,
                            kappa=kappa_val,
                            n_prompts=100,
                            escalation_required=esc,
                            reason=(
                                f"[FIXTURE] Cell ({bm}/{fp}): kappa={kappa_val:.3f} "
                                f"— {'ESCALATION REQUIRED' if esc else 'κ ≥ 0.6 floor'} (D-11)"
                            ),
                        )
                    )
            fixture_mode = True
        else:
            raise FigureDataError(
                f"Judge sensitivity data not found: {kappa_data_path}. "
                "Pass --allow-fixtures to run against fixture data (watermark applied). "
                "Do NOT include fixture figures in the dissertation (D-09)."
            )

        kappa_out = output_dir / "kappa-matrix"
        plot_kappa_heatmap(kappa_cells, kappa_out, fixture=fixture_mode)
        watermark_note = " [FIXTURE DATA — watermarked]" if fixture_mode else ""
        print(f"[setdrift-eval figures] kappa-matrix -> {kappa_out}.pdf + .png{watermark_note}")

    # --- f1-curve figure — placeholder; future plan fills in ---
    if args.all_figures or getattr(args, "f1_curve", False):
        # NOTE: F1-over-versions curve is not a Phase-3-gated figure in Plan 06.
        # It is scaffolded here for completeness; implementation deferred.
        print("[setdrift-eval figures] f1-curve — not yet implemented")

    return 0

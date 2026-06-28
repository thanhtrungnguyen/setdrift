"""Carbon/cost figure for Setdrift dissertation (REQ-DELIV-02, Phase 5).

What this module does:
  - Converts token counts to estimated energy/cost/carbon metrics (tokens_to_cost)
  - Renders a per-config-version cost-delta bar chart with dual axes (kWh left, USD right)
  - Annotates ±50% uncertainty error bars (RESEARCH Pitfall 3)
  - Exposes tokens_to_cost as a secondary-metric value for experiments/ JSON (D-02)

What it does NOT do:
  - Never calls plt.show() — headless Agg backend only; rcparams.apply() is called by CLI (D-10)
  - Never claims to produce authoritative energy figures — constants are [ASSUMED] estimates

Goodhart firewall: ExperimentManifest imported as read-only schema reference only.
"""
from __future__ import annotations

from pathlib import Path

# FROZEN RULER — import only; schema fields drive cost computation
from setdrift_eval.schemas.experiment import ExperimentManifest  # noqa: F401 — guard import

# Energy-per-token conversion constants.
# [ASSUMED] — empirical estimates; Anthropic publishes no official figures.
# Source: energycosts.co.uk/articles/anthropic-claude-ai-energy (accessed 2026-06-15)
# Uncertainty: ±50% (range 0.0001–0.002 Wh/token across model sizes).
# Dissertation caption MUST state these are estimates, not authoritative figures.
KWHR_PER_TOKEN: float = 0.000003       # [ASSUMED] kWh per token, Claude Sonnet class
USD_PER_KWHR: float = 0.08             # [ASSUMED] US average grid price (US EIA 2024)
GRID_CO2_KG_PER_KWHR: float = 0.386   # [ASSUMED] US average carbon intensity (EPA eGRID 2023)

# Uncertainty factor for error bars (±50% per RESEARCH Pitfall 3)
_UNCERTAINTY_FACTOR: float = 0.50


def tokens_to_cost(n_tokens: int) -> dict:
    """Convert token count to estimated energy/cost/carbon metrics.

    All values are ESTIMATES with ±50% uncertainty. See KWHR_PER_TOKEN docstring.

    Args:
        n_tokens: Total input+output token count for a cell or run.

    Returns:
        dict with keys: kwh, usd_electricity, co2_kg, api_cost_note
    """
    kwh = n_tokens * KWHR_PER_TOKEN
    usd_electricity = kwh * USD_PER_KWHR
    co2_kg = kwh * GRID_CO2_KG_PER_KWHR
    return {
        "kwh": kwh,
        "usd_electricity": usd_electricity,
        "co2_kg": co2_kg,
        "api_cost_note": "API cost ($/token) is separate from electricity cost",
    }


def plot_cost_delta(
    per_version_token_counts: dict[str, int],
    output_path: Path,
    *,
    fixture: bool = False,
) -> None:
    """Render a per-config-version cost-delta bar chart (REQ-DELIV-02).

    Shows kWh on the left Y-axis and USD electricity cost on a twinx() right axis.
    Error bars span ±50% uncertainty (RESEARCH Pitfall 3 — annotated estimates, not
    authoritative figures). Y-axis starts at 0 (UI-SPEC B.5). No chart junk.

    Args:
        per_version_token_counts: mapping of config-version label → total token count
        output_path: path stem for output (extensions .pdf and .png added automatically)
        fixture: if True, apply [FIXTURE DATA] watermark (D-09) — never use for dissertation
    """
    import matplotlib.pyplot as plt  # lazy import inside figures/

    from setdrift_eval.figures.rcparams import (
        PRIMARY_BLUE,
        ORANGE,
        _apply_fixture_watermark,
        _save_figure,
    )

    versions = list(per_version_token_counts.keys())
    token_counts = [per_version_token_counts[v] for v in versions]
    costs = [tokens_to_cost(n) for n in token_counts]

    kwh_values = [c["kwh"] for c in costs]
    usd_values = [c["usd_electricity"] for c in costs]

    # ±50% uncertainty error bars (RESEARCH Pitfall 3)
    kwh_errs = [v * _UNCERTAINTY_FACTOR for v in kwh_values]
    usd_errs = [v * _UNCERTAINTY_FACTOR for v in usd_values]

    x = range(len(versions))

    fig, ax_kwh = plt.subplots()

    ax_kwh.bar(
        x,
        kwh_values,
        color=PRIMARY_BLUE,
        alpha=0.85,
        label="Energy (kWh)",
        yerr=kwh_errs,
        capsize=4,
        error_kw={"elinewidth": 1.0, "ecolor": PRIMARY_BLUE, "alpha": 0.6},
    )

    ax_kwh.set_xlabel("Config version")
    ax_kwh.set_ylabel("Energy (kWh)  [ESTIMATED ±50%]", color=PRIMARY_BLUE)
    ax_kwh.tick_params(axis="y", labelcolor=PRIMARY_BLUE)
    ax_kwh.set_xticks(list(x))
    ax_kwh.set_xticklabels(versions, rotation=15, ha="right")
    ax_kwh.set_ylim(bottom=0)  # UI-SPEC B.5: Y-axis starts at 0

    # Secondary right axis: USD electricity cost
    ax_usd = ax_kwh.twinx()
    ax_usd.errorbar(
        list(x),
        usd_values,
        yerr=usd_errs,
        fmt="o-",
        color=ORANGE,
        linewidth=1.5,
        markersize=5,
        label="Electricity cost (USD)",
        capsize=4,
        elinewidth=1.0,
        ecolor=ORANGE,
        alpha=0.85,
    )
    ax_usd.set_ylabel("Electricity cost (USD)  [ESTIMATED ±50%]", color=ORANGE)
    ax_usd.tick_params(axis="y", labelcolor=ORANGE)
    ax_usd.set_ylim(bottom=0)  # UI-SPEC B.5

    # Title + annotation note
    ax_kwh.set_title(
        "Cost per Config Version: Energy & Electricity Cost (REQ-DELIV-02)",
        fontsize=10,
    )
    fig.text(
        0.5, -0.02,
        "[ASSUMED] Energy-per-token estimates (±50% uncertainty); Anthropic publishes no official figures.\n"
        "Sources: energycosts.co.uk, EPA eGRID 2023, US EIA 2024. API token cost not included.",
        ha="center",
        fontsize=7,
        style="italic",
        color="#555555",
    )

    # Combine legends
    lines1, labels1 = ax_kwh.get_legend_handles_labels()
    lines2, labels2 = ax_usd.get_legend_handles_labels()
    ax_kwh.legend(lines1 + lines2, labels1 + labels2, fontsize=8, loc="upper right")

    if fixture:
        _apply_fixture_watermark(fig)

    _save_figure(fig, Path(output_path))

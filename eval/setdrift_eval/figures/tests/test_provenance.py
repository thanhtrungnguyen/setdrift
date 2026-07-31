"""Tests for the machine-readable FIXTURE/REAL provenance stamp (FIG-01, D9-05).

Provenance is stamped by `rcparams._save_figure` into PNG tEXt (Comment) +
PDF Info (Keywords) metadata, and by `genealogy.dag_to_mermaid` as a leading
HTML comment. This is deliberately NOT the same channel as
`_apply_fixture_watermark`'s rendered text: that text is rasterized into
pixels in the PNG and font-encoded inside a compressed content stream in the
PDF, so it is not reliably byte-searchable. The provenance token is the sole
machine-readable contract `.planning/dissertation/scripts/check_no_watermark.py`
scans (Phase 9 plan 09-01, Task 2).

Figures are built via the real `plot_cost_delta` / `dag_to_mermaid` entry
points (not by calling `_save_figure` directly) so these tests prove the
whole call chain is wired, not just the helper in isolation.
"""

from __future__ import annotations

from setdrift_eval.figures.rcparams import PROVENANCE_FIXTURE, PROVENANCE_REAL


# ---------------------------------------------------------------------------
# Raster figures (PNG + PDF) via plot_cost_delta
# ---------------------------------------------------------------------------


def test_cost_delta_fixture_png_and_pdf_carry_fixture_token(tmp_path):
    """plot_cost_delta(fixture=True) stamps PROVENANCE_FIXTURE in PNG + PDF bytes."""
    from setdrift_eval.figures.rcparams import apply
    from setdrift_eval.figures.cost import plot_cost_delta

    apply()
    output = tmp_path / "cost-delta-fixture"
    plot_cost_delta({"v1": 50_000}, output, fixture=True)

    png_bytes = (tmp_path / "cost-delta-fixture.png").read_bytes()
    pdf_bytes = (tmp_path / "cost-delta-fixture.pdf").read_bytes()

    assert PROVENANCE_FIXTURE.encode("ascii") in png_bytes, (
        "PNG bytes must contain the FIXTURE provenance token"
    )
    assert PROVENANCE_FIXTURE.encode("ascii") in pdf_bytes, (
        "PDF bytes must contain the FIXTURE provenance token"
    )


def test_cost_delta_real_png_and_pdf_carry_real_token_never_fixture(tmp_path):
    """plot_cost_delta(fixture=False) stamps PROVENANCE_REAL and NEVER PROVENANCE_FIXTURE."""
    from setdrift_eval.figures.rcparams import apply
    from setdrift_eval.figures.cost import plot_cost_delta

    apply()
    output = tmp_path / "cost-delta-real"
    plot_cost_delta({"v1": 50_000}, output, fixture=False)

    png_bytes = (tmp_path / "cost-delta-real.png").read_bytes()
    pdf_bytes = (tmp_path / "cost-delta-real.pdf").read_bytes()

    assert PROVENANCE_REAL.encode("ascii") in png_bytes, (
        "PNG bytes must contain the REAL provenance token"
    )
    assert PROVENANCE_REAL.encode("ascii") in pdf_bytes, (
        "PDF bytes must contain the REAL provenance token"
    )
    # Negative assertion — the whole point of the gate (T-09-02, T-09-03).
    assert PROVENANCE_FIXTURE.encode("ascii") not in png_bytes, (
        "Real-mode PNG must NEVER contain the FIXTURE provenance token"
    )
    assert PROVENANCE_FIXTURE.encode("ascii") not in pdf_bytes, (
        "Real-mode PDF must NEVER contain the FIXTURE provenance token"
    )


def test_save_figure_default_fixture_false_is_backward_compatible(tmp_path):
    """_save_figure(fig, path) with no fixture= kwarg still works and defaults to REAL."""
    import matplotlib.pyplot as plt
    from setdrift_eval.figures.rcparams import apply, _save_figure

    apply()
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    output = tmp_path / "no-fixture-kwarg"

    _save_figure(fig, output)  # no fixture= kwarg — must not raise

    png_bytes = (tmp_path / "no-fixture-kwarg.png").read_bytes()
    assert PROVENANCE_REAL.encode("ascii") in png_bytes
    assert PROVENANCE_FIXTURE.encode("ascii") not in png_bytes


# ---------------------------------------------------------------------------
# Text artifact (genealogy Mermaid .md) via dag_to_mermaid
# ---------------------------------------------------------------------------


def test_dag_to_mermaid_fixture_carries_fixture_token_and_raster_note():
    """dag_to_mermaid(fixture=True) contains both the provenance token and the
    existing [FIXTURE DATA] blockquote note."""
    import networkx as nx
    from setdrift_eval.figures.genealogy import dag_to_mermaid

    G = nx.DiGraph()
    G.add_node("v1", skill="spring-boot-endpoint", f1=0.8, status="active")

    out = dag_to_mermaid(G, fixture=True)

    assert PROVENANCE_FIXTURE in out
    assert "[FIXTURE DATA — awaiting Phase-3 output]" in out


def test_dag_to_mermaid_real_carries_real_token_never_fixture():
    """dag_to_mermaid(fixture=False) contains PROVENANCE_REAL and never PROVENANCE_FIXTURE."""
    import networkx as nx
    from setdrift_eval.figures.genealogy import dag_to_mermaid

    G = nx.DiGraph()
    G.add_node("v1", skill="spring-boot-endpoint", f1=0.8, status="active")

    out = dag_to_mermaid(G, fixture=False)

    assert PROVENANCE_REAL in out
    assert PROVENANCE_FIXTURE not in out

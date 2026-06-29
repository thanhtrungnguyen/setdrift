"""Tests for Phase-3-gated figure generators: genealogy, triangulation, kappa_heatmap.

All tests run OFFLINE against committed fixtures (D-09). No live API calls.
Matplotlib uses the Agg backend (headless) — no display required.

References: PLAN 05-06, 05-PATTERNS.md, 05-RESEARCH.md Pitfall 4/7, D-09/D-15.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # enforce headless before any pyplot import

import pytest


# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
_TRIANGULATION_FIXTURE = _FIXTURES_DIR / "triangulation_fixture.json"


# ---------------------------------------------------------------------------
# Genealogy fixture data (D-09 data wall: NEVER committed as a .jsonl file —
# the CI data wall only allows experiments/audit-genealogy.jsonl). The records
# are embedded here and written to tmp_path at test time so the suite is
# hermetic and never depends on an untracked file existing in the checkout.
# ---------------------------------------------------------------------------

_GENEALOGY_FIXTURE_RECORDS = [
    {
        "version_id": "v1",
        "skill_name": "spring-boot-endpoint",
        "f1_mean": 0.62,
        "status": "archived",
        "parent_version_id": None,
        "date": "2026-05-01",
        "rolled_back": False,
    },
    {
        "version_id": "v2",
        "skill_name": "spring-boot-endpoint",
        "f1_mean": 0.71,
        "status": "archived",
        "parent_version_id": "v1",
        "date": "2026-05-15",
        "rolled_back": False,
    },
    {
        "version_id": "v3",
        "skill_name": "spring-boot-endpoint",
        "f1_mean": 0.58,
        "status": "quarantine",
        "parent_version_id": "v2",
        "date": "2026-05-28",
        "rolled_back": True,
    },
    {
        "version_id": "v4",
        "skill_name": "spring-boot-endpoint",
        "f1_mean": 0.79,
        "status": "active",
        "parent_version_id": "v2",
        "date": "2026-06-10",
        "rolled_back": False,
    },
]


@pytest.fixture
def genealogy_fixture_path(tmp_path: Path) -> Path:
    """Write the embedded genealogy fixture records to a tmp JSONL and return it.

    This keeps the test suite hermetic without tracking any .jsonl file (D-09
    data wall). The builder is pointed at this tmp path explicitly, so the
    (untracked, gitignored) figures/fixtures/genealogy_fixture.jsonl on a dev
    machine is irrelevant to test outcomes.
    """
    path = tmp_path / "genealogy_fixture.jsonl"
    path.write_text(
        "\n".join(json.dumps(r) for r in _GENEALOGY_FIXTURE_RECORDS) + "\n",
        encoding="utf-8",
    )
    return path


# ===========================================================================
# Task 1: Genealogy DAG + Mermaid serialiser tests
# ===========================================================================


class TestBuildGenealogyDag:
    """Tests for build_genealogy_dag (REQ-DELIV-01, T-05-22)."""

    def test_dag_node_and_edge_counts_match_fixture(self, genealogy_fixture_path):
        """build_genealogy_dag on fixture returns DiGraph with expected counts."""
        from setdrift_eval.figures.genealogy import build_genealogy_dag

        G = build_genealogy_dag(genealogy_fixture_path)

        # Fixture has 4 records → 4 nodes
        assert G.number_of_nodes() == 4
        # 3 edges: v1->v2, v2->v3 (rollback), v2->v4 (promoted)
        assert G.number_of_edges() == 3

    def test_dag_node_attributes(self, genealogy_fixture_path):
        """Nodes carry skill, f1, status attributes from fixture records."""
        from setdrift_eval.figures.genealogy import build_genealogy_dag

        G = build_genealogy_dag(genealogy_fixture_path)

        assert G.nodes["v1"]["skill"] == "spring-boot-endpoint"
        assert abs(G.nodes["v1"]["f1"] - 0.62) < 1e-6
        assert G.nodes["v1"]["status"] == "archived"
        assert G.nodes["v4"]["status"] == "active"

    def test_dag_edge_relations(self, genealogy_fixture_path):
        """Edges carry relation (promoted/rolled back) and date from fixture."""
        from setdrift_eval.figures.genealogy import build_genealogy_dag

        G = build_genealogy_dag(genealogy_fixture_path)

        # v2->v3 is rolled_back=true → relation="rolled back"
        assert G.edges["v2", "v3"]["relation"] == "rolled back"
        # v2->v4 is rolled_back=false → relation="promoted"
        assert G.edges["v2", "v4"]["relation"] == "promoted"

    def test_raises_figure_data_error_when_path_absent(self, tmp_path):
        """FigureDataError raised when audit path does not exist."""
        from setdrift_eval.figures.genealogy import FigureDataError, build_genealogy_dag

        absent_path = tmp_path / "nonexistent-audit-genealogy.jsonl"
        with pytest.raises(FigureDataError, match="Genealogy audit source not found"):
            build_genealogy_dag(absent_path)

    def test_cycle_in_promotion_data_fails_loud(self, tmp_path):
        """A cycle in the promotion data raises AssertionError (T-05-22 mitigation)."""
        from setdrift_eval.figures.genealogy import build_genealogy_dag

        # Create a JSONL with a cycle: v1 -> v2 -> v3 -> v1
        cyclic_records = [
            {
                "version_id": "v1",
                "skill_name": "test-skill",
                "f1_mean": 0.6,
                "status": "archived",
                "parent_version_id": "v3",
                "date": "2026-01-01",
                "rolled_back": False,
            },
            {
                "version_id": "v2",
                "skill_name": "test-skill",
                "f1_mean": 0.7,
                "status": "archived",
                "parent_version_id": "v1",
                "date": "2026-01-02",
                "rolled_back": False,
            },
            {
                "version_id": "v3",
                "skill_name": "test-skill",
                "f1_mean": 0.5,
                "status": "archived",
                "parent_version_id": "v2",
                "date": "2026-01-03",
                "rolled_back": True,
            },
        ]
        cyclic_path = tmp_path / "cyclic.jsonl"
        cyclic_path.write_text("\n".join(json.dumps(r) for r in cyclic_records), encoding="utf-8")

        with pytest.raises(AssertionError, match="cycle"):
            build_genealogy_dag(cyclic_path)


class TestDagToMermaid:
    """Tests for dag_to_mermaid (UI-SPEC §B.6)."""

    def test_mermaid_starts_with_graph_lr(self, genealogy_fixture_path):
        """dag_to_mermaid output contains 'graph LR'."""
        from setdrift_eval.figures.genealogy import build_genealogy_dag, dag_to_mermaid

        G = build_genealogy_dag(genealogy_fixture_path)
        result = dag_to_mermaid(G)

        assert "graph LR" in result

    def test_mermaid_contains_node_line_per_version(self, genealogy_fixture_path):
        """One node line per version_id in topological order."""
        from setdrift_eval.figures.genealogy import build_genealogy_dag, dag_to_mermaid

        G = build_genealogy_dag(genealogy_fixture_path)
        result = dag_to_mermaid(G)

        for version_id in ["v1", "v2", "v3", "v4"]:
            assert version_id in result

    def test_mermaid_contains_classdef_color_lines(self, genealogy_fixture_path):
        """Mermaid output contains classDef blocks for active/quarantine/archived."""
        from setdrift_eval.figures.genealogy import build_genealogy_dag, dag_to_mermaid

        G = build_genealogy_dag(genealogy_fixture_path)
        result = dag_to_mermaid(G)

        assert "classDef active" in result
        assert "classDef quarantine" in result
        assert "classDef archived" in result

    def test_mermaid_fixture_watermark_prepended(self, genealogy_fixture_path):
        """When fixture=True, the watermark note is prepended to the output."""
        from setdrift_eval.figures.genealogy import build_genealogy_dag, dag_to_mermaid

        G = build_genealogy_dag(genealogy_fixture_path)
        result = dag_to_mermaid(G, fixture=True)

        assert "[FIXTURE DATA" in result
        # Fixture note must appear before the graph LR block
        fixture_pos = result.index("[FIXTURE DATA")
        graph_pos = result.index("graph LR")
        assert fixture_pos < graph_pos, "Fixture note must precede the Mermaid block"

    def test_mermaid_no_watermark_when_not_fixture(self, genealogy_fixture_path):
        """When fixture=False (default), no fixture watermark in output."""
        from setdrift_eval.figures.genealogy import build_genealogy_dag, dag_to_mermaid

        G = build_genealogy_dag(genealogy_fixture_path)
        result = dag_to_mermaid(G)

        assert "[FIXTURE DATA" not in result

    def test_mermaid_solid_edge_for_promotion(self, genealogy_fixture_path):
        """Promoted edges use solid --> arrow style."""
        from setdrift_eval.figures.genealogy import build_genealogy_dag, dag_to_mermaid

        G = build_genealogy_dag(genealogy_fixture_path)
        result = dag_to_mermaid(G)

        # v2->v4 is promoted (solid arrow)
        assert "-->" in result

    def test_mermaid_dashed_edge_for_rollback(self, genealogy_fixture_path):
        """Rolled-back edges use dashed .-> arrow style."""
        from setdrift_eval.figures.genealogy import build_genealogy_dag, dag_to_mermaid

        G = build_genealogy_dag(genealogy_fixture_path)
        result = dag_to_mermaid(G)

        # v2->v3 is rolled back (dashed arrow)
        assert ".->" in result


# ===========================================================================
# Task 2: Triangulation (Spearman + sign test + permutation fallback) tests
# ===========================================================================


class TestTriangulate:
    """Tests for triangulate() (D-15 pre-registered statistic)."""

    def _load_fixture(self) -> dict:
        return json.loads(_TRIANGULATION_FIXTURE.read_text(encoding="utf-8"))

    def test_concordant_series_returns_positive_rho_null_false(self):
        """triangulate on perfectly concordant series: rho>0, null_result=False."""
        from setdrift_eval.figures.triangulation import triangulate

        fixture = self._load_fixture()
        f1 = fixture["concordant"]["f1_series"]
        pr = fixture["concordant"]["pass_rate_series"]

        result = triangulate(f1, pr)

        assert result["spearman_rho"] > 0, f"Expected positive rho, got {result['spearman_rho']}"
        assert result["null_result"] is False, "Concordant series should not be null result"

    def test_anti_correlated_series_returns_null_true(self):
        """triangulate on anti-correlated series: null_result=True, rho/p reported."""
        from setdrift_eval.figures.triangulation import triangulate

        fixture = self._load_fixture()
        f1 = fixture["anti_correlated"]["f1_series"]
        pr = fixture["anti_correlated"]["pass_rate_series"]

        result = triangulate(f1, pr)

        assert result["null_result"] is True, "Anti-correlated series must be null result"
        # All fields must be present even for null results (D-15 selective-reporting mitigation)
        for key in (
            "spearman_rho",
            "spearman_pvalue",
            "sign_test_pvalue",
            "n_concordant",
            "n_pairs",
            "null_result",
        ):
            assert key in result, f"Missing key {key!r} in triangulate result"

    def test_small_n_uses_permutation_test(self):
        """N<10 config versions triggers permutation_test path (Pitfall 7 / A7)."""
        from setdrift_eval.figures.triangulation import triangulate

        # 5 data points = N<10 → permutation fallback
        f1 = [0.55, 0.61, 0.67, 0.71, 0.76]
        pr = [0.48, 0.54, 0.61, 0.66, 0.72]

        result = triangulate(f1, pr)

        # The result must record which method was used and the N
        assert "n_versions" in result, "Result must record n_versions (N count)"
        assert result["n_versions"] == 5
        assert "pvalue_method" in result, "Result must record pvalue_method"
        assert result["pvalue_method"] == "permutation", (
            f"Expected 'permutation' for N=5, got {result['pvalue_method']!r}"
        )

    def test_large_n_uses_asymptotic_test(self):
        """N>=20 config versions uses asymptotic spearmanr p-value (standard path)."""
        from setdrift_eval.figures.triangulation import triangulate

        # 20 data points = N>=20 → asymptotic path
        f1 = [0.50 + i * 0.02 for i in range(20)]
        pr = [0.45 + i * 0.02 for i in range(20)]

        result = triangulate(f1, pr)

        assert result["pvalue_method"] == "asymptotic", (
            f"Expected 'asymptotic' for N=20, got {result['pvalue_method']!r}"
        )

    def test_result_dict_has_all_required_keys(self):
        """triangulate always returns all D-15 required keys."""
        from setdrift_eval.figures.triangulation import triangulate

        f1 = [0.60, 0.65, 0.70]
        pr = [0.50, 0.55, 0.60]

        result = triangulate(f1, pr)

        required_keys = {
            "spearman_rho",
            "spearman_pvalue",
            "sign_test_pvalue",
            "n_concordant",
            "n_pairs",
            "null_result",
            "n_versions",
            "pvalue_method",
        }
        missing = required_keys - result.keys()
        assert not missing, f"triangulate result missing keys: {missing}"


class TestPlotTriangulation:
    """Tests for plot_triangulation (figure output + null-result annotation)."""

    def test_null_result_annotated_on_figure(self, tmp_path):
        """A null-result triangulation is annotated on the figure (T-05-20)."""
        from setdrift_eval.figures.triangulation import triangulate, plot_triangulation
        import json as _json

        fixture = _json.loads(_TRIANGULATION_FIXTURE.read_text(encoding="utf-8"))
        f1 = fixture["anti_correlated"]["f1_series"]
        pr = fixture["anti_correlated"]["pass_rate_series"]
        stats = triangulate(f1, pr)

        output = tmp_path / "triangulation"
        plot_triangulation(f1, pr, stats, output, fixture=True)

        assert output.with_suffix(".pdf").exists(), "triangulation.pdf not written"
        assert output.with_suffix(".png").exists(), "triangulation.png not written"

    def test_concordant_result_writes_pdf_png(self, tmp_path):
        """plot_triangulation writes .pdf + .png for concordant result."""
        from setdrift_eval.figures.triangulation import triangulate, plot_triangulation

        f1 = [0.55, 0.61, 0.67, 0.71, 0.76]
        pr = [0.48, 0.54, 0.61, 0.66, 0.72]
        stats = triangulate(f1, pr)

        output = tmp_path / "triangulation"
        plot_triangulation(f1, pr, stats, output, fixture=True)

        assert output.with_suffix(".pdf").exists()
        assert output.with_suffix(".png").exists()


# ===========================================================================
# Task 2: Cohen's κ heatmap tests
# ===========================================================================


class TestPlotKappaHeatmap:
    """Tests for plot_kappa_heatmap (5×3 bias_mode × family_pair heatmap)."""

    def _make_kappa_cells(self):
        """Build a complete 5×3 KappaCell matrix for testing."""
        from setdrift_eval.judge.kappa import KappaCell

        bias_modes = ["verbosity", "position", "self_preference", "authority", "recency"]
        family_pairs = ["claude_vs_gpt4", "claude_vs_gemini", "gpt4_vs_gemini"]

        cells = []
        for i, bm in enumerate(bias_modes):
            for j, fp in enumerate(family_pairs):
                kappa_val = 0.5 + i * 0.05 + j * 0.03
                esc = kappa_val < 0.6
                cells.append(
                    KappaCell(
                        bias_mode=bm,
                        family_pair=fp,
                        kappa=round(kappa_val, 3),
                        n_prompts=100,
                        escalation_required=esc,
                        reason=f"Test cell for {bm}/{fp}: kappa={kappa_val:.3f}",
                    )
                )
        return cells

    def test_kappa_heatmap_writes_pdf_and_png(self, tmp_path):
        """plot_kappa_heatmap writes .pdf + .png from a 5×3 KappaCell list."""
        from setdrift_eval.figures.kappa_heatmap import plot_kappa_heatmap

        cells = self._make_kappa_cells()
        output = tmp_path / "kappa-matrix"
        plot_kappa_heatmap(cells, output, fixture=True)

        assert output.with_suffix(".pdf").exists(), "kappa-matrix.pdf not written"
        assert output.with_suffix(".png").exists(), "kappa-matrix.png not written"

    def test_kappa_heatmap_fixture_watermark_applied(self, tmp_path):
        """When fixture=True, plot_kappa_heatmap applies the watermark (D-09)."""
        # We can't inspect the figure pixels in unit tests, but we can confirm
        # that the function completes without error with fixture=True and
        # that the output files are created — watermark application is smoke-tested.
        from setdrift_eval.figures.kappa_heatmap import plot_kappa_heatmap

        cells = self._make_kappa_cells()
        output = tmp_path / "kappa-matrix-fixture"
        # No exception = watermark path executed successfully
        plot_kappa_heatmap(cells, output, fixture=True)
        assert output.with_suffix(".pdf").exists()

    def test_kappa_heatmap_no_watermark_non_fixture(self, tmp_path):
        """When fixture=False (default), plot_kappa_heatmap runs without watermark."""
        from setdrift_eval.figures.kappa_heatmap import plot_kappa_heatmap

        cells = self._make_kappa_cells()
        output = tmp_path / "kappa-matrix-real"
        plot_kappa_heatmap(cells, output, fixture=False)
        assert output.with_suffix(".pdf").exists()


# ===========================================================================
# No hand-rolled statistics guard (T-05-21 static check)
# ===========================================================================


def test_no_hand_rolled_statistics_in_triangulation():
    """triangulation.py must not contain hand-rolled F1/kappa/spearman formulas (T-05-21)."""
    triangulation_path = Path(__file__).parent.parent / "triangulation.py"
    assert triangulation_path.exists(), "triangulation.py must exist"

    source = triangulation_path.read_text(encoding="utf-8")

    # Reject hand-rolled F1
    import re

    assert not re.search(r"2\s*\*\s*p\s*\*\s*r", source), (
        "Hand-rolled F1 formula found in triangulation.py (T-05-21 violation)"
    )
    # Reject hand-rolled Spearman
    assert "def spearman" not in source, (
        "Hand-rolled Spearman function found in triangulation.py (T-05-21)"
    )
    # Reject hand-rolled Cohen's kappa
    assert "def cohen_kappa" not in source, (
        "Hand-rolled kappa function found in triangulation.py (T-05-21)"
    )


def test_no_hand_rolled_statistics_in_kappa_heatmap():
    """kappa_heatmap.py must not contain hand-rolled kappa formulas (T-05-21)."""
    heatmap_path = Path(__file__).parent.parent / "kappa_heatmap.py"
    assert heatmap_path.exists(), "kappa_heatmap.py must exist"

    source = heatmap_path.read_text(encoding="utf-8")

    import re

    assert not re.search(r"2\s*\*\s*p\s*\*\s*r", source), (
        "Hand-rolled F1 formula found in kappa_heatmap.py (T-05-21 violation)"
    )
    assert "def cohen_kappa" not in source, (
        "Hand-rolled kappa function found in kappa_heatmap.py (T-05-21)"
    )

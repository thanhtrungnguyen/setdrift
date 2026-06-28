"""Skill genealogy DAG builder and Mermaid serialiser (REQ-DELIV-01, D-10).

What this module does:
  - Loads optimizer promotion history from experiments/audit-genealogy.jsonl
    and builds a validated NetworkX DiGraph (build_genealogy_dag).
  - Serialises the DAG to Mermaid LR graph source (dag_to_mermaid), with
    classDef colors per UI-SPEC §B.6 (active/quarantine/archived nodes,
    solid promoted edges, dashed rollback edges).
  - Raises FigureDataError when the audit source is absent and --allow-fixtures
    was not passed (D-09 data gate, RESEARCH Pitfall 4).
  - When fixture=True, prepends a [FIXTURE DATA] note to the Mermaid output so
    a fixture diagram can never be mistaken for real data (D-09).

What it does NOT do:
  - NEVER calls plt.show() — this module produces Mermaid text, not raster figures.
  - NEVER recomputes F1 — scorer.macro_f1 is imported as a guard import only
    (FROZEN RULER, D-04 / D-15).
  - NEVER writes a fixture Mermaid diagram to docs/figures/ without the watermark note.

Goodhart firewall:
  macro_f1 is imported from the FROZEN scorer.py as a guard import only.
  It must never be re-implemented or overridden here.

References: 05-PATTERNS.md §figures/genealogy.py, 05-RESEARCH.md Pattern 6,
05-UI-SPEC.md §B.6, PLAN 05-06 Task 1, REQ-DELIV-01.
"""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx

# FROZEN RULER — import only; never recompute macro_f1 (D-04 / D-15).
from setdrift_eval.telemetry.scorer import macro_f1  # noqa: F401 — guard import only


# ---------------------------------------------------------------------------
# Data gate error (D-09 / RESEARCH Pitfall 4)
# ---------------------------------------------------------------------------


class FigureDataError(RuntimeError):
    """Raised when required Phase-3 output data is absent (D-09 gate).

    Gate: if the data file does not exist and --allow-fixtures was not passed,
    raise this error. This prevents a fixture figure from silently entering
    the dissertation as real data.
    """


# ---------------------------------------------------------------------------
# DAG builder
# ---------------------------------------------------------------------------


def build_genealogy_dag(audit_path: Path) -> nx.DiGraph:
    """Load optimizer promotion history and build a validated DiGraph.

    Reads experiments/audit-genealogy.jsonl (or a fixture path) and constructs
    a NetworkX DiGraph with version_id nodes and promoted/rolled-back edges.

    The DAG invariant is asserted fail-loud: a cycle in the promotion data
    indicates a data integrity error (T-05-22 threat mitigation).

    Args:
        audit_path: Path to a JSONL file where each line is a promotion record
            with fields: version_id, skill_name, f1_mean, status,
            parent_version_id (null for roots), date, rolled_back.

    Returns:
        nx.DiGraph with node attrs {skill, f1, status} and edge attrs
        {relation, date} where relation in {"promoted", "rolled back"}.

    Raises:
        FigureDataError: If audit_path does not exist (caller must check
            --allow-fixtures before calling with a fixture path).
        AssertionError: If the loaded graph contains a cycle (data integrity
            error — fail loud per T-05-22).
    """
    audit_path = Path(audit_path)
    if not audit_path.exists():
        raise FigureDataError(
            f"Genealogy audit source not found: {audit_path}. "
            "Pass --allow-fixtures to run against fixture data (watermark applied). "
            "Do NOT include fixture figures in the dissertation (D-09)."
        )

    raw_lines = [
        line for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    try:
        records = [json.loads(line) for line in raw_lines]
    except json.JSONDecodeError as exc:
        raise FigureDataError(
            f"Genealogy audit source is not valid JSONL: {audit_path}. "
            f"Parse error: {exc}. "
            "Pass --allow-fixtures to run against fixture data (watermark applied). "
            "Do NOT include fixture figures in the dissertation (D-09)."
        ) from exc

    # Validate that the first record has the expected genealogy schema fields.
    # The live optimizer audit log uses cycle_id/step/ts (different schema) and
    # must not be mistaken for the version-promotion genealogy (different purpose).
    _REQUIRED_FIELDS = {"version_id", "skill_name", "f1_mean", "status"}
    if records and not _REQUIRED_FIELDS.issubset(records[0].keys()):
        found = set(records[0].keys())
        raise FigureDataError(
            f"Genealogy audit source has unexpected schema: {audit_path}. "
            f"Expected fields {_REQUIRED_FIELDS!r}, found {found!r}. "
            "The file may be the optimizer cycle log (different schema). "
            "Pass --allow-fixtures to run against fixture data (watermark applied). "
            "Do NOT include fixture figures in the dissertation (D-09)."
        )

    G: nx.DiGraph = nx.DiGraph()
    for r in records:
        G.add_node(
            r["version_id"],
            skill=r["skill_name"],
            f1=float(r["f1_mean"]),
            status=r["status"],
        )
        if r.get("parent_version_id"):
            relation = "rolled back" if r.get("rolled_back") else "promoted"
            G.add_edge(
                r["parent_version_id"],
                r["version_id"],
                relation=relation,
                date=r["date"],
            )

    assert nx.is_directed_acyclic_graph(G), (
        "Promotion graph has a cycle — data integrity error (T-05-22). "
        "Check audit-genealogy.jsonl for circular version references."
    )
    return G


# ---------------------------------------------------------------------------
# Mermaid serialiser (UI-SPEC §B.6)
# ---------------------------------------------------------------------------


def dag_to_mermaid(G: nx.DiGraph, *, fixture: bool = False) -> str:
    """Serialise the genealogy DiGraph to Mermaid LR graph source.

    Follows UI-SPEC §B.6:
      - graph LR (left-right flow, older versions leftmost)
      - Node labels: v<N>\\n<skill>\\nF1: <0.000>
      - Solid --> edges for promotions; dashed .-> edges for rollbacks
      - classDef active/quarantine/archived with pre-registered colors
      - When fixture=True, prepends a [FIXTURE DATA] note block so a fixture
        diagram can never be included in the dissertation undetected (D-09).

    Args:
        G: A validated DiGraph returned by build_genealogy_dag.
        fixture: If True, the output is prefixed with a fixture watermark note.

    Returns:
        str: Mermaid graph source, optionally prefixed with a fixture note block.
    """
    lines: list[str] = ["graph LR"]

    for n in nx.topological_sort(G):
        d = G.nodes[n]
        skill = d.get("skill", "unknown")
        f1_val = d.get("f1", 0.0)
        status = d.get("status", "archived")
        # Node label: version_id["label"]:::classDef
        lines.append(f'    {n}["{n}\\n{skill}\\nF1: {f1_val:.3f}"]:::{status}')

    for u, v, d in G.edges(data=True):
        relation = d.get("relation", "promoted")
        date = d.get("date", "")
        edge_style = "-->" if relation == "promoted" else ".->"
        lines.append(f'    {u} {edge_style}|"{relation} {date}"| {v}')

    # classDef color block (UI-SPEC §B.6 — pre-registered sentinel colors)
    lines += [
        "    classDef active fill:#029E73,stroke:#014D40,color:#fff",
        "    classDef quarantine fill:#DE8F05,stroke:#7E5800,color:#fff",
        "    classDef archived fill:#949494,stroke:#555,color:#fff",
    ]

    mermaid_src = "\n".join(lines)

    if fixture:
        fixture_note = (
            "> [FIXTURE DATA — awaiting Phase-3 output]\n"
            "> This diagram was generated against fixture data, NOT real optimizer output.\n"
            "> DO NOT include this figure in the dissertation (D-09).\n\n"
        )
        return fixture_note + "```mermaid\n" + mermaid_src + "\n```\n"

    return "```mermaid\n" + mermaid_src + "\n```\n"

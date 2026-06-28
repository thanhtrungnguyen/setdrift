"""Metric widget helpers for the Setdrift dashboard (UI-SPEC §A.2).

What this module does:
  - MetricWidget: a 3-line Static reactive card showing a label + value pair.
  - SkillTable: wraps DataTable with the 7 columns defined in UI-SPEC §A.2;
    provides add_skill_row() and update_skill_row() that NEVER call table.clear()
    after initial population (RESEARCH Pitfall 5 guard).

What it does NOT do:
  - Recompute any metric (D-04 single-source-of-truth: all data comes from run_health).
  - Assign .renderable on any widget (RESEARCH Pitfall 2 guard; use .update() always).
"""

from __future__ import annotations

from textual.widgets import DataTable, Static


class MetricWidget(Static):
    """A single reactive metric card (label + value, 3-line height).

    Use set_value(value_str) to update — never assign .renderable directly
    (RESEARCH Pitfall 2: use widget.update() in Textual 8.x).
    """

    DEFAULT_CSS = """
    MetricWidget {
        height: 3;
        color: $foreground;
        background: $panel;
        margin-bottom: 1;
        padding: 0 1;
        border: round $primary-darken-3;
    }
    """

    def __init__(self, label: str, widget_id: str) -> None:
        # widget_id must NOT include the leading '#' (that's CSS selector syntax only)
        clean_id = widget_id.lstrip("#")
        super().__init__("", id=clean_id, classes="metric-widget")
        self._label = label
        # Initialize with en-dash (A.6 no-data state)
        self.update(f"[bold dim]{self._label}[/]\n[bold]—[/]")

    def set_value(self, value: str) -> None:
        """Update the displayed value.  Uses .update() — never .renderable (Pitfall 2)."""
        self.update(f"[bold dim]{self._label}[/]\n[bold accent]{value}[/]")

    def set_loading(self) -> None:  # type: ignore[override]
        """Show loading state (A.6)."""
        self.update(f"[bold dim]{self._label}[/]\n[dim]…[/]")

    def set_error(self, msg: str = "ERROR") -> None:
        """Show error state with $error border (A.6)."""
        self.update(f"[bold dim]{self._label}[/]\n[$error]{msg}[/$error]")
        self.styles.border = ("round", "$error")

    def set_gated(self) -> None:
        """Show GATED state — precision/kappa gate not yet passed (A.6)."""
        self.update(f"[bold dim]{self._label}[/]\n[bold $warning]GATED[/]")

    def set_stale(self, value: str) -> None:
        """Show stale-data state: ⚠ STALE prefix + $warning border (A.6)."""
        self.update(f"[bold $warning]⚠ STALE {self._label}[/]\n[bold accent]{value}[/]")
        self.styles.border = ("round", "$warning")

    def reset_border(self) -> None:
        """Reset border to default after recovering from error/stale."""
        self.styles.border = ("round", "$primary-darken-3")


# ---------------------------------------------------------------------------
# Column definitions (UI-SPEC §A.2 — fixed order)
# ---------------------------------------------------------------------------
_SKILL_COLUMNS: list[tuple[str, str, int]] = [
    # (key, header, width)
    ("skill", "Skill", 24),
    ("f1", "F1", 7),
    ("band_lo", "Band lo", 8),
    ("band_hi", "Band hi", 8),
    ("pass_rate", "Pass%", 7),
    ("cost_usd", "Cost $", 9),
    ("status", "Status", 10),
]


def _status_markup(status: str) -> str:
    """Colour-code the status cell via Rich markup (UI-SPEC §A.5 CSS comment)."""
    status = status.upper()
    if status == "ACTIVE":
        return "[$success]ACTIVE[/$success]"
    if status == "QUARANTINE":
        return "[$warning]QUARANTINE[/$warning]"
    if status == "ARCHIVED":
        return "[$foreground-muted]ARCHIVED[/$foreground-muted]"
    return status


class SkillTable:
    """Wrapper around a DataTable that enforces the UI-SPEC §A.2 column layout.

    Never calls table.clear() after initial population — doing so resets the
    cursor (RESEARCH Pitfall 5).  Use update_skill_row() for live updates.
    """

    def __init__(self, table: DataTable) -> None:
        self._table = table
        self._initialized = False
        self._row_keys: dict[str, object] = {}  # skill_name -> row_key

    def setup_columns(self) -> None:
        """Add columns once on first mount.  Idempotent guard via _initialized."""
        if self._initialized:
            return
        for key, header, width in _SKILL_COLUMNS:
            self._table.add_column(header, key=key, width=width)
        self._initialized = True

    def add_skill_row(
        self,
        name: str,
        f1: float,
        band_lo: float,
        band_hi: float,
        pass_rate: float,
        cost_usd: float,
        status: str,
    ) -> None:
        """Append a new skill row.  Safe to call after initial population (appends, no clear)."""
        row_key = self._table.add_row(
            name,
            f"{f1:.3f}",
            f"{band_lo:.3f}",
            f"{band_hi:.3f}",
            f"{pass_rate:.1%}",
            f"${cost_usd:.4f}",
            _status_markup(status),
            key=name,
        )
        self._row_keys[name] = row_key

    def update_skill_row(
        self,
        name: str,
        f1: float,
        band_lo: float,
        band_hi: float,
        pass_rate: float,
        cost_usd: float,
        status: str,
    ) -> None:
        """Update an existing skill row WITHOUT clearing the table (Pitfall 5 guard).

        If the skill does not exist yet, adds it instead.
        """
        if name not in self._row_keys:
            self.add_skill_row(name, f1, band_lo, band_hi, pass_rate, cost_usd, status)
            return
        t = self._table
        t.update_cell(name, "f1", f"{f1:.3f}")
        t.update_cell(name, "band_lo", f"{band_lo:.3f}")
        t.update_cell(name, "band_hi", f"{band_hi:.3f}")
        t.update_cell(name, "pass_rate", f"{pass_rate:.1%}")
        t.update_cell(name, "cost_usd", f"${cost_usd:.4f}")
        t.update_cell(name, "status", _status_markup(status))

    def show_no_data(self) -> None:
        """Show the empty-state row (UI-SPEC §A.8 no-data copy).

        Only called when the table has never been populated.
        """
        if self._row_keys:
            return  # already has data — don't overwrite with empty-state
        if not self._initialized:
            self.setup_columns()
        self._table.add_row(
            "[italic]No telemetry events yet. Run a session with the Setdrift plugin installed.[/italic]",
            "",
            "",
            "",
            "",
            "",
            "",
            key="__empty__",
        )

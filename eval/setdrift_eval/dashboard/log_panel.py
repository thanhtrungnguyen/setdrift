"""Loop + Telemetry log panel for the Setdrift Dashboard (D-17, UI-SPEC §A.9).

What this module does:
  - LogPanel: a Collapsible widget containing a RichLog that surfaces two streams:
      1. Loop-lifecycle events (observe→diagnose→patch→verify transitions).
         Shows "No loop events yet (Phase 3 pending)" until Phase 3 lands (D-09).
      2. A follow-tail of data/telemetry/events.jsonl (single-source-of-truth, D-04).
  - tail_telemetry(): reads last N lines of events.jsonl; OSError → warning in log.
  - write_loop_event(): writes one event with level-to-color mapping.

What it does NOT do:
  - Write to data/ (read-only consumer of the gitignored data wall).
  - Recompute any metric (D-04).
  - Export raw log content to experiments/ (T-05-16 data wall boundary).
"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.widgets import Collapsible, RichLog

# Phase-3-pending copy (D-09, D-17)
_LOOP_PENDING_MSG = "[dim]No loop events yet (Phase 3 pending)[/dim]"

# Level → Textual theme-variable color (no hardcoded hex — UI-SPEC §A.5)
_LEVEL_COLORS: dict[str, str] = {
    "info": "$success",
    "warning": "$warning",
    "error": "$error",
}


class LogPanel(Collapsible):
    """Scrollable log pane: loop-lifecycle events + telemetry tail (D-17).

    Placed as a Collapsible (collapsed by default) below the main metric/skill
    region so it does not displace the primary metrics (UI-SPEC §A.9).
    """

    DEFAULT_CSS = """
    LogPanel {
        height: 12;
        border-top: solid $primary-darken-2;
    }

    LogPanel RichLog {
        height: 1fr;
        background: $surface;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(
            title="Loop + Telemetry Log",
            collapsed=True,  # collapsed by default (UI-SPEC §A.9)
            **kwargs,
        )
        self._loop_events_written = False

    def compose(self) -> ComposeResult:
        yield RichLog(id="log-panel", markup=True, max_lines=500, auto_scroll=True)

    def on_mount(self) -> None:
        """Write the Phase-3-pending placeholder on first mount."""
        log = self.query_one("#log-panel", RichLog)
        log.write(_LOOP_PENDING_MSG)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def tail_telemetry(self, events_path: Path, n_lines: int = 50) -> None:
        """Append the last n_lines of events.jsonl to the log panel.

        Single-source-of-truth (D-04): reads data/telemetry/events.jsonl directly.
        OSError → warning line (UI-SPEC §A.9 read-error copy).
        Never writes to the file; never exports raw content (T-05-16 guard).
        """
        log = self.query_one("#log-panel", RichLog)
        try:
            text = events_path.read_text(encoding="utf-8")
            lines = [ln for ln in text.splitlines() if ln.strip()]
            if not lines:
                log.write("[dim]No telemetry events yet — run a Setdrift session[/dim]")
                return
            for line in lines[-n_lines:]:
                log.write(f"[dim]{line}[/dim]")
        except OSError:
            log.write("[$warning]⚠ log source unreadable — check data/telemetry/[/$warning]")

    def write_loop_event(self, event: str, level: str = "info") -> None:
        """Write one loop-lifecycle event with level-to-theme-color mapping.

        Level: "info" | "warning" | "error"
        If no loop events have been written yet, clears the Phase-3-pending
        placeholder first so real events are not buried under it.
        """
        log = self.query_one("#log-panel", RichLog)
        if not self._loop_events_written:
            # First real loop event — clear the Phase-3-pending placeholder
            log.clear()
            self._loop_events_written = True
        color = _LEVEL_COLORS.get(level, "$foreground")
        log.write(f"[{color}]{event}[/{color}]")

    def clear_log(self) -> None:
        """Clear the log and re-show the Phase-3-pending placeholder."""
        log = self.query_one("#log-panel", RichLog)
        log.clear()
        log.write(_LOOP_PENDING_MSG)
        self._loop_events_written = False

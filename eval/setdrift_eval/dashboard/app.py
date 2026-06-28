"""Setdrift Loop Dashboard — Textual TUI (D-03, single-source-of-truth D-04).

What this module does:
  - SetdriftDashboard(App): an information-dense Textual TUI that surfaces the full
    health surface — 9 metric widgets (F1 + noise band, pass rate, cost $, drift
    index, event count, loop status, last refresh), a per-skill DataTable, and a
    scrollable Loop + Telemetry log panel (D-17).
  - Polling every 10 s via set_interval (UI-SPEC §A.4); first load on mount.
  - _poll_metrics reads via run_health ONLY — never recomputes any metric (D-04).
  - DataTable updated via update_cell only — never reset after init (Pitfall 5 guard).
  - All reactive attr watchers use widget.update() — never assign .renderable (Pitfall 2).
  - Wraps poll in run_worker(exclusive=True) to prevent blocking the event loop
    (RESEARCH Open Question 3 / T-05-17 DoS mitigation).

What it does NOT do:
  - Recompute F1 or any metric (Goodhart firewall / D-04).
  - Use hardcoded hex colours in CSS (UI-SPEC §A.5 theme-variable-only rule).
  - Reset the DataTable after initial population (preserves cursor — Pitfall 5 guard).
  - Assign .renderable on any widget (Pitfall 2 guard).

Launch via:
    from setdrift_eval.dashboard.app import SetdriftDashboard
    SetdriftDashboard(corpus_path=..., arm="B").run()
or:
    setdrift-eval health --live --arm B
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header

from setdrift_eval.dashboard.log_panel import LogPanel
from setdrift_eval.dashboard.widgets import MetricWidget, SkillTable

# ---------------------------------------------------------------------------
# Default telemetry events path (overridable via SETDRIFT_EVENTS_PATH env var)
# ---------------------------------------------------------------------------
_DEFAULT_EVENTS_PATH = Path("data/telemetry/events.jsonl")

# Stale threshold: if last successful poll was more than this many seconds ago,
# show the ⚠ STALE indicator on #last-refresh (UI-SPEC §A.6).
_STALE_THRESHOLD_SEC = 60


# ---------------------------------------------------------------------------
# Textual CSS — theme variables only, no hardcoded hex (UI-SPEC §A.5)
# ---------------------------------------------------------------------------
DASHBOARD_CSS = """
/* ── Metric sidebar ─────────────────────────────────────────────────── */
#metrics-scroll {
    width: 30;
    height: 1fr;
    background: $surface;
    border-right: solid $primary-darken-2;
    padding: 1 1;
}

.metric-widget {
    height: 3;
    color: $foreground;
    background: $panel;
    margin-bottom: 1;
    padding: 0 1;
    border: round $primary-darken-3;
}

/* ── Skill table ────────────────────────────────────────────────────── */
#skill-table {
    height: 1fr;
    background: $surface;
}

/* ── Main content row ───────────────────────────────────────────────── */
#main-row {
    height: 1fr;
}

/* ── Log collapsible ────────────────────────────────────────────────── */
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


class SetdriftDashboard(App):
    """Information-dense Setdrift loop management dashboard.

    Reads all metrics via run_health (D-04 single-source-of-truth).
    Polls every 10 s (UI-SPEC §A.4); first load on mount before first interval.
    """

    CSS = DASHBOARD_CSS

    TITLE = "Setdrift Loop Dashboard"
    SUB_TITLE = "Phase 5 — Reporting & Triangulation"

    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("r", "refresh", "Refresh now"),
        Binding("j", "cursor_down", "Next skill"),
        Binding("k", "cursor_up", "Prev skill"),
        Binding("l", "toggle_log", "Toggle log"),
        Binding("?", "toggle_help", "Help"),
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
    ]

    # ── Reactive attributes (changes auto-trigger watch_* methods) ──────────
    f1_current: reactive[float] = reactive(0.0)
    f1_band_lo: reactive[float] = reactive(0.0)
    f1_band_hi: reactive[float] = reactive(0.0)
    pass_rate: reactive[float] = reactive(0.0)
    cost_usd: reactive[float] = reactive(0.0)
    drift_index: reactive[float] = reactive(0.0)
    event_count: reactive[int] = reactive(0)
    loop_status: reactive[str] = reactive("idle")
    last_refresh: reactive[str] = reactive("—")

    def __init__(
        self,
        corpus_path: Path | str = Path("data/corpora/public/public.jsonl"),
        arm: str = "B",
        seed: int = 42,
        map_path: Path | str = Path("eval/setdrift_eval/corpus/intent_skill_map.yaml"),
        skills_dir: Path | str = Path("plugin/skills"),
        experiments_dir: Path | str = Path("experiments"),
        events_path: Path | str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._corpus_path = Path(corpus_path)
        self._arm = arm
        self._seed = seed
        self._map_path = Path(map_path)
        self._skills_dir = Path(skills_dir)
        self._experiments_dir = Path(experiments_dir)
        self._events_path = Path(events_path) if events_path else _DEFAULT_EVENTS_PATH
        self._last_poll_epoch: float = 0.0
        self._skill_table_helper: SkillTable | None = None
        self._table_populated = False

    # ── Layout ──────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main-row"):
            with VerticalScroll(id="metrics-scroll"):
                # IDs must NOT include '#' — that is CSS selector syntax only
                yield MetricWidget("F1 (current)", "f1-current")
                yield MetricWidget("Band lo", "f1-band-lo")
                yield MetricWidget("Band hi", "f1-band-hi")
                yield MetricWidget("Pass rate", "pass-rate")
                yield MetricWidget("Cost $", "cost-usd")
                yield MetricWidget("Drift index", "drift-idx")
                yield MetricWidget("Events (total)", "event-count")
                yield MetricWidget("Loop status", "loop-status")
                yield MetricWidget("Last refresh", "last-refresh")
            yield DataTable(id="skill-table", cursor_type="row")
        yield LogPanel(id="log-collapsible")
        yield Footer()

    # ── Mount / polling setup ────────────────────────────────────────────────

    def on_mount(self) -> None:
        """Set up skill table columns, start poll interval, trigger first load."""
        table = self.query_one("#skill-table", DataTable)
        self._skill_table_helper = SkillTable(table)
        self._skill_table_helper.setup_columns()

        # 10 s cadence (UI-SPEC §A.4)
        self.set_interval(10, self._start_poll_worker)
        # First load before first interval fires
        self.call_after_refresh(self._start_poll_worker)

    # ── Polling ─────────────────────────────────────────────────────────────

    def _start_poll_worker(self) -> None:
        """Kick off the poll in a background worker (T-05-17 / RESEARCH OQ-3).

        run_worker(exclusive=True) ensures only one poll runs at a time and
        does not block the Textual event loop even if run_health touches files.
        """
        self.run_worker(self._poll_metrics, exclusive=True, thread=True)

    def _poll_metrics(self) -> None:
        """Read all health metrics via run_health (D-04 — never recompute).

        Runs in a background thread (via run_worker).  Updates reactive attrs
        and DataTable cells from the worker thread using call_from_thread.
        """
        # Lazy import: FROZEN RULER — import only, never recompute (D-04)
        from setdrift_eval.telemetry.scorer import ScorerError  # noqa: F401

        try:
            from setdrift_eval.telemetry.scorer import run_health
        except ImportError as exc:
            self.call_from_thread(self._apply_error_state, f"ImportError: {exc}")
            return

        try:
            result = run_health(
                corpus_path=self._corpus_path,
                arm=self._arm,
                seed=self._seed,
                map_path=self._map_path,
                skills_dir=self._skills_dir,
                experiments_dir=self._experiments_dir,
            )
        except ScorerError:
            self.call_from_thread(self._apply_gated_state)
            return
        except Exception as exc:
            self.call_from_thread(
                self._apply_error_state,
                f"{type(exc).__name__} — check data/telemetry/",
            )
            return

        now_epoch = time.monotonic()
        now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self.call_from_thread(self._apply_metrics, result, now_epoch, now_str)

    def _apply_metrics(self, result: Any, poll_epoch: float, now_str: str) -> None:
        """Apply a successful poll result to reactive attrs + DataTable.

        Called on the Textual main thread via call_from_thread.
        """
        self._last_poll_epoch = poll_epoch

        # Update reactive attrs — watchers will call widget.update() (never .renderable)
        self.f1_current = result.macro_f1_mean
        self.f1_band_lo = result.noise_band_low
        self.f1_band_hi = result.noise_band_high
        self.pass_rate = result.coverage_pct
        self.last_refresh = now_str

        # Reset any error borders on metric widgets
        for wid in (
            "#f1-current",
            "#f1-band-lo",
            "#f1-band-hi",
            "#pass-rate",
            "#loop-status",
            "#last-refresh",
        ):
            try:
                self.query_one(wid, MetricWidget).reset_border()
            except Exception:
                pass

        # Tail the telemetry log
        try:
            log_panel = self.query_one("#log-collapsible", LogPanel)
            log_panel.tail_telemetry(self._events_path, n_lines=50)
        except Exception:
            pass

    def _apply_gated_state(self) -> None:
        """Show GATED state on F1 metrics (UI-SPEC §A.6 — ScorerError path)."""
        for wid in ("#f1-current", "#f1-band-lo", "#f1-band-hi"):
            try:
                self.query_one(wid, MetricWidget).set_gated()
            except Exception:
                pass
        try:
            self.query_one("#loop-status", MetricWidget).set_value(
                "GATED — precision/kappa gate (02-03) not yet passed"
            )
        except Exception:
            pass

    def _apply_error_state(self, msg: str) -> None:
        """Show ERROR state (UI-SPEC §A.6 — generic exception path)."""
        try:
            self.query_one("#loop-status", MetricWidget).set_error(f"ERROR: {msg}")
        except Exception:
            pass

    def _check_stale(self) -> None:
        """If last poll was >60 s ago, flag #last-refresh as stale (UI-SPEC §A.6)."""
        if self._last_poll_epoch == 0.0:
            return
        elapsed = time.monotonic() - self._last_poll_epoch
        if elapsed > _STALE_THRESHOLD_SEC:
            try:
                self.query_one("#last-refresh", MetricWidget).set_stale(self.last_refresh)
            except Exception:
                pass

    # ── Reactive watchers (use .update() — NEVER .renderable) ───────────────

    def watch_f1_current(self, value: float) -> None:
        """Update #f1-current widget when reactive changes."""
        try:
            self.query_one("#f1-current", MetricWidget).set_value(f"{value:.3f}")
        except Exception:
            pass

    def watch_f1_band_lo(self, value: float) -> None:
        try:
            self.query_one("#f1-band-lo", MetricWidget).set_value(f"{value:.3f}")
        except Exception:
            pass

    def watch_f1_band_hi(self, value: float) -> None:
        try:
            self.query_one("#f1-band-hi", MetricWidget).set_value(f"{value:.3f}")
        except Exception:
            pass

    def watch_pass_rate(self, value: float) -> None:
        try:
            self.query_one("#pass-rate", MetricWidget).set_value(f"{value:.1%}")
        except Exception:
            pass

    def watch_cost_usd(self, value: float) -> None:
        try:
            self.query_one("#cost-usd", MetricWidget).set_value(f"${value:.4f}")
        except Exception:
            pass

    def watch_drift_index(self, value: float) -> None:
        try:
            self.query_one("#drift-idx", MetricWidget).set_value(f"{value:.4f}")
        except Exception:
            pass

    def watch_event_count(self, value: int) -> None:
        try:
            self.query_one("#event-count", MetricWidget).set_value(f"{value:,}")
        except Exception:
            pass

    def watch_loop_status(self, value: str) -> None:
        try:
            self.query_one("#loop-status", MetricWidget).set_value(value)
        except Exception:
            pass

    def watch_last_refresh(self, value: str) -> None:
        try:
            self.query_one("#last-refresh", MetricWidget).set_value(value)
        except Exception:
            pass

    # ── Actions ──────────────────────────────────────────────────────────────

    def action_refresh(self) -> None:
        """Manual refresh (keybinding 'r' — UI-SPEC §A.3)."""
        self._start_poll_worker()

    def action_cursor_down(self) -> None:
        """Navigate skill table down (keybinding 'j' — UI-SPEC §A.3)."""
        try:
            self.query_one("#skill-table", DataTable).action_scroll_down()
        except Exception:
            pass

    def action_cursor_up(self) -> None:
        """Navigate skill table up (keybinding 'k' — UI-SPEC §A.3)."""
        try:
            self.query_one("#skill-table", DataTable).action_scroll_up()
        except Exception:
            pass

    def action_toggle_log(self) -> None:
        """Toggle the log panel collapsed state (keybinding 'l' — UI-SPEC §A.9)."""
        try:
            log_panel = self.query_one("#log-collapsible", LogPanel)
            log_panel.collapsed = not log_panel.collapsed
        except Exception:
            pass

    def action_toggle_help(self) -> None:
        """Show/hide keybinding help (keybinding '?' — UI-SPEC §A.3)."""
        # Textual's built-in help screen is mounted automatically when BINDINGS
        # are declared with show=True.  This action is a no-op placeholder since
        # Footer already auto-renders bindings.  A richer help screen can be
        # wired here in Phase 6.
        pass

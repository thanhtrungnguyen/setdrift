"""Shared figure-pipeline error types (WR-01 fix, D-09 / RESEARCH Pitfall 4).

Single source of truth for FigureDataError. Previously figures/cli.py and
figures/genealogy.py each defined an unrelated class with the identical name,
so `except FigureDataError` caught only one of the two depending on which the
caller imported (cross-catch hazard). All figure modules now import this one
class; figures/genealogy.py re-exports it for backward compatibility.
"""

from __future__ import annotations


class FigureDataError(RuntimeError):
    """Raised when required Phase-3 output data is absent (D-09 gate).

    Gate: if the data file does not exist and --allow-fixtures was not passed,
    raise this error. This prevents a fixture figure from silently entering
    the dissertation as real data.
    """
